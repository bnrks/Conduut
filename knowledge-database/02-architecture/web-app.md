# Web App

Merkez: [[index]]

`apps/web` Conduut frontend uygulamasidir.

## Stack

- Next.js `16.2.1`.
- React `19.2.4`.
- TypeScript strict mode.
- Tailwind CSS 4.
- Firebase client SDK.
- Zustand stores.
- `lucide-react`, `framer-motion`, `sonner`, `react-markdown`.

`apps/web/AGENTS.md` Next versiyonu konusunda uyarir: bu Next.js eski
bilinen davranislardan farkli olabilir; kod yazmadan once lokal dokuman veya
mevcut ornekler kontrol edilmeli.

Docker image Node `20-alpine` kullanir. `apps/web/Dockerfile` Corepack ile
pnpm'i `10.19.0` surumune pinler; aksi halde Corepack pnpm 11 indirebilir ve
pnpm 11 Node 22.13+ istedigi icin Node 20 runtime'da `node:sqlite` hatasiyla
web container baslamaz.

Tarayici sekme ikonu root metadata'da `/images/icons/conduut-icon.svg` olarak
tanımlidir; `src/app/icon.svg` ayni Conduut ikonunu Next app icon convention'i
icin saglar.

## Route Gruplari

- `(marketing)`: landing/marketing sayfasi.
- `(auth)`: login, register, forgot-password.
- `(chat)`: `/chat` ve `/chat/[conversationId]`.
- `(dashboard)`: dashboard shell, workflows, connections, usage, settings.
- `api`: Next route handler'lari; agent servisine proxy/BFF katmani.

## Auth

Firebase client auth `src/hooks/use-auth.ts` icinde kullanilir. Browser
`user.getIdToken()` ile token alir ve `Authorization: Bearer ...` header'i ile
Next API route'larina gonderir. Next API route'lari ayni header'i agent
servisine aktarir. Dashboard workflows sayfasi ilk listeleme isteginde
`user.getIdToken(true)` ile taze ID token ister; auth state henuz hazir degilse
listeleme bekler, kullanici yoksa local loading state'ini kapatir. Agent 401
veya baska hata donerse BFF payload'indaki `detail.message`, `detail` veya
`message` toast'a yansitilir.

## BFF API Routes

Baslica route handler'lar:

- `api/chat/send`: FastAPI `/api/chat/send` endpoint'ine SSE stream proxy eder.
- `api/conversations`: conversation listesi.
- `api/conversations/[conversationId]`: conversation detail/delete.
- `api/artifacts`: kalici artifact preview snapshot listesi.
- `api/artifacts/[artifactId]`: kalici artifact preview snapshot silme.
- `api/workflows`: workflow listesi.
- `api/workflows/[workflowId]`: activate/deactivate/delete proxy.
- `api/connections`: connection listeleme.
- `api/connections/[connectionId]`: connection silme proxy.
- `api/oauth/google/authorize?service=gmail|sheets`: Firebase token ile agent
  Google Gmail veya Google Sheets authorize endpoint'ine proxy eder. Next 16
  dev ortaminda `api/connections/[connectionId]` dinamik route'u ile ayni dal
  altindaki `api/connections/google/.../authorize` route'lari 404'e dustugu
  icin authorize BFF yuzeyi `api/oauth/google` agacina tasindi.
- `api/oauth/google/callback`: Google OAuth callback'ini auth header olmadan
  generic agent Google callback endpoint'ine iletir ve connection id ile
  dashboard'a success/error redirect yapar.
- `api/settings/llm`: aktif provider/model/API key ayarlari.
- `api/settings/llm/providers`: provider ekleme/listeleme.
- `api/settings/llm/providers/[provider]/models`: model listeleme.
- `api/settings/llm/providers/[provider]/verify`: provider key dogrulama.
- `api/settings/favorites`: favorite modeller.

