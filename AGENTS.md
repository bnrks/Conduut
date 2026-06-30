# Conduut Agent Guide

This is the **canonical root guide for any coding agent** (Claude Code, Codex,
etc.) working in the Conduut repo. Treat it as the current working map before
making changes. Root `CLAUDE.md` is a thin pointer back to this file plus the
knowledge-database.

## Session Startup Protocol

At the start of every new agent session in this repo, read in this order:

1. Root `AGENTS.md`.
2. `knowledge-database/index.md`.
3. The Obsidian note or notes relevant to the user's task, selected from the
   links in `index.md`.
4. The source files needed for the task.

Task-to-note routing:

- Product, scope, roadmap, or project direction: read `project-overview` and
  `current-state`.
- Architecture, service boundaries, data flow, or infra: read
  `system-architecture` plus the relevant service note.
- Web/frontend work: read `web-app`, `dashboard` or
  `chat-workflow-generation` as relevant, and `apps/web/AGENTS.md`.
- Agent/backend work: read `agent-service`, `n8n-registry`, and relevant ADRs.
- Workflow generation behavior: read `chat-workflow-generation` and
  `n8n-registry`.
- Bugs, cleanup, odd files, or regressions: read `known-issues`.
- Agent instruction or memory behavior: read `agent-instructions`.

## Project Snapshot

Conduut lets users build and manage n8n workflow automations by chatting with an
AI agent. The long-term platform vision includes per-user n8n containers,
control-plane orchestration, OAuth proxying, usage tracking, billing, and
monitoring. The current repo is an MVP and differs from that target in several
important ways.

## Current Reality

- `apps/web` is the Next.js frontend. It currently uses Next `16.2.1`, React
  `19.2.4`, Tailwind CSS 4, Firebase client auth, Zustand, and Next API route
  handlers as a BFF/proxy to the agent service.
- `apps/agent` is the FastAPI agent service. It uses Python 3.12, LiteLLM,
  Firebase Admin, Firestore, SSE streaming, and a single shared n8n instance.
- `packages/n8n-registry` is a local Python package for tool-based n8n node
  knowledge. It loads node schemas and workflow templates, then exposes lookup
  functions used by the agent's tools.
- `docker-compose.yml` runs three MVP services: `conduut-n8n`,
  `conduut-agent`, and `conduut-web`. The agent listens on container port
  `8000` and is published on host port `8100` to avoid Windows port exclusion
  conflicts.
- `apps/control-plane`, `apps/oauth-proxy`, `apps/node-agent`, PostgreSQL,
  Redis, Vault, Stripe, monitoring, and real per-user container isolation are
  not implemented yet.

## Documentation Priority

When docs disagree, prefer this order:

1. Current source code and manifests.
2. `knowledge-database/index.md` and linked Obsidian notes.
3. `PROJECT.md` and `BRAND.md` for product and long-term architecture.
4. `.claude/*` (subagents, skills) as Claude Code tooling context.

Note: root `CLAUDE.md` is now a thin pointer to this guide plus the
knowledge-database. Its old session-by-session history and "Önemli dosyalar"
file map were archived to
`knowledge-database/99-archive/claude-md-snapshot-2026-06-29.md`. The former
root and `.github/` Copilot instruction files were removed in the 2026-06-29
workspace refactor (Faz 2); see `knowledge-database/01-project/workspace-refactor.md`.

## Coding Rules

- Preserve user and prior-agent changes. The worktree may be dirty; do not
  revert unrelated edits.
- Keep changes scoped. Do not edit `.claude`, generated `CLAUDE.md` stub files,
  or application code unless the task explicitly needs it.
- For frontend work, check `apps/web/AGENTS.md`: this is Next 16, so verify
  local Next behavior before assuming older App Router conventions.
- For backend work, keep FastAPI routes thin and put durable business logic in
  service/client modules where the current codebase already does that.
- Mandatory memory rule: after every change we make, update the relevant
  `knowledge-database` note or notes in the same task. This includes code,
  config, architecture, feature, debugging, documentation, and project-state
  changes. Add new notes, edit existing notes, and connect them with Obsidian
  wikilinks when that makes the memory graph more useful. Do not wait for the
  user to ask.

## Verification Commands

- Web lint: `cd apps/web && pnpm lint`
- Web type check: `cd apps/web && pnpm exec tsc --noEmit`
- Agent checks: `cd apps/agent && ruff check . && ruff format --check . && pytest`
- n8n registry lint: `cd packages/n8n-registry && ruff check .`
- Docker validation/build: `docker compose config` and `docker compose build`

The web package currently has no `test` or `typecheck` npm scripts in
`apps/web/package.json`; use the explicit commands above.

## Operational Notes

- n8n node schema refresh: run
  `python packages/n8n-registry/scripts/fetch_nodes.py` while `conduut-n8n` is
  running. It writes `packages/n8n-registry/data/nodes.json`, which is ignored.
- Template refresh: run
  `python packages/n8n-registry/scripts/fetch_templates.py --limit 200` when
  template data needs updating.
- Credential type schema refresh: run
  `python packages/n8n-registry/scripts/fetch_credentials.py` while `conduut-n8n`
  is running. It writes `packages/n8n-registry/data/credentials.json`, which is
  ignored and must exist before the agent Docker build (ADR-0015).
- Firestore is the MVP persistence layer for conversations, messages, workflow
  metadata (input/output schema, resources), credential metadata, and artifacts.
- LLM access is Conduut-managed: a tiered router picks a fixed model per request
  tier using Conduut's own provider keys from env (ADR-0011). The old
  BYO-provider flow (user LLM keys, providers, favorites) was removed.

## Knowledge Database

The Obsidian vault lives in `knowledge-database`. Use it as persistent project
memory across sessions:

- Start at `knowledge-database/index.md`.
- Use `index.md` as the central graph hub, then navigate to the task-relevant
  note before editing.
- Add new decisions under `03-decisions` (renamed from the old misspelled
  `03-desicions` in the 2026-06-30 knowledge-database cleanup).
- Keep notes Turkish-first, while preserving technical identifiers in English.
- Prefer Obsidian wikilinks such as `[[system-architecture]]` to keep the graph
  connected.
- Keep the graph current after every change. The knowledge database is Codex's
  project memory; maintain it in the structure that will be most useful in
  future sessions.
