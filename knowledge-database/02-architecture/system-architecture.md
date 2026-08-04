# System Architecture

Merkez: [[index]]

Conduut mimarisi iki provider modunda dusunulmeli: local gelistirme icin
shared-n8n ve production icin customer-owned n8n (BYO).

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

## Hedef Platform: Customer-Owned n8n

Aktif production hedefinde her kullanici kendi VPS/cloud hesabinda kendi n8n
instance'ini satin alir ve yonetir. Conduut n8n'i host etmez; authenticated
`user_id` uzerinden kullanicinin HTTPS n8n origin'ini ve secret-store'daki API
key referansini cozer, sonra public n8n API'sine tenant-scoped client ile
baglanir.

```text
Browser
  -> Next.js BFF
  -> FastAPI agent
  -> N8nInstanceResolver(user_id)
  -> Firestore instance metadata + secret store
  -> customer's self-hosted n8n
```

V1'de uygulanan bilesenler:

- Customer-owned n8n connect/deploy onboarding'i.
- `N8nInstanceProvider` / `N8nTarget` / tenant-scoped client factory.
- Firestore user-instance metadata ve production secret store.
- HTTPS, SSRF, TLS, version ve capability preflight.
- Instance-scoped workflow, credential, OAuth, sandbox ve execution lineage'i.
- Remote health/diagnostics ve typed hata contract'i.

Production deployment egress policy, iki public instance pilotu, billing ve
monitoring halen operasyonel/urun takip maddeleridir.

Control plane, node-agent ve Conduut-managed per-user container aktif hedeften
ertelenmistir. `PROJECT.md` bu eski managed vizyonu tarihsel/deferred alternatif
olarak korur. Ayrintili tasarim: [[customer-owned-n8n]]. Karar:
[[adr-0022-customer-owned-n8n]].

## Ana Veri Akislari

- Chat: [[web-app]] -> [[agent-service]] -> request-scope target -> Pydantic AI
  tools -> direct platform APIs veya secili n8n.
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
  spreadsheet'i bir kez olusturur -> workflow metadata `resources` -> secili n8n
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
- Customer-owned production provider karari ve migration plani icin bkz.
  [[adr-0022-customer-owned-n8n]] ve [[customer-owned-n8n]].
- Firestore MVP karari icin bkz. [[adr-0002-firestore-mvp]].
- Platform capability/direct action karari icin bkz.
  [[adr-0006-platform-capability-layer]].
- API-key credential injection resolver'in sectigi customer-owned instance'a
  yonelir, metadata `instance_id` tasir ve raw n8n API key production'da Google
  Secret Manager'da tutulur.
