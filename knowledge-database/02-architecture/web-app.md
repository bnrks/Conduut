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

Global font `src/app/layout.tsx` icinde `next/font/google` ile Inter ve
JetBrains Mono olarak yuklenir. Inter `400`, `500` ve `600` weight'lerini
yukler; `600`, Tailwind `font-semibold` kullanan metinlerin Webpack/Turbopack
ve browser sentetik font farklarindan etkilenmeden tutarli kalmasi icin
eklenmistir.

## Route Gruplari

- `(marketing)`: landing/marketing sayfasi.
- `(auth)`: login, register, forgot-password.
- `(chat)`: `/chat` ve `/chat/[conversationId]`.
- `(dashboard)`: dashboard shell, workflows, connections, usage, settings.
- `api`: Next route handler'lari; agent servisine proxy/BFF katmani.

`(marketing)` route grubu platform tema tercihinden bilincli olarak ayrilir.
Landing acik renk tasarimidir; route-scoped `layout.module.css` layout kokundeki
semantic tema degiskenlerini light degerlere sabitler. Boylece `<html>`
uzerindeki persist edilmis `.dark` sinifi dashboard/chat icin korunurken logo
ve ortak button variant'lari landing'de koyu metin ve acik yuzey renklerini
kullanir.

Landing yeniden tasariminin Part 1 adiminda hero, provider ve uygulanmamis plan
iddialarindan arindirildi. Ilk ekran artik Conduut'un guncel urun zincirini
anlatir: dogal dil istegi, n8n workflow draft'i, Gmail/Sheets connection
kontrolu, Safe preview ve gercek run oncesi structured approval. Urun tiyatrosu
bilincli olarak `No live run yet` siniri tasir; kullanici onayi ve execution
kaniti olmadan workflow calismis gibi sunulmaz. Ana hero metni SSR'da gorunur,
Framer Motion yalniz destekleyici urun panellerini progressive olarak getirir.
Sag urun tiyatrosu dashboard-benzeri ozel kartlar yerine gercek chat yuzeyinin
gorsel sozlugunu kullanir: user message bubble, assistant avatar + activity
satirlari + segmentli cevap, dogrudan paylasilan `WorkflowPreview` attachment'i
ve `ClarificationPanel` ile ayni secenek/onay dili. Marketing ornegi canli chat
state'ine baglanmaz; statik ve yan etkisizdir.
Hero chat tiyatrosunun dis olculeri mesaj/attachment sayisina bagli degildir.
Masaustunde genis yatay panel sol metin bloguyla yaklasik ayni yuksekliktedir;
header sabit kalir, conversation govdesi `min-h-0` + `overflow-y-auto` ile kendi
icinde dikey kayar. Mobilde de ayni sabit viewport modeli korunur ve sayfa
genisliginde yatay tasma olusmaz.
Marketing chat ornegi mount sonrasi tek seferlik deterministik bir demo oynatir:
idle viewport -> user message -> agent activity -> assistant cevabi ->
`WorkflowPreview` -> structured approval. Her yeni asama conversation
viewport'unu yumusak bicimde alta kaydirir; dis panel olculeri degismez. Timer'lar
unmount'ta temizlenir; `prefers-reduced-motion` aktifse gecisler atlanip son
durum dogrudan gosterilir.
User mesajindan sonra kisa bir assistant typing asamasi vardir: Conduut avatarina
eslik eden animasyonlu `...` balonu `AnimatePresence` ile girip activity
satirlari baslamadan yumusakca kaybolur. Alt fade katmani typing/son mesajlari
ortmemesi icin kullanilmaz; scrollbar conversation viewport'unu belirtir.

Landing Part 2, eski uc adimli jenerik `HowItWorks` anlatimini
`Request -> Draft -> Check and preview -> Approval -> Run and review` akisini
gosteren tek merkez omurgali koyu timeline ile degistirir. Adim kartlari `sm`
ve uzerinde omurganin iki yanina sirayla yerlesir; mobilde omurga solda kalir ve
butun kartlar ayni kolonda akar. Ayri connector grid hucreleri, kart disina
tasan yatay elemanlar veya genislige bagli kolon hesaplari kullanilmaz.
Omurga uzerindeki hareketli durum isareti icerik yuksekligine yuzdeyle baglidir
ve reduced-motion tercihinde gosterilmez.

Landing Part 3, eski gercek-disi feature vaatlerini (`per-user isolated
container`, genel `one-click OAuth`, `400+ integrations`) kaldirir. Yeni
Features bolumu teknik altyapi adini one cikarmadan otomasyon dili kullanir.
Platform yetenekleri alti ayri component card ile sergilenir: `AI Automation
Builder`, `Integrations`, `Safe/Fast Checks`, `Approval Controls`,
`Results & Artifacts` ve `Run History & Recovery`. Her kart yalniz ikon ve
metin degil, ilgili urun davranisini gosteren kucuk bir UI motifi tasir.
Integrations karti mevcut kapsami Google Workspace, HTTP API ve
credential-backed servislerle sinirli ve dogru anlatir. Duzen genis
masaustunde 3x2, tablette iki kolon, mobilde tek kolon kullanir; teknik altyapi
adi kart metinlerinde yer almaz.

