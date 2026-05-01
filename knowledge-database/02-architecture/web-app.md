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
- `api/settings/llm`: aktif provider/model/API key ayarlari.
- `api/settings/llm/providers`: provider ekleme/listeleme.
- `api/settings/llm/providers/[provider]/models`: model listeleme.
- `api/settings/llm/providers/[provider]/verify`: provider key dogrulama.
- `api/settings/favorites`: favorite modeller.

## Chat UI

Yeni chat sayfasi model/provider secimine izin verir. Conversation olustuktan
sonra `conversation-cache` ile gecici cache kullanilir ve router
`/chat/[conversationId]` sayfasina gider. Devam eden conversation'da provider ve
model kilitlenir.

SSE event'leri `src/lib/chat/sse.ts` ile parse edilir:

- `token`: assistant cevabina text ekler.
- `tool_call`: chat input altindaki typing indicator metnini gunceller; UI
  ham tool adini gostermek yerine `src/lib/chat/tool-activity.ts` mapping'iyle
  sade islem durumlari gosterir.
- `attachment`: workflow preview veya oauth prompt gibi ekleri ekler.
- `done`: provider/model bilgisini mesaj uzerine yazar.
- `error`: toast ile hata gosterir.

`WorkflowPreview` workflow kaydini daha belirgin bir "Workflow saved" paneliyle
gosterir. Workflow run sonuclari icin ayri sonuc/kanit karti render edilmez;
agent execution sonucunu kendi icinde dogrular ve kullaniciya normal assistant
mesaji olarak cevap verir.

## UI State

- `chat-store.ts`: conversation sidebar state.
- `ui-store.ts`: sidebar collapse gibi UI state.
- `use-model-selector.ts`: provider, model ve favorite model secimi.

Ilgili notlar: [[chat-workflow-generation]], [[dashboard]], [[agent-service]].
