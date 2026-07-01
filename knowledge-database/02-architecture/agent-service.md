# Agent Service

Merkez: [[index]]

`apps/agent` FastAPI tabanli Conduut agent servisidir.

> **Guncelleme (2026-06-30, [[workspace-refactor]] Faz 3):** Bu not bazi yerlerde
> tarihseldir. IR compiler'lar (`graph_compiler`/`spec_compiler`/`blocks`,
> `WorkflowPlan`/`WorkflowSpec` IR'lari ve `create_workflow_from_plan`/`_spec`
> tool'lari) **kaldirildi** — ADR-0010 zaten model yuzeyinden cikarmisti, Faz 3
> olu kodu sildi. Tek yuzey `create_workflow`/`update_workflow` + `agent/repair.py`.
> Ayrica `store.py`→`store/` paketi, `tools/validation.py`→`tools/build_pipeline.py`,
> runner history blogu→`agent/history.py`. **Guncelleme (2026-06-30 reconcile):**
> compiler / BYO-provider / settings-favorites bolumleri kod gercegiyle
> hizalandi (IR yolu kaldirildi → tek native-JSON yuzeyi; LLM = Conduut-yonetimli
> kademeli model). Tarihsel baglam "eski X → artik Y" notlariyla korundu.

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

Router'lar `/api` prefix'i altinda include edilir (bkz. `main.py`):

- `chat`
- `conversations`
- `artifacts`
- `credentials`
- `connections`
- `workflows`

> Eski `settings` ve `favorites` router'lari **kaldirildi** (BYO-provider yolu
> ADR-0011 ile elendi; artik kullanici LLM ayari/provider/favorite kaydi yok).

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

## Konfigurasyon

`src/config.py` Pydantic settings'i `CONDUUT_` env prefix'iyle okur. Lokal
calismada agent genellikle `apps/agent` klasorunden `python -m uvicorn
src.main:app --reload --host 0.0.0.0 --port 8100` ile baslatildigi icin sadece
calisma dizinindeki `.env` dosyasina guvenilmez. Config repo kokunu
`docker-compose.yml` veya `AGENTS.md` marker'iyle yukariya dogru arayarak bulur;
marker yoksa mevcut app dizinine duser. Boylece local dosya yolu
`apps/agent/src/config.py` iken root `.env` ve `apps/agent/.env` okunur, Docker
image icinde `/app/src/config.py` iken `parents[3]` gibi sabit path varsayimi
yuzunden startup kirilmaz. Lokal n8n default URL'i Windows port mapping'iyle
uyumlu olacak sekilde `http://localhost:6180`'dir; Docker compose agent
container'inda `CONDUUT_N8N_URL=http://n8n:5678` env override'i kullanilir.

## Diagnostic Logging

Agent servisinde merkezi structured logging `src/logging_config.py` uzerinden
kurulur. `structlog` stdout'a JSON event basmaya devam eder; local ve Docker
gelistirme icin ayrica rotating JSONL dosyasi yazar. Varsayilan dosya
`logs/agent/conduut-agent.jsonl`, Docker container icinde `/app/logs` altidir.
`docker-compose.yml` agent servisine `./logs/agent:/app/logs` volume'u baglar;
`start-local-dev.bat` lokal uvicorn akisi icin `CONDUUT_LOG_DIR` degerini repo
root `logs\agent` klasorune ayarlar.

Ilgili env ayarlari:

- `CONDUUT_LOG_LEVEL`
- `CONDUUT_LOG_FILE_ENABLED`
- `CONDUUT_LOG_DIR`
- `CONDUUT_LOG_MAX_BYTES`
- `CONDUUT_LOG_BACKUP_COUNT`
- `CONDUUT_LOG_PAYLOAD_PREVIEW_CHARS`
- `CONDUUT_CONNECTION_ENCRYPTION_KEY` direct Google API icin refresh token'lari
  encrypted saklamayi acan secret'tir; Docker Compose bu env'i agent
  container'ina passthrough eder.

Loglar hata triage icin tasarlanmistir. FastAPI middleware her istege
`X-Request-ID` uretir veya gelen degeri korur; web BFF route'lari bu header'i
agent'a tasir. Agent run, tool call, n8n API, OAuth callback, credential
readiness ve workflow run event'leri ayni `request_id`, `conversation_id` ve
varsa `workflow_id` baglaminda izlenebilir. Redaction processor
`authorization`, `api_key`, token, secret, password, `clientSecret`,
`code_verifier` ve `oauthTokenData` gibi alanlari maskeler; buyuk string/list
degerleri truncate eder. Raw kullanici mesaji, provider API key'i ve OAuth token
degerleri loglanmamalidir. `structlog` disindaki stdlib loglari da
`ProcessorFormatter` uzerinden JSON satirina cevrilir; aksi halde `httpx` gibi
kutuphaneler JSONL dosyasina duz metin satirlari karistirabilir.

