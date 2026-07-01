# Conduut

Build and manage [n8n](https://n8n.io) workflow automations by **chatting with an AI agent** —
no node graphs, no JSON. Describe the automation in plain language and the agent designs,
validates, and (with your connected accounts) runs it. It can also perform one-off Gmail/Sheets
actions directly, and surface run results as readable cards in a dashboard.

Status: **MVP.** Working today: chat → workflow generation, workflow dashboard (run/activate/batch),
Google Gmail & Sheets (OAuth connections + direct actions), credential management. Not yet built:
per-user n8n isolation, control plane, general OAuth proxy, billing, monitoring. See
[`knowledge-database/01-project/current-state.md`](knowledge-database/01-project/current-state.md).

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
- **Automation:** a single shared n8n instance (MVP); the agent talks to it over the REST API.
- **Infra:** Docker Compose.

## Getting started

**Prerequisites:** Docker, Python 3.12, Node + pnpm.

**Secrets / config (not committed):**
- `apps/agent/serviceAccount.json` — Firebase Admin credentials.
- `apps/web/.env.local` — web env (see `apps/web`).
- Root `.env` — optional Google OAuth (`CONDUUT_GOOGLE_OAUTH_CLIENT_ID/SECRET`, `CONDUUT_CONNECTION_ENCRYPTION_KEY`) and LLM provider keys.

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
