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

Local `pnpm dev` ile web host uzerinde calistiginda BFF route'lari agent'a
`AGENT_API_BASE_URL=http://localhost:8100` ile ulasir; Docker compose icindeki
web container ise `AGENT_API_BASE_URL=http://agent:8000` kullanir. Root
`start-local-dev.bat`, Windows'ta port `3000` excluded olabildigi icin web'i
default olarak `127.0.0.1:3007` uzerinde baslatir; port `CONDUUT_WEB_PORT` ile
degistirilebilir. Env veya port degisirse Next dev server yeniden
baslatilmalidir.

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
- `attachment`: workflow preview, oauth prompt, credential request veya
  user input request gibi ekleri ekler.
- `done`: provider/model bilgisini mesaj uzerine yazar.
- `error`: toast ile hata gosterir.

`WorkflowPreview` workflow kaydini daha belirgin bir "Workflow saved" paneliyle
gosterir. `OAuthPrompt` artik simule connect yapmaz; agent'tan gelen
`authorizePath` ile Google Gmail veya Google Sheets OAuth authorize route'unu
cagirir ve authorization URL'ine yonlendirir. Varsayilan Gmail authorize path'i
`/api/oauth/google/authorize?service=gmail`'dir. Buton dili Google Workspace
capability modeline uygun olarak "Grant access" aksiyonunu kullanir. Workflow
run sonuclari icin ayri sonuc/kanit karti render edilmez; agent execution
sonucunu kendi icinde dogrular ve kullaniciya normal assistant mesaji olarak
cevap verir.

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
- `use-model-selector.ts`: provider, model ve favorite model secimi.

Ilgili notlar: [[chat-workflow-generation]], [[dashboard]], [[agent-service]].
