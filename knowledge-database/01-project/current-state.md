# Current State

Merkez: [[index]]

Bu not, repo icin mevcut gercegi ozetler. Planlanan mimari icin
[[system-architecture]] ve `PROJECT.md` kullanilabilir, fakat kod yazarken
once bu not ve kaynak kod esas alinmalidir.

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

## Gercek Veriyle Bagli Olanlar

- Chat mesajlari, conversation listesi, workflow metadata, credential metadata
  ve artifact'lar Firestore'a yaziliyor. (BYO provider ayarlari/favorites
  [[adr-0011-conduut-managed-tiered-models]] ile kaldirildi.)
- Workflow dashboard shared n8n instance uzerinden workflow listeliyor,
  activate/deactivate/delete ve runtime input ile run islemleri yapiyor.
- Runs dashboard shared n8n execution API'sinden gercek run gecmisini,
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

- Per-user n8n container izolasyonu.
- Control plane.
- Node agent.
- Genel amacli OAuth proxy ve production secret isolation.
- PostgreSQL/pgvector, Redis, Vault.
- Stripe/billing.
- Monitoring: Prometheus, Grafana, Loki.

## Dokuman Uyumsuzluklari

- `PROJECT.md` hedef (uzun vadeli) mimariyi anlatir; mevcut MVP Firestore +
  shared n8n kullanir — kod yazarken bu not ve kaynak esas alinir.
- Kanonik agent rehberi `AGENTS.md`; root `CLAUDE.md` ince pointer'dir. Copilot
  talimat dosyalari (root + `.github/`) Faz 2'de kaldirildi. (bkz.
  [[workspace-refactor]])

## Branch Durumu

- 2026-05-09: `codex-pydantic-ai-agent-backend` artik deney dali degil;
  Pydantic AI tabanli agent altyapisi ana gelistirme zemini olarak `main`
  dalina fast-forward merge edildi.

Ilgili notlar: [[known-issues]], [[issue-backlog]],
[[adr-0001-shared-n8n-mvp]], [[adr-0002-firestore-mvp]],
[[adr-0003-google-oauth-broker-mvp]], [[adr-0006-platform-capability-layer]].
