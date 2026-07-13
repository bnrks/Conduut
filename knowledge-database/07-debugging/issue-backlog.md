# Issue Backlog

Merkez: [[index]]

Bu not, kullanicinin fark ettigi cozulmesi gereken sorunlari, buglari ve
iyilestirme adaylarini hizlica kaydetmesi icin ayrilmis triage alanidir.

Detaylandirilmis ve proje gercegi olarak kabul edilmis maddeler gerekirse
[[known-issues]], [[current-state]] veya ilgili servis/feature notuna tasinir.

## Nasil Kullanilir

- Yeni bir sorun goruldugunde once `Triage Bekleyenler` altina kisa bir madde
  ekle.
- Biliniyorsa etkilenen alan icin [[web-app]], [[agent-service]],
  [[n8n-registry]], [[dashboard]] veya [[chat-workflow-generation]] linkini
  kullan.
- Sorun davranisi netlestiginde `Aktif Buglar`, `Cozulecek Sorunlar` veya
  `Kapananlar` bolumune tasi.
- Kalici teknik borc ya da dikkat noktasi haline gelenleri [[known-issues]]
  notuna bagla.

## Triage Bekleyenler

<!-- Yeni fark edilen sorunlari buraya ekle.

Ornek format:
- [ ] Kisa baslik - Etkilenen alan: [[web-app]] / [[agent-service]].
  Not: Beklenen davranis, gorulen davranis, varsa tarih veya tekrar adimi.
  
-->

- [ ] Workflow duzenleyebilme ozelligi eklenecek - Etkilenen alan:
  [[dashboard]] / [[chat-workflow-generation]].
  Not: Bug degil; kullanicinin workflow'lari sonradan duzenleyebilmesi icin
  urun/UX ihtiyaci.
- [ ] Workflow olusturma sonrasi chat'te bos mesaj balonu gorunuyor -
  Etkilenen alan: [[web-app]] / [[chat-workflow-generation]].
  Not: Workflow component'i ekrana yazildiktan sonra agent mesaji en son
  geldigi icin mesaj once geliyormus gibi bos bir baloncuk gorunuyor.
  Triage: 2026-05-15 kod incelemesinde `Message` component'inin bos text ve
  attachment olmayan mesajlari render etmedigi goruldu. Olasilik daha cok
  stream acikken `MessageList` icindeki typing indicator balonunun workflow
  preview attachment'i geldikten sonra da gorunmesi. Browser ile yeniden
  uretilip gerekirse attachment geldikten sonra indicator davranisi ayrilmali.
## Aktif Buglar

<!-- Triage sonrasi bug olarak dogrulanan maddeler buraya tasinir. -->

