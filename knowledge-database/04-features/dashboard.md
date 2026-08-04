# Dashboard

Merkez: [[index]]

Dashboard, workflow yonetimi ve hesap ayarlari icin MVP arayuzudur.

## Navigation

`apps/web/src/config/navigation.ts` ana dashboard nav'ini tutar:

- Chat.
- Workflows.
- Runs.
- Artifacts.
- Connections.
- Usage.
- Settings.

Yerel web dev script'i `next dev --webpack` kullanir. Next 16.2.1'in Turbopack
dev server'i Windows ortaminda ikinci seviye App Router route'larini
(`/dashboard/workflows`, `/dashboard/artifacts`, `/chat/[conversationId]` ve
nested API route'lari) 404'e dusurebildigi icin dashboard gelistirmesinde
Webpack dev server tercih edilir.

## Workflows

`/dashboard/workflows` gercek n8n API'sine baglidir:

- Workflow listesi alinir.
- Arama ve status filtresi vardir.
- Activate/deactivate optimistic update ile yapilir.
- Delete optimistic update ile yapilir.
- Workflow kartindaki Run aksiyonu footer'da status switch'inin yaninda
  durur; `inputSchema` varsa modal form acar, schema yoksa workflow'u input
  olmadan calistirir.
- Run formu backend'e `{ input, source: "dashboard" }` payload'i gonderir ve
  ayni Conduut run endpoint'ini agent ile paylasir.
- `inputSchema` olan workflow'larda Run modalinda `Run once` ve `Run batch`
  modlari vardir. Batch modunun iki kaynagi vardir (`File | Manual entry`
  alt-sekmesi):
  - **File** (varsayilan): kullanici `.xlsx`, `.xls` veya `.csv` dosyasi
    yukler; browser tarafinda `xlsx` ile sheet, header row, data row araligi ve
    workflow input field -> dosya kolonu/sabit deger eslemesi secilir.
  - **Manual entry**: kullanici degerleri elle, duzenlenebilir bir tabloda tek
    tek girer (sutunlar `inputSchema` alanlari, her satir bir calistirma; `Add
    row` / satir sil; 1 bos satirla baslar). Tamamen bos satirlar calistirma
    oncesi elenir; required alan dogrulamasi satir bazlidir.
  Her iki kaynak da ayni `{ rowNumber, input }` satir listesini (max 50) uretir
  ve ayni stream akisini kullanir; backend degismez (frontend-only).
- Batch run BFF payload'i `POST /api/workflows/{workflowId}?action=batch-run`
  uzerinden agent `POST /api/workflows/{workflow_id}/batch-run` endpoint'ine
  gider. Agent satirlari sequential calistirir, required input'u bos satirlari
  skip eder, hatali satirdan sonra kalan satirlara devam eder ve dashboard
  row-level success/failed/skipped sonuc modalini gosterir.
- Batch run UI artik `POST /api/workflows/{workflowId}?action=batch-run-stream`
  stream yolunu kullanir. Agent her satir icin `started`, `row_started`,
  `row_finished` ve `completed` SSE event'leri dondurur; dashboard bu event'lerle
  calisan satir / toplam satir sayisini, success/failed/skipped sayaclarini,
  progress bar'i ve client tarafinda uretilen kisa row input onizlemesini
  gosterir. Stream tamamlaninca mevcut batch sonuc modalina gecilir; stream
  hatasinda progress paneli hata durumunda kalir.
- Batch sonuc modalindaki her satir **genisletilebilir**: presentation veya ham
  cikti olan satirlara tiklaninca (chevron) satir acilir ve run once'daki gibi
  `WorkflowResultView` presentation karti + `RunOutputsDetails` (ham veri) inline
  gosterilir. Backend satir sonucu artik `presentation` + `outputs` tasir
  ([[adr-0017-workflow-result-presentation]] 2026-07-01 eki).
- Run sonucu Google Sheets artifact'i dondururse dashboard toast'a ek olarak
  sonuc panelinde `ArtifactPreview` karti gosterir. Bu kart kucuk tablo
  snapshot'i ve Google Sheets linki tasir; tam Sheets editoru degildir.
- Workflow kartinda uc nokta aksiyon menusu yoktur. Silme aksiyonu header'da
  status badge yanindaki cop kutusu butonudur; activate/deactivate yalnizca
  footer'daki switch ile yapilir.
- Workflow kartinda uzun workflow adlari tek satirda kisaltilir; fareyle adin
  uzerine gelince tam ad kart uzerinde kucuk tooltip olarak gosterilir.
- Delete aksiyonu calismadan once Conduut custom confirm dialog ile onay
  ister; yanlis menu tiklamasi veya stale UI durumunda dogrudan silme
  engellenir. Dialog altyapisi `ConfirmDialogProvider` + `useConfirm()`
  olarak reusable yazildi ve native `window.confirm` kullanimi kaldirildi.
- Workflow listesinde **toplu secim** modu vardir: toolbar'daki `Select`
  toggle'i secim moduna girer; kartlarda checkbox belirir, kart-ici
  Run/activate/tekil-sil gizlenir, ustte `BulkActionBar` (N selected /
  Select all / Cancel / Delete) cikar. Toplu silme simdilik tek toplu
  aksiyondur; backend'e batch endpoint eklenmedi — tekil
  `DELETE /api/workflows/{id}` cagrilari `Promise.allSettled` ile paralel
  yapilir, kismi hata "N deleted, M failed" toast + refetch ile resync edilir.
  Paylasilan parcalar: `components/ui/checkbox.tsx`,
  `hooks/use-multi-select.ts`, `components/dashboard/bulk-action-bar.tsx`.
- Activate/deactivate hatalarinda frontend artik agent/n8n hata mesajini
  gosterir. Eksik credential gibi durumlar genel `Could not update workflow
  status` mesaji arkasinda saklanmaz.

Veri akisi:

```text
Workflow page
  -> /api/workflows
  -> agent /api/workflows
  -> n8n_client.py
  -> shared n8n REST API

Workflow run
  -> /api/workflows/{workflowId}?action=run
  -> agent /api/workflows/{workflow_id}/run
  -> workflow_metadata input validation
  -> n8n webhook payload
  -> optional artifacts[] response

Workflow batch run
  -> browser builds rows from XLSX/CSV mapping OR manual-entry table
  -> /api/workflows/{workflowId}?action=batch-run-stream
  -> agent /api/workflows/{workflow_id}/batch-run/stream
  -> workflow_metadata input validation per row
  -> sequential n8n webhook payloads
  -> row-level SSE progress
  -> row-level results + optional artifacts[] final event
```

Run endpoint'i n8n'e JSON body ile POST atar. n8n Webhook node'unda
`httpMethod` eksikse n8n default GET kaydedebildigi icin agent mevcut workflow'u
run oncesi POST webhook'a patch'ler; boylece dashboard Run formundan alinan
runtime input production webhook tarafindan kabul edilir.

Run once sonucu HTTP olarak basarili donse bile execution `error`/`failed` ise
dashboard success toast gostermez; failed step ve hata sonuc panelinde yer alir.

## Runs

`/dashboard/runs`, shared n8n execution API'sine bagli gercek gecmis ekranidir.
Status/workflow filtresi, cursor `Load more`, timing/status listesi ve sanitize
detay paneli vardir. Hata detayindaki `Fix with Conduut`, exact execution id'yi
structured chat handoff'uyla agente tasir. Ayrinti: [[execution-history]].

MVP siniri: shared n8n nedeniyle workflow'lar user ownership ile filtrelenmez.
BYO hedefinde Runs BFF contract'i korunur; backend authenticated user'i
customer-owned n8n instance'a cozer ve liste/detail islemlerini yalniz o
instance'ta yapar ([[customer-owned-n8n]]).

## Artifacts

`/dashboard/artifacts` gercek artifact preview collection'ina baglidir:

- `GET /api/artifacts` BFF route'u agent `GET /api/artifacts` endpoint'ine
  Firebase token ile proxy eder.
- Sayfa `All`, `Sheets`, `Gmail` servis filtresi sunar.
- Sheets kayitlari dashboard'da `spreadsheetId` veya Google Sheets URL'i
  uzerinden gruplanir. Chat'te uretilen `spreadsheet.create`,
  `range.update`, `range.read` veya workflow run snapshot'lari Firestore'da ayri
  action kayitlari olarak kalir, fakat dashboard ayni Google Sheet icin tek
  resource karti gosterir.
- Sheets karti spreadsheet adini, sheet/range bilgisini, son tarihi, origin
  ozetini (`Chat`, `Workflow run` veya ikisi) ve en yeni gercek veri
  preview'ini gosterir. `Spreadsheet ID / Title / Sheet` gibi metadata-only
  create tablolarini veri preview'i olarak render etmez.
- Gmail kayitlari `message_preview` olarak render edilir. Kart Google Gmail
  servis bilgisini, origin/tarih ozetini, title/description alanlarini ve varsa
  `message.to`, `fromEmail`, `subject`, `query`, `resultCount`,
  `bodyPreview` veya `snippet` alanlarini gosterir; Gmail linki `Open`
  aksiyonuyla dis uygulamada acilir.
- Artifact kartlarinda cop kutusu aksiyonu vardir. Tek Gmail veya generic
  preview silindiginde ilgili artifact dokumani kaldirilir; Sheets resource
  karti birden fazla snapshot'i grupluyorsa silme aksiyonu o resource kartina
  ait tum preview dokumanlarini kaldirir.
- Artifacts listesinde de ayni **toplu secim + toplu silme** deseni vardir
  (paylasilan `useMultiSelect` + `BulkActionBar`, workflows ile ortak). Secim
  kart bazlidir; bir Sheets karti gruplu oldugundan silmede altindaki tum
  `artifactIds` duzlestirilir. `deleteArtifacts` artik `Promise.allSettled`
  kullanir (kismi hata toast + refetch).
- Tam spreadsheet/editor Conduut icinde acilmaz; kart yalniz kucuk preview ve
  Google Sheets `Open` linki tasir.
- Bos durumda kullanici chat'e yonlendirilir.

## Connections

`/dashboard/connections` artik Google Workspace permission pack modelini gercek
API ile yonetir:

- `GET /api/connections` ile kullanicinin connection metadata'si yuklenir.
- Ekran Gmail ve Sheets'i eskisi gibi ayri servis kartlari olarak gosterir.
  Her kartta arrow ile acilan permission pack bolumu vardir. Gmail karti
  Gmail Send, Gmail Read, Gmail Organize ve Gmail Full Control pack'lerini;
  Sheets karti Sheets App Files ve Sheets Full Access pack'lerini
  "Granted"/"Grant" durumlariyla listeler.
- Connection metadata'si `permissionPacks`, `directApiEnabled` ve
  `missingRecommendedCapabilities` alanlarini tasir. Bagli servis direct API
  token'i olmadan duruyorsa UI yeniden baglanma notu gosterir.
- Gmail ve Sheets servis kartlari logo icin inline SVG yerine
  `apps/web/public/images/icons/gmail_png.png` ve
  `apps/web/public/images/icons/sheets_png.png` asset'lerini kullanir.
- Kart grid'i `items-start` kullanir; bu sayede arrow ile izin bolumu
  kapatildiginda kart kendi icerik yuksekligine iner ve ayni satirdaki diger
  acik kartin yuksekligine stretch olmaz. Permission pack bolumu
  `framer-motion` ile height/opacity animasyonu kullanarak acilip kapanir; bu
  sayede dropdown hizli ve sert sekilde ziplayarak degismez.
- `Grant`, Firebase token ile Google OAuth authorize BFF route'unu cagirir:
  Gmail pack'leri `/api/oauth/google/authorize?service=gmail`, Sheets pack'leri
  `/api/oauth/google/authorize?service=sheets`. Body/query `permission_pack`
  veya chat OAuth prompt'undan gelen `requested_capabilities` tasiyabilir.
  Next 16 dev ortaminda `api/connections/google/.../authorize` route'lari
  `api/connections/[connectionId]` dinamik sibling'iyle ayni agac altinda 404
  verdigi icin authorize route'u `api/oauth/google` altina alindi.
  OAuth hata payload'lari nested `detail.message` formatindan okunur; UI'da
  `[object Object]` toast'i gosterilmez.
- Google callback `/api/oauth/google/callback` Next route'una gelir; bu route
  agent callback endpoint'ine code/state iletir ve sonra Connections sayfasina
  success/error query'siyle geri doner.
- `Disconnect`, legacy service connection id'si (`google_gmail` veya
  `google_sheets`) uzerinden Firestore metadata'yi siler ve n8n credential
  delete islemini agent tarafinda best-effort calistirir. Disconnect onayi da
  ayni custom confirm dialog uzerinden alinir.

