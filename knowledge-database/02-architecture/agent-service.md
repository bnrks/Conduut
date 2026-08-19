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
- `executions`
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

Global JSONL'e ek olarak her chat agent calismasi icin insan ve LLM tarafindan
kolay okunabilen tek bir timeline uretilir:
`logs/agent/runs/YYYY-MM-DD/HH-MM-SS_<run-id>.log`. `run_id`, model
`attempt_id`'lerinden bagimsizdir ve global JSONL baglamina da eklenir; boylece
iki log gorunumu birbiriyle eslestirilebilir. Ayni run icindeki DeepSeek retry
denemeleri ayri dosyalara bolunmez. Dosya baslik, guvenli/kisa task preview,
INFO+ structured event timeline'i ve success/error/cancelled final ozetinden
olusur. Token/thinking stream parcalari, `user_id`, raw payload/body ve ucuncu
parti stdlib loglari run timeline'ina alinmaz; event detaylari denylist yerine
guvenli alan allowlist'iyle secilir. Prompt/final preview'leri inline
Bearer/JWT/API-key/secret kaliplarini maskeler ve varsayilan 300 karakterde
kesilir. Browser/SSE stream'i erken kapanirsa ic model task'i cancel+await
edilir; timeline `cancelled` ozetiyle kapanirken arka planda tool/aksiyon
calismaya devam etmez.

Ilgili env ayarlari:

- `CONDUUT_LOG_LEVEL`
- `CONDUUT_LOG_FILE_ENABLED`
- `CONDUUT_LOG_DIR`
- `CONDUUT_LOG_MAX_BYTES`
- `CONDUUT_LOG_BACKUP_COUNT`
- `CONDUUT_LOG_PAYLOAD_PREVIEW_CHARS`
- `CONDUUT_RUN_LOG_ENABLED` (varsayilan `true`)
- `CONDUUT_RUN_LOG_RETENTION_DAYS` (varsayilan `30`)
- `CONDUUT_RUN_LOG_PREVIEW_CHARS` (varsayilan `300`)
- `CONDUUT_CONNECTION_ENCRYPTION_KEY` direct Google API icin refresh token'lari
  encrypted saklamayi acan secret'tir; Docker Compose bu env'i agent
  container'ina passthrough eder.

Run log dizini ayrica ayarlanmaz; her zaman `<CONDUUT_LOG_DIR>/runs` olarak
turetilir. Agent startup'inda yalniz bu agac altindaki retention suresini asan
`.log` dosyalari ve bos tarih klasorleri temizlenir. Run-log dosya sistemi
hatalari fail-open'dir ve chat/agent akisini durdurmaz. Retention degeri sifir
veya negatifse guvenli bicimde temizlik yapilmaz.

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

**DeepSeek canli reliability recovery (2026-07-11):** Eski #1244 guard'i DeepSeek
attempt'inin tum event'lerini sona kadar buffer edip temiz sonucu replay ediyordu; bu yol
kaldirildi. DeepSeek de `token`/`thinking`/`tool_call` event'lerini canli yollar. Her event
`attempt_id` tasir; incremental guard duz-metin tool call/runaway/repetition yakalarsa
`recovery` SSE (`failed_attempt_id`, `next_attempt_id`, `attempt`, `max_attempts`,
`reason_code`, `retrying`, `message`) emit eder. Frontend eski attempt state'ini siler ve
yeni attempt'i canli izler. Ilk deneme + en cok iki retry vardir. Merkezi tool replay-safety
katalogu dis mutation baslamissa retry'yi fail-closed durdurur; boylece workflow, credential
ve platform aksiyonlari iki kez calismaz. Bozuk attempt ve recovery aktivitesi history'ye
yazilmaz. Detay: [[model-cost-research-2026-06]].