- [x] Kompleks teklif otomasyonu istegi agent lookup dongusunde request limit'e
  takiliyor - Etkilenen alan: [[chat-workflow-generation]] /
  [[agent-service]] / [[n8n-registry]].
  ✅ Eskidi (2026-06-30, Faz 3): Kok-neden olarak gosterilen `WorkflowPlan` IR'i,
  sinirli aksiyon seti (`gmail.send`/`sheets.*`/`core.filter`) ve
  `create_workflow_from_plan` tool'u tamamen kaldirildi; canli yol genel kompakt
  n8n JSON yuzeyi (`create_workflow`/`update_workflow`) + `repair.py`
  ([[adr-0010-json-surface-repair-normalizer]]). Registry Gmail operation loader
  fix'i (asagida) gecerli kaldi. Bu IR-yolu lookup-dongusu sorunu gecersiz;
  request-limit dongusu tekrar gorulurse kompakt-JSON yoluna gore yeniden triage
  edilmeli. Tarihsel kayit asagida korunur.
  Not: 2026-06-04 gercek dunya testi: kullanici runtime input olarak firma
  ismi, firma maili, firma ozeti ve teklif verilebilecek servisleri alip her
  firma icin AI ile ozel teklif metni hazirlayan ve Gmail ile gonderen otomatik
  teklif workflow'u istedi. Log request_id
  `c66ef24c-6550-400d-a1da-165f61e4f6b6`, conversation
  `db539fce-de8c-4302-946f-b5763139acce`. Agent `gpt-5` + `medium`
  reasoning ile basladi, OpenAI yanitlari 200 dondu, fakat
  `search_n8n_nodes` ve `get_node_schema` arasinda donup
  `create_workflow_from_plan`, `request_user_input` veya n8n workflow create
  asamasina hic gecemedi. Son hata:
  `agent_usage_limit_exceeded` / `The next request would exceed the
  request_limit of 12`, `attachment_count=0`. Kok neden adayi:
  `WorkflowPlan` su an `gmail.send`, `sheets.row.append`,
  `sheets.read_rows`, `core.filter` ile sinirli; AI metin uretme aksiyonu ve
  cok alanli teklif workflow'u icin semantic action/compiler destegi yok.
  Beklenen davranis: agent ya desteklenen deterministic bir `llm.generate` /
  email compose action graph'ina compile etmeli ya da ilk bloklayici eksik
  bilgiyi `request_user_input` ile sormalidir; lookup dongusunde generic
  max-rounds hatasina dusmemelidir.
  Uygulama: 2026-06-04'te compiler case'lerini buyutmek yerine generative
  authoring yolu eklendi. Agent artik exact n8n schema lookup yapip raw n8n
  node/connection draft'i uretmeli, `validate_workflow_draft` ile side
  effect'siz dogrulamali, validation veya n8n 4xx hatalarini ModelRetry ile
  tamir etmeli ve yalniz valid draft'i `create_workflow` ile yazmali. Teklif
  metni gibi AI text uretimi icin n8n workflow'larinin kullanabilecegi internal
  `POST /api/internal/llm/generate` endpoint'i eklendi. Unit/integration
  testleri gecti; canli chat -> n8n E2E tekrar testi henuz yapilmadi.
  Canli tekrar: 2026-06-04 request
  `f04d332d-6114-469c-839b-01f8b4cb7e0e`, conversation
  `90b1dfa3-645d-4a48-8c22-d95aed3c0fda`. Agent lookup ve draft validation
  akisina girdi, fakat ilk draft'ta Gmail `operation=send` validator tarafindan
  hatali reddedildi; sonra `create` ve `emailSend` alternatiflerini ararken
  `The next request would exceed the request_limit of 12` hatasiyla durdu.
  Kök neden `packages/n8n-registry` loader'inin Gmail gibi node'larda yalniz
  ilk `operation` property'sini okuyup `message/send` operasyonunu global
  operation listesine eklememesiydi. Loader tum operation property'lerini
  resource baglaminda toplayacak sekilde duzeltildi; registry testleri gecti.

## Cozulecek Sorunlar

<!-- Bug olmayabilir ama duzeltilmesi gereken urun/teknik sorunlar buraya tasinir. -->

- [ ] n8n LLM/API-key node credential auto-injection (broker) - Etkilenen alan:
  [[agent-service]] / [[system-architecture]].
  Not: 2026-06-15 canli testte AI workflow'u (OpenAI Chat Model) calistirilirken
  n8n node'u kendi `openAiApi` credential'ina ihtiyac duydu; kullanici elle
  bagladi ("missing credential"). Bu credential, agent'in workflow'u KURMAK icin
  kullandigi app-side LLM key'inden (artik Conduut-yonetimli env key'leri + tier
  router, [[adr-0011-conduut-managed-tiered-models]]; eski BYO `ProviderConnection`
  kaldirildi) ayridir. Gmail/Sheets icin OAuth broker var (ADR-0003) ama LLM/API-key node'lari
  icin yok. Hedef: Conduut workflow kaydederken AI/API-key node'lari icin n8n
  credential'ini kullanicinin kayitli key'inden otomatik olusturup baglasin
  (`POST /api/v1/credentials` + node'a referans). Mimari niyet (kullanici
  2026-06-15): her kullanicinin kendi n8n container'i olacak, credential'lar o
  container'da izole; agent yalniz konustugu kullanicinin container'ina baglanir.
  Bu yuzden per-user container fazina (izolasyon) bagli; shared-n8n MVP'de pooled
  Conduut-managed key ile gecici cozulebilir. Su an tekil calistigi icin
  ertelendi. Bkz. [[known-issues]] "Acik feature".

