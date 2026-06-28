# Artifacts

Merkez: [[index]]

Artifacts, Conduut'un bagli platformlarda olusan veya okunan somut ciktilari
chat ve dashboard icinde kucuk, guvenli onizleme kartlari olarak gostermesi
icin tasarlanan urun yuzeyidir.

## Durum

Artifacts V1, 2026-05-25 itibariyla Google Sheets create + range update akisi
icin end-to-end smoke testten gecti. Logda iki `artifact_preview` attachment'i
emit edildi, spreadsheet create ve `Leads!A1` range update Google API'den 200
dondu, chat UI hem linki hem tablo onizlemesini gosterdi. Ayni incelemede
Firestore'un nested array kabul etmemesi nedeniyle assistant message write
hatasina neden olan `table.rows: string[][]` formati duzeltildi; rows artik
kolon adina gore maplenen satir objeleri olarak saklanir.
2026-05-27'de gecmis chat yuklemelerinde artifact kartlarinin kaybolmus gibi
gorunmesine neden olan web/API shape uyumsuzlugu da duzeltildi: conversation
detail response'u artik `createdAt`, `messageCount`, `reasoningEffort` gibi
camelCase alanlari snake_case alanlarla birlikte dondurur; web chat sayfasi
gecmis mesajlari normalize ederek `assistant` rolunu `agent` UI rolune cevirir
ve `artifact_preview` attachment'larini korur.
2026-05-27'de Dashboard Artifacts V1 uygulandi: chat ve workflow run
sonuclarinda uretilen `artifact_preview` snapshot'lari artik
`users/{uid}/artifacts/{artifactId}` Firestore collection'ina deterministik id
ile yazilir ve `/dashboard/artifacts` sayfasinda kucuk preview kartlari olarak
listelenir.
2026-05-27'de dashboard gosterimi resource bazli hale getirildi: Google Sheets
icin Firestore'da action-level snapshot'lar kalmaya devam eder, ancak
`/dashboard/artifacts` ayni `spreadsheetId` altindaki create/update/read
snapshot'larini tek Sheet kartinda gruplayarak gosterir. `spreadsheet.create`
sonucundaki `Spreadsheet ID / Title / Sheet` metadata tablosu artik dashboard'da
veri preview'i gibi basilmiyor; kart basligi spreadsheet adindan, detaylari
sheet/range bilgisinden, tablo preview'i ise en yeni gercek veri snapshot'indan
uretiliyor.
2026-05-27'de Gmail artifacts kapsam disindan V1'e alindi: direct Gmail
action'lari ve Gmail node'u iceren workflow run sonuclari artik
`artifact_preview` attachment'i olarak `service=gmail`, `type=message_preview`
ve `message` ozet payload'i uretir. Chat karti alici/konu/govde veya snippet
onizlemesini gosterir; dashboard `Artifacts` sayfasi Gmail filtresinde ayni
kalici snapshot'lari mail karti olarak listeler.
2026-05-27 Gmail send -> Google Sheets append workflow smoke testinde n8n
execution basarili olsa da `run_time` kolonu literal `NOW()` olarak yazildi.
Compiler fix'iyle `WorkflowPlan` icindeki Sheets append kolon degeri `NOW()`
veya `=NOW()` ise Set node artik `={{$now.toISO()}}` uretir; boylece log
satirlarinda gercek calisma zamani yazilir. Ayni oturumda mevcut smoke test
workflow'u `DKBOwrgfTcSPnNSt` de n8n API ile patch'lendi ve aktif kaldi.
Ilk manuel testte "gelen son maili artifact olarak kaydet" isteginde model once
`gmail.message.search(query="in:inbox")`, sonra bos `message_id` ile
`gmail.message.get` cagirdi; backend bos id'yi Gmail list endpoint'ine
dusurdugu icin tek mail yerine inbox ozeti artifact oldu. 2026-05-27 fix'iyle
Gmail search sonucundaki ilk message id `AgentDeps.platform_resources.gmail`
baglamina yazilir; takip eden get/mark/archive/trash/label action'i bos
`message_id` tasirsa bu context kullanilir, context de yoksa Google API'ye
bos id ile gidilmeden `missing_input` doner.

