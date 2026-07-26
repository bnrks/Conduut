# Chat Workflow Generation

Merkez: [[index]]

Chat, Conduut MVP'nin ana urun akisi.

## Kullanici Akisi

1. Kullanici Firebase ile giris yapar.
2. `/chat` ekranina mesaj yazar (LLM key/provider/model secimi YOK — bkz. asagi).
3. Web app `POST /api/chat/send` route'una Firebase token ile istek atar.
4. Next route FastAPI agent'a proxy eder.
5. Agent runner mesaji bir tier'a siniflar (router), aktif profile'in o tier
   modelini Conduut'un kendi key'iyle kurar ve Pydantic AI tool calling
   dongusu calistirir.
6. Agent n8n REST API uzerinden workflow olusturur/gunceller (native JSON).
7. Frontend SSE token/thinking/attachment event'lerini render eder.

> **DIKKAT — BYO-provider kaldirildi ([[adr-0011-conduut-managed-tiered-models]]):**
> Bu akis eskiden "Settings altinda LLM provider API key'i ekler" ve "provider +
> model + reasoning effort secer" adimlarini iceriyordu. **Artik yok:** kullanici
> LLM key girmez, provider/model/effort secmez; model Conduut tarafindan tier
> router ile otomatik secilir ve Conduut'un env key'leri kullanilir.

## Yeni Conversation

`/chat` sayfasi sade bir composer'dir (provider/model/effort secimi yok). Ilk
mesajdan sonra agent conversation id dondurur. Web app `conversation-cache` ile
yeni mesajlari gecici tutar ve `/chat/[conversationId]` sayfasina gecer.

## Devam Conversation

`/chat/[conversationId]` sayfasi conversation detayini yukler. Model secimi her
mesajda runner'daki tier router tarafindan yapildigi icin conversation'a kilitli
bir provider/model/effort yoktur.

## Model Selector (KALDIRILDI)

> **DIKKAT (ADR-0011):** Bu bolum eskiden chat model selector'in
> `/api/settings/llm/providers` ve `.../{provider}/models` endpoint'lerinden
> provider/model listesi cektigini, eski `settings/llm` kaydini fallback
> dondurdugunu anlatiyordu. **BYO-provider yolu kaldirildi:** bu BFF route'lari,
> `providers` collection'i ve chat'teki provider/model selector'in tamami silindi.
> Model artik backend'de tier router ile otomatik secilir; bkz.
> [[agent-service]] "Model Registry, Router ve Provider Factory".

## SSE Event'leri

- `token`: assistant cevabinin text parcasini ekler.
- `tool_call`: tool calistigini UI'a bildirir. Web UI bunu teknik tool adini
  gostermeden "Checking available n8n steps", "Creating the workflow",
  "Running the workflow" gibi yuksek seviye durum metinlerine cevirir. Agent
  typing/think indicator'i normal assistant mesajlariyla ayni Conduut ikon
  avatarini gosterir. Raw model dusuncesi gosterilmez; typing balonu yalnizca
  mevcut `tool_call` event'lerinden turetilen son 3 guvenli progress adimini
  listeler.
- `attachment`: `workflow_preview`, `oauth_prompt`, `credential_request` ve
  `user_input_request` gibi ekleri mesaja ekler. Google Sheets sonuc
  onizlemeleri icin `artifact_preview` attachment'i de ayni SSE sozlesmesini
  kullanir.
- `recovery`: Yalniz DeepSeek reliability guard tetiklenince gelir. `attempt_id`
  sozlesmesiyle yarim content/thinking/steps/attachment state'ini temizler, gec kalan eski
  attempt event'lerini yok sayar ve "Agent tarafinda bir sorun olustu. Bastan tekrar
  deniyorum…" aktivitesini ephemeral gosterir. Recovery assistant content/history'ye girmez.
- Gecmis conversation yuklemelerinde web tarafinda `normalizeMessages`
  kullanilir: backend snake_case zaman alanlari dondurse veya Firestore'daki
  rol `assistant` olsa bile UI mesajlari `createdAt`, `conversationId`, `agent`
  rol ve attachment listesiyle render edilir. Bu, stream sirasinda gorunen
  `artifact_preview` kartlarinin sayfa yenileme/sohbet gecmisi acma sonrasi da
  gorunur kalmasi icin gereklidir.
