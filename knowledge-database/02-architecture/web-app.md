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
servisine aktarir.

## BFF API Routes

Baslica route handler'lar:

- `api/chat/send`: FastAPI `/api/chat/send` endpoint'ine SSE stream proxy eder.
- `api/conversations`: conversation listesi.
- `api/conversations/[conversationId]`: conversation detail/delete.
- `api/workflows`: workflow listesi.
- `api/workflows/[workflowId]`: activate/deactivate/delete proxy.
- `api/connections`: connection listeleme.
- `api/connections/[connectionId]`: connection silme proxy.
- `api/connections/google/gmail/authorize`: Firebase token ile agent Google
  Gmail authorize endpoint'ine proxy eder.
- `api/oauth/google/callback`: Google OAuth callback'ini auth header olmadan
  agent callback endpoint'ine iletir ve dashboard'a success/error redirect
  yapar.
- `api/settings/llm`: aktif provider/model/API key ayarlari.
- `api/settings/llm/providers`: provider ekleme/listeleme.
- `api/settings/llm/providers/[provider]/models`: model listeleme.
- `api/settings/llm/providers/[provider]/verify`: provider key dogrulama.
- `api/settings/favorites`: favorite modeller.

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
`authorizePath` ile Google Gmail OAuth authorize route'unu cagirir ve
authorization URL'ine yonlendirir. Workflow run sonuclari icin ayri sonuc/kanit
karti render edilmez; agent execution sonucunu kendi icinde dogrular ve
kullaniciya normal assistant mesaji olarak cevap verir.

`ClarificationPanel` component'i agent'in `user_input_request` attachment'ini
render eder. `user_input_request` mesajlari normal chat balonu/karti olarak
gosterilmez; aktif son soru chat input'unun hemen ustunde Conduut temasina uygun
bir panel olarak acilir. Panel agent sorusunu, varsa secilebilir cevaplari ve
tek bir serbest cevap input'unu gosterir. Secenek tiklama veya serbest cevap,
normal chat mesaji olarak agent'a gonderilir.

## UI State

- `chat-store.ts`: conversation sidebar state.
- `ui-store.ts`: sidebar collapse gibi UI state.
- `use-model-selector.ts`: provider, model ve favorite model secimi.

Ilgili notlar: [[chat-workflow-generation]], [[dashboard]], [[agent-service]].
