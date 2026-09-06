# Conduut

**An AI-assisted operations layer for self-hosted [n8n](https://n8n.io).**

Conduut lets a user describe an automation in conversation, turns that intent
into a native n8n workflow, validates the result before it is used, and makes
the workflow, its credentials, and its execution history easier to operate.

> **Project status:** portfolio MVP and engineering case study — not a hosted
> production service or a replacement for n8n's native AI/MCP capabilities.

## The problem it explores

Generating an automation graph is only one part of making an automation useful.
Teams still need to connect their own n8n instance, handle credentials, review
risky changes, test workflows safely, understand a failed execution, and turn
that failure into a repair task.

Conduut explores that operating layer around n8n. Its active product direction
is **customer-owned n8n**: the customer controls their self-hosted n8n instance
and Conduut connects through the public API.

## What is implemented

| Area | What Conduut demonstrates |
| --- | --- |
| Conversational builder | An agent turns a natural-language request into native n8n workflow JSON. |
| Guarded workflow generation | Deterministic JSON repair, static semantic checks, sandbox previews, and approval gates before activation. |
| Customer-owned n8n | Connect, check, rotate, disconnect, and resolve a user's selected n8n instance at request scope. |
| Operations dashboard | Browse workflows, activate/deactivate, run with inputs, execute batches, and inspect output cards. |
| Execution evidence | Read execution history, redact error details, and hand a failed run back to chat as structured repair context. |
| Credentials and connections | Manage n8n credentials plus Google Gmail/Sheets OAuth connections; supported actions can attach the right credential. |
| Direct actions and artifacts | Run selected Gmail/Sheets actions without creating a workflow and surface resulting Sheets/artifact previews. |
| Usage visibility | Record completed agent-run usage events and show time-window/provider/model breakdowns. |

## Architecture at a glance

```text
Browser
  │  Next.js 16 dashboard, chat, and server-side BFF routes
  ▼
Conduut agent service
  │  FastAPI · Firebase verification · Firestore · SSE · LLM router
  ├──────────────► n8n public API
  │                 customer-owned instance in production
  │                 shared local adapter for development
  ├──────────────► n8n registry
  │                 node, template, and credential schema lookup
  └──────────────► Firestore
                    conversations, metadata, artifacts, usage events
```

The repository is a monorepo:

| Path | Responsibility |
| --- | --- |
| [`apps/web`](apps/web) | Next.js 16 / React 19 interface, Firebase client auth, and BFF routes. |
| [`apps/agent`](apps/agent) | FastAPI agent, n8n provider/client layer, streaming, validation, and platform actions. |
| [`packages/n8n-registry`](packages/n8n-registry) | Local n8n node/template/credential schema lookup package. |
| [`knowledge-database`](knowledge-database/index.md) | Architecture notes, ADRs, scenarios, and current-state documentation. |
| [`infra/terraform`](infra/terraform/README.md) | Secret-only Google Cloud foundation; runtime deployment remains intentionally disabled. |

## Local development

### Prerequisites

- Docker Desktop with Docker Compose
- Python 3.12+
- Node.js LTS and pnpm
- A Firebase project and a local Firebase Admin service-account JSON for
  authenticated end-to-end flows
- At least one supported LLM provider key if you want to use the agent

### 1. Create local-only configuration

PowerShell:

```powershell
Copy-Item .env.example .env
Copy-Item apps/web/.env.example apps/web/.env.local
```

Fill in only the providers and integrations you intend to use. For an
authenticated flow, save a Firebase Admin export as
`apps/agent/serviceAccount.json`. These files are intentionally ignored by Git.

Never commit API keys, OAuth secrets, service accounts, private keys, raw email
exports, or local runtime data.

### 2. Start local n8n and build its registry data

The agent image expects local n8n node and credential schemas. Start n8n first,
then copy its generated schema cache:

```powershell
docker compose up -d n8n
python packages/n8n-registry/scripts/fetch_nodes.py
python packages/n8n-registry/scripts/fetch_credentials.py
```

Both generated JSON files are ignored. Refresh them whenever the local n8n
version changes.

### 3. Start the stack

```powershell
docker compose up -d --build
docker compose ps
```

Local endpoints:

| Service | Address |
| --- | --- |
| Web | <http://localhost:3000> |
| Agent health | <http://localhost:8100/health> |
| n8n | <http://localhost:6180> |

On Windows, [`start-local-dev.bat`](start-local-dev.bat) is a faster development
path: it runs only n8n in Docker and starts the agent and web app with reload.

### Verify changes

```powershell
Set-Location apps/web
pnpm lint
pnpm exec tsc --noEmit

Set-Location ../agent
ruff check .
ruff format --check .
pytest

Set-Location ../../packages/n8n-registry
ruff check .
pytest
```

`docker compose config` is a useful final configuration check. The repository's
automated workflow/deployment configuration is deliberately absent; this project
does not deploy itself from GitHub.

## Current scope and boundaries

Conduut is deliberately specific about what it proves today.

- The customer-owned n8n provider flow, dashboard operations, workflow
  generation/repair, sandbox/evidence model, and selected Google integrations
  are implemented in the MVP.
- The shared n8n container exists only as a local-development adapter. It is not
  the production tenancy model.
- Production pilots with multiple public customer instances, broad n8n-version
  compatibility, network-level egress controls, billing, monitoring, and a
  general OAuth proxy are not complete.
- Terraform documents a Google Cloud secret foundation, but Cloud Run, Artifact
  Registry, VPC/NAT runtime infrastructure, and CI/CD deployment are not enabled.

For the source-of-truth detail, see
[`knowledge-database/01-project/current-state.md`](knowledge-database/01-project/current-state.md)
and the customer-owned decision in
[`ADR-0022`](knowledge-database/03-decisions/adr-0022-customer-owned-n8n.md).

## Reading the project

- [`AGENTS.md`](AGENTS.md) — contributor and coding-agent guide.
- [`knowledge-database/index.md`](knowledge-database/index.md) — documentation graph and ADR index.
- [`PROJECT.md`](PROJECT.md) — long-term product context; some managed-hosting
  sections are explicitly historical rather than the active BYO direction.
- [`SECURITY.md`](SECURITY.md) — responsible disclosure guidance.

## Security

Use GitHub's private vulnerability reporting flow for suspected security issues.
Do not put credentials, access tokens, customer data, or raw execution payloads
in public issues, screenshots, or example workflows.

## License

This code is public for portfolio and evaluation purposes. No open-source
license is currently granted; reuse requires permission from the copyright
holder.