MVP'de Google OAuth callback n8n credential yaratmaya devam eder. Ek olarak
`CONDUUT_CONNECTION_ENCRYPTION_KEY` varsa refresh token encrypted Firestore'da
saklanir ve direct Gmail/Sheets action'lari acilir. Vault/Secret Manager henuz
yoktur; profile/security/preferences gibi alanlar hala mock veya kismi
entegrasyondur. Usage token gozlemi gercek veriye baglidir; plan/billing yoktur.

## Usage

`/dashboard/usage`, tamamlanan Conduut agent run'larinin gercek token kullanimini
gosterir. Agent runner `result.usage()` icindeki input/output/cache token,
model-request ve tool-call sayilarini kullaniciya ait `usage_events`
collection'ina deterministic run kimligiyle append-only/idempotent kaydeder.
`GET /api/usage?days=1|7|30|90` ham event'lerden toplam, UTC gunluk seri ve
provider/model/tier kirilimi uretir; Next BFF ayni endpoint'i Firebase bearer
token ile proxy eder. Dashboard toplam/input/output token, tamamlanan run,
cache/request/tool ayrintisi ve trend sunar. Provider/model/tier kirilimi
backend gozlemi icin korunur ancak son kullanici arayuzunde gosterilmez.
`days` once HTTP query string'inden `int` olarak parse edilir, ardindan izinli
`1/7/30/90` degerleriyle sinirlanir; integer `Literal` dogrudan query tipi
olarak kullanilmaz.

