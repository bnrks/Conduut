# Conduut

Conduut is an AI-assisted operations layer for self-hosted
[n8n](https://n8n.io). It helps users build workflows through conversation,
validate and approve them safely, monitor executions, and repair failures.

This repository is an **MVP and engineering case study**, not a hosted
production service. It demonstrates the product and technical work behind an
agentic automation system: native n8n workflow generation, deterministic JSON
repair, sandbox and approval gates, execution evidence, credential handling,
and a Next.js operations dashboard.

Working today includes chat-based workflow generation, customer-owned n8n
connection management, workflow run/activate/batch operations, execution
history and repair handoff, Google Gmail and Sheets OAuth/direct actions, and
credential management. Production hardening such as broader n8n version
compatibility, network-level egress controls, billing, and monitoring remains
out of scope. See
[`knowledge-database/01-project/current-state.md`](knowledge-database/01-project/current-state.md).

## Why this project exists

n8n is powerful, but operating reliable automations still involves more than
generating a graph. Conduut explores the layer around that graph: connecting a
customer-owned instance, resolving credentials, validating risky changes,
collecting execution evidence, and turning a failed run into a structured
repair conversation.

The repository is shared as a portfolio project and technical reference. It is
not presented as a replacement for n8n's own AI or MCP capabilities.

## Repository layout

Monorepo:

| Path | What |
|------|------|
| `apps/web` | Next.js 16 frontend — chat UI, dashboard, auth, BFF API routes proxying the agent. |
| `apps/agent` | FastAPI agent service — Pydantic AI runner, SSE streaming, Firestore, n8n tools, direct platform actions. |
| `packages/n8n-registry` | Python package: n8n node / template / credential schema lookup used by the agent. |
| `knowledge-database/` | Obsidian vault — persistent project memory (ADRs, architecture, current state). |
| `docker-compose.yml`, `start-local-dev.bat` | Local orchestration. |

## Tech stack

- **Frontend:** Next.js 16, React 19, Tailwind CSS 4, Firebase client auth, Zustand.
- **Agent:** Python 3.12, FastAPI, Pydantic AI, Firestore (MVP persistence), HTTPX. LLMs are
  Conduut-managed via a tiered router (simple/medium/hard → fixed model per tier).
- **Automation:** customer-owned n8n connections plus a shared local-development adapter; the agent talks to n8n over its public API.
- **Infra:** Docker Compose.

## Getting started

**Prerequisites:** Docker, Python 3.12, Node + pnpm.

**Secrets / config (not committed):**
- Copy `.env.example` to `.env` for agent, n8n, OAuth, and LLM settings.
- Copy `apps/web/.env.example` to `apps/web/.env.local` for the BFF target and Firebase web configuration.
- `apps/agent/serviceAccount.json` contains Firebase Admin credentials and must remain local.

Never commit real API keys, OAuth secrets, service-account exports, private keys,
raw email exports, or local runtime data. The repository ignore rules cover the
standard local paths, but review `git status` before every commit.

**Registry data** (gitignored, generated from a running n8n — do this before building the agent):

```bash
python packages/n8n-registry/scripts/fetch_nodes.py         # → data/nodes.json
python packages/n8n-registry/scripts/fetch_credentials.py   # → data/credentials.json
```

**Full stack (Docker):**

```bash
docker compose up          # web :3000 · agent :8100 · n8n :6180
```

**Local dev with hot reload (Windows):**

```bat
start-local-dev.bat        :: n8n (Docker) + agent (uvicorn :8100) + web (:3007)
```

## Verification

```bash
cd apps/web            && pnpm lint && pnpm exec tsc --noEmit
cd apps/agent          && ruff check . && ruff format --check . && pytest
cd packages/n8n-registry && ruff check . && pytest
docker compose config  # validate the compose file
```

## Documentation

- **[`AGENTS.md`](AGENTS.md)** — canonical guide for contributors and coding agents (project
  structure, rules, verification, operational notes). **Start here.**
- **[`PROJECT.md`](PROJECT.md)** — long-term product & architecture vision (DB schema, flows, cost).
- **[`knowledge-database/index.md`](knowledge-database/index.md)** — persistent project memory:
  ADRs, architecture notes, feature docs, known issues.
- **[`BRAND.md`](BRAND.md)** — colors, typography, logo.

## Security and licensing

Please do not include credentials or private data in issues, logs, screenshots,
or example workflows. See [`SECURITY.md`](SECURITY.md) for reporting guidance.

No open-source license is currently granted. The code is public for portfolio
and evaluation purposes; reuse requires the copyright holder's permission.