Conversation history modele aktarilirken assistant attachment'lari da korunur.
`workflow_preview` workflow id baglamini, `workflow_run_result` execution
baglamini, `user_input_request` ise agent'in once sordugu eksik bilgi
sorusunu ic context olarak modele ekler. Boylece kullanici sadece eksik cevabi
yazdiginda agent onceki isi devam ettirebilir.
User-message `execution_reference` attachment'i da son prompt ve reload sonrasi
history icinde korunur. Backend reference'i execution id'den canonicalize eder;
agent exact execution'i inspect etmeden workflow degisikligine baslamaz.

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
  OpenAI-uyumlu istemciler (`openai`+`deepseek`) `_openai_compatible_client` ile
  **stall-safe timeout** (`httpx.Timeout` read=120s + `max_retries=2`) alir; aksi
  halde SDK'nin 600s default'u yuzunden hung bir DeepSeek stream'i run'i ~10dk
  dondurur (bkz. [[known-issues]] "DeepSeek ~10dk stall").
  `normalize_model_name` eski LiteLLM prefix'lerini (`gemini/`, `google/`,
  `groq/`, `openrouter/`, ...) temizler; `normalize_provider` liste disindaki
  provider'i reddeder. `build_model_settings` bir tier'in `ThinkingSpec`'ini
  saglayici-ozgu `model_settings`'e cevirir (Anthropic `anthropic_thinking`,
  Google `google_thinking_config`, OpenAI `openai_reasoning_effort`, DeepSeek
  `extra_body.thinking`). Lokal kosularda root `.env` icindeki
  `CONDUUT_MODEL_PROFILE` degeri runtime'i override eder; H1 senaryo kosusunda
  bu deger `default` kaldigi icin DeepSeek profili yerine Sonnet calismisti
  (2026-07-07), `.env` tekrar `deepseek` yapildi.

> **Ayrim (2026-07-08):** Conduut agent'in kendi LLM router'i DeepSeek profile ile
> calisirken bile uretilen workflow icinde ayrica n8n `Anthropic Chat Model`
> node'u bulunabilir. Bu node kullanicinin/predefined Anthropic credential'iyle
> n8n execution sirasinda Anthropic API'ye gider; bu, `provider_factory` secimi
> degildir. H1 kosusunda bu node eski Claude ID'leri (`claude-3-haiku-20240307`,
> `claude-3-5-sonnet-20241022`) yazdigi icin sandbox `AI Agent` node'unda dustu.
> Duzeltme agent prompt'una veya validation'a hardcoded model ID gommek degil,
> [[n8n-registry]] schema extraction'ini duzeltmek oldu: latest version'a uyan
> `resourceLocator` `model` parametresi, default degeri ve `searchListMethod`
> metadata'si artik `get_node_schema` ile agent'a gelir. Validation yalniz generic
> `lmChat*` string model degerini `{__rl, mode, value}` resourceLocator bicimine
> sarar; Anthropic'e ozel model katalogu tutmaz.

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
- `setup_guide.py`: customer-owned Ubuntu 24.04/x86_64 VPS icin versioned,
  deterministic, tek-adimlik n8n `1.121.3` kurulum rehberi; komutlar, file
  payload'lari, beklenen sinyaller ve guvenli troubleshooting sinirlari.
  2026-08-17 itibariyla destek matrisi Ubuntu 22.04 veya 24.04 + x86_64'tur
  (24.04 preferred). Ayni modul chat icin snake_case stage payload'i ve
  Settings/BFF icin secret-free camelCase `GET /api/n8n/setup-guide` payload'i
  uretir. Docker install adimi official `docker.asc` + `.sources` akisini
  dinamik codename ile verir; deploy compose `N8N_WEBHOOK_URL` kullanir ve
  5678'i public'e publish etmez.
- `prompt.py`: agent system prompt'u.
- `runtime_inputs.py`: reusable workflow input schema ve Gmail runtime input
  inference.
- `workflow_runner.py`: Conduut'tan workflow run hazirligi ve execution.
- `readiness.py`: credential/readiness analizi ve managed Gmail connection
  attach davranisi.