2026-06-28'de Dashboard `Artifacts` sayfasinin "yuklenemiyor" hatasi (yalniz
Sheets geliyor, Gmail patliyor) cozuldu. Kok neden: batch workflow run'lari
(ADR-0007) artifact'i `origin.kind="workflow_batch_run"` ile kaydediyor
(`routes/workflows.py:88`), ama read-side response modeli
`ArtifactOriginOut.kind` yalnizca `Literal["chat","workflow_run"]` kabul
ediyordu. `GET /api/artifacts` tum listeyi serialize ederken bu tek kayitta
`ValidationError` firlatip 500 donuyordu; `?service=google_sheets` filtresi
calistigi icin (kotu kayit bir Gmail batch artifact'iydi) yalniz Sheets
geliyordu. Loglarda kanit: `1 validation error for ArtifactOriginOut / kind /
Input should be 'chat' or 'workflow_run' [input_value='workflow_batch_run']`.
Fix (`routes/artifacts.py`, TDD): (1) read-path origin-kind normalizasyonu —
`workflow_batch_run` → `workflow_run` alias'i (batch run, batch alanlarini
zaten gostermeyen kontrat icin sade bir workflow run'dir); bilinmeyen kind →
`chat` fallback. (2) Defense-in-depth: liste serileştirmesi artik kayit-bazli
`try/except ValidationError`; tek bozuk kayit (orn. beklenmeyen `service`)
`artifact_serialize_skipped` uyarisiyla atlanir, tum sayfayi 500'lemez. Hem
mevcut hem gelecekteki batch artifact'lari duzeltir; frontend `workflow_run`'i
zaten dogru etiketler (degisiklik gerekmedi). Yeni testler:
`test_list_artifacts_normalizes_batch_run_origin`,
`test_list_artifacts_skips_unserializable_artifact`. **Backend 388 passed
(5 on-mevcut Windows-tmp), ruff temiz.** Not: write tarafi `workflow_batch_run`'i
(zengin `batchRunId`/`rowNumber` ile) kasitli olarak korur.

## V1 Kapsami

- Ilk kapsam Google Sheets ve Gmail icindir.
- Artifact modeli Google Sheets icin `table preview + external link`, Gmail
  icin `message preview + Gmail link` seklindedir.
- Chat'te agent mesajina `artifact_preview` attachment olarak eklenir.
- Dashboard workflow run sonucunda toast'a ek olarak sonuc panelinde gosterilir.
- Dashboard `Artifacts` bolumu son artifact snapshot'larini kalici olarak
  listeler; Sheets icin listeleme action kaydi degil spreadsheet resource karti
  olarak gruplanir, Gmail icin message snapshot'lari mail karti olarak kalir.
- Dashboard kartlari artifact preview silmeyi destekler. Gmail/generic kartta
  tek dokuman silinir; Sheets resource kartinda ayni gruptaki preview
  dokumanlari birlikte silinir.
- Kalicilik `users/{uid}/artifacts/{artifactId}` collection'indadir; chat
  attachment snapshot'i conversation history icinde de korunur.

## V1 Davranisi

- Backend `artifact_preview` attachment tipi uretir.
- Payload `service`, `title`, `description`, `url`, `source` ve opsiyonel
  `table` veya `message` alanlarini tasir.
- Google Sheets tablo onizlemesi en fazla 10 satir ve 12 kolon gosterir.
- `table.columns` sirali kolon listesidir; `table.rows` Firestore uyumlulugu
  icin nested array degil, kolon adindan hucre preview'ine giden satir
  objeleri listesi olarak saklanir.
- Gmail message onizlemesi `messageId`, `threadId`, `to`, `fromEmail`,
  `subject`, `snippet`, `bodyPreview`, `labels`, `query` ve `resultCount`
  gibi guvenli ozet alanlarini tasiyabilir. Direct send action'i kullanicinin
  verdigi recipient/subject/body preview'inden kart olusturur; search/get ve
  mark/archive/trash/label action'lari Gmail API sonucundaki mesaj id, snippet
  ve label ozetini kullanir.
- Hucre degerleri kisa preview'e indirgenir; token, secret, credential,
  authorization ve password benzeri alanlar artifact tablosuna veya message
  payload'ina alinmaz.
- Tam veri dogrulama kaynagi ilgili Google uygulamasi linkidir; Conduut
  yalnizca kucuk kanit/ozet onizlemesi gosterir.
- Artifact kayit id'si `service`, `title`, `url`, `source.spreadsheetId`,
  `source.range`, `source.messageId`, `source.threadId`, `source.query`,
  `source.action` ve origin (`chat` veya `workflow_run`) baglamindan
  deterministik uretilir; ayni artifact yeniden yazilirsa ayni dokuman
  guncellenir.
- `GET /api/artifacts` son preview snapshot'larini `createdAt` camelCase alani
  ve `origin` metadata'siyle dondurur. Web BFF ayni endpoint'i
  `/api/artifacts` altindan dashboard'a proxy eder.
- `DELETE /api/artifacts/{artifactId}` current user altindaki kalici preview
  dokumanini siler. Chat message attachment snapshot'i conversation history'de
  kalmaya devam eder.
- Dashboard gosterimi backend'in dondurdugu ham action snapshot'larini
  degistirmez; yalniz UI'da `spreadsheetId`/URL bazli gruplayip spreadsheet
  adini, sheet/range bilgisini, son tarihi ve guvenli kucuk veri preview'ini
  tek kartta sunar. Bu sayede ayni Sheet icin `Google Sheets spreadsheet
  created` ve `Google Sheets range updated` gibi iki ayri aksiyon karti
  gorunmez.
- Tek seferlik "yeni spreadsheet + yeni tab + veri yaz" akisinda agent once
  `sheets.spreadsheet.create`, sonra `sheets.range.update` kullanmalidir.
  `range.update` ve `row.append` hedef `sheet_name`/range icin tab yoksa direct
  Sheets client onu once olusturur; `sheets.sheet.create` ayni tab zaten varsa
  idempotent basari dondurur. Boylece artifact testlerinde spreadsheet
  olusup veri yazma adiminin tab hatasiyla yarida kalmasi engellenir.
- Artifact snapshot'i yalniz UI karti degil, sonraki agent turlari icin resource
  baglamidir. Runner en son Google Sheets artifact'inden `spreadsheetId`, link
  ve sheet/range bilgisini `AgentDeps.platform_resources` icine alir.
- Gecmis conversation detail payload'lari snake_case veya `assistant` roluyla
  gelse bile web normalizer bunlari chat UI'in bekledigi camelCase mesaj
  seklinde render eder; artifact kartlari bu normalize katmanindan sonra
  attachment olarak korunur.
- Direct Sheets action'lari ayni turdaki basarili create/read/write
  sonuclarindan da resource baglamini gunceller. Sonraki read/update/append
  cagrilari `spreadsheet_id` eksikse bu baglamdan tamamlar.
- Backend bos `spreadsheet_id` ile Google API'ye gitmez; resource baglami da
  yoksa `missing_input` dondurur. Bu, `spreadsheets//...` 404 dongulerini ve
  "tekrar dene" mesajinda yeni spreadsheet acma egilimini azaltir.
- Workflow run artifact'lari agent icindeki execution output ozetinden
  uretilir. Sheets icin `Prepare Sheets Row` veya Google Sheets node output'u
  preview tablosuna cevrilir; Gmail node output'u mesaj id/thread id/label
  ozetiyle message preview'e cevrilir.

## V1 Disi

- Tam tablo editoru veya Sheets klonu yoktur.
- Share/retention UI yoktur.
- Uzun donem retention policy yoktur.
- Arbitrary n8n workflow'larinin her platform ciktisini otomatik anlamasi
  hedeflenmez; V1 Conduut'un bildigi Sheets direct action ve workflow run
  ciktisina odaklanir.

## Gelecek Buyume

- Dosya, rapor, CSV, PDF veya image artifact tipleri.
- Retention, privacy, paylasim ve silme politikalari.
- Platform adapter modeli: her platform action pack kendi artifact
  builder'ini tanimlar.

Ilgili notlar: [[chat-workflow-generation]], [[agent-service]], [[web-app]],
[[dashboard]], [[feature-backlog]].