Landing yeniden tasariminda pricing bolumu simdilik degistirilmeden birakildi.
Pricing altindaki ayri `CtaSection` (`Get started today / Ready to automate
your work?`) root marketing sayfa akisindan kaldirildi; component dosyasi
yeniden kullanim ihtimali icin silinmedi.

## Auth

Firebase client auth `src/hooks/use-auth.ts` icinde kullanilir. Browser
`user.getIdToken()` ile token alir ve `Authorization: Bearer ...` header'i ile
Next API route'larina gonderir. Web BFF route'lari ortak server-only
`src/lib/agent-client.ts` uzerinden agent'a gider. Bu katman kullanicinin
Firebase token'ini `Authorization` header'inda korur, `X-Request-ID` tasir ve
Cloud Run private agent modu aciksa metadata server'dan audience-bound Google
ID token alip `X-Serverless-Authorization` header'ina ekler. `AGENT_API_BASE_URL`
artik yalniz server env'dir; `NEXT_PUBLIC_AGENT_API_BASE_URL` fallback'i
kullanilmaz. JSON ve SSE deadline controller'i response body tamamlanana veya
stream iptal edilene kadar yasatilir. Dashboard workflows sayfasi ilk listeleme isteginde
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
- `api/workflows/[workflowId]`: activate/deactivate/delete proxy; `POST`
  `?action=run` tekil workflow run, `?action=batch-run` batch run JSON proxy,
  `?action=batch-run-stream` ise batch run SSE progress proxy eder. Stream
  proxy chat send route'undaki gibi upstream body'yi manuel `ReadableStream`
  ile pompalar; boylece Next response'u batch bitene kadar bufferlamaz.
- `api/connections`: connection listeleme.
- `api/connections/[connectionId]`: connection silme proxy.
- `api/n8n/setup-guide`: authenticated agent `GET /api/n8n/setup-guide`
  endpoint'ini no-store olarak proxy eder. Secret-free camelCase payload,
  Settings icindeki embedded BYO kurulum rehberinin ve chat'teki canonical
  setup kaynaginin ayni kalmasini saglar.
- `api/oauth/google/authorize?service=gmail|sheets`: Firebase token ile agent
  Google Gmail veya Google Sheets authorize endpoint'ine proxy eder. Next 16
  dev ortaminda `api/connections/[connectionId]` dinamik route'u ile ayni dal
  altindaki `api/connections/google/.../authorize` route'lari 404'e dustugu
  icin authorize BFF yuzeyi `api/oauth/google` agacina tasindi.
- `api/oauth/google/callback`: Google OAuth callback'ini auth header olmadan
  generic agent Google callback endpoint'ine iletir ve connection id ile
  dashboard'a success/error redirect yapar.
- `api/credentials` + `api/credentials/[credentialId]` (+ `/finalize`),
  `api/credentials/types`, `api/credentials/catalog/...`, `api/credentials/icon`:
  custom HTTP + agent-managed + predefined credential kutuphanesi BFF'leri.

> **Kaldirildi (BYO-provider, [[adr-0011-conduut-managed-tiered-models]]):** eski
> `api/settings/llm`, `api/settings/llm/providers`,
> `.../providers/[provider]/models`, `.../providers/[provider]/verify` ve
> `api/settings/favorites` BFF route'lari **silindi**. Kullanici artik LLM
> key/provider/model/favorite kaydetmez; model backend'de tier router ile secilir.

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
saklanamaz. Cloud Run staging/production contract'i icin root `.env.example`
dosyasina `AGENT_API_AUTH_MODE`, `AGENT_API_AUDIENCE`,
JSON/SSE timeout'lari ile birlikte eklendi. Env veya port degisirse Next dev
server yeniden baslatilmalidir.

Settings `Automation Server` yuzeyi
`components/settings/automation-server-section.tsx` icinde connection
yonetimi ile embedded setup rehberini birlestirir. Rehber public hostname'i
strict DNS etiketi olarak dogruladiktan sonra yalniz `<your-hostname>`
placeholder'larina uygular ve HTTPS connection URL'ini prefill eder; API key
rehber state'ine, URL'e veya browser storage'a yazilmaz. Rehber connected
instance'ta kapali kalir; disconnected kullanici `Set up a new n8n` yolunu
sectiginde acilir. Ilerleme state'i kalici tutulmaz; son provider preflight'i
authoritative kabul edilir.