- Tool'larin `attachment` event'leri final model cevabindan once gelebilir.
  Web UI bu event'leri stream sirasinda buffer'lar; assistant metni token
  olarak render edilir, artifact/credential/OAuth kartlari ise `done` event'i
  ile ayni assistant mesajinin altinda gosterilir. Bu, Google Sheets artifact
  kartlarinin final "islem tamamlandi" cevabindan once ekranda belirmesini
  engeller.
- `done`: conversation, provider ve model bilgisini tamamlar. Web UI bu
  metadata'yi mesajda saklar, ancak chat mesajlarinin hover alaninda model
  ismini gostermez; kartlarin yaninda yalnizca zaman bilgisi kalir.
- `error`: toast ile hata gosterir.

DeepSeek artik guard nedeniyle tum run'i buffer edip sonradan replay etmez. Kisa tool-imza
look-behind'i disinda gercek token/thinking/tool aktivitesi canlidir. Replay-unsafe bir tool
basladiysa recovery otomatik tekrar yapmaz; gecerli attachment'lari korur ve ayni islemin
tekrarlanmadigini bildirir. Her iki chat route'u ayni attempt-aware stream-state reducer'ini
kullanir.

## Workflow Preview

`create_workflow` ve `update_workflow` basarili olursa agent attachment olarak
`workflow_preview` dondurur. Frontend `WorkflowPreview` component'i bunu
assistant mesajinin altinda gosterir.

Workflow n8n'e yazilmadan once Pydantic model validation ve
[[n8n-registry]] destekli yapisal kontrollerden gecer. Hata varsa agent
Pydantic AI `ModelRetry` ile workflow JSON'unu duzeltmeye zorlanir ve n8n'e
side effect yapilmaz. n8n registry `Edit Fields (Set)` gibi node'larda
decimal `typeVersion` (`3.4` vb.) dondurebildigi icin workflow validator
numeric `int | float` kabul eder. Registry'nin cozebildigi kisa node type'lari
canonical type ve registry typeVersion'a normalize edilir; bu, modelin `set`
gibi kisa ad uretmesi halinde gereksiz retry dongusunu azaltir. Agent ayrica
connection referanslarini node `name` formatina normalize eder; model `1`/`2`
veya `node1`/`node2` gibi id/sira alias'lari uretirse bunlar n8n'e yazilmadan
once ilgili node adlarina cevrilir.

Filtreleme native JSON yolunda node-specific contract ile korunur. Tek-yollu
satir elemede `n8n-nodes-base.filter`, iki gercek branch gerektiginde
`n8n-nodes-base.if` tercih edilir; ikisi de v2+ icin dolu
`conditions.conditions` ve object operator ister. Model Code'a kacarsa v2
JavaScript kontrati exact `language="javaScript"` ve dolu `jsCode` gerektirir.
Registry bu nested ornekleri `get_node_schema` ile verir, validator hatali
sekilleri n8n side effect'inden once `ModelRetry` ile reddeder.

`update_workflow` parameter-only editlerde mevcut operasyonel state'i korur:
connections bos/atlanmissa var olan graf kullanilir; retained node ID'leri ve
credential baglari model payload'iyla degistirilemez. Topology degisikligi tam
non-empty connections ister, credential degisikligi ise yalniz dedicated attach
tool'lariyla yapilir. Boylece alici/konu gibi tek alanli bir edit tum workflow'u
yeniden wire etmez veya baglantilari koparmaz.

Gmail send icin format niyeti aciktir: formatted/styled digest veya newsletter
`emailType=html` ve gercek HTML body kullanir; ham Markdown `emailType=text`
altinda render edilmis sayilmaz. Bilerek plain-text istenirse `emailType=text`
korunur.

> **DIKKAT — IR/compiler yolu kaldirildi ([[adr-0010-json-surface-repair-normalizer]],
> [[workspace-refactor]] Faz 3):** Bu bolum eskiden tercih edilen yolun
> `WorkflowPlan` action graph IR + `create_workflow_from_plan` tool'u (ve eski
> `WorkflowSpec` + `create_workflow_from_spec`) oldugunu, compiler'in
> `gmail.send`/`sheets.row.append`/`sheets.read_rows`/`core.filter` gibi semantic
> action'lardan n8n node/connection ve `Prepare Sheets Row` + `autoMapInputData`
> yapisini deterministic urettigini anlatiyordu. **Tum IR tool'lari, schema'lari
> ve compiler'lar (`spec_compiler.py`/`graph_compiler.py`/`blocks.py`) silindi.**