- [ ] Takip mesajinda agent mevcut workflow'u kullanmak yerine duplicate
  workflow olusturabiliyor - Etkilenen alan: [[chat-workflow-generation]] /
  [[agent-service]].
  Not: 2026-05-17 log incelemesinde ayni conversation icinde Gmail -> Sheets
  append workflow'u once `tBNZM1Qn3wdjV9B4`, takip/run mesajinda tekrar
  `PXHaWOjDOgDnnvEx` olarak olusturuldu. Ikinci workflow basariyla calisti;
  bu compiler hatasi degil, takip mesajinda `workflow_preview.id` baglaminin
  yeterince agresif kullanilmamasi. Beklenen davranis: workflow preview
  olustuktan sonra kullanici "calistir/test et" dediginde agent yeniden
  `create_workflow_from_plan` cagirmak yerine mevcut workflow id ile
  `execute_workflow` kullanmali. (2026-05-17)
  **Tekrar/agirlasti (2026-06-16):** Kullanici runtime girdileri ("benden alacagi
  girdiler sunlar...") tarif eden tek istek verdi; agent her clarification
  cevabinda yeniden `create_workflow` cagirip **5 duplicate** workflow uretti
  (ADmS0Fjx, pZGKfSsn, b48RYv5u, svRsOiqP, idRw9 — hepsi "AI ile Teklif E-postasi
  Gonder"), hic `update_workflow` cagirmadi. Ayrica runtime alanlarin DEGERLERINI
  `request_user_input` ile topladi (yanlis). **Fix:** (1) prompt — runtime-input
  tanima kurali (degerlerini sorma, input_schema yap) + "tek workflow kur, sonra
  update" kurali; (2) deterministik dedup — `history._conversation_workflows_from_messages`
  (runner cagirir; Faz 3'te `runner`'dan `agent/history.py`'ye tasindi)
  history'den name->id cikariyor, `AgentDeps.conversation_workflows`'a koyuyor,
  `create_workflow` ayni isimde mevcut workflow varsa create yerine update yapiyor
  (`create_workflow_deduped_to_update`). Testler: `test_runner.py` (+2). Duplicate'ler
  silindi. **DIKKAT:** local agent stale idi (08:03 UTC'den beri reload yok); fix'in
  devreye girmesi icin agent restart sart.
- [x] WorkflowSpec compiler akislara ozel hardcoded shape'lere bagli ve dinamik
  degil - Etkilenen alan: [[chat-workflow-generation]] / [[agent-service]] /
  [[n8n-registry]].
  ✅ Eskidi (2026-06-30, Faz 3): `WorkflowSpec`/`WorkflowPlan` compiler'lari
  (`spec_compiler.py`, `graph_compiler.py`, `blocks.py`) ve `create_workflow_from_*`
  tool'lari tamamen kaldirildi. Canli yol tek kompakt n8n JSON yuzeyi
  (`create_workflow`/`update_workflow`) + `repair.py` — herhangi bir n8n
  node/operation/shape'i destekler, "hardcoded shape" limiti yok
  ([[adr-0010-json-surface-repair-normalizer]]). Bu sorun gecersiz; tarihsel
  inceleme asagida korunur.
  Not: Kullanici "Gmail ile mail at, atilan mailin adres/title/icerigini bir
  Sheets tablosuna kaydet" istediginde agent mevcut Google Sheets ID istedi.
  Scope/permission problemi degil; Google Sheets connection `spreadsheets` ve
  `drive.file` ile write/create yetkisine sahip. Kök sorun mevcut
  `WorkflowSpec` compiler'in yalnizca Gmail send ve Google Sheets read rows ->
  Filter -> Gmail send gibi az sayida hardcoded shape desteklemesi. Bu prod
  icin olceklenmez; her ihtimal icin compiler case'i eklemek yerine
  capability/action tabanli IR gerekir. Ornek hedef: `gmail.send`,
  `sheets.spreadsheet.create`, `sheets.row.append` gibi reusable action
  primitive'leri operation-level registry metadata'siyle compose edilmeli.
  Sheet belirtilmemisse agent guvenli varsayimla yeni spreadsheet provision
  edip ID'yi workflow metadata'ya kaydedebilmeli; yalniz gercek is bilgisi
  eksikse kullaniciya sormali. Ilgili karar: [[adr-0005-workflow-spec-compiler]].
  (2026-05-17)
  Inceleme: 2026-05-17'de mevcut kodda `WorkflowStepSpec.capability` yalnizca
  `send_email`, `read_sheet_rows`, `filter_items` kabul ediyor; compiler da
  sadece Gmail on-demand ve Sheets read -> Filter -> Gmail shape'lerini
  dispatch ediyor. Google Sheets node schema'sinda `resource=spreadsheet` +
  `operation=create` ve `resource=sheet` + `operation=append` destekleniyor;
  readiness katmani append/create gibi read disi Sheets operasyonlarini zaten
  `google.sheets.write` capability'sine baglayabiliyor. Kisa vadeli cozum:
  mevcut Sheet ID/sheet name verilen akislarda `sheets.row.append` primitive'i
  eklenip Webhook -> Gmail -> Sheets Append shape'i compile edilmeli. Sheet
  belirtilmediginde otomatik provisioning ayri karar ister; Google token'lari
  Firestore'da tutulmadigi icin MVP'de ya n8n-managed gecici provisioning
  workflow'u kullanilmali ya da kullanicidan mevcut Sheet istenmeli. Uzun
  vadede hardcoded `len(steps)` dispatch yerine action/capability registry'si
  ve node factory'leriyle compose edilen IR'e gecilmeli.
  Uygulama: 2026-05-17'de `WorkflowPlan` action graph IR ve
  `create_workflow_from_plan` tool'u eklendi. Ilk action factory'leri
  `gmail.send`, `sheets.row.append`, `sheets.read_rows` ve `core.filter`.
  Gmail send -> Sheets append log akisi artik semantic action planindan
  deterministic n8n workflow'a compile ediliyor. Eski `WorkflowSpec` yolu
  uyumluluk icin kaldi. Otomatik spreadsheet provisioning henuz yok; Sheet
  bilgisi eksikse agent sormali.
- [ ] Agent reusable Gmail workflow isteginde teknik OAuth/API bilgisi istiyor -
  Etkilenen alan: [[chat-workflow-generation]] / [[agent-service]].
  Not: Kullanici "Create a reusable Gmail workflow..." dediginde agent workflow
  olusturmak veya mevcut `google_gmail` connection/OAuth prompt akisina
  yonlendirmek yerine "Google API Credentials" ve "Gmail OAuth2 setup for n8n"
  gibi teknik bilgiler istedi. Beklenen davranis: alici/konu/mesaj runtime
  input schema olarak tanimlanmali; Gmail connection yoksa Conduut'un OAuth
  prompt'u kullanilmali, kullanicidan n8n/Google API kurulumu istenmemeli.
  (2026-05-04)
  Debug: 2026-05-06 loglarinda agent'in bu istekte retry dongusune girdigi
  goruldu; validation `Gmail node 'Gmail' sendTo must be a real recipient email`
  hatasini uretiyordu. Kök neden `create_workflow` icinde runtime Gmail
  input binding'in validation'dan sonra uygulanmasiydi. Kodda runtime binding
  validation oncesine alindi ve n8n expression recipient'lari valid kabul
  edildi; container rebuild/restart sonrasi end-to-end yeniden denenmeli.
  Ek debug: 2026-05-06 canli container loglarinda ayni kullanici istegi
  workflow validation'a ulasmadan OpenAI `429 insufficient_quota` hatasiyla
  durdu. Workspace'te reusable Gmail runtime input testleri geciyor; agent'in
  cevap vermemesi bu denemede provider quota/billing kaynakliydi. Backend hata
  siniflandirmasi quota hatasini rate limit'ten ayiracak sekilde guncellendi.

## Kapananlar

- [x] Artifact preview assistant mesaji Firestore'a yazilamiyordu -
  Etkilenen alan: [[artifacts]] / [[agent-service]] / [[web-app]].
  Not: 2026-05-25 smoke testinde UI iki artifact kartini dogru gosterdi ve
  Google Sheets create/update cagrilari 200 dondu, fakat logda assistant
  message write sirasinda `400 Property array contains an invalid nested
  entity` hatasi goruldu. Kok neden `ArtifactPreviewTable.rows` alaninin
  `string[][]` seklinde nested array olarak Firestore'a yazilmasiydi. Cozum:
  backend rows formatini kolon adindan hucre preview'ine giden satir objeleri
  listesine cevirdi; web `ArtifactPreview` hem yeni object row formatini hem
  eski array row formatini render edebilir. Dogrulamalar: `ruff check`,
  `ruff format --check`, `pytest`, `pnpm lint`, `pnpm exec tsc --noEmit` ve
  Docker build. (2026-05-25)
- [x] Sheets artifact retry bos `spreadsheet_id` ile 404 dongusune giriyordu -
  Etkilenen alan: [[agent-service]] / [[artifacts]] /
  [[chat-workflow-generation]].
  Not: 2026-05-24 log incelemesinde artifact testinde spreadsheet basariyla
  olustuktan sonra Google API cagrilarinin `spreadsheets//...` seklinde bos
  `spreadsheet_id` ile gittigi goruldu. "Tekrar dene" mesajinda agent onceki
  artifact'teki spreadsheet id'yi resource baglami olarak kullanmadigi icin
  yeni spreadsheet olusturuyor ve tekrar ayni bos id write/read denemelerine
  dusuyordu; uzun "Working on the workflow" durumu tool request limitine kadar
  suren retry dongusuydu. Cozum: runner history'deki Google Sheets
  `artifact_preview` attachment'larini `AgentDeps.platform_resources`
  baglamina tasiyor, direct Sheets action'lari ayni turdaki create sonucunu bu
  baglama kaydediyor, read/update/append action'lari eksik `spreadsheet_id`yi
  buradan tamamliyor ve hala id yoksa Google API'ye gitmeden `missing_input`
  donduruyor. Dogrulama: `ruff check`, `ruff format --check`, `pytest`.
  (2026-05-24)
- [x] Sheets artifact testinde spreadsheet olusup Leads tab/veri yazma adimi
  yarida kaliyordu - Etkilenen alan: [[agent-service]] /
  [[chat-workflow-generation]].
  Not: Testte `sheets.spreadsheet.create` basarili olup artifact karti
  gorundu, fakat sonraki tab olusturma/veri yazma adimi hata aldigi icin
  kullanici yalnizca spreadsheet linki ve create preview'i gordu. Canli istek
  lokal log dosyasina dusmemisti; kod yolunda direct Sheets action'lari daha
  dayaniksizdi. Cozum: `sheets.sheet.create` idempotent yapildi, `range.update`
  ve `row.append` hedef tab yoksa once olusturacak sekilde guclendirildi, yeni
  spreadsheet + veri yazma icin agent prompt'una dogru tool sirasi eklendi.
  Dogrulama: `ruff check`, `ruff format --check`, `pytest`. (2026-05-24)
- [x] OpenAI model listesi settings ekraninda 502 donuyordu - Etkilenen alan:
  [[agent-service]].
  Not: `GET /api/settings/llm/providers/openai/models` OpenAI
  `/v1/models` cagrisi hata verdiginde UI'ye 502 tasiyordu. OpenAI model picker
  artik Anthropic/Google gibi Conduut'un bilinen statik model katalogundan
  donuyor; key dogrulamasi ayri verify akisinda kaldi. Regression testi remote
  model API'sinin bu path'te cagrilmadigini dogrular. (2026-05-24)
- [x] Agent Docker image rebuild sonrasi `src/config.py` startup'ta
  `IndexError: 3` ile dusuyordu - Etkilenen alan: [[agent-service]].
  Not: 2026-05-17 agent container rebuild'inde `/app/src/config.py` path'i
  icin `Path(...).parents[3]` bulunmadigi goruldu. Config repo root'u artik
  `docker-compose.yml` veya `AGENTS.md` marker'larini yukariya dogru arayarak
  buluyor, marker yoksa app dizinine dusuyor. Bu local `.env` okuma davranisini
  korurken Docker image startup'ini kirmaz. Regression testi eklendi.
  (2026-05-17)
- [x] Gmail -> Sheets append akisinda bos Sheet'e Gmail output alanlari
  yaziliyordu - Etkilenen alan: [[chat-workflow-generation]] /
  [[agent-service]].
  Not: Kullanici `to`, `subject`, `message` alanlarini Sheets'e kaydetmesini
  istedi, fakat bos Sheet'te `id`, `threadId`, `labelIds` kolonlari olustu.
  2026-05-17 log ve n8n workflow incelemesinde compiler'in
  `columns.mappingMode=defineBelow` ve dogru `input.*` expression'larini
  urettigi goruldu. Kok neden n8n Google Sheets append node'unun sheet tamamen
  bossa kendi implementasyonunda `defineBelow` yerine `autoMapInputData`
  moduna dusmesi; Sheets node'u Gmail node'undan sonra bagli oldugu icin
  auto-map Gmail send output'unu yaziyordu. Cozum: `sheets.row.append` action
  factory'si artik Google Sheets Append oncesine `Prepare Sheets Row` Set node'u
  ekliyor, current item'i hedef kolonlara donusturuyor ve Sheets Append'i bu Set
  cikisini `autoMapInputData` ile yazacak sekilde kuruyor. Boylece n8n bos
  sheet'te veya daha once yanlis header yazilmis sheet'te `to`, `subject`,
  `message` gibi semantic kolonlari yazar. Dogrulama: `ruff check`,
  `ruff format --check`, `pytest` ve container compiler smoke check. (2026-05-17)
- [x] Clarification panel coklu eksik bilgiyi tek input'a sikistiriyordu -
  Etkilenen alan: [[web-app]] / [[chat-workflow-generation]].
  Not: 2026-05-16 log incelemesinde agent'in ilk istekte
  `request_user_input` ile birden fazla bilgi istedigi, kullanici "Gmail"
  secince bunu tek cevap sayip kalan Sheet bilgilerini tekrar sordugu goruldu.
  Web `ClarificationPanel` artik birden fazla `missingFields` varsa her alan
  icin ayri kontrol gosterir; `choices` varsa bunlari ayri cevap kartlari
  yerine ilk eksik alanin secim kontrolu olarak kullanir ve ayni alan icin
  ayrica text input render etmez. Coklu bilgi panelinde ayrica "gerekli
  bilgiler" ozet karti acilmaz; dogrudan doldurulacak kontroller gosterilir.
  Aktif clarification varken ana chat input composer'i gizlenir. Tum alanlar
  dolmadan cevap gonderilmez. Cevap modele `Alan: deger` satirlariyla tek mesaj
  olarak gider. Dogrulama: `pnpm lint`, `pnpm exec tsc --noEmit`.
  Guncelleme: Agent artik eksik bilgileri varsayilan olarak adim adim soracak;
  `request_user_input` tool'u model coklu `missing_fields` gonderse bile
  attachment'i ilk eksik alanla sinirlar. (2026-05-16, guncelleme 2026-05-17)
- [x] Workflow'larda disaridan verilen dinamik calisma girdileri - Etkilenen
  alan: [[chat-workflow-generation]] / [[agent-service]] / [[dashboard]].
  Not: Runtime `input_schema`, dashboard run formu ve agent/dashboard ortak
  run endpoint contract'i eklendi. Karar icin bkz.
  [[adr-0004-parameterized-workflow-inputs]]. (2026-05-04)
- [x] Issue backlog notu olusturuldu ve [[index]] ile [[known-issues]]
  uzerinden knowledge graph'a baglandi. (2026-05-04)
- [x] Google OAuth Connections Grant hatasi kapatildi - Etkilenen alan:
  [[dashboard]] / [[agent-service]] / [[web-app]].
  Not: 2026-05-15'te iki kok neden duzeltildi. Agent lokal `apps/agent`
  baglamindan calisirken root `.env` okunmadigi icin Google OAuth ve n8n
  ayarlari eksikti; `src/config.py` repo root `.env` ve `apps/agent/.env`
  dosyalarini mutlak path ile okuyacak sekilde guncellendi. Next 16 dev
  ortaminda `/api/connections/google/.../authorize` nested route'u 404
  dondugu icin authorize BFF yuzeyi
  `/api/oauth/google/authorize?service=gmail|sheets` path'ine tasindi.
  Kullanici yeniden denedi ve sorunun cozuldugunu dogruladi. Dogrulamalar:
  `ruff check`, `pytest tests/test_connections_route.py tests/test_tools.py
  -q`, `pnpm lint`, `pnpm exec tsc --noEmit`. (2026-05-15)
- [x] Dashboard Run sonrasi reusable Gmail workflow hata veriyordu - Etkilenen
  alan: [[dashboard]] / [[agent-service]] / [[chat-workflow-generation]].
  Not: Ilk kok neden eski workflow webhook node'unda `httpMethod` eksikligi
  nedeniyle n8n'in GET kaydetmesi ve Conduut'un POST gondermesiydi. Agent
  create/update ve run oncesi webhook'u POST'a normalize edecek sekilde
  duzeltilmisti. Sonraki denemelerde sorun Gmail OAuth tarafina daraldi:
  execution `20` invalid/expired/revoked OAuth grant/refresh token hatasi,
  reconnect sonrasi execution `21` ise silinen eski `gmailOAuth2` credential id
  `cFNpdJVfi01IKbzT` workflow node'unda stale kaldigi icin hata verdi. Readiness
  analizi artik managed Gmail/Sheets connection varsa node'da credential alani
  dolu olsa bile guncel n8n credential id'sini workflow'a yeniden attach eder.
  Kullanici tekrar Run etti ve sorunun cozuldugunu dogruladi. Dogrulamalar:
  `ruff check src/agent/tools/readiness.py tests/test_tools.py
  src/routes/connections.py`, `pytest tests/test_connections_route.py
  tests/test_tools.py -q`. (2026-05-15)
- [x] Issue backlog Markdown checkbox formatlari duzeltildi; Google OAuth
  Grant hatasi ayri aktif bug olarak netlestirildi. (2026-05-15)
- [x] Local diagnostic log mekanizmasi kuruldu - Etkilenen alan:
  [[agent-service]] / [[web-app]].
  Not: Agent-first structured JSONL logging eklendi. FastAPI request
  middleware `X-Request-ID` uretir/korur; web BFF route'lari bu header'i
  agent'a tasir. Agent run, tool call, n8n API, OAuth callback,
  credential/readiness ve workflow run event'leri redaction'li olarak
  `logs/agent/conduut-agent.jsonl` dosyasina yazilir. Docker compose
  `./logs/agent:/app/logs` volume'u kullanir, `start-local-dev.bat`
  local agent icin `CONDUUT_LOG_DIR` ayarlar. Dogrulamalar: `ruff check`,
  `ruff format --check`, `pytest`, `pnpm lint`, `pnpm exec tsc --noEmit`,
  `docker compose config`. (2026-05-16)
- [x] Agent run bazli insan/LLM-okunabilir timeline loglari eklendi - Global
  `conduut-agent.jsonl` korunurken her run
  `logs/agent/runs/YYYY-MM-DD/HH-MM-SS_<run-id>.log` altinda baslik, INFO+
  event timeline'i ve success/error/cancelled ozetine ayrilir. `run_id` global
  JSONL'e de baglanir; retry attempt'leri ayni dosyada kalir. Prompt/final
  preview'leri inline secret redaction sonrasi 300 karakterle sinirlidir;
  `user_id`, raw payload ve token/thinking stream yazilmaz; event alanlari
  allowlist'le secilir. SSE iptalinde ic model task'i cancel+await edilir.
  Varsayilan retention 30 gundur, non-positive deger temizlik yapmaz ve dosya
  hatalari agent akisini bozmaz. Dogrulamalar: hedefli logging/runner testleri,
  tam agent `pytest`, `ruff check`,
  degisen Python dosyalarinda `ruff format --check`, `docker compose config`.
  (2026-07-13)

## Ilgili Dugumler

- [[known-issues]]
- [[current-state]]
- [[system-architecture]]
- [[web-app]]
- [[agent-service]]
- [[n8n-registry]]
- [[dashboard]]
- [[chat-workflow-generation]]
