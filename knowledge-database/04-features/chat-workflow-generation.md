# Chat Workflow Generation

Merkez: [[index]]

Chat, Conduut MVP'nin ana urun akisi.

## Kullanici Akisi

1. Kullanici Firebase ile giris yapar.
2. Settings altinda LLM provider API key'i ekler.
3. `/chat` ekraninda provider ve model secer; secilen model destekliyorsa
   reasoning effort (`minimal`/`none`/`low`/`medium`/`high`/`xhigh` alt
   kumesi) de secebilir.
4. Mesaj gonderir.
5. Web app `POST /api/chat/send` route'una Firebase token ile istek atar.
6. Next route FastAPI agent'a proxy eder.
7. Agent Pydantic AI ile tool calling dongusu calistirir.
8. Agent n8n REST API uzerinden workflow olusturur/gunceller.
9. Frontend SSE token'lari ve attachment event'lerini render eder.

## Yeni Conversation

`/chat` sayfasi provider/model secimini acik tutar. Ilk mesajdan sonra agent
conversation id dondurur. Web app `conversation-cache` ile yeni mesajlari
gecici tutar ve `/chat/[conversationId]` sayfasina gecer. Reasoning destekleyen
OpenAI modellerinde model listesi daha frontend'e gelmeden backend tarafinda
`reasoning_efforts` ile zenginlestirilir; UI bu alan yoksa secici gostermez.
Default secim destek varsa `medium` olur.

## Devam Conversation

`/chat/[conversationId]` sayfasi conversation detayini yukler. Provider ve model
conversation metadata'sindan kilitlenir. Reasoning effort secildiyse o da
metadata'dan kilitlenir. Kullanici ayni conversation icinde model veya
reasoning effort degistirmez.

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
  `user_input_request` gibi ekleri mesaja ekler.
- `done`: conversation, provider ve model bilgisini tamamlar.
- `error`: toast ile hata gosterir.

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

Gmail on-demand workflow'lar icin yeni pilot yol `WorkflowSpec` IR + compiler
akisini kullanir. Agent bu dar kapsamdaki istekte raw `nodes/connections` JSON
yazmak yerine `create_workflow_from_spec` tool'una compact spec verir. Backend
Webhook trigger, Gmail send node'u, nested connections ve `to`/`subject`/
`message` runtime input schema'sini deterministic olarak uretir; sonuc yine
mevcut validator, metadata ve readiness akislariyla islenir.

WorkflowSpec compiler'in ikinci desteklenen ailesi Google Sheets satirlarini
okuyup filtreleyen ve eslesen satirlar icin Gmail gonderen workflow'lardir.
Agent spec'i su sira ile vermelidir: `read_sheet_rows`/`google_sheets`,
`filter_items`/`core`, `send_email`/`gmail`. Gerekli is bilgisi gercek
`document_id` veya `spreadsheet_id`, `sheet_name` veya `sheet_id`, filtre
kolonu/operatoru/degeri, Gmail `to_field` ve subject/message kaynagidir. Bunlar
eksikse agent placeholder uydurmaz, `request_user_input` ile sorar. Trigger
on-demand olabilir veya gunluk schedule icin `frequency=daily` ve `time=HH:MM`
tasiyabilir. Subject/message sabit metin icinde `{{...}}` n8n expression'i
tasiyorsa compiler degeri `=` ile baslatir; tamamen sabit metinlerde expression
modu acilmaz.

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
- Gmail message/thread/label `get` ve `getAll` operasyonlari icin
  `google.gmail.read`, send/reply/create operasyonlari icin
  `google.gmail.send` capability'si gerekir. Kullanici `google_gmail`
  connection'i bu capability'yi tasiyorsa readiness analizi n8n workflow
  node'una `gmailOAuth2` credential'i otomatik attach eder ve missing credential
  dondurmez. n8n Gmail v2 message send node'u modelden
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
- Gmail read/send connection veya gerekli capability yoksa chat'e Gmail
  `oauth_prompt` attachment gelir. Google Sheets node'u credential istediginde
  read operasyonlari icin `google.sheets.read`, write operasyonlari icin
  `google.sheets.write` capability'si aranir; connection veya capability yoksa
  chat'e Sheets `oauth_prompt` attachment'i gelir. Web component'i artik simule
  etmez; attachment `authorizePath` degerine gore
  `/api/oauth/google/authorize?service=gmail` veya
  `/api/oauth/google/authorize?service=sheets` BFF route'undan gercek Google
  authorization URL alir. Bu path, Next 16 dev ortaminda eski
  `/api/connections/google/.../authorize` nested route'larinin 404'e dusmesi
  nedeniyle kullanilir.
- Eksik credential/OAuth prompt emit edildikten sonra agent ayni turda workflow
  calistirma veya aktive etme denemesi yapmamalidir. Tool sonucu
  `missing_credentials > 0`, `ready=false` veya `waiting_for_user_input=true`
  ise model durur ve kullanicidan gosterilen connection/credential aksiyonunu
  tamamlamasini ister. Bu, workflow olusturulduktan sonra Sheets/Gmail
  baglantisi beklenirken generic max-rounds hatasina dusmeyi engeller.
- Gmail delete/mark-read/mark-unread gibi modify operasyonlari V1 read/send
  OAuth scope ile otomatik attach edilmez; bu durum eski credential request
  davranisina duser.
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
  Chat'e artik ayri `workflow_run_result` attachment/kart gonderilmez; agent
  dogrulamayi kendi yapar ve kullaniciya yalnizca sade metin cevabi verir.
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

On-demand Gmail send/reusable email workflow'larda ve Google Sheets satir
filtreleme -> Gmail gonderim akisi isteyen workflow'larda agent once
`create_workflow_from_spec` kullanmalidir. Bu compiler desteklemiyorsa raw
`create_workflow` fallback'i korunur. Tek seferlik gonderimlerde gerekli runtime
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