- `build_pipeline.py`: create/update oncesi workflow normalize → repair →
  runtime-input → validate akisi (eski adi `validation.py`; Faz 3'te rename).
- `execution.py`: execution output ozetleme.
- `src/executions.py`: web route'lari ve agent tool'lari icin user-aware,
  sanitize execution list/detail service siniri ([[execution-history]]).
- `history.py`: konusma gecmisini Pydantic AI mesaj gecmisine ceviren saf
  fonksiyonlar (Faz 3'te runner.py'den cikarildi).
- `src/platforms/*`: platform capability registry, permission pack mapping,
  encrypted Google token kullanimi, direct Gmail/Sheets client'lari ve platform
  action audit kaydi.
- `src/agent/artifacts.py`: Google Sheets ve Gmail direct action / workflow run
  ciktilarindan kullaniciya guvenli `artifact_preview` snapshot'lari uretir.

Kayitli tool'lar:

- Registry: `search_n8n_nodes`, `get_node_schema`, `find_workflow_template`.
- Setup: read-only/replay-safe `get_automation_server_setup_step`; agent bu
  tool olmadan VPS/n8n kurulum komutu uretmez, VPS'e baglanmaz ve shell
  calistirmaz. Secret'lar chat yerine ilgili kaynak sistem/Settings write-only
  formunda kalir. Setup conversation mode'u Firestore'da immutable saklanir;
  runner bu modda yalniz setup step + safe clarification tool'larini kaydeder.
  Route belirgin secret-bearing setup mesajlarini persistence/model oncesi
  reddeder; setup stage sirasi conversation state ile server-side enforce edilir.
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
- Gmail Trigger ve Gmail read/send/modify operasyonlari icin kullanicinin `google_gmail`
  connection'i ve gereken canonical capability'si varsa agent n8n workflow
  node'una `gmailOAuth2` credential'i otomatik attach eder. Gmail Trigger
  `gmail.message.read` ister. Gmail read
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
- OAuth tabanli credential tipleri genel `credential_request` formuna
  dusurulmez. Managed Google tipleri ilgili `oauth_prompt` akisini kullanir;
  henuz broker destegi olmayan OAuth tipleri `serverUrl`, client secret veya
  token semasi gostermek yerine destek varsa Connections, yoksa dogrudan n8n
  uzerinden OAuth yapilandirmasina yonlendirir.
- API key/token isteyen diger node'larda eski `credential_request` form akisi
  korunur.
- Google Sheets v4 append column mapping'inde model `mappingMode=define`
  uretirse repair bunu canonical `defineBelow` degerine cevirir; duz value
  map'inden `columns.schema` ve `matchingColumns` sentezler. Validation append
  icin desteklenmeyen mapping mode ile eksik value/schema seklini n8n'e
  ulasmadan reddeder.
- Execution ozetleri n8n error `extra.parameterName`/`context.parameterName`
  bilgisini hata mesajina ekler; `Could not get parameter` gibi genel hatalarda
  agent gercek parametreyi gorur.
- Gmail/Schedule gibi external-trigger workflow'lari n8n editorunde manuel
  kosulabilir; Conduut chat runner'in public API yolu ise halen webhook ile
  sinirlidir. Runner bu durumu n8n imkansizligi gibi sunmaz, Conduut chat siniri
  ve editor Execute workflow alternatifini soyler. n8n internal manual-run
  route'u session cookie ve editor push baglantisina bagli oldugu icin backend
  entegrasyonu degildir.
- `POST /api/workflows/{workflow_id}/run` dashboard ve agent icin ortak
  runtime contract'tir. Body `{ input, source }` tasir; backend required input
  schema validation yapar, credential readiness'i korur ve n8n webhook'una
  validated payload gonderir. `execute_workflow` ayni helper'i kullanir. Domain
  sonucu basarisizsa response `success=false`, `failed_node` ve `error` tasir;
  web HTTP 200'u tek basina basari saymaz.
- `GET /api/executions` ve `GET /api/executions/{execution_id}` gercek n8n run
  gecmisini cursor/filter ve sanitize detail contract'iyla sunar. Raw execution
  data ve outputs web contract'ina girmez ([[execution-history]]).
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
- `users/{uid}/usage_events/{eventId}` (tamamlanan agent run token/request/tool
  sayilari; prompt veya response metni yok; outer run-log `run_id` tabanli
  deterministic id ile idempotent, `event_type=agent_run_completed`,
  `schema_version=1`)
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

Usage gozlem akisi `runner._persist_and_done` icinde Pydantic AI
`result.usage()` degerini best-effort kaydeder; usage persist hatasi basarili
chat SSE `done` event'ini engellemez. `src/usage.py` bu immutable event'leri son
24 saat/7/30/90 gun icin okur ve toplam, UTC gunluk seri ve model kirilimi
uretir; `routes/usage.py` authenticated ince HTTP yuzeyidir. Bu ilk kapsam
provider faturasi veya billing source-of-truth degildir: router, basarisiz
attempt, terminal hata ve cancellation usage'i kapsanmaz.

## Test ve Tooling

`apps/agent/pyproject.toml` agent paketi icin `pydantic-ai` dependency'sini
tutar. LiteLLM dependency'si kaldirildi. Pytest cache provider'i Windows local
calismada erisim sorunu ureten gecici cache klasorleri olusturabildigi icin
agent testlerinde kapatildi; `pytest-cache-files-*` klasorleri pytest ve ruff
tarafindan ignore edilir.

## n8n Client

`src/n8n_client.py` instance-scoped `N8nClient` ile target'in base/webhook URL
ve API key'ini kullanir. `N8nInstanceResolver` authenticated `user_id` icin
aktif Firestore instance metadata'sini ve secili secret backend'indeki secret'i cozer;
`N8nClientFactory` ayni request context'ini route, agent tools, readiness,
executions, sandbox ve platform state boyunca tasir. Shared global facade yalniz
`shared_dev` geriye uyumluluk/test adapter'idir. Production resolver hatasinda
shared fallback yoktur.

Secret backend secimi `CONDUUT_N8N_SECRET_MANAGER_BACKEND` ile yapilir:
`memory` unit/test adapter'i, `encrypted_file` local restart-persistent adapter,
`google_secret_manager` production adapter'idir. Local encrypted store yolu
`CONDUUT_N8N_LOCAL_SECRET_STORE_PATH` ile override edilebilir; default
`apps/agent/.local/n8n-secrets.json`'dir. Store value'lari Fernet ile ayri ayri
encrypt eder, adjacent `.key` dosyasini tekrar kullanir ve atomik file replace
uygular. Bilinmeyen backend sessizce memory'ye dusmez; startup fail-fast olur.
Production validation yalniz `customer_owned + google_secret_manager` kabul
eder. Local `.local/` payload/key Git'e girmez (2026-08-19).
Local `customer_owned + memory` kombinasyonu da startup'ta reddedilir; boylece
restartta API key kaybina yol acan eski konfigurasyona sessizce donulemez.
Windows'ta file/key ACL'i workspace kullanicisinin mevcut NTFS izin sinirina
dayanir; bu adapter ayni makinedeki kotu niyetli kullaniciya karsi production
vault garantisi vermez.

Connect preflight ve her kritik transport, `src/n8n_security.py` uzerinden
HTTPS/public-address kontrolu ve yeniden DNS cozumleme yapar; redirect izlemez.
Canonical surum bundled registry manifest'indeki `1.121.3` ile eslesmelidir.
Provider/secret/transport hatalari public typed detail contract'ina cevrilir.

2026-08-03 itibariyla workflow yazmalari `(instance_id, workflow_id)` bazli ortak mutation
primitive'inden gecer. Ayni agent process'i icinde ayni workflow'a eszamanli
read-modify-write islemleri siralanir; farkli workflow'lar birbirini bekletmez.
Normal `update_workflow` mevcut node `id` degerlerini ve credential baglarini
korur, yeni/retype edilmis node'daki model-kaynakli `credentials` alanini atar;
credential degisikligi yalniz ownership/onay kontrollu dedicated attach
yollarindan yapilir. `connections` update'te verilmez veya bos verilirse mevcut
graf korunur; topology degisikligi tam ve non-empty connection payload'i ister.
Bu kural clarification sonrasi `create_workflow` ayni conversation workflow'una
dedupe oldugunda da gecerlidir; eksik connections mevcut branched grafi lineer
olarak yeniden kurmaz. Credential attach, committed n8n sonucunda istenen bagin
gercekten bulundugunu; generic HTTP auth icin ayrica
`authentication=genericCredentialType` ve dogru `genericAuthType` wiring'ini
dogrulamadan basari donmez. Lock process-local'dir. Gelecekte coklu agent replica veya
kullanicinin kendi n8n editor yazarlari icin distributed/optimistic concurrency
ve drift tespiti ayrica gerekecektir.

Ilgili notlar: [[n8n-registry]], [[chat-workflow-generation]],
[[known-issues]], [[customer-owned-n8n]].

## Workflow Assurance V1 (2026-07-16)

[[adr-0019-workflow-assurance-v1]] ile workflow create/update/run zincirine
ortak assurance katmani eklendi:

- Build pipeline native n8n JSON'i `agent/assurance` contract katalogu ile
  statik olarak inceler ve canonical fingerprint hesaplar. Schedule +
  Gmail/Sheets write-back akislari ilk action oncesinde runtime identity guard
  ile korunur.
- Sandbox V2 Gmail/Sheets side effect node'larini probe/stub'a cevirir;
  action/write-back count, bos required field ve identity riskini PII-safe
  ledger'da uzlastirir. Sonuc fingerprint ile metadata'ya yazilir.
- `WorkflowRunResultData` raw `status` yaninda `functionalStatus`, `assessment`
  ve `claimableOutcome` tasir. HTTP route'lari ayni veriyi snake_case additive
  contract ile sunar; `success` yalniz `verified/no_action` icindir.
- n8n Webhook `responseMode=lastNode` akisi sifir item uretilen temiz
  execution'da HTTP 500 + `No item to return was found` dondurebilir. Execution
  snapshot'i `success`, mutation runData'si bos ve runData mevcutsa bu exact
  sentinel transport failure sayilmaz; sonuc deterministik `no_action`
  (`0/0/0`) olur. Herhangi bir mutation calismissa veya execution hata
  durumundaysa ayni 500 normalize edilmez ve partial/failed davranisi korunur.
- `/preview-run` ve `/batch-preview` endpoint'leri side-effect run oncesi safe
  probe sonucu ve fingerprint/input-hash bagli, tek kullanimlik 10 dakikalik
  token verir. Run ve batch-run tokeni atomik tuketir; stale veya consumed token
  409 ile reddedilir. Chat `execute_workflow` tool'u da side-effect workflow'da
  ayni preview servisini kullanir, maskeli count/hedef ozetini gosterip
  `request_user_input` ile kullanici onayi bekler; sonraki turda yalniz gercek
  tek-kullanimlik token ile execution'a gecebilir.
- AgentDeps evidence ledger'i create/sandbox/run/inspect kanitini claim
  seviyesinde tutar. Output validator kaniti asan basari iddiasinda modele
  `ModelRetry` gondermez; cumle stream gate ile ayni deterministic policy'yi
  kullanarak dogrudan safe summary dondurur. Boylece dahili validator
  elestirisinin model tarafindan kullanici duzeltmesi gibi yorumlanmasi
  (`Haklisiniz...`) ve reddedilen ara taslagin stream/persist edilmesi engellenir.
  `action_verified`,
  partial contract coverage altinda node-specific runtime effect'i ayri tutar:
  Gmail send sonucu non-empty message `id` ve `SENT` etiketi tasiyorsa agent
  "mail gonderildi" diyebilir, fakat `run_verified` olmadan "tum workflow
  basariyla tamamlandi" diyemez. `no_action`, `action_verified` ve
  `run_verified` birbirinin yerine gecmez; explicit claim compatibility matrix
  kullanilir. Evidence item'i verifier effect turunu (`gmail_message_sent`)
  tasir; bu nedenle Gmail kaniti Sheet/status update claim'ini yetkilendirmez.
  `run_verified` da spesifik action cümleleri için aynı effect-scope kontrolünden
  geçer; whole-run doğrulaması ilgisiz bir mutation claim'ini açmaz.
  Claim gate ayni turdaki en son execution/inspect evidence kaydini esas alir;
  onceki execution kaniti yeni sonuca tasinmaz.
- Chat run preview onayi structured bir round-trip'tir: attachment opaque
  `requestId` + `workflowId` tasir, frontend `user_input_response` gonderir,
  route bunu authenticated user attachment'i olarak saklar ve runner yalniz
  son user mesajindaki karari AgentDeps'e yukler. Token prompt metnine
  eklenmez; server-side decision modelin yazdigi tokeni override eder ve bir
  kez tuketilir. Eski onaylar sonraki serbest mesajlarda yeniden kullanilmaz.
- Agent bir `user_input_request` beklerken output claim validator kanittan
  yuksek bir cumle gorurse yeni `ModelRetry` baslatmaz. Preview approval kendi
  deterministik "onizleme hazir, henuz side effect yok" ozetini; diger eksik
  alan/credential akislari genel "kullanici girdisi bekleniyor" ozetini
  kullanir. Persisted request karti tek otorite kalir; modelin
  readiness/execution tool'larina geri donmesi ve tek onayin iki izin gibi
  gorunmesi engellenir.
- Preview token gecersiz/stale/consumed ise veya known-side-effect sandbox
  harness'i calisamaz ya da repair butcesi biterse `awaiting_user_input` ayni
  turdaki yeni mutation denemelerini kapatir. Boylece ayni izin sorusu veya
  ayni sandbox duzeltmesi model loop'u icinde tekrar tekrar uretilmez.
- Preview consume sirasi validation-first'tur: single/batch runtime input
  metadata schema'sina gore kontrol edilmeden token transaction'da silinmez;
  fingerprint veya input hash uyusmazligi da tokeni yakmaz. Activation
  assurance'i `input_payload=None` ile schema sample'i uretir. Ilk gercek run
  oncesindeki gecikmis sandbox pretest'i varsa kullanicinin gercek input'u
  `_test_and_gate` uzerinden probe'a aktarilir.
- `list_credentials` custom/service API credential kutuphanesine ozeldir;
  managed Gmail/Sheets Connections durumunu temsil etmez. Platform-state bu
  iki listeyi ayri etiketler ve workflow node'u icin baglanti otoritesi
  `analyze_workflow_readiness` sonucudur.
- Sandbox probe degerlendirmesi action'a kadar olan tum upstream ancestor
  output'larini tarar. `undefined`/`null` gibi structured placeholder satirlari
  veya resolve olmamis n8n expression'i daha sonraki AI node'u tarafindan duzgun
  gorunen metne cevrilse bile real side effect oncesinde `needs_attention`
  uretir. Findings business payload'i loglamaz; yalniz etkilenen node adlarini
  tasir. Gmail probe ayrica `emailType` kaydeder; formatted digest/newsletter
  niyetinde text/ham Markdown ile rendered HTML uyusmazligi judge tarafindan
  reddedilir.
- IF v2+ node'lari n8n'e yazilmadan once canonical condition shape'e zorlanir:
  dolu `conditions.conditions` listesi ve her rule icin object
  `operator={type, operation}` gerekir; legacy/string operator ModelRetry ile
  reddedilir. Static assurance ayrica side-effect parametrelerinde dogrudan
  non-trigger predecessor icin `.first()` referansini blocking finding yapar;
  direct predecessor current item olarak `$json` ile okunmalidir. Sandbox,
  basit string `equals` IF'lerde branch
  output'unu predicate ile uzlastirir; celiski real side-effect onayini kapatir.
- Ayni fail-closed condition shape kontrolu `n8n-nodes-base.filter` v2+ icin de
  uygulanir. Tek-yollu satir elemede system prompt `Filter` node'unu IF/Code'a
  tercih eder. Code v2 `language` verilirse yalniz `javaScript|python|pythonNative`
  kabul edilir; JavaScript default'unda `jsCode` dolu olmak zorundadir. Boylece
  `language="javascript"` nedeniyle n8n runtime'inda `Parameter: jsCode` ile
  patlayan workflow n8n'e yazilmadan `ModelRetry` alir.
  Condition rule'lari ayrica dolu `leftValue` ister; binary operator'larda
  `rightValue` zorunludur, `isEmpty/isNotEmpty` gibi unary operator'lar bu sag
  operand zorunlulugundan muaftir.

Rollout `CONDUUT_WORKFLOW_ASSURANCE_MODE` ile `observe|hybrid|enforce` olarak
yonetilir; varsayilan `hybrid`'dir. Dashboard single/batch sonucu raw n8n
status yerine functional status ile renklendirir ve execution evidence'ini
Runs sayfasina baglar. n8n request debug loglari workflow/runtime payload
degerlerini yazmaz; yalniz payload key'leri, node type/count, connection count
ve row count gibi PII-safe teknik sekil ozeti tutulur.

## Assurance V2 ve Card Readiness (2026-07-23)

[[adr-0020-workflow-node-cards-assurance-v2]] su runtime sinirlarini ekler:

- Startup `workflow_cards.jsonl`, `node_cards.jsonl`, `retrieval.sqlite` ve
  `registry_manifest.json` hash/version uyumunu kontrol eder.
  `CONDUUT_WORKFLOW_CARD_RETRIEVAL_MODE=auto` production'da enforce, dev'de
  observe olur. Enforce eksik/uyumsuz artifact'te fail eder; observe legacy
  registry'ye warning ile duser. `/health` card readiness durumunu gosterir.
- Registry data path'i deployment baglamina gore cozulur: Docker image'inda
  `/app/data` (`apps/agent/data`), repo icinden local calismada ise
  `packages/n8n-registry/data` kullanilir. Boylece local agent generated
  card/index corpus'unu yanlislikla bos `apps/agent/data` altinda aramaz.
  Health/readiness detayi secilen `dataDir` yolunu da raporlar.
- Compose n8n default image'i ve agent'in bekledigi schema surumu ayni
  `CONDUUT_N8N_VERSION` (default `1.121.3`) degerine pinlidir. Docker agent
  runtime'inda provider factory'nin Groq adapter import'u icin `groq`
  dependency'si image'a acikca kurulur; registry startup'i provider import
  hatasi nedeniyle atlanmaz.
- Build pipeline dynamic contract resolution'dan sonra final validation yapar.
  Managed Sheets header okunamazsa veya `columns.value/matchingColumns` live
  header ile uyusmazsa write workflow n8n'e yazilmaz. Exact Gmail/Sheets
  side-effect contract'i yoksa fail-closed olur.
- `OracleContract` fingerprint, node contract hash, action/write-back rolleri,
  expected effect, identity, cardinality, typed postcondition, coverage ve
  claim scope'u tek yerde tasir. Sandbox preview ve execution assessment bu
  contract'i kullanir.
- Sandbox ledger'i typed `ProbeEvidence`'dir. Full contract-covered yolda LLM
  judge success otoritesi degildir. Basit Filter/IF status-loop projected ikinci
  turda `0/0/0` kanitlamalidir.
- Execution `workflowData` snapshot'i olmadan whole-run verified uretemez.
  Gmail receipt her output item icin sayilir. Sheets write-back bounded
  `read_range` ile identity/deger bazinda tekrar okunur; bu gecmeden en fazla
  effect-scoped `action_verified` olur. Write node kolon degeri dinamik n8n
  expression'i ise (ornegin `={{ $('IF').item.json.record_id }}`) remote
  karsilastirmadaki beklenen deger immutable write-node execution output'undan
  alinir; expression metni literal kimlik olarak aranmaz. Duz string sabitler
  (`Evet` gibi) yine configured postcondition olarak korunur.
- Firestore `execution_evidence` kaydi `executionId + evidenceHash` document
  anahtariyla append-only ve dedupe'dir. Raw execution/PII saklanmaz; bounded
  assessment, counts, effect/rule/claim state ve contract hash'i saklanir.
- Partial gercek side effect ilk kosuda auto-retry/compensation'i durdurur ve
  reconciliation icin acik onay ister. Runner cümle bazli stream claim gate ile
  kanitsiz basari cümlesini token yayinlanmadan degistirir.

## H2 Loop ve readiness kapanisi (2026-07-25)

`splitInBatches` artik build validation, semantic assurance ve sandbox
katmanlarinda typeVersion-aware denetlenir. v3'te per-item body `main[1]`,
post-loop `main[0]`; v2'de bunun tersidir. Loop body'nin done koluna
baglanmasi, geri-donus edge'inin olmamasi, done kolundan feedback verilmesi ve
done/loop kollarinin ortak bir node'da birlesip oradan loop'a donmesi blocking
finding'dir. Yalniz loop koluna ozel feedback edge'i sanctioned cycle sayilir;
genel `main_flow_cycle` kontrolu bunun disindaki donguleri gizlemez.

Sandbox functional oracle'i artik action node'unun en yakin Filter/IF/Loop
eligibility boundary'sini izler. Boundary pozitif item uretmisken action
calismadiysa run `no_action` kabul edilmez. Loop output item urettigi halde
downstream veya feedback yoksa ve feedback done koluyla ortaksa
`needs_attention` olur. Sifir-item `no_action` yalniz gercekten 0 eligibility
kaniti ile gecer.

Credential readiness ile test readiness ayrildi:
`credential_ready`, `test_required`, `test_status`, `test_coverage` ve
`ready_for_activation` ayri alanlardir. "Her sey hazir" ve "test gecti"
iddialari full sandbox kaniti olmadan claim gate'ten gecmez. Persisted sandbox
kaniti `WORKFLOW_TEST_POLICY_VERSION=2` ile surumlenir; eski v1 `passed` veya
`no_action` fingerprint'i ayni olsa bile activation oncesi yeniden test edilir.

## Conversation Execution Policy (2026-07-25)

[[adr-0021-chat-execution-policy]] backend conversation sozlesmesine
`execution_policy=safe|fast` ve `execution_policy_locked` alanlarini ekler.
Yeni conversation ilk user mesaji kabul edilirken policy ile olusturulur ve
kilitlenir; sonraki istekte persisted deger otoritedir. Legacy kayitlar
`safe + locked` olarak normalize edilir. Celisen explicit policy chat
route'unda `409 execution_policy_locked` olur.

Runner policy'yi request body'sinden dogrudan kullanmaz; conversation
store'dan cozulmus degeri `AgentDeps.execution_policy` olarak tool katmanina
tasir. Build tool'lari runtime sandbox calistirmaz. Chat manual execute
preview'i Safe icin `safe_sandbox`, Fast icin `fast_static` basis'i
uretir. Token store conversation, policy ve basis alanlarini fingerprint/input
hash ile birlikte kontrol eder.

Safe preview failure repair butcesi agent run basina iki denemedir; workflow
degisikligi sonrasi yeni preview `ModelRetry` ile istenir. Butce sonunda
workflow `needs_attention` ve run terminal olur. Fast static failure runtime
repair baslatmaz. Dashboard/batch route'lari ve activation yolu policy input'u
kabul etmez, Safe sinirini korur.