Local `pnpm dev`, Next 16.2.1 icin `next dev --webpack` calistirir. Turbopack
dev server Windows ortaminda ikinci seviye App Router sayfa ve API route'larini
404'e dusurebildigi icin yerel gelistirmede Webpack tercih edilir.
Web host uzerinde calistiginda BFF route'lari agent'a
`AGENT_API_BASE_URL=http://localhost:8100` ile ulasir; Docker compose icindeki
web container ise `AGENT_API_BASE_URL=http://agent:8000` kullanir. Root
`start-local-dev.bat`, Windows'ta port `3000` excluded olabildigi icin web'i
default olarak `localhost:3007` uzerinde baslatir; port `CONDUUT_WEB_PORT` ile
degistirilebilir. Google OAuth redirect URL'i de `localhost:3007` kullandigi
icin local browser oturumlari `127.0.0.1` yerine `localhost` uzerinden
acilmalidir; aksi halde Firebase/browser session origin'i degisir ve callback
sonrasi tekrar login istenebilir. Script root `.env` icinden Google OAuth
client bilgilerine ek olarak `CONDUUT_CONNECTION_ENCRYPTION_KEY` degerini de
agent process'ine tasir; bu key yoksa Google connection n8n credential olarak
kaydedilir ama direct Sheets/Gmail API aksiyonlari icin refresh token encrypted
saklanamaz. Env veya port degisirse Next dev server yeniden baslatilmalidir.

## Chat UI

Yeni chat sayfasi model/provider secimine izin verir. Conversation olustuktan
sonra `conversation-cache` ile gecici cache kullanilir ve router
`/chat/[conversationId]` sayfasina gider. Devam eden conversation'da provider ve
model kilitlenir. Model liste endpoint'i her model icin varsa
`reasoning_efforts` dizisini dondurur; chat input yalnizca destekleyen modelde
kompakt reasoning effort secicisini gosterir ve secimi chat request body'de
`reasoning_effort` olarak yollar. Yeni conversation cache'i ve conversation
detail response'u bu effort'u da tasir, bu yuzden devam mesajlarinda ayar
degismez.

SSE event'leri `src/lib/chat/sse.ts` ile parse edilir:

- `token`: assistant cevabina text ekler.
- `tool_call`: chat input altindaki typing indicator metnini gunceller; UI
  ham tool adini gostermek yerine `src/lib/chat/tool-activity.ts` mapping'iyle
  sade islem durumlari gosterir.
- `attachment`: workflow preview, oauth prompt, credential request,
  artifact preview veya user input request gibi ekleri ekler.
- `done`: provider/model bilgisini mesaj uzerine yazar.
- `error`: toast ile hata gosterir.

`WorkflowPreview` workflow kaydini daha belirgin bir "Workflow saved" paneliyle
gosterir. `OAuthPrompt` artik simule connect yapmaz; agent'tan gelen
`authorizePath` ile Google Gmail veya Google Sheets OAuth authorize route'unu
cagirir ve authorization URL'ine yonlendirir. Varsayilan Gmail authorize path'i
`/api/oauth/google/authorize?service=gmail`'dir. Buton dili Google Workspace
capability modeline uygun olarak "Grant access" aksiyonunu kullanir. Workflow
run sonuclari icin teknik sonuc/kanit karti render edilmez; agent execution
sonucunu kendi icinde dogrular ve kullaniciya normal assistant mesaji olarak
cevap verir. Google Sheets iceren direct action veya workflow run sonuclarinda
`ArtifactPreview` component'i kucuk tablo snapshot'i ve Google Sheets linki
gosterir; tam spreadsheet Conduut icinde kopyalanmaz. Artifact tablo satirlari
Firestore uyumlu yeni formatta kolon adindan hucre preview'ine giden obje
olarak gelir; component geriye donuk olarak eski array row formatini da
render edebilir. Gmail direct action veya Gmail node'lu workflow run
sonuclarinda ayni `ArtifactPreview` component'i mail ikonlu `message_preview`
karti gosterir; alici, gonderen, konu, arama sorgusu, sonuc sayisi ve
govde/snippet ozeti varsa kart icinde basilir, Gmail linki `Open` aksiyonu
olarak kalir. Gecmis conversation detail response'lari backend'den
`created_at`/`assistant` seklinde gelse bile `src/lib/chat/messages.ts`
normalizer'i bunlari `createdAt` ve `agent` UI rolune cevirir; bu hem
`Invalid Date` gorunumunu hem de kalici message attachment'larinin UI'da
atlanmasini engeller.
Streaming sirasinda `attachment` event'leri tool calisirken final assistant
metninden once gelebilir; web chat sayfalari bu attachment'lari hemen render
etmez, assistant text'i akitir ve `done` event'inde kartlari ayni mesajin
altinda acar. Boylece artifact kartlari once gorunup sonradan ustlerine final
cevap bubble'i eklenmis gibi ziplama yapmaz.