## Chat UI

Chat sayfasi sade bir composer'dir; **provider/model/reasoning-effort secimi
yoktur** (BYO-provider [[adr-0011-conduut-managed-tiered-models]] ile kaldirildi).
Model her mesajda backend'deki tier router tarafindan otomatik secilir. Conversation
olustuktan sonra `conversation-cache` ile gecici cache kullanilir ve router
`/chat/[conversationId]` sayfasina gider.

> Eski hali: chat sayfasi model/provider secimine izin verir, devam eden
> conversation'da provider+model kilitlenir, destekleyen modelde reasoning effort
> secicisi gosterilirdi. Bu UI tamamen kaldirildi. `Message` tipindeki
> `provider`/`model`/`reasoningEffort` alanlari yalniz geriye donuk tolere edilen
> opsiyonel alanlar olarak kaldi (secici degil).

SSE event'leri `src/lib/chat/sse.ts` ile parse edilir:

- `token`: assistant cevabina text ekler.
- `tool_call`: chat input altindaki typing indicator metnini gunceller; UI
  ham tool adini gostermek yerine `src/lib/chat/tool-activity.ts` mapping'iyle
  sade islem durumlari gosterir.
- `attachment`: workflow preview, oauth prompt, credential request,
  artifact preview veya user input request gibi ekleri ekler.
- `done`: provider/model bilgisini mesaj uzerine yazar.
- `error`: toast ile hata gosterir.

Chat mesajlarinda provider/model bilgisi response metadata'sinda tutulsa da
`Message` component'i bunu hover metadata'sinda gostermez; workflow preview ve
artifact kartlarinin yaninda yalnizca zaman bilgisi kalir.

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

Aktif clarification paneli yalniz ayni `user_input_request` attachment'inin
kompakt ozet kartini gizler; assistant mesajinin daha once stream edilmis
`content` ve segmentlenmis `steps` alanlarini gizlemez. Boylece agent once
aciklama yapip sonra soru sordugunda aciklama `done` event'inde veya conversation
reload sonrasinda kaybolmaz.
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

## Responsive Layout

Platform `>=768px` (tablet, laptop, masaustu) destekler; `<768px` (telefon)
hedef degil ama kirilmaz (graceful). Eski `app/layout.tsx` `<body>` uzerindeki
`min-w-[1024px]` sabit tabani **kaldirildi** — bu, sekme daraltildiginda cikan
yatay scrollbar'in kok nedeniydi. `overflow-x-hidden` ile maskelenmedi; gercek
tasma kaynaklari duzeltildi.

Breakpoint esigi `lg` (1024px):

- `>=1024px`: kalici sidebar (mevcut daraltma toggle'i korunur).
- `768-1023px` (ve altinda graceful): sidebar **overlay drawer**'a doner;
  icerik tam genislik.

Mekanizma:

- `hooks/use-media-query.ts` (`useMediaQuery(query, defaultValue=true)`):
  masaustu tespiti. Ilk render `defaultValue` doner (SSR/hydration uyumu;
  masaustunde flash olmamasi icin `true`), mount sonrasi gercek degere gecer.
- `ui-store.ts`: kalici `sidebarCollapsed` (masaustu daraltma) + yeni
  `mobileNavOpen`/`setMobileNavOpen`/`toggleMobileNav` (dar-ekran drawer).
- Dashboard (`components/layout/sidebar.tsx`) ve chat
  (`components/chat/conversation-sidebar.tsx`) sidebar'lari `isDesktop`'a gore
  iki mod render eder; mobilde `fixed` overlay + framer `x` slide. Drawer
  route degisiminde, backdrop tikinda ve `Escape` ile kapanir.
- Layout'lar (`(dashboard)/layout.tsx`, `(chat)/layout.tsx`) `lg:hidden`
  backdrop + hamburger acar; daraltma toggle butonu `hidden lg:flex`. `<main>`
  dolgu `p-4 sm:p-6`; chat ana icerik flex cocuguna `min-w-0` (genis kod
  blogu/icerik tasmasini onler).
- Marketing/auth zaten `md:`/`lg:` responsive sinifli; body tabani kalkinca
  devreye girer.

## UI State

- `chat-store.ts`: conversation sidebar state (`lib/stores/chat-store.ts`).
- `ui-store.ts`: `sidebarCollapsed` (masaustu sidebar daraltma) + `mobileNavOpen`
  (dar-ekran overlay drawer) UI state (`lib/stores/ui-store.ts`).

> **Kaldirildi (ADR-0011):** eski `use-model-selector.ts` hook'u (provider/model/
> favorite model secimi + `settings/llm` fallback mantigi) **silindi**; chat'te
> model selector yok, model backend tier router ile otomatik secilir.

Ilgili notlar: [[chat-workflow-generation]], [[dashboard]], [[agent-service]].
