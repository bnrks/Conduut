# Agent Service

Merkez: [[index]]

`apps/agent` FastAPI tabanli Conduut agent servisidir.

## Stack

- Python 3.12.
- FastAPI.
- Pydantic settings.
- Pydantic AI.
- HTTPX.
- Firebase Admin.
- Firestore.
- structlog.

## Baslangic

`src/main.py` FastAPI uygulamasini olusturur. Lifespan startup asamasinda
`initialize_registry(settings.n8n_url)` calisir ve n8n node registry hazirlanir.

Router'lar `/api` prefix'i altinda include edilir:

- `chat`
- `conversations`
- `settings`
- `favorites`
- `workflows`

Health endpoint: `GET /health`.

## Auth

`src/auth.py` Authorization header'ini bekler ve Firebase Admin ile ID token
dogrular. Gecerli token yoksa 401 doner. Firebase ID token dogrulamasinda
Docker/browser saat farkindan dogan kisa `Token used too early` hatalarini
azaltmak icin 5 saniyelik clock skew toleransi kullanilir.

`src/firebase.py` Docker icinde `/app/serviceAccount.json` dosyasini, local
test/dev ortaminda ise `apps/agent/serviceAccount.json` dosyasini kullanir.
Firebase Admin uygulamasi daha once initialize edildiyse yeniden initialize
etmez.

## Chat Flow

`POST /api/chat/send` akisi:

1. Firebase user id alinir.
2. Firestore'dan aktif LLM ayarlari okunur.
3. Request provider/model override iceriyorsa provider connection kullanilir.
4. Conversation olusturulur veya mevcut conversation yuklenir.
5. User mesaji Firestore'a yazilir.
6. Conversation history Pydantic AI message history formatina cevrilir.
7. `src/agent/runner.py` SSE stream olarak calistirilir.

Agent runner Pydantic AI tool calling kullanir. Tool'lar event queue uzerinden
`tool_call` ve `attachment` SSE event'lerini uretir; final text cevabi mevcut
frontend sozlesmesi icin `token` event'leriyle parca parca gonderilir. Tool
execution uzunsa keep-alive ping yollanir.

`src/agent/provider_factory.py` Firestore'daki provider/model/API key bilgisine
gore Pydantic AI model instance uretir. Desteklenen provider'lar: `openai`,
`anthropic`, `google`, `groq`, `openrouter`. Eski LiteLLM prefix'leri
(`gemini/`, `google/`, `groq/`, `openrouter/`) normalize edilir. Settings
route'lari ve chat provider override path'i bu liste disindaki provider
anahtarlarini 422 ile reddeder.

## Agent Tools

`src/agent/tools.py` icindeki Pydantic AI tool'lari:

- Registry: `search_n8n_nodes`, `get_node_schema`, `find_workflow_template`.
- Workflow CRUD: `list_workflows`, `get_workflow`, `create_workflow`,
  `update_workflow`, `delete_workflow`.
- Runtime: `activate_workflow`, `deactivate_workflow`, `execute_workflow`,
  `list_executions`.

Workflow create/update oncesi `src/agent/validation.py` validator pipeline'i
calisir:

- `nodes` bos olmamali.
- Her node gerekli alanlara sahip olmali.
- Node id'leri unique olmali.
- Node type exact n8n type olmali veya n8n-compatible prefix tasimali.
- Registry schema varsa `typeVersion` schema ile uyumlu olmali. n8n bazi core
  node'larda `3.4` gibi decimal typeVersion dondurdugu icin validator
  `int | float` kabul eder; bool/string kabul etmez.
- `n8n-nodes-base.set` node'u `manual` modda en az bir
  `parameters.assignments.assignments` item'i icermeli; her item `id`, `name`,
  `type`, `value` tasimali. `raw` modda `parameters.jsonOutput` bos olamaz.
- En az bir trigger node bulunmali.
- `connections` sadece mevcut node adlarina referans vermeli.

Registry'nin kesin cozdugu kisa node type'lari (`set`, `manualTrigger` gibi)
n8n'e yazmadan once canonical `type` ve registry `typeVersion` degerine
normalize edilir. `connections` icindeki source/target referanslari da n8n'in
bekledigi node `name` formatina cevrilir; model `id`, `1`, `2`, `node1`,
`node2` gibi alias'lar uretirse node sirasi ve id bilgisiyle cozulur. Kalan
validation hatalarinda n8n'e side effect yapilmaz; Pydantic AI `ModelRetry` ile
modele duzeltme yaptirir. Validation retry'a giden hatalar
`workflow_validation_failed` log event'iyle kaydedilir.

## Persistence

`src/store.py` Firestore kullanir:

- `users/{uid}/settings/llm`
- `users/{uid}/providers/{provider}`
- `users/{uid}/settings/favorites`
- `users/{uid}/conversations/{convId}`
- `users/{uid}/conversations/{convId}/messages/{messageId}`

Firestore sync SDK cagrilari `asyncio.to_thread` ile sarilir.

## Test ve Tooling

`apps/agent/pyproject.toml` agent paketi icin `pydantic-ai` dependency'sini
tutar. LiteLLM dependency'si kaldirildi. Pytest cache provider'i Windows local
calismada erisim sorunu ureten gecici cache klasorleri olusturabildigi icin
agent testlerinde kapatildi; `pytest-cache-files-*` klasorleri pytest ve ruff
tarafindan ignore edilir.

## n8n Client

`src/n8n_client.py` tek shared n8n instance REST API'siyle konusur. Bu MVP
davranisi [[adr-0001-shared-n8n-mvp]] icinde kayitlidir.

Ilgili notlar: [[n8n-registry]], [[chat-workflow-generation]],
[[known-issues]].
