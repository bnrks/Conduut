# Current State

Merkez: [[index]]

Bu not, repo icin mevcut gercegi ozetler. Planlanan mimari icin
[[system-architecture]] ve `PROJECT.md` kullanilabilir, fakat kod yazarken
once bu not ve kaynak kod esas alinmalidir.

Google Cloud production foundation icin kabul edilen hedef ve asamali uygulama
plani [[google-cloud-production-foundation]] ile
[[adr-0023-google-cloud-secret-and-runtime-foundation]] notlarindadir. Bootstrap
ve secret-only staging temeli canlidir; production/runtime kaynaklari kurulmus
kabul edilmemelidir. Repo icinde `infra/terraform/bootstrap`,
`infra/terraform/modules/conduut-environment`,
`infra/terraform/environments/staging` bulunur. Repo su anda GitHub Actions
workflow'u icermez. Cloud Run, Artifact Registry repository ve staging VPC/NAT
flag'lerle kapali tutulur.

## Calisan Parcalar

- `apps/web`: Next.js 16 frontend, React 19, Tailwind CSS 4, Firebase client
  auth, chat UI, dashboard shell, auth sayfalari ve BFF API route'lari.
- `apps/agent`: FastAPI servis, Firebase token dogrulama, Firestore store,
  Pydantic AI tabanli agent runner, SSE streaming, n8n workflow tool'lari.
- `packages/n8n-registry`: n8n node schema ve template bilgisini lookup
  tool'lari icin hazirlayan Python paketi.
- `docker-compose.yml`: shared n8n, agent ve web servislerini lokal/dev ortamda
  ayaga kaldirir.
- `start-local-dev.bat`: hizli Windows lokal gelistirme icin sadece n8n'i
  Docker Compose ile calistirir; agent'i lokal Uvicorn reload, web'i lokal
  `npm run dev` ile ayaga kaldirir.
- Customer-owned n8n V1: authenticated kullaniciyi aktif instance'a cozen
  request-scope provider/client, pluggable secret store, guvenli connect/check/rotate/
  disconnect, migration ve web onboarding yuzeyleri uygulanmistir. Aktif
  customer-owned instance'taki workflow'lar ek `External/Adopt` adimi olmadan
  dogrudan yonetilir.
  Local customer-owned testte API key restartlar arasinda Git-ignored
  Fernet-encrypted file store'da kalir; production hala Google Secret Manager
  ve IAM kurulumu ister. Shared n8n yalniz `shared_dev` local gelistirme
  adapter'idir.
- Google Cloud foundation repo implementasyonu: backend GSM secret adlari PII-free hash,
  delayed-destruction rotation ve ADC/certificate Firebase init matrisi ile
  sertlesti. Web BFF agent cagrilari ortak server-only client'a tasindi; private
  Cloud Run agent icin `X-Serverless-Authorization` header destegi repo
  seviyesinde vardir. Terraform bootstrap/staging modulleri vardir; bootstrap ve
  secret-only apply canlidir. Ilk WIF image deploy workflow'u dogrulanmis olsa da
  kullanici karariyla repodan kaldirilmistir; uygulama deploy'u ve staging pilotu
  henuz yapilmamistir.
- Canli GCP foundation hazirligi: `conduut-1` billing/Firebase/Firestore
  envanteri dogrulandi; Firestore Native `(default)` database `europe-west3`
  bolgesindedir. Cloud Run, Artifact Registry, Secret Manager, Compute, IAM,
  IAM Credentials ve STS API'leri 2026-08-25'te etkinlestirildi. Tek-project
  Secret-only Terraform plan'i `35 add, 0 change, 0 destroy` verdi ve uygulandi.
- Bootstrap foundation canlidir: `conduut-1-terraform-state` GCS remote backend,
  GitHub WIF pool/provider ve `github-actions-deployer` service account
  olusturuldu; WIF yalniz `bnrks/Conduut` `main` ref'ini kabul eder. Sonraki
  bootstrap plan'i `No changes` verdi. Ayrica bes regional Secret Manager
  container'i, `staging-agent`/`staging-web` service account'lari ve sinirli
  agent IAM binding'leri olusturuldu; staging remote state dogrulandi ve sonraki
  plan `No changes` verdi. Bes secret'in guncel version'lari Terraform/Git'e
  deger yazmadan seed edildi ve byte-level readback ile dogrulandi. CRLF'li ilk
  deneme version'lari disabled ve yedi gunluk delayed destruction altindadir;
  kullanilmayan bos Anthropic, OpenAI ve OpenRouter container'lari kaldirildi.
  `staging-agent` statik read, tenant-prefix create/add/read/delete ve prefix-disi
  read-denied canary'lerini gecti; gecici binding/canary kaynaklari temizlendi. Cloud Run,
  Artifact Registry repository ve staging VPC/NAT olusturulmadi. GitHub Actions
  workflow'u yoktur, GitHub variable'lari set edilmemistir ve deploy service
  account project-level role almaz.
- Kullanici karari: GitHub Actions simdi kullanilmayacak. Workflow,
  environment variable'lari, deploy IAM rolleri ve deploy enable flag'i ancak
  uygulamayi canliya alma calismasi acikca baslatildiginda eklenecek.

## Gercek Veriyle Bagli Olanlar

- Chat mesajlari, conversation listesi, workflow metadata, credential metadata
  ve artifact'lar Firestore'a yaziliyor. (BYO provider ayarlari/favorites
  [[adr-0011-conduut-managed-tiered-models]] ile kaldirildi.)
- Workflow dashboard secili provider target'i uzerinden workflow listeliyor,
  activate/deactivate/delete ve runtime input ile run islemleri yapiyor.