Ilk kapsam billing metrigi degil, gozlemdir: yalniz basariyla tamamlanip
`_persist_and_done`'a ulasan final agent usage'i kaydedilir. Router tokenlari,
basarisiz recovery attempt'lari, terminal hata ve cancellation tuketimi dahil
degildir. Cache read/write ayri detaydir ve `total_tokens=input+output`
hesabina ikinci kez eklenmez. Tracking deployment oncesi loglari geriye donuk
aktarmaz. Plan, kredi, kota ve billing enforcement henuz yoktur. Workflow run
gecmisi `/dashboard/runs` altinda kalir ([[execution-history]]).

## Settings

`/dashboard/settings` bes tab icerir:

- Profile: UI var, kaydetme backend'e bagli degil.
- Security: UI var, password update backend'e bagli degil.
- Preferences: theme local behavior var, email notification kaydi yok.
- Assistant Connections: gercek LLM provider ekleme/listeleme/dogrulama akisi
  vardir.
- Automation Server: customer-owned n8n connect formu, provider-independent
  yeni kurulum rehberi, canonical version/health, stored-key check, key rotation
  ve uzak n8n verisini silmeyen disconnect aksiyonlarini sunar.

Next.js 16 route segment ayarlari statik analiz edildigi icin BYO BFF
route'larinin `dynamic` ve `runtime` degerleri her `route.ts` icinde literal
olarak export edilir; ortak helper'dan re-export edilmez.

Assistant Connections, Firestore'daki provider ve LLM settings dokumanlarini
kullanir. API key saklama sekli MVP icin yeterli kabul edilmis, production icin
guvenli degildir.

Chat, Workflows, Runs ve Credentials baglanti olmadan acilabilir. n8n gerektiren
aksiyonlar Automation Server sekmesine yonlendiren soft gate gosterir; chat tool
gereksiniminde `n8n_connection_prompt` attachment'i render eder. Metadata'siz
remote workflow `External` ve read-only gorunur; `Adopt` sonrasinda yonetilir.

Ilgili notlar: [[current-state]], [[chat-workflow-generation]],
[[known-issues]].