Tek yuzey artik **kompakt native n8n JSON**'dur: agent `create_workflow`/
`update_workflow` ile dogrudan `nodes/connections` JSON yazar; `agent/repair.py`
deterministik onarir (sub-node main wiring, `{{input.x}}` runtime ref'leri,
`$json.body` atlama) ve `agent/validation.py` validator pipeline'i yapisal
kontrol yapar (bkz. asagi). Desteklenen akislar (Gmail send, Gmail send ->
Google Sheets append log, Sheets read -> Filter -> Gmail send) hala calisir,
fakat artik prompt rehberligi + repair ile native JSON uzerinden olusur.

Mevcut Sheet ID yoksa ama istek `spreadsheet_title`/`spreadsheet_name`/
`document_title` tasiyorsa agent direct Sheets API ile spreadsheet'i bir kez
provision edip `spreadsheet_id`'yi workflow'a yazma + metadata `resources`
davranisini korur; title de yoksa placeholder uydurmaz, `request_user_input`
ile ilk eksik gercek is bilgisini sorar.

Action Registry / platform action pack ("reusable `slack.message.send` semantic
action'lar") fikri artik ileri vadeli bir backlog kalemidir; bkz.
[[feature-backlog]] (ADR-0005/0008/0009 ADR-0010 ile **superseded**).

## Direct Platform Actions

Agent artik anlik platform yonetim isteklerinde n8n workflow yazmak yerine
`run_platform_action` tool'unu kullanir. Bu akis
[[adr-0006-platform-capability-layer]] ile tanimlanan capability registry'ye
baglidir.

Direct action ornekleri Gmail icin mail gonderme, arama/listeleme, mesaj
detayi alma, read/unread isaretleme, archive/trash ve label islemleridir.
Sheets icin spreadsheet olusturma, sheet/tab olusturma/silme, range
read/update/clear ve row append desteklenir.

Gmail direct action'lari basarili olursa agent `artifact_preview` attachment'i
emit eder. Bu kart `message_preview` seklindedir; alici, konu, gonderilen
metin/snippet, message id, thread id, label, search query ve sonuc sayisi gibi
guvenli ozet alanlarini tasir. Chat UI karti assistant mesajinin altinda
gosterir; ayni snapshot dashboard `Artifacts` bolumunde Gmail filtresiyle
kalici mail karti olarak listelenir. Gmail node'u iceren workflow run
sonuclarinda da n8n execution output'undaki message id/thread id bilgisi
message artifact'e cevrilir.

Google Sheets create/read/update/append direct action'lari basarili olursa
agent `artifact_preview` attachment'i emit eder. Bu kart kucuk tablo preview'i
ve Google Sheets linki tasir; tam platform verisini Conduut icinde kopyalamaz.
Yeni bir spreadsheet olusturup ayni istekte veri yazma gibi tek seferlik
Sheets akislarinda agent once `sheets.spreadsheet.create` ile `title` ve
`sheet_name` vermeli, sonra donen `spreadsheetId` ile `sheets.range.update`
cagirip `range='<sheet_name>!A1'` ve header dahil `values` gondermelidir.
Backend tarafinda `range.update` ve `row.append` hedef tab yoksa once
olusturur; `sheets.sheet.create` ayni tab zaten varsa hata yerine idempotent
basari dondurur.
Takip mesajlarinda runner onceki Google Sheets `artifact_preview`
attachment'larini internal platform resource baglamina cevirir. Bu yuzden
"tekrar dene", "veriyi yaz", "son olusturdugun sheet'e kaydet" gibi mesajlarda
agent yeni spreadsheet acmak yerine son artifact'teki `spreadsheetId` ile devam
edebilir. Backend de `spreadsheet_id` eksik Sheets read/update/append
action'larini bu baglamdan tamamlar; baglam yoksa Google API'ye bos id ile
gitmeden `missing_input` dondurur.
Artifact tablo satirlari Firestore uyumlulugu icin nested array olarak degil,
kolon adlariyla keylenmis satir objeleri olarak saklanir. Chat UI bu formatla
render eder ve eski array row formatina toleranslidir.

Kullanicinin eksik capability'si varsa agent direct action veya workflow side
effect yapmadan `oauth_prompt` attachment'i dondurur. Attachment artik
`requiredCapabilities`, `permissionPack` ve `riskLevel` tasiyabilir; web BFF bu
pack/capability istegini Google authorize route'una iletir. Direct action icin
refresh token yalnizca `CONDUUT_CONNECTION_ENCRYPTION_KEY` ayarlandiginda
encrypted Firestore metadata'sindan okunabilir; yoksa agent n8n credential
tabanli workflow path'ini kullanir veya yeniden baglanti ister.
Bu key OAuth callback sirasinda yoksa sonradan `.env` dosyasina eklemek mevcut
connection'i direct API uyumlu hale getirmez; kullanici Gmail/Sheets hesabini
yeniden baglamalidir. Agent direct action `reconnect_required` hatasinda artik
generic clarification yerine ilgili Google service icin `oauth_prompt`
attachment'i gonderir.

## Credential ve Run Capability

Agent workflow olusturduktan veya guncelledikten sonra readiness analizi yapar:

- Reusable workflow'lar runtime input alabilir. Agent `create_workflow` ve
  `update_workflow` tool'larina `input_schema` verebilir; schema Firestore
  `workflow_metadata` altinda saklanir ve dashboard run formu tarafindan
  kullanilir. Gmail send workflow'larinda `to`, `subject`, `message` field'lari
  otomatik runtime input olarak infer edilir ve Gmail node parametreleri
  webhook trigger varsa `={{$json.body.to}}`, `={{$json.body.subject}}`,
  `={{$json.body.message}}` expression'larina normalize edilir. Webhook yoksa
  eski `$json.to`/`$json.subject`/`$json.message` formu korunur.
- Credential isteyen node'larda eksik credential varsa chat'e
  `credential_request` attachment gelir.
- Managed Gmail/Sheets credential node'a ayni credential ID'siyle zaten bagliysa
  readiness mutasyonsuz no-op yapar; `before_mutation` ve n8n workflow `PUT`
  cagrilmaz. Credential gercekten degisirse workflow yazilir. Aktif workflow'a
  yapilan gercek `PUT` sonrasi n8n cron/trigger kaydini korumak icin client,
  guncel active durumunu tekrar okur; kullanici bu arada kapatmadiysa
  `deactivate -> activate` dongusuyle yeniden registration yapar.
- Schedule Trigger saatleri kullanicinin yerel duvar saati olarak yazilir;
  agent UTC donusumu yapmaz. `CONDUUT_WORKFLOW_TIMEZONE` ve workflow
  `settings.timezone` varsayilani `Europe/Istanbul`; local n8n instance da
  `GENERIC_TIMEZONE`/`TZ` ile ayni degeri kullanir. Schedule field/interval,
  saat/dakika ve custom cron'un alti alanli expression shape'i n8n'e yazilmadan
  once validator'da kontrol edilir. Scheduled calisma kaniti `triggerCount` veya
  `recurrenceRules` degil, gercek execution kaydidir.
- Agent system instruction'i etkin `CONDUUT_WORKFLOW_TIMEZONE` degerini runtime'da
  acikca tasir. Mevcut workflow icin `get_workflow.settings.timezone` otoritedir;
  create/update tool sonucu da etkin `timezone` degerini modele dondurur. Bu nedenle
  agent host OS veya UTC execution timestamp'lerinden hareketle "sistem UTC ise"
  varsayimi yapmaz.
- Gmail message/thread/label `get` ve `getAll` operasyonlari icin
  `gmail.message.read`, send/reply/create operasyonlari icin
  `gmail.message.send`, organize/mark/trash operasyonlari icin
  `gmail.message.modify` veya `gmail.message.trash` capability'si gerekir.
  Kullanici `google_gmail` connection'i bu capability'yi tasiyorsa readiness
  analizi n8n workflow node'una `gmailOAuth2` credential'i otomatik attach eder
  ve missing credential dondurmez. Eski `google.gmail.read/send` etiketleri
  alias olarak cozulur. n8n Gmail v2 message send node'u modelden
  `operation=create` olarak gelebilir; agent bunu n8n'e yazmadan once
  `operation=send` degerine normalize eder.
- Gmail send node'unda model `toEmail`, `bodyContent` gibi eski/uydurma alias
  alanlar uretirse agent bunlari n8n v2'nin bekledigi `sendTo`, `message`,
  `subject`, `emailType` alanlarina normalize eder. `receiver@email.com`,
  `test@example.com` gibi placeholder alicilar validation hatasi sayilir; gercek
  alici yoksa workflow n8n'e yazilmamalidir. Reusable Gmail workflow'larda
  runtime `input_schema` validation oncesi uygulanir; boylece `sendTo`,
  `subject` ve `message` alanlari webhook output shape'ine gore expression'a
  cevrildikten sonra validate edilir. n8n expression recipient degerleri
  placeholder email kontrolunden gecirilmez.
- Clarification sonrasi agent ayni adla tekrar `create_workflow` cagirirsa bu
  cagri mevcut conversation workflow'una dedupe edilir. Model connections'i
  vermediyse mevcut topology korunur; ozellikle branched graf lineer inference
  ile ezilmez. Topology degisikligi tam ve non-empty connections ister.
- Gmail/Sheets connection veya gerekli canonical capability yoksa chat'e
  `oauth_prompt` attachment gelir. Google Sheets node'u credential istediginde
  read operasyonlari icin `sheets.range.read`, write/append/create
  operasyonlari icin `sheets.range.update`, `sheets.row.append` veya
  `sheets.spreadsheet.create` capability'si aranir; eski
  `google.sheets.read/write` etiketleri alias olarak cozulur. Web component'i
  artik simule etmez; attachment `authorizePath` degerine gore
  `/api/oauth/google/authorize?service=gmail` veya
  `/api/oauth/google/authorize?service=sheets` BFF route'undan gercek Google
  authorization URL alir ve varsa `permissionPack`/`requiredCapabilities`
  bilgilerini body'de tasir. Bu path, Next 16 dev ortaminda eski
  `/api/connections/google/.../authorize` nested route'larinin 404'e dusmesi
  nedeniyle kullanilir.
- Eksik credential/OAuth prompt emit edildikten sonra agent ayni turda workflow
  calistirma veya aktive etme denemesi yapmamalidir. Tool sonucu
  `missing_credentials > 0`, `ready=false` veya `waiting_for_user_input=true`
  ise model durur ve kullanicidan gosterilen connection/credential aksiyonunu
  tamamlamasini ister. Bu, workflow olusturulduktan sonra Sheets/Gmail
  baglantisi beklenirken generic max-rounds hatasina dusmeyi engeller.
- `list_credentials` yalniz custom/service API credential kutuphanesini
  listeler; bos donmesi Gmail veya Sheets managed Connection'in kopuk oldugu
  anlamina gelmez. Workflow node'larinda connection karari icin
  `analyze_workflow_readiness` kullanilir ve platform state managed servisleri
  custom credential'lardan ayri gosterir.
- Gmail permanent delete default akista kullanilmaz; trash ve organize
  aksiyonlari permission pack/risk metadata'siyle ayrilir ve eksik izin varsa
  OAuth prompt'a duser.
- Webhook gibi credential'i opsiyonel olan node'larda registry schema'da
  credential type listelenmesi tek basina yeterli sayilmaz. Agent actual node
  `parameters.authentication` ve schema default degerini kontrol eder; default
  `none` ise credential istemez.
- Kullanici API-key credential'i Conduut chat formundan girer; Next BFF
  `/api/credentials` uzerinden agent'a proxy eder. Google Gmail ve Google
  Sheets credential'lari icin chat formu yerine managed OAuth connection akisi
  kullanilir.
- Agent credential'i n8n'e kaydeder, workflow node'una attach eder ve
  Firestore'a credential metadata yazar.
- `execute_workflow` ilk fazda sadece webhook-triggered workflow'lari
  Conduut'tan calistirir ve n8n execution detayini agent icinde kanit olarak
  kontrol eder. Tool artik opsiyonel `input` payload alir; eksik required
  runtime input varsa workflow'u calistirmadan `request_user_input` ile sorar.
  Chat'e teknik `workflow_run_result` attachment/kart gonderilmez; agent
  dogrulamayi kendi yapar ve kullaniciya sade metin cevabi verir. Sheets
  ciktisi varsa teknik kanit yerine kullanici odakli `artifact_preview` karti
  gosterilir.
- Side-effect preview onayi clarification panelinde structured tasinir.
  Assistant attachment'indaki opaque `requestId` ve `workflowId`, kullanici
  Approve/Cancel secenegine bastiginda `user_input_response` body alanina
  yazilir. Runner yalniz o anki son user mesajindaki karari kabul eder; onceki
  turdaki consumed token yeniden oynatilmaz ve modelin tokeni metinden
  hatirlamasi gerekmez. Gecersiz token yeni bir onay karti uretir ama ayni
  agent turunda `execute_workflow` tekrar cagrilmaz.
- Agent cevap uretirken ana chat composer disabled olur. `handleSend` zaten
  concurrent gonderimi reddettigi icin bu UI siniri, kullanicinin yazdigi
  cevabin sessizce dusup input alaninin temizlenmesini engeller. Preview
  attachment'i emit edildikten sonra output claim validator retry'a girmez;
  run approval'a ozel preview ozeti kullanilir. Normal eksik alan/credential
  sorulari preview/onay metniyle karistirilmaz ve genel bekleme ozeti alir.
  Final `done` event'inden sonra tek structured approval paneli gosterilir.
- Output claim validator hicbir akista dahili `ModelRetry` metnini modele geri
  vermez. Kaniti asan run/send/update cumlesi sentence-buffered stream gate'te
  yayinlanmadan deterministic evidence summary ile degistirilir; final validator
  da ayni ozeti terminal sonuc yapar. Bu nedenle modelin validator elestirisine
  `Haklisiniz` diye cevap verdigi ara tur kullaniciya stream edilmez veya
  assistant mesaji olarak saklanmaz.
- Sandbox V2 en cok iki model repair denemesi yapar. Known-side-effect harness
  hatasi veya biten repair butcesi `needs_attention` ve terminal user-input
  siniri uretir; ayni turda update/run dongusune devam edilmez.
- Manual/Schedule gibi Conduut'un dogrudan baslatamadigi trigger'lar production
  workflow'da degistirilmez; sandbox gecici clone icinde trigger'i webhook'a
  cevirip ayni govdeyi surer. HTTP Request ciktisindaki `$json.statusCode` ile
  IF/Filter yapan akislar artik `options.response.response.fullResponse=true`
  ve `neverError=true` olmadan validation'dan gecmez. Kosulun downstream'i bir
  side effect'e ulasiyorsa DNS/timeout gibi transport hatalarinin da karar
  dalina ulasmasi icin top-level `onError=continueRegularOutput` zorunludur.
  Sandbox HTTP node gercekte `statusCode` uretmedigi halde alarm probe'una
  ulasan kosuyu fail-closed `needs_attention` sayar; eksik alanin
  `undefined != 200` olarak yanlis alarm uretmesi artik `passed` olamaz.
- Runtime-input side-effect run'da approval token input validation'dan sonra
  tuketilir; eksik alan veya input/fingerprint uyusmazligi tokeni silmez.
  Credential bekledigi icin build sirasinda sandbox edilmemis workflow'un ilk
  pretest'i de kullanicinin gercek run payload'uyla yapilir. Activation ise
  runtime degeri olmadigi icin `{}` gondermez; schema'dan guvenli sample
  uretilen `None` yolunu kullanir.
- Conversation execution policy (2026-07-25): chat composer kullaniciya ilk
  mesajdan once `safe|fast` secimi verir ve bu secim conversation'da kilitlenir.
  `safe` mod yalniz chat manual execute yolunda gercek input ile bir adet
  `safe_sandbox` preview + structured approval + bir adet real run zinciri
  kullanir. `fast` mod n8n runtime sandbox'i atlar; yalniz full coverage
  typed/static contract preview (`fast_static`) ile approval ister, sonra tek
  real run yapar. Build-time `create_workflow`/`update_workflow` runtime
  sandbox calistirmaz; static validation, readiness, typed Oracle, approval,
  execution assessment ve claim gate her iki modda da zorunludur. Dashboard,
  batch ve activation yolu ilk surumde safe-only kalir.
- Dashboard, runtime input schema'si olan workflow'lari `.xlsx`/`.csv`
  satirlariyla batch calistirabilir. Bu V1 ozellik [[adr-0007-batch-workflow-runs]]
  ile Conduut tarafinda loop olarak tasarlanmistir; workflow JSON'u
  degismez, chat agent batch tool'u henuz yoktur.
- n8n production webhook registration icin Webhook node'larinda `webhookId`
  bulunmali. Agent validator/normalizer eksikse otomatik UUID uretir.
- Connections yapisi n8n editor uyumlulugu icin nested output array formatina
  normalize edilir. Model `main: [{...}]` gibi flat liste uretirse agent bunu
  `main: [[{..., index: 0}]]` formatina cevirir.
- Webhook node'u `Respond to Webhook` node'una bagliyse `responseMode`
  otomatik `responseNode` yapilir; aksi halde n8n `Unused Respond to Webhook
  node found in the workflow` hatasi verir.
- Conversation history modele verilirken assistant attachment'larindan gizli
  workflow context uretilir. Boylece kullanici "run the workflow" gibi takip
  mesaji yazdiginda model onceki `workflow_preview.id` degerini kullanabilir ve
  `workflow_id=1` gibi uydurma id'lere dusmez.
- `user_input_request` attachment'i da history context'ine eklenir. Agent eksik
  alici, mesaj metni, servis hesabi veya zamanlama gibi is bilgilerini adim
  adim sorar; once en bloklayici karar/alan sorulur, kullanici cevabindan sonra
  bir sonraki eksik alan sorulur. Kullanici sadece cevabi yazarsa agent onceki
  otomasyon istegini devam ettirebilir. Web tarafinda aktif
  `user_input_request` varken ana chat composer'i gizlenir ve alt cevap alaninda
  sadece clarification paneli gosterilir. Bu aktif soru ayni anda mesaj
  listesinde kompakt ozet olarak render edilmez; sadece onceki
  `user_input_request` attachment'lari mesaj listesinde kompakt ozet olarak
  kalir, boylece clarification gecmisi kaybolmaz. Panel `missingFields`
  degerlerini cevap kontrolu etiketlerine cevirir; bu yuzden agent
  `request_user_input` cagrilarinda tek eksik alani insan tarafindan okunabilir
  etiketle doldurmalidir. Tool isterse 2-4 secenek de gonderebilir. Web paneli
  coklu `missingFields` icin fallback olarak ayri kontroller gostermeyi
  destekler, fakat tool model yanlislikla coklu alan gonderirse attachment'i ilk
  alanla sinirlar. Tek eksik alan ya da sadece secenekle cevaplanabilecek
  sorularda secenek tiklama dogrudan cevap gonderebilir.
- Runner conversation history'ye, `user_input_request` sonrasi gelen user
  mesajlari icin internal "bu mesaj onceki clarification'a cevap olabilir"
  context'i ekler. Bu modelin cevaplanmis alanlari biriktirmesine ve ayni eksik
  bilgiyi tekrar sormamasina yardim eder.
- Acuity/Gmail/Slack gibi external event trigger'lari icin credential ve
  readiness saglanir; gercek external event gelmeden agent calistirdim demez.

Set/Edit Fields node icin ek davranis: agent prompt'u ve registry schema
ornekleri `parameters.assignments.assignments` formatini gosterir. Validator
bos Set node'u kabul etmez; boylece UI'da gorunen ama output'u bos olan
workflowlar n8n'e yazilmadan once ModelRetry'a duser.

## Agent Davranis Kurallari

Agent prompt'u onay sormadan aksiyon almayi ister. Yeni workflow icin
`create_workflow`, mevcut workflow icin `get_workflow` sonra `update_workflow`
kullanmalidir. Bilinmeyen node type'lar asla tahmin edilmemeli; once
[[n8n-registry]] tool'lari kullanilmalidir. Node arama tool'u varsayilan 20
sonuc dondurur ve agent yeterli adayi bulamazsa `limit` parametresini artirarak
tekrar arayabilir; limit registry tarafinda 50 ile sinirlanir.

On-demand Gmail send/reusable email workflow'larda, Gmail send -> Sheets append
log akislari ve desteklenen Google Sheets satir akisi workflow'larda agent
`create_workflow`/`update_workflow` ile dogrudan native n8n JSON yazar; `repair.py`
ve validator pipeline onarir/dogrular. (Eski `create_workflow_from_plan`/`_spec`
IR tool'lari kaldirildi — ADR-0010.) Tek seferlik gonderimlerde gerekli runtime
input tamamlandiktan sonra agent olusan on-demand workflow'u `execute_workflow`
ile calistirabilir.

Agent artik kullanicidan n8n, webhook, workflow veya node terminolojisi
beklememelidir. "Su mail adreslerine bu paragrafi gonder" gibi dogal dil
isteklerinde otomasyon niyetini kendisi cikarmali, teknik yapiyi kendisi
secmeli ve sadece gerekli is bilgisi eksikse `request_user_input` tool'u ile
tek, net ve kendi basina anlasilir bir soru sormalidir. Birden fazla bilgi
eksikse hepsi tek seferde istenmez; servis/hesap gibi akisi belirleyen en
bloklayici karar once sorulur, sonra kullanici cevabina gore bir sonraki alan
sorulur. `missing_fields` tek alan icermeli ve "Google Sheet ID",
"sheet/tab name", "kaydedilecek input alanlari" gibi acik etiketlerle
doldurulmalidir. Placeholder alici, fake URL veya ornek metin uydurmak yerine
bu soru akisi kullanilir; tool cagrildiktan sonra ayni turda workflow yazilmaz.

Conduut'un chat'ten "sen tetikle/test et" diyerek calistirabilecegi on-demand
workflow'larda agent kullaniciya webhook terimini soylemeden internal POST
Webhook trigger kullanmalidir. Daha once manual trigger ile olusmus workflow
run isteginde otomatik Conduut webhook trigger'a cevrilir; boylece agent kendi
olusturdugu basit Gmail gibi workflow'lari n8n editor butonuna muhtac kalmadan
tetikleyebilir.

Webhook trigger zaten varsa fakat `httpMethod` eksikse n8n bunu GET olarak
kaydedebilir. Conduut run endpoint'i runtime input'u JSON body ile POST
gonderdigi icin create/update normalizer artik webhook method'unu varsayilan
POST yapar; mevcut eski workflow run edilirken de webhook POST kabul etmiyorsa
workflow once POST'a patch'lenir.

LiteLLM agent loop'u kaldirildi; provider cagrilari Pydantic AI native
provider'lariyla yapilir. Mevcut SSE event sozlesmesi korunur:
`token`, `tool_call`, `attachment`, `done`, `error`.

Ilgili notlar: [[web-app]], [[agent-service]], [[dashboard]].

## Lookup-first Card Akisi ve Claim Gate V2 (2026-07-23)

[[adr-0020-workflow-node-cards-assurance-v2]] sonrasinda non-trivial workflow
uretim sirasi zorunlu olarak:

`search_workflow_cards(limit=10) -> get_workflow_card(max 3) ->
search_n8n_nodes/get_node_schema -> get_node_contract(exact) ->
create_workflow/update_workflow`

Agent community card'ini kopyalamaz; topology, invariant ve risk fikri olarak
kullanir. Gmail, Google Sheets, Filter, IF, Code, Set/Edit Fields ve Merge icin
exact typeVersion/resource/operation contract'i okunur. Secilen card ID/hash ve
node contract hash'leri workflow metadata `resources.lookup` alanina yazilir.

Create/update native n8n JSON imzasini korur. Repair hala safety net'tir;
correctness otoritesi dynamic header contract, static/dataflow validation ve
typed Oracle'dir. Gercek run sonucunda streamed/final metin yalniz evidence
scope'u kadar claim kurabilir. Partial side effect yeni bir otomatik run
baslatmaz; reconciliation preview + kullanici onayi gerekir.

## Chat Bazli Safe/Fast Execution Policy (2026-07-25)

[[adr-0021-chat-execution-policy]] ile yeni chat composer'inda varsayilan Safe
olan kompakt bir execution policy switch'i bulunur. Switch, uzun aciklama
paneli yerine composer'in alt arac satirinda `Safe mode` etiketiyle gosterilir;
yanindaki bilgi ikonu hover/focus ile opak kart zemininde
hiz-maliyet-risk aciklamasini acar.
Kullanici ilk mesaji gondermeden Fast'i secebilir; ilk mesaj conversation'i
olusturdugunda secim persist edilir ve kilitlenir. Mevcut ve legacy
conversation'lar server'daki policy'yi kullanir; policy sonraki mesajlarla
degistirilemez.

- Safe: gercek input ile bir yan-etkisiz n8n sandbox preview, structured
  kullanici onayi ve bir real run.
- Fast: full typed/static contract preview, structured kullanici onayi ve bir
  real run; n8n runtime sandbox yoktur.

Create/update yalniz build validation ve static assurance calistirir; build
aninda runtime sandbox yapmaz. Safe preview basarisizsa model workflow'u
degistirip ayni gercek input ile yeniden deneyebilir, fakat butce iki runtime
preview ile sinirlidir. Fast static failure runtime repair loop'una girmez.
Readiness, credential/header contract, approval token, execution assessment ve
claim gate iki modda da zorunludur.

Policy ilk surumde yalniz chat manual execute yolunu etkiler. Dashboard manual
run, batch ve activation Safe davranisini korur. Preview token'lari chat,
policy, preview basis, workflow fingerprint ve input hash'ine baglanir.
