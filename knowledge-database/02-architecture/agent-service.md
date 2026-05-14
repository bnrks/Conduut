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
- `credentials`
- `connections`

Health endpoint: `GET /health`.

## Auth

`src/auth.py` Authorization header'ini bekler ve Firebase Admin ile ID token
dogrular. Gecerli token yoksa 401 doner. Firebase ID token dogrulamasinda
Docker/browser saat farkindan dogan `Token used too early` hatalarini azaltmak
icin Firebase Admin'in izin verdigi ust sinir olan 60 saniyelik clock skew
toleransi kullanilir. Reddedilen token'lar `firebase_token_rejected` log
event'iyle hata tipi ve mesaji korunarak kaydedilir.

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

Conversation history modele aktarilirken assistant attachment'lari da korunur.
`workflow_preview` workflow id baglamini, `workflow_run_result` execution
baglamini, `user_input_request` ise agent'in once sordugu eksik bilgi
sorusunu ic context olarak modele ekler. Boylece kullanici sadece eksik cevabi
yazdiginda agent onceki isi devam ettirebilir.

`src/agent/provider_factory.py` Firestore'daki provider/model/API key bilgisine
gore Pydantic AI model instance uretir. Desteklenen provider'lar: `openai`,
`anthropic`, `google`, `groq`, `openrouter`. Eski LiteLLM prefix'leri
(`gemini/`, `google/`, `groq/`, `openrouter/`) normalize edilir. Settings
route'lari ve chat provider override path'i bu liste disindaki provider
anahtarlarini 422 ile reddeder.
OpenAI model listesi donerken Conduut bilinen model id/prefix'lerine gore
`reasoning_efforts` bilgisini ekler; `gpt-5*` ve `o*` reasoning destekleyen
modeller icin chat request'i `reasoning_effort` tasiyabilir. Backend secilen
effort'u modelin destek listesine karsi validate eder ve Pydantic AI
`model_settings.openai_reasoning_effort` olarak agent run'a iletir. Conversation
metadata'si provider/model ile birlikte secilen reasoning effort'u da saklar;
devam eden chat ayni ayara kilitlenir.
Provider hata siniflandirmasi auth/model-not-found/rate-limit durumlarina ek
olarak `insufficient_quota`, quota ve billing mesajlarini ayri yakalar; chat
SSE error event'i kullaniciya provider quota/billing problemini net soyler.

## Agent Tools

`src/agent/tools/` paketi Pydantic AI tool'larini ve yardimci workflow
mantigini tasir. Eski tek dosya `src/agent/tools.py` bolundu; public import
yuzeyi `src.agent.tools` paketinin `__init__.py` dosyasindan korunur. Ana
moduller:

- `factory.py`: `create_agent` ve Pydantic AI tool registration.
- `prompt.py`: agent system prompt'u.
- `runtime_inputs.py`: reusable workflow input schema ve Gmail runtime input
  inference.
- `workflow_runner.py`: Conduut'tan workflow run hazirligi ve execution.
- `readiness.py`: credential/readiness analizi ve managed Gmail connection
  attach davranisi.
- `validation.py`: create/update oncesi workflow normalize/validate akisi.
- `execution.py`: execution output ozetleme.
- `spec_compiler.py`: desteklenen `WorkflowSpec` IR'larini deterministic n8n
  node/connection/input schema payload'una ceviren pilot compiler.

Kayitli tool'lar:

- Registry: `search_n8n_nodes`, `get_node_schema`, `find_workflow_template`.
- Workflow CRUD: `list_workflows`, `get_workflow`, `create_workflow_from_spec`,
  `create_workflow`, `update_workflow`, `delete_workflow`.
- Runtime: `activate_workflow`, `deactivate_workflow`, `execute_workflow`,
  `list_executions`, `analyze_workflow_readiness`, `inspect_execution`.
- Clarification: `request_user_input`.

`create_workflow` ve `update_workflow` opsiyonel `input_schema` alabilir.
Schema MVP'de Firestore `users/{uid}/workflow_metadata/{workflowId}` altinda
saklanir. Gmail send node'u reusable workflow olarak uretildiginde `to`,
`subject`, `message` runtime field'lari infer edilir ve Gmail parametreleri
webhook payload expression'larina baglanir. Webhook trigger output'u body'yi
`$json.body` altinda verdigi icin Webhook + Gmail send workflow'larinda
compiler/normalizer `={{$json.body.to}}`, `={{$json.body.subject}}` ve
`={{$json.body.message}}` kullanir.

`create_workflow_from_spec`, WorkflowSpec IR pilotudur. Desteklenen compiler
sekilleri:

