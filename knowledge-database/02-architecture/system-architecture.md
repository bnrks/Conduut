# System Architecture

Merkez: [[index]]

Conduut mimarisi iki katmanda dusunulmeli: mevcut MVP ve hedef platform.

## Mevcut MVP

```text
Browser
  -> Next.js web app / API routes
  -> FastAPI agent service
  -> shared n8n instance and direct platform APIs
  -> Firestore for app state
```

Mevcut `docker-compose.yml` uc servis calistirir:

- `conduut-web`: Next.js frontend, port `3000`.
- `conduut-agent`: FastAPI agent, container port `8000`; local host port
  `8100` because Windows can reserve host port `8000`.
- `conduut-n8n`: tek shared n8n instance, container port `5678`; local host
  port `6180` because this Windows environment reserves ranges including
  `5678` and `5980`.

Lokal hizli gelistirme icin root `start-local-dev.bat` hibrit akis saglar:
yalnizca `docker compose up -d n8n` ile shared n8n image'ini ayaga kaldirir,
agent'i `apps/agent` altindan `python -m uvicorn src.main:app --reload --port
8100` ile lokal koddan calistirir, web'i de `apps/web` altindan
`npm run dev -- --hostname localhost --port 3007` ile baslatir. Bu akista
agent `CONDUUT_N8N_URL` olarak `http://localhost:6180`,
`CONDUUT_PUBLIC_WEB_URL` olarak `http://localhost:3007`, web BFF route'lari ise
`AGENT_API_BASE_URL` olarak `http://localhost:8100` kullanir; web/agent Docker
image build'i gerekmez. n8n host portu `CONDUUT_N8N_PORT`, web portu
`CONDUUT_WEB_PORT` ile override edilebilir.
Script agent'i `apps/agent` calisma dizininden baslattigi icin root `.env`
dosyasi Pydantic tarafindan otomatik okunmaz; bu nedenle
`CONDUUT_GOOGLE_OAUTH_CLIENT_ID`, `CONDUUT_GOOGLE_OAUTH_CLIENT_SECRET` ve
opsiyonel `CONDUUT_OAUTH_STATE_TTL_SECONDS` root `.env` icinden agent
process'ine aktarilir.

`apps/web/src/app/api/*` route handler'lari BFF/proxy gorevi gorur. Firebase ID
token'i browser'dan Next API route'a, oradan agent servisine Authorization
header olarak tasinir.

## Hedef Platform

Uzun vadeli hedef, `PROJECT.md` icinde anlatilan cok servisli platformdur:

- Agent service.
- Control plane.
- OAuth proxy.
- Her VPS uzerinde node-agent.
- Her kullaniciya ayri n8n container.
- PostgreSQL + pgvector, Redis, Vault, MinIO/S3.
- Traefik, monitoring ve billing.

Bu hedef henuz kodda yoktur. Yeni is planlanirken hedef mimariyle uyumlu
olmak iyi, fakat mevcut MVP'nin gercek sinirlarini bozmamak daha onemlidir.

## Ana Veri Akislari

- Chat: [[web-app]] -> [[agent-service]] -> Pydantic AI tools -> direct
  platform APIs veya shared n8n.
- Conversation persistence: [[agent-service]] -> Firestore.
- Workflow list/toggle/delete: [[web-app]] API route -> agent workflow route ->
  `n8n_client.py` -> n8n REST API.
- Credential request: chat attachment -> [[web-app]] `/api/credentials` BFF ->
  [[agent-service]] `/api/credentials` -> n8n credential API -> workflow node
  attach.
- Managed Google OAuth connection: chat/dashboard OAuth prompt -> [[web-app]]
  Google authorize BFF -> [[agent-service]] connection route -> Google OAuth ->
  n8n credential API -> encrypted Firestore connection metadata. MVP'de Gmail
  ve Google Sheets ayri connection id'leriyle tutulur. `permission_pack` veya
  `requested_capabilities` registry'den Google scope listesine cozulur.
- Direct platform action: [[agent-service]] `run_platform_action` ->
  encrypted Google refresh token -> Gmail/Sheets API -> platform action audit
  log. n8n bu akista execution backend degildir.
- Workflow platform provisioning: [[agent-service]] `create_workflow`/
  `update_workflow` (native n8n JSON; eski `create_workflow_from_plan` IR tool'u
  ADR-0010 ile kaldirildi) -> gerekirse direct Sheets API ile eksik
  spreadsheet'i bir kez olusturur -> workflow metadata `resources` -> shared n8n
  workflow create/update (`agent/repair.py` normalize/onarir).
- Workflow run: dashboard run form veya agent tool -> Conduut run endpoint ->
  runtime input validation -> webhook-triggered workflow call -> n8n execution
  API -> agent/internal verification -> normal assistant text response veya
  dashboard toast. Google Sheets ciktisi varsa backend ayni response/attachment
  icinde `artifact_preview` snapshot'i uretir.
- Execution history: n8n execution API -> `src/executions.py(user_id)` ->
  FastAPI `/api/executions` -> Next BFF -> Runs dashboard. Ayni service agent
  `list_executions`/`inspect_execution` tool'larina ve structured chat repair
  handoff'una hizmet eder; raw execution data web'e cikmaz.
- Node knowledge: [[agent-service]] -> [[n8n-registry]].

## Mimari Dikkat Noktalari

- Shared n8n MVP karari icin bkz. [[adr-0001-shared-n8n-mvp]].
- Firestore MVP karari icin bkz. [[adr-0002-firestore-mvp]].
- Platform capability/direct action karari icin bkz.
  [[adr-0006-platform-capability-layer]].
- API-key credential injection'in ilk fazi chat uzerinden uygulanmistir. OAuth
  proxy ve per-user isolation dokumanlarda gecse de henuz uygulanmamistir.
