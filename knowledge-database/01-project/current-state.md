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

- Chat mesajlari, conversation listesi, provider ayarlari ve favorites
  Firestore'a yaziliyor.
- Workflow dashboard shared n8n instance uzerinden workflow listeliyor,
  activate/deactivate/delete ve runtime input ile run islemleri yapiyor.
- Agent, workflow olustururken `search_n8n_nodes`, `get_node_schema` ve
  `find_workflow_template` tool'larini kullanabiliyor.
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

## Stub veya Mock Olanlar

- Usage sayfasi mock usage ve execution history kullaniyor.
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

- `PROJECT.md` ve eski Copilot talimatlari hedef mimariyi anlatir; mevcut MVP
  Firestore ve shared n8n kullanir.
- `.github/copilot-instructions.md` icinde `apps/control-plane` gibi henuz
  bulunmayan yollar ve eski moduller geciyor.
- Root `CLAUDE.md` daha gunceldir, ancak yine de kod ve manifestlerle
  dogrulanmalidir.

## Branch Durumu

- 2026-05-09: `codex-pydantic-ai-agent-backend` artik deney dali degil;
  Pydantic AI tabanli agent altyapisi ana gelistirme zemini olarak `main`
  dalina fast-forward merge edildi.

Ilgili notlar: [[known-issues]], [[issue-backlog]],
[[adr-0001-shared-n8n-mvp]], [[adr-0002-firestore-mvp]],
[[adr-0003-google-oauth-broker-mvp]], [[adr-0006-platform-capability-layer]].