- `trigger.kind=on_demand` ve tek `send_email`/`gmail` step'i: Webhook + Gmail
  send workflow'u uretir ve `to`/`subject`/`message` runtime input schema'si
  kaydeder.
- `trigger.kind=on_demand` veya gunluk `trigger.kind=schedule` ile
  `read_sheet_rows`/`google_sheets` -> `filter_items`/`core` ->
  `send_email`/`gmail`: Google Sheets read, Filter ve Gmail send node'larini
  deterministic olarak uretir. Bu workflow sheet satiri uzerinden email
  gonderdigi icin compiler explicit bos `input_schema` dondurur; Gmail runtime
  input inference bu akista devreye girmez.

Tool LLM'in raw n8n JSON yazmasi yerine desteklenen node/connection yapilarini
compiler ile uretir, registry'den Webhook/Gmail/Google Sheets/Filter/Schedule
`typeVersion` bilgisini alir, mevcut validation/readiness/metadata akisini
kullanir ve unsupported spec veya eksik registry schema durumunda n8n'e side
effect yapmadan hata dondurur.

`request_user_input`, kullanicinin otomasyon isteginde gerekli is bilgisi
eksikse kullanilir. Ornekler: gercek alici email adresleri, gonderilecek
metin, hangi hesap/servis kullanilacagi, schedule/trigger zamani veya
destructive aksiyon onayi. Tool `user_input_request` attachment'i emit eder ve
ayni agent turunda workflow create/update/activate/run/delete gibi yan etkili
tool'larin devam etmesini engeller. Kullanici cevabi ayni chat'e yazinca
history baglami sayesinde agent task'a kaldigi yerden devam eder. Attachment
opsiyonel `choices` listesi ve `allowSkip` flag'i tasiyabilir; web UI aktif son
istekte bunu modal benzeri cevap paneli olarak render eder.

Workflow readiness davranisi:

- Workflow create/update sonrasi agent n8n'deki full workflow'u tekrar okur.
- Registry schema'sinda credential isteyen node'larda credential bagli degilse
  `credential_request` attachment emit eder.
- Activate/run islemleri eksik credential varsa n8n'e side effect yapmadan
  durur ve kullanicidan credential ister.
- Gmail read/send operasyonlari icin kullanicinin `google_gmail` connection'i
  ve gereken capability'si varsa agent n8n workflow node'una `gmailOAuth2`
  credential'i otomatik attach eder. Gmail read operasyonlari
  `google.gmail.read`, send/reply/create operasyonlari `google.gmail.send`
  ister. n8n Gmail v2 message send icin model bazen `operation=create`
  uretebilir; agent bunu n8n'e yazmadan once canonical `operation=send`
  degerine normalize eder. Gmail send parameter alias'lari da canonical
  `sendTo`, `subject`, `message`, `emailType` alanlarina cevrilir; placeholder
  alici email'leri validation hatasi sayilir.
- Managed Google connection metadata'si `scopes` yaninda capability listesi de
  tasir: `google.gmail.read`, `google.gmail.send`, `google.sheets.read`,
  `google.sheets.write`. Eski dokumanlarda capability yoksa agent scope
  listesinden capability turetir.
- Google Sheets node'lari icin kullanicinin `google_sheets` connection'i ve
  gereken Sheets capability'si varsa agent `googleSheetsOAuth2Api`
  credential'ini otomatik attach eder. Read operasyonlari `google.sheets.read`,
  write operasyonlari `google.sheets.write` ister. Sheets connection veya
  capability yoksa chat'e Google Sheets `oauth_prompt` attachment'i gelir.
- Workflow create/update/activate/run/readiness kontrollerinde eksik credential
  veya managed OAuth connection bulunursa agent runtime `awaiting_user_input`
  durumuna gecer. Bu, workflow olustuktan sonra ayni turda activate/run gibi
  ek side effect tool'larinin denenmesini engeller; agent kullaniciya once
  gosterilen connection/credential aksiyonunu tamamlamasini soylemelidir.
- Gmail connection yoksa chat'e Gmail `oauth_prompt` attachment emit edilir.
  Gmail delete/mark-read/mark-unread gibi modify operasyonlari V1 read/send
  credential ile otomatik attach edilmez.
- API key/token isteyen diger node'larda eski `credential_request` form akisi
  korunur.
- `POST /api/workflows/{workflow_id}/run` dashboard ve agent icin ortak
  runtime contract'tir. Body `{ input, source }` tasir; backend required input
  schema validation yapar, credential readiness'i korur ve n8n webhook'una
  validated payload gonderir. `execute_workflow` ayni helper'i kullanir.