## Dashboard Artifacts

`/dashboard/artifacts` kullanicinin kalici artifact preview snapshot'larini
listeler. Sayfa Firebase token ile `/api/artifacts?limit=50` BFF route'unu
cagirir; servis filtresi secildiginde `service=google_sheets` veya
`service=gmail` query parametresi gonderir. Chat ve workflow run tarafinda
uretilen raw snapshot sozlesmesi ayni kalir, ancak dashboard Sheets icin bu
snapshot'lari dogrudan chat karti gibi basmaz. Web sayfasi Google Sheets
kayitlarini `spreadsheetId` veya URL'e gore tek resource kartinda gruplar;
metadata-only `spreadsheet.create` tablosundan spreadsheet adi/sheet bilgisini
alir, veri preview'i icin ise en yeni metadata disi tablo snapshot'ini kullanir.
Bu sayede ayni Sheet icin "spreadsheet created" ve "range updated" aksiyonlari
ayri kartlar olarak gorunmez.
Gmail artifact kayitlari `message_preview` olarak kalir; dashboard generic
kart yolu `message` payload'indan alici/gonderen/konu/search/snippet ozetini
render eder ve Gmail `Open` linkini dis uygulamaya birakir. Dashboard kartlari
silme aksiyonu da sunar; tekil kartlar tek artifact dokumanini, Sheets resource
kartlari ise ayni gruptaki artifact dokumanlarini BFF `DELETE
/api/artifacts/{artifactId}` uzerinden kaldirir.

`ClarificationPanel` component'i agent'in aktif `user_input_request`
attachment'ini render eder. Aktif son soru varken ana `ChatInput` composer'i
gizlenir; alt cevap alaninda sadece clarification paneli gosterilir ve ayni
anda message list icinde ozet karti olarak tekrar render edilmez. Panel agent
sorusunu ve `missingFields` etiketlerinden uretilen cevap kontrollerini
gosterir; boylece agent genel bir soru sorsa bile kullanici hangi alanlarin
beklendigini gorur.
Birden fazla `missingFields` varsa panel ayrica ozet/kart listesi acmaz, her
alan icin dogrudan doldurulacak kontrol gosterir ve hepsi dolmadan submit aktif
olmaz. Coklu alanda `choices` gelirse bunlar ayri cevap kartlari olarak degil
ilk eksik alanin secim kontrolu olarak render edilir; o alan icin ayrica text
input gosterilmez. Tek eksik alan veya seceneklerin tek basina yeterli oldugu
sorularda secenek tiklama normal chat mesaji olarak agent'a gonderilir. Coklu
alan cevabi modele `Alan: deger` satirlari olarak iletilir.

Gecmis `user_input_request` mesajlari tamamen gizlenmez. `Message` component'i
bunlari kompakt "Conduut asked for details" ozeti olarak render eder; boylece
kullanici once hangi sorularin soruldugunu gorebilir ama aktif clarification
paneliyle cift gorunum olusmaz.

## UI State

- `chat-store.ts`: conversation sidebar state.
- `ui-store.ts`: sidebar collapse gibi UI state.
- `use-model-selector.ts`: provider, model ve favorite model secimi. Backend
  eski aktif `settings/llm` kaydini provider fallback'i olarak dondurdugu icin
  yeni chat selector'i sadece yeni provider collection'i dolu olan
  kullanicilarda degil, eski ayar formatina sahip kullanicilarda da gorunur.

Ilgili notlar: [[chat-workflow-generation]], [[dashboard]], [[agent-service]].