## Chat Flow

`POST /api/chat/send` akisi (`routes/chat.py`):

1. Firebase user id alinir.
2. Conversation olusturulur veya mevcut conversation yuklenir.
3. User mesaji Firestore'a yazilir.
4. Conversation history Pydantic AI message history formatina cevrilir.
5. `src/agent/runner.py` SSE stream olarak calistirilir.

> **Model secimi (ADR-0011, BYO kaldirildi):** Eskiden burada Firestore'dan
> aktif LLM ayarlari okunur ve request provider/model override'i uygulanirdi;
> artik bu yok. Model seçimi **runner içinde** olur: `agent/router.py`
> `classify_tier()` mesaji simple/medium/hard tier'ina siniflar,
> `agent/model_registry.py` aktif profile (`CONDUUT_MODEL_PROFILE`) için o
> tier'in sabit model+thinking `ModelChoice`'unu cozer ve `provider_factory`
> Conduut'un **kendi** env key'iyle (`key_for_provider`) modeli kurar. Chat
> request'i hala tolere etsin diye `provider`/`model`/`reasoning_effort`
> alanlarini 422 atmadan **yok sayar** (`ConfigDict(extra="ignore")`).

Agent runner Pydantic AI tool calling kullanir. Tool'lar event queue uzerinden
`tool_call` ve `attachment` SSE event'lerini uretir. Tool execution uzunsa
keep-alive ping yollanir.

**Gercek token streaming + thinking (2026-06-23):** Eskiden runner `agent.run()`
ile tum cevabi sona kadar hesaplayip metni 10 karakterlik sahte parcalara bolup
art arda (sleep'siz) gonderiyordu → cevap "tek balon" gibi aninda beliriyordu.
Artik `agent.iter()` ile graph node-node surulur; `Agent.is_model_request_node`
olan node'da `node.stream(run.ctx)` ile model cevabi **gercek zamanli** akar.
`_emit_stream_event` helper'i: `TextPartDelta`/`TextPart` -> `token` (gorunur
metin, persist icin `text_chunks`'a da eklenir), `ThinkingPartDelta`/`ThinkingPart`
-> **yeni `thinking` SSE event'i** (ChatGPT/Claude tarzi canli dusunce; ephemeral,
store'a kaydedilmez). token/thinking, tool'larin kullandigi AYNI `event_queue`'ya
gider → siralama, keep-alive ve drain mimarisi degismeden korunur. Persist edilen
icerik akan token'larin birlesimi (`"".join(text_chunks)`), bos ise
`run.result.output`'a duser. Dusunce yalnizca Orta/Zor tier'da uretilir
(ADR-0011: Sonnet adaptive / Gemini HIGH); saglayici farki: Anthropic ham dusunce,
Gemini ozet, OpenAI cogu zaman bos → frontend icerik geldiyse panel gosterir.
Frontend: `thinking` event'i ephemeral `Message.thinking`'e birikir, acilir-kapanir
`ThinkingPanel` (cevap baslayinca otomatik kapanir). UX rotuslari (2026-06-23):
(1) "Conduut is thinking" gostergesi artik balon degil **duz metin** ve cevap
metni akmaya baslayinca **gizlenir** (`message-list.tsx` `showTypingIndicator`);
(2) stream sirasinda paragraf/liste metni **kelime kelime fade-in** olur
(`message.tsx` `FadeWords` + `globals.css` `conduut-word-in`; yalniz `streaming`
prop'u true iken, canli markdown korunur, index-key ile sadece yeni kelimeler
animasyon alir). Detay: [[chat-workflow-generation]].

Conversation history modele aktarilirken assistant attachment'lari da korunur.
`workflow_preview` workflow id baglamini, `workflow_run_result` execution
baglamini, `user_input_request` ise agent'in once sordugu eksik bilgi
sorusunu ic context olarak modele ekler. Boylece kullanici sadece eksik cevabi
yazdiginda agent onceki isi devam ettirebilir.

## Model Registry, Router ve Provider Factory (ADR-0011)

> **DIKKAT — BYO-provider kaldirildi:** Bu not eskiden kullanicinin Firestore'a
> kendi provider/model/API key'ini kaydedip chat'te sectigi BYO akisini
> anlatiyordu (settings/favorites route'lari, OpenAI model picker UI,
> `users/{uid}/providers` + `settings/llm` fallback, `verify_provider_connection`).
> **Bu yol [[adr-0011-conduut-managed-tiered-models]] ile tamamen elendi.** Artik
> kullanici LLM key girmez; Conduut kendi provider key'lerini env'den kullanir.

Aktif yapi 3 dosyaya boluner:

- `src/agent/model_registry.py` — Conduut-yonetimli **3 kademe + router**, named
  profile'lar icinde. `Tier` (simple/medium/hard) her biri sabit bir
  `ModelChoice` (provider + model + `ThinkingSpec` + request/tool-call limitleri).
  Profiller: `default` (onerilen; Medium=Sonnet adaptive, Hard=Gemini Pro HIGH,
  her tier'in 2.tercihi native GPT), `gpt` (tek-switch full-OpenAI) ve `deepseek`
  (maliyet bake-off; first-party OpenAI-uyumlu API). `CONDUUT_MODEL_PROFILE` ile
  secilir; `_validate_profiles()` start'ta yanlis profile'da fail-fast yapar.
- `src/agent/router.py` — `classify_tier()` aktif profile'in ucuz router modeliyle
  (thinking OFF, tek istek, structured output) mesaji tier'a siniflar; herhangi
  bir hatada MEDIUM'a duser (router cokuyse chat bloklanmaz).
- `src/agent/provider_factory.py` — `build_model(provider, model, api_key)`
  Conduut'un **kendi** key'inden Pydantic AI model instance'i kurar. Desteklenen
  provider'lar: `openai`, `anthropic`, `google`, `groq`, `openrouter`, `deepseek`
  (DeepSeek OpenAI-uyumlu oldugu icin `OpenAIChatModel` + custom `base_url`).
  `normalize_model_name` eski LiteLLM prefix'lerini (`gemini/`, `google/`,
  `groq/`, `openrouter/`, ...) temizler; `normalize_provider` liste disindaki
  provider'i reddeder. `build_model_settings` bir tier'in `ThinkingSpec`'ini
  saglayici-ozgu `model_settings`'e cevirir (Anthropic `anthropic_thinking`,
  Google `google_thinking_config`, OpenAI `openai_reasoning_effort`, DeepSeek
  `extra_body.thinking`).