- `execute_workflow` Conduut'tan sadece webhook-triggered workflow'lari test
  eder. Manuel tetikleyiciyle olusmus Conduut workflow'lari run isteginde
  otomatik olarak POST webhook trigger'a cevrilir ve sonra Conduut tarafindan
  tetiklenir. Diger external trigger'lar icin agent hazirlik/credential
  durumunu bildirir, gercek event gelmeden calistirdim demez.
- Workflow run dogrulamasi agent icinde kalir. `execute_workflow` webhook
  response ve n8n execution detayini okuyarak sonucu modele tool sonucu olarak
  verir, fakat chat'e `workflow_run_result` attachment'i emit etmez. Kullanici
  teknik kanit karti gormez; agent kanita dayanarak sade metin cevap uretir.

Credential route'lari:

- `GET /api/credentials`: kullanicinin Conduut uzerinden kaydedilen workflow
  credential metadata listesini dondurur.
- `POST /api/credentials`: API-key credential'i n8n public API'ye kaydeder,
  ilgili workflow node'una attach eder ve Firestore'a metadata yazar.

Connection route'lari:

- `GET /api/connections`: kullanicinin app connection metadata listesini
  dondurur.
- `POST /api/connections/google/gmail/authorize` ve
  `/api/connections/google/sheets/authorize`: Firebase auth ister, OAuth state
  ve PKCE verifier uretir, Firestore `oauth_states/{state}` yazar ve servis
  bazli Google authorization URL dondurur.
- `POST /api/connections/google/callback`: auth header beklemez; state icindeki
  Google service degerine gore token exchange ve userinfo okur. Gmail icin
  n8n'de `gmailOAuth2`, Sheets icin `googleSheetsOAuth2Api` credential
  olusturur; Google token response `scope` alanindan granted scope ve
  capability listesini cikarip Firestore connection metadata yazar. Eski
  `/connections/google/gmail/callback` endpoint'i Gmail icin compatibility
  alias'i olarak kalir.
- n8n public API schema'si Gmail/Sheets Google OAuth credential'lari icin token
  datasina ek olarak `serverUrl`, `sendAdditionalBodyProperties` ve
  `additionalBodyProperties` alanlarini bekler. n8n `1.121.3`
  `googleSheetsOAuth2Api` schema'si `additionalProperties=false` oldugu icin
  Sheets credential data'sina top-level `scope` yazilmaz; scope
  `oauthTokenData.scope` icinde kalir.
- `DELETE /api/connections/{connection_id}`: metadata'yi siler ve n8n
  credential'i best-effort siler.

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
Google Sheets node'unda model `operation=append` ile `resource=spreadsheet`
uretirirse normalizer bunu `resource=sheet` olarak duzeltir; n8n Google Sheets
v4 append operasyonu spreadsheet resource'u altinda calismadigi icin aksi halde
runtime'da `Cannot read properties of undefined (reading 'execute')` hatasi
olur.

Connection normalizer, model `{"main": [{"node": "Gmail", "type": "main"}]}`
gibi flat output listesi uretirse bunu n8n editor'un bekledigi
`{"main": [[{"node": "Gmail", "type": "main", "index": 0}]]}` formatina
cevirir. Aksi halde n8n workflow'u API'den kabul etse bile editor
`object is not iterable` hatasiyla acamayabilir.

## Persistence

`src/store.py` Firestore kullanir:

- `users/{uid}/settings/llm`
- `users/{uid}/providers/{provider}`
- `users/{uid}/settings/favorites`
- `users/{uid}/conversations/{convId}`
- `users/{uid}/conversations/{convId}/messages/{messageId}`
- `oauth_states/{state}`
- `users/{uid}/connections/google_gmail`
- `users/{uid}/connections/google_sheets`
- `users/{uid}/workflow_metadata/{workflowId}`

Firestore sync SDK cagrilari `asyncio.to_thread` ile sarilir.

## Test ve Tooling

`apps/agent/pyproject.toml` agent paketi icin `pydantic-ai` dependency'sini
tutar. LiteLLM dependency'si kaldirildi. Pytest cache provider'i Windows local
calismada erisim sorunu ureten gecici cache klasorleri olusturabildigi icin
agent testlerinde kapatildi; `pytest-cache-files-*` klasorleri pytest ve ruff
tarafindan ignore edilir.

## n8n Client

`src/n8n_client.py` tek shared n8n instance REST API'siyle konusur. Workflow,
credential create/delete/attach ve execution islemlerinde n8n hata body'lerini
koruyan typed hata sinifi kullanir. Bu MVP davranisi
[[adr-0001-shared-n8n-mvp]] icinde kayitlidir. Google Gmail connection karari
[[adr-0003-google-oauth-broker-mvp]] icinde kayitlidir.

Ilgili notlar: [[n8n-registry]], [[chat-workflow-generation]],
[[known-issues]].