- Runs dashboard secili n8n instance'inin execution API'sinden gercek run gecmisini,
  status/timing ve redakte hata detayini listeliyor; basarisiz run agent chat'ine
  structured `execution_reference` ile gonderilebiliyor ([[execution-history]]).
- Agent, workflow olustururken `search_n8n_nodes`, `get_node_schema` ve
  `find_workflow_template` tool'larini kullanabiliyor.
- Workflow generation tek kompakt-JSON yuzeyi uzerinden: model
  `create_workflow`/`update_workflow` ile n8n JSON yazar, `agent/repair.py` bunu
  deterministik onarir (boilerplate, lineer wiring, AI sub-node portlari,
  runtime-input expression'lari). Eski IR compiler yollari
  (`create_workflow_from_plan`/`_spec`/`_graph` + WorkflowPlan/Spec/Graph IR'lari)
  [[adr-0010-json-surface-repair-normalizer]] ile supersede edildi ve Faz 3'te
  koddan kaldirildi (eski tasarim: [[adr-0005-workflow-spec-compiler]],
  [[adr-0008-typed-workflow-intent-engine]], [[adr-0009-workflow-graph-compiler]]).
- Connections sayfasi Google Gmail ve Sheets permission pack OAuth akisiyle
  gercek connection listeleme, connect/reconnect, pack grant ve disconnect
  islemlerine bagli.
- Gmail/Sheets workflow'lari kullanicinin managed Google connection'i ve
  gereken canonical capability'si varsa n8n credential'ini otomatik attach
  edebiliyor.
- Agent direct platform action katmaniyla Gmail send/read/organize ve Sheets
  create/read/update/append islemlerini n8n workflow yazmadan yapabiliyor.
- Google Sheets direct action ve desteklenen workflow run sonuclari chat ve
  dashboard'da `artifact_preview` karti olarak kucuk tablo snapshot'i ve Sheets
  linki gosterebiliyor.
- Artifact preview snapshot'lari `users/{uid}/artifacts` Firestore
  collection'ina kaydediliyor ve `/dashboard/artifacts` sayfasinda
  listeleniyor.
- Sheets append workflow planinda Sheet ID yoksa ama spreadsheet title varsa
  agent direct Sheets API ile spreadsheet'i bir kez olusturup workflow
  metadata'sina resource olarak kaydedebiliyor.
- Gmail send workflow'lari `to`, `subject`, `message` runtime input schema'si
  ile tekrar kullanilabilir sekilde calistirilabiliyor; dashboard ve agent ayni
  run endpoint'ini kullaniyor.
- Tamamlanan agent run'larinin input/output/cache token, model request ve tool
  call sayilari `users/{uid}/usage_events` altinda immutable/idempotent event
  olarak kaydediliyor. `/dashboard/usage`, gercek `/api/usage` ozetiyle son 24
  saat, 7, 30 veya 90 gunu ve provider/model/tier kirilimini gosteriyor.

## Stub veya Mock Olanlar

- Plan, kredi, kota ve billing enforcement henuz yoktur. Usage token takibi
  gercektir; router cagrilari, basarisiz retry attempt'lari ve iptal edilen
  run'lar bu ilk gozlem kapsaminda degildir.
- Settings icindeki profile, password ve preferences kaydetme aksiyonlari tam
  backend entegrasyonuna sahip degil.
- Sidebar kullanici bilgisi bazi yerlerde mock.

## Eksik Kritik Sistemler

- Customer-owned n8n icin iki gerçek public instance pilotu ve production
  rollout/observability kaniti.
- Production deployment'ta application SSRF kontrolune ek ag-seviyesi egress
  bloklari ve Google Secret Manager IAM kurulumu.
- Canonical `1.121.3` disindaki n8n surumleri icin compatibility calismasi.
- Genel amacli OAuth proxy ve production secret isolation.
- PostgreSQL/pgvector, Redis, Vault.
- Stripe/billing.
- Monitoring: Prometheus, Grafana, Loki.

Control plane, node-agent ve Conduut-managed per-user container aktif BYO
roadmap'inin parcasi degildir; managed hosting alternatifi olarak ertelenmistir
([[adr-0022-customer-owned-n8n]]).

## Dokuman Uyumsuzluklari

- `PROJECT.md` icindeki control-plane/per-user-container plani ertelenmis managed
  vizyonu anlatir. Aktif production hedefi [[customer-owned-n8n]] ve
  [[adr-0022-customer-owned-n8n]] icindedir; mevcut MVP ise Firestore + shared
  n8n kullanir.
- Kanonik agent rehberi `AGENTS.md`; root `CLAUDE.md` ince pointer'dir. Copilot
  talimat dosyalari (root + `.github/`) Faz 2'de kaldirildi. (bkz.
  [[workspace-refactor]])

## Branch Durumu

- 2026-08-03: `codex/byo-n8n-v1`, customer-owned n8n provider, migration,
  onboarding ve tam n8n cagri zinciri cutover uygulama dalidir.

- 2026-05-09: `codex-pydantic-ai-agent-backend` artik deney dali degil;
  Pydantic AI tabanli agent altyapisi ana gelistirme zemini olarak `main`
  dalina fast-forward merge edildi.

Ilgili notlar: [[known-issues]], [[issue-backlog]],
[[adr-0001-shared-n8n-mvp]], [[adr-0002-firestore-mvp]],
[[adr-0003-google-oauth-broker-mvp]], [[adr-0006-platform-capability-layer]],
[[customer-owned-n8n]], [[adr-0022-customer-owned-n8n]].