`classify_provider_error` saglayici SDK hatalarini stabil kullanici mesajlarina
esler: auth, model-not-found, rate-limit'e ek olarak `insufficient_quota`/quota/
billing durumlarini ayri yakalar; chat SSE error event'i kullaniciya provider
quota/billing problemini net soyler.

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
- `build_pipeline.py`: create/update oncesi workflow normalize → repair →
  runtime-input → validate akisi (eski adi `validation.py`; Faz 3'te rename).
- `execution.py`: execution output ozetleme.
- `history.py`: konusma gecmisini Pydantic AI mesaj gecmisine ceviren saf
  fonksiyonlar (Faz 3'te runner.py'den cikarildi).
- `src/platforms/*`: platform capability registry, permission pack mapping,
  encrypted Google token kullanimi, direct Gmail/Sheets client'lari ve platform
  action audit kaydi.
- `src/agent/artifacts.py`: Google Sheets ve Gmail direct action / workflow run
  ciktilarindan kullaniciya guvenli `artifact_preview` snapshot'lari uretir.

Kayitli tool'lar:

- Registry: `search_n8n_nodes`, `get_node_schema`, `find_workflow_template`.
- Workflow CRUD: `list_workflows`, `get_workflow`, `create_workflow`,
  `update_workflow`, `delete_workflow`. (IR tool'lari
  `create_workflow_from_plan`/`_spec` Faz 3'te kaldirildi — ADR-0010.)
- Runtime: `activate_workflow`, `deactivate_workflow`, `execute_workflow`,
  `list_executions`, `analyze_workflow_readiness`, `inspect_execution`.
- Platform direct action: `run_platform_action`.
- Credential: `list_credentials`, `attach_credential`, `prepare_api_credential`
  (agent-managed, [[adr-0013-agent-managed-credentials]]), `add_service_credential`
  (predefined, [[adr-0015-predefined-credential-library]]).
- Clarification: `request_user_input`.

## Artifacts

V1 artifact modeli [[artifacts]] notunda tanimlidir. Agent Google Sheets ve
Gmail direct action'lari veya bu node'lari iceren workflow run sonuclari icin
`artifact_preview` attachment'i emit eder. Assistant mesajinin attachment
snapshot'i conversation history icinde kalir; ayrica preview payload'i
`users/{uid}/artifacts/{artifactId}` collection'ina kalici dashboard snapshot'i
olarak yazilir.

`WorkflowRunResultData` ve workflow run route response'u `artifacts` listesi
tasir. Direct Sheets/Gmail action sonucunda `PlatformActionResult.artifacts`
ayni preview payload'unu dondurur. Preview tablolar en fazla 10 satir ve 12
kolon tasir; Gmail message preview'leri message id, thread id, alici, konu,
snippet/govde ozeti ve label/search metadatasini tasir. Secret/token benzeri
alanlar tabloya veya message payload'ina alinmaz. Kullanici tam veri icin
ilgili Google uygulamasi linkine gider.
`ArtifactPreviewTable.rows`, Firestore'un dogrudan nested array kabul etmemesi
nedeniyle `list[dict[column, cellPreview]]` seklinde saklanir; frontend legacy
array row formatini da okuyabilir ama backend yeni snapshot'larda map row
formatini uretmelidir. Gmail artifact'lari `message_preview` type'i ve
`message` dict'iyle saklanir.

Runner, conversation history'deki Google Sheets `artifact_preview`
attachment'larini `AgentDeps.platform_resources` baglamina cevirir. En son
artifact'teki `spreadsheetId`, link ve sheet/range bilgisi sonraki
`run_platform_action` cagrilarinda varsayilan resource olarak kullanilir.
Direct Sheets action'lari ayni agent turunda basarili create/read/write
sonuclarindan da bu resource baglamini gunceller. Boylece kullanici "tekrar
dene" dediginde agent'in onceki spreadsheet'i kullanmasi desteklenir; backend
bos `spreadsheet_id` ile Google API'ye `spreadsheets//...` cagrisi yapmak
yerine `missing_input` hatasi dondurur.
Gmail direct action'lari da ayni runtime resource baglamini kullanir. Search
sonucundaki ilk message id/thread id `AgentDeps.platform_resources.gmail`
altina yazilir; takip eden get/mark/archive/trash/label action'i bos
`message_id` tasirsa bu deger kullanilir. Context de yoksa backend Gmail API'ye
`/messages/` gibi bos id'li istek atmaz, `missing_input` dondurur.

`GET /api/artifacts`, kullanicinin son artifact snapshot'larini `createdAt`
camelCase alani ve `origin` metadata'siyle dondurur. `DELETE
/api/artifacts/{artifactId}` yalniz current user altindaki artifact dokumanini
siler; dokuman yoksa 404 dondurur. Agent runner chat artifact'larini
`origin.kind=chat`, dashboard workflow run route'u ise run sonucundaki
artifact'lari `origin.kind=workflow_run` ile kaydeder. Persist hatalari asil
chat veya run response'unu kirmadan structured log'a yazilir.

## Platform Capability Layer

Conduut agent artik yalnizca n8n workflow builder degil, bagli platformlari
direct API ile yoneten ve gerekirse ayni niyeti n8n workflow'una compile eden
bir platform agent'i olarak davranir. Bu karar [[adr-0006-platform-capability-layer]]
icinde kayitlidir.

`src/platforms/capabilities.py` canonical capability ve permission pack
registry'sidir. Google V1 icin Gmail capability'leri
`gmail.message.send/read/modify/trash/delete_permanently`, Sheets
capability'leri `sheets.spreadsheet.create`, `sheets.sheet.manage`,
`sheets.range.read/update/clear` ve `sheets.row.append` seklindedir. Eski
`google.gmail.send/read` ve `google.sheets.read/write` etiketleri geriye donuk
alias olarak cozulur.

Permission pack'ler kullaniciya daha anlasilir izin setleri sunar:
`gmail.basic`, `gmail.send`, `gmail.read`, `gmail.organize`,
`gmail.full_control`, `sheets.app_files` ve `sheets.full_access`. OAuth
authorize body/query'si `permission_pack` veya `requested_capabilities`
alabilir; scope listesi registry'den turetilir.

`src/platforms/google_clients.py` direct Gmail/Sheets HTTP client'larini tasir.
Refresh token `CONDUUT_CONNECTION_ENCRYPTION_KEY` varsa
`src/platforms/crypto.py` ile sifrelenerek Firestore connection metadata'sina
yazilir. Env yoksa `direct_api_enabled=false` kalir ve n8n credential bazli
workflow davranisi devam eder. Raw refresh/access token loglanmamalidir.

`run_platform_action` tool'u anlik Gmail/Sheets islemlerini direct API ile
calistirir. Eksik capability varsa side effect yapmadan `oauth_prompt`
attachment'i dondurur. Desteklenen V1 islemleri Gmail send/search/get/mark
read-unread/archive/trash/label ve Sheets spreadsheet create, sheet
create/delete, range read/update/clear, row append aksiyonlaridir. Her direct
aksiyon `users/{uid}/platform_action_audit/{id}` altina secret veya payload
yazmadan audit metadata'si kaydeder.
Sheets direct action'larda `sheets.sheet.create` idempotent davranir: hedef tab
zaten varsa hata yerine basarili sonuc dondurur. `sheets.range.update` ve
`sheets.row.append`, `sheet_name` veya range icinden hedef tab adini
cozebiliyorsa yazmadan once tab'in varligini garanti eder; yoksa olusturur.
Google API hata mesajlari artik status koduyla birlikte sanitize edilmis kisa
mesaj olarak `PlatformActionError` ve log'a tasinir.
Sheets read/update/append/clear ve sheet manage action'lari eksik
`spreadsheet_id` tasiyorsa once `AgentDeps.platform_resources.google_sheets`
baglamindan tamamlanir. `range` yalniz `A1:D4` gibi tab icermeyen bir degerse
ve `sheet_name` biliniyorsa backend bunu `<sheet_name>!A1:D4` formatina
cevirir. Hala spreadsheet id bulunamiyorsa Google API'ye istek atilmaz.
Direct API icin `CONDUUT_CONNECTION_ENCRYPTION_KEY` key'i connection OAuth
callback aninda mevcut olmalidir. Key sonradan eklenirse eski
`google_gmail`/`google_sheets` connection dokumanlari n8n credential olarak
calismaya devam eder, fakat `encrypted_refresh_token` ve `direct_api_enabled`
alanlari olmadigi icin Sheets spreadsheet provisioning gibi direct action'lar
icin hesap yeniden baglanmalidir. `reconnect_required` direct action hatalari
artik generic error olarak yutulmaz; ilgili Google service icin `oauth_prompt`
attachment'i emit edilir.

`create_workflow` ve `update_workflow` opsiyonel `input_schema` alabilir.
Schema MVP'de Firestore `users/{uid}/workflow_metadata/{workflowId}` altinda
saklanir. Gmail send node'u reusable workflow olarak uretildiginde `to`,
`subject`, `message` runtime field'lari infer edilir ve Gmail parametreleri
webhook payload expression'larina baglanir. Webhook trigger output'u body'yi
`$json.body` altinda verdigi icin Webhook + Gmail send workflow'larinda
normalizer (`agent/repair.py`) `={{$json.body.to}}`, `={{$json.body.subject}}`
ve `={{$json.body.message}}` kullanir.

> **DIKKAT — IR compiler yolu kaldirildi ([[adr-0010-json-surface-repair-normalizer]],
> [[workspace-refactor]] Faz 3):** Bu not eskiden tercih edilen yol olarak
> `create_workflow_from_plan` (action graph IR) ve `create_workflow_from_spec`
> (WorkflowSpec IR) tool'larini, bunlari n8n JSON'a ceviren `spec_compiler.py`/
> `graph_compiler.py`/`blocks.py` derleyicilerini ve `Prepare Sheets Row` Set
> node'u + `autoMapInputData` gibi compiler-ozgu node uretim numaralarini
> anlatiyordu. **Tum bu IR tool'lari, schema'lari (WorkflowPlan/WorkflowSpec/
> WorkflowGraph) ve compiler'lar silindi.**
>
> Tek yuzey artik **kompakt native n8n JSON**'dur: model `create_workflow`/
> `update_workflow` ile dogrudan n8n JSON yazar, `agent/repair.py` deterministik
> onarir (sub-node main wiring, `{{input.x}}`, `$json.body` atlama vb. uc klasik
> ham-yol bug'i). Gmail send -> Google Sheets append log akisi hala desteklenir,
> fakat artik prompt rehberligi + repair ile native JSON uzerinden olusur.
> Sheet ID yoksa ama istek `spreadsheet_title`/`document_title` tasiyorsa agent
> direct Sheets API ile spreadsheet'i bir kez provision edip `spreadsheet_id`'yi
> workflow'a enjekte etme + `resources` metadata davranisini korur; title de
> yoksa `request_user_input` ile gercek Sheet bilgisini ister.
>
> Action Registry / platform action pack refactoru (eski "factory'ler
> `spec_compiler.py` icinde" notu) artik ileri vadeli bir backlog kalemidir; bkz.
> [[feature-backlog]] ve [[adr-0005-workflow-spec-compiler]] (ADR-0005/0008/0009
> ADR-0010 ile **superseded**).

`request_user_input`, kullanicinin otomasyon isteginde gerekli is bilgisi
eksikse kullanilir. Ornekler: gercek alici email adresleri, gonderilecek
metin, hangi hesap/servis kullanilacagi, schedule/trigger zamani veya
destructive aksiyon onayi. Tool `user_input_request` attachment'i emit eder ve
ayni agent turunda workflow create/update/activate/run/delete gibi yan etkili
tool'larin devam etmesini engeller. Kullanici cevabi ayni chat'e yazinca
history baglami sayesinde agent task'a kaldigi yerden devam eder. Agent
varsayilan olarak eksik bilgileri adim adim sorar: her `request_user_input`
cagrisi tek eksik karar/alan icindir. Tool tarafinda model yanlislikla birden
fazla `missing_fields` verirse attachment ilk alanla sinirlanir; kalan alanlar
sonraki user cevabindan sonra yeniden sorulacak baglam olarak kalir. Attachment
opsiyonel `choices` listesi ve `allowSkip` flag'i tasiyabilir; web UI aktif son
istekte bunu modal benzeri cevap paneli olarak render eder.

Workflow readiness davranisi:

- Workflow create/update sonrasi agent n8n'deki full workflow'u tekrar okur.
- Registry schema'sinda credential isteyen node'larda credential bagli degilse
  `credential_request` attachment emit eder.
- Activate/run islemleri eksik credential varsa n8n'e side effect yapmadan
  durur ve kullanicidan credential ister.
- Gmail read/send/modify operasyonlari icin kullanicinin `google_gmail`
  connection'i ve gereken canonical capability'si varsa agent n8n workflow
  node'una `gmailOAuth2` credential'i otomatik attach eder. Gmail read
  operasyonlari `gmail.message.read`, send/reply/create operasyonlari
  `gmail.message.send`, label/mark/archive/trash operasyonlari
  `gmail.message.modify` veya `gmail.message.trash` ister. Eski
  `google.gmail.read/send` etiketleri alias olarak kabul edilir. n8n Gmail v2
  message send icin model bazen `operation=create` uretebilir; agent bunu n8n'e
  yazmadan once canonical `operation=send` degerine normalize eder. Gmail send
  parameter alias'lari da canonical `sendTo`, `subject`, `message`,
  `emailType` alanlarina cevrilir; placeholder alici email'leri validation
  hatasi sayilir.
  Reconnect sonrasi eski n8n credential id'leri workflow node'larinda stale
  kalabilecegi icin readiness analizi managed Gmail/Sheets connection varsa
  node'da credential alani dolu olsa bile guncel connection credential id'sini
  workflow'a yeniden attach eder.
- Managed Google connection metadata'si `scopes` yaninda `capabilities`,
  `permission_packs`, `direct_api_enabled`, `encrypted_refresh_token` ve
  `n8n_credential_id` alanlarini tasir. Eski dokumanlarda capability yoksa
  agent scope listesinden canonical capability turetir.
- Google Sheets node'lari icin kullanicinin `google_sheets` connection'i ve
  gereken Sheets capability'si varsa agent `googleSheetsOAuth2Api`
  credential'ini otomatik attach eder. Read operasyonlari `sheets.range.read`,
  write/append operasyonlari `sheets.range.update`, `sheets.row.append` veya
  `sheets.spreadsheet.create` ister. Eski `google.sheets.read/write`
  etiketleri alias olarak kabul edilir. Sheets connection veya capability yoksa
  chat'e Google Sheets `oauth_prompt` attachment'i gelir.
- Workflow create/update/activate/run/readiness kontrollerinde eksik credential
  veya managed OAuth connection bulunursa agent runtime `awaiting_user_input`
  durumuna gecer. Bu, workflow olustuktan sonra ayni turda activate/run gibi
  ek side effect tool'larinin denenmesini engeller; agent kullaniciya once
  gosterilen connection/credential aksiyonunu tamamlamasini soylemelidir.
- Gmail connection yoksa chat'e Gmail `oauth_prompt` attachment emit edilir.
  Gmail permanent delete default akista kullanilmaz; trash ve organize
  aksiyonlari permission pack/risk metadata'siyle ayrilir.
- API key/token isteyen diger node'larda eski `credential_request` form akisi
  korunur.
- `POST /api/workflows/{workflow_id}/run` dashboard ve agent icin ortak
  runtime contract'tir. Body `{ input, source }` tasir; backend required input
  schema validation yapar, credential readiness'i korur ve n8n webhook'una
  validated payload gonderir. `execute_workflow` ayni helper'i kullanir.
- `POST /api/workflows/{workflow_id}/batch-run` dashboard batch/loop
  calistirma contract'idir. Body `{ rows, source, options }` tasir; her row
  `{ rowNumber, input }` seklindedir. Endpoint credential readiness'i batch
  basinda kontrol eder, workflow'u Conduut-runnable POST webhook'a hazirlar,
  en fazla 50 satiri sequential calistirir, required input'u bos satirlari
  webhook'a gondermeden `skipped` yapar ve satir bazli `success`/`failed`/
  `skipped` sonuc dondurur. Artifact origin'i `workflow_batch_run`,
  `batchRunId`, `rowNumber` ve `executionId` bilgilerini tasir.
- Workflow webhook'u 4xx/5xx donse bile runner son n8n execution detayini
  okumayi dener. Boylece dashboard single/batch run sonuclari genel
  `"Error in workflow"` cevabi yerine mumkunse `failedNode` ve node-level hata
  mesajini (ornegin Gmail OAuth refresh token invalid/expired) kullaniciya
  tasir.
- `execute_workflow` Conduut'tan sadece webhook-triggered workflow'lari test
  eder. Manuel tetikleyiciyle olusmus Conduut workflow'lari run isteginde
  otomatik olarak POST webhook trigger'a cevrilir ve sonra Conduut tarafindan
  tetiklenir. Diger external trigger'lar icin agent hazirlik/credential
  durumunu bildirir, gercek event gelmeden calistirdim demez.
- Workflow run dogrulamasi agent icinde kalir. `execute_workflow` webhook
  response ve n8n execution detayini okuyarak sonucu modele tool sonucu olarak
  verir, fakat chat'e `workflow_run_result` attachment'i emit etmez. Kullanici
  teknik kanit karti gormez; agent kanita dayanarak sade metin cevap uretir.

Credential route'lari (custom HTTP credential kutuphanesi, [[adr-0012-custom-http-credentials]]):

- `GET /api/credentials`: kullanicinin kayitli custom credential metadata
  listesini dondurur (`users/{uid}/credentials`; label/type/host, secret yok).
- `POST /api/credentials`: credential'i n8n public API'ye kaydeder, Firestore
  `credentials` koleksiyonuna metadata yazar; body `workflow_id`+`node_name`
  tasiyorsa ilgili node'a da baglar (HTTP generic tipleri icin
  `generic_auth_type` ile `authentication=genericCredentialType` +
  `genericAuthType` wiring). Host outbound HTTP library create / tip-secici kart
  icin zorunlu (`generic_auth_type` set ya da workflow'suz); eski reaktif
  per-workflow yol (Webhook basic auth) host gerektirmez.
- `GET /api/credentials/types`: V1 tip katalogu (Header/Basic/Query/Custom Auth +
  alanlar), dashboard ve chat formunu besler.
- `DELETE /api/credentials/{id}`: Firestore metadata'sini siler + best-effort
  n8n credential'i siler; yoksa 404.
- `POST /api/credentials/{id}/finalize`: agent-hazirladigi **taslak** credential'i
  tamamlar (kullanici secret'i girer) → `auth_config`+secret'tan n8n `data` kurar,
  n8n credential olusturur, `status=ready` yapar, bekleyen workflow node'una baglar
  ([[adr-0013-agent-managed-credentials]]).

Agent-yonetimli credential ([[adr-0013-agent-managed-credentials]]):

- `agent/research.py` `research_api_auth(host)` sabit, ucuz **Gemini Flash +
  grounding** alt-agent'i (tier/router'dan bagimsiz, provider-bagimsiz)
  calistirir; `AuthResearchResult` (scheme/field_name/value_prefix/secret_fields/
  source_url/confidence) doner. Sonuc paylasimli global `api_auth_cache/{host}`'e
  yazilir (secret yok, TTL 60g). Grounding cagrisi `_run_grounding_research`
  arkasinda (cache/map mantigi test edilebilir).
- `prepare_api_credential(api_or_url, workflow_id?, node_name?)` tool'u: host-eslesen
  ready/draft varsa kisa devre; yoksa research → secret'siz **taslak** credential
  (`store.save_draft_credential`, n8n credential YOK) + secret-only `credential_request`
  karti. Dusuk guven/belirsiz → taslak uydurmaz, duz-dil manuel karta duser; `none`
  → auth'suz. Secret asla agent'tan gecmez; kullanici chat karti veya dashboard
  "Tamamla" ile girer.

Custom HTTP credential eslestirme/baglama:

- `agent/credential_types.py` V1 tip katalogu + `normalize_host` +
  `match_credentials` (deterministik host eslestirme).
- `agent/tools/readiness.py` yalniz `n8n-nodes-base.httpRequest` node'larinda
  `authentication=genericCredentialType` icin `genericAuthType`'tan gereken
  tipi okur; kullanicinin kutuphanesinde host eslesirse kart yerine
  `reuse_candidates` dondurur (create/update sonucunda `credential_suggestions`),
  eslesme yoksa tip-secicili `credential_request` (host onceden dolu) emit eder.
- `agent/tools/credentials.py` `list_credentials_payload` (secret yok,
  host-eslesme bayrakli) ve `attach_credential_payload` (ownership Firestore'dan
  dogrulanir, `n8n_client.attach_credential_to_workflow(..., generic_auth_type=)`
  ile auth parametrelerini de yazar). Tool'lar: `list_credentials`,
  `attach_credential`. Baglama onay-once: agent `request_user_input` ile sorar,
  onay gelince `attach_credential` cagirir.

Connection route'lari:

- `GET /api/connections`: kullanicinin app connection metadata listesini
  dondurur.
- `POST /api/connections/google/gmail/authorize` ve
  `/api/connections/google/sheets/authorize`: Firebase auth ister, OAuth state
  ve PKCE verifier uretir, Firestore `oauth_states/{state}` yazar ve servis
  bazli Google authorization URL dondurur. Body/query `permission_pack` veya
  `requested_capabilities` tasiyabilir; istenen scope listesi platform
  registry'den cozulur.
- `POST /api/connections/google/callback`: auth header beklemez; state icindeki
  Google service degerine gore token exchange ve userinfo okur. Gmail icin
  n8n'de `gmailOAuth2`, Sheets icin `googleSheetsOAuth2Api` credential
  olusturur; Google token response `scope` alanindan granted scope ve
  canonical capability/permission pack listesini cikarip Firestore connection
  metadata yazar. `CONDUUT_CONNECTION_ENCRYPTION_KEY` varsa refresh token'i
  encrypted saklar ve direct API'yi etkinlestirir; yoksa direct API kapali
  kalir ama n8n credential id'si korunur. Eski
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

`src/store/` paketi (Faz 3'te `store.py`'den koleksiyon-bazli bolundu; re-export
`__init__` ile ayni public yuzey) Firestore kullanir:

- `users/{uid}/conversations/{convId}`
- `users/{uid}/conversations/{convId}/messages/{messageId}`
- `users/{uid}/workflow_metadata/{workflowId}`
- `users/{uid}/connections/{connectionId}` ( or. `google_gmail`, `google_sheets`)
- `oauth_states/{state}`
- `users/{uid}/platform_action_audit/{auditId}`
- `users/{uid}/artifacts/{artifactId}`
- `users/{uid}/credentials/{credentialId}` (custom HTTP + agent-managed +
  predefined credential metadata; secret yok)
- `api_auth_cache/{host}` (global, kullanici-disi; agent-managed auth research
  cache, secret yok)

> **Kaldirilan koleksiyonlar (BYO-provider, ADR-0011):** eski `settings/llm`,
> `providers/{provider}` ve `settings/favorites` koleksiyonlari artik yok;
> kullanici LLM key/model/favorite kaydetmez. `workflow_credentials` da dead
> legacy cluster olarak kaldirildi (Faz 3, `store/__init__` notuna bkz.).

Artifact preview payload'lari hem conversation message attachment'i olarak
saklanir hem de dashboard listesi icin `artifacts` collection'ina yazilir.

Conversation detail route'u frontend uyumlulugu icin message response'larinda
snake_case alanlari korurken `createdAt`, `messageCount`, `updatedAt` ve
`reasoningEffort` camelCase alias'larini da dondurur. Firestore'da assistant
mesajlari `assistant` roluyla saklanabilir; API chat UI icin bunu `agent`
rolune normalize eder ve `artifact_preview` attachment'larini aynen korur.

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
[[adr-0003-google-oauth-broker-mvp]] icinde, platform capability katmani ise
[[adr-0006-platform-capability-layer]] icinde kayitlidir.

Ilgili notlar: [[n8n-registry]], [[chat-workflow-generation]],
[[known-issues]].
