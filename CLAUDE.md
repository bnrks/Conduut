# Conduut

Conduut, kullanıcıların AI agent ile sohbet ederek n8n workflow'ları oluşturmasını sağlayan bir platformdur.

## Proje yapısı

```
conduut/
├── apps/
│   ├── web/                 ← Next.js 14+ frontend (App Router)
│   ├── agent/               ← Agent servisi (Python, FastAPI)
│   ├── control-plane/       ← Container orkestrasyon (Python, FastAPI)
│   ├── oauth-proxy/         ← Merkezi OAuth yönetimi (Python, FastAPI)
│   └── node-agent/          ← Her VPS'te çalışan container yönetici
├── packages/
│   ├── n8n-registry/        ← n8n node şemaları, RAG verisi
│   └── shared/              ← Ortak tipler, utils, config
├── infra/
│   ├── docker/              ← Dockerfile'lar
│   ├── traefik/             ← API gateway config
│   └── monitoring/          ← Prometheus, Grafana, Loki
├── brand/                   ← Logo, renk paleti, font dosyaları
├── docs/                    ← Mimari dokümanlar
└── scripts/                 ← Yardımcı scriptler
```

## Teknoloji kararları

- Frontend: Next.js 14+, App Router, Tailwind CSS, TypeScript
- Backend servisleri: Python 3.12+, FastAPI, async/await
- Veritabanı: PostgreSQL 16 (pgvector eklentisi ile)
- Cache: Redis 7
- Container runtime: Docker, Docker Compose
- API gateway: Traefik
- LLM: Claude Sonnet API (Anthropic SDK)
- Font: Inter (Google Fonts)
- Ana renk: #534AB7 (Conduut Purple)

## Kodlama kuralları

- Python: ruff formatter + linter, type hints zorunlu, async fonksiyonlar tercih
- TypeScript: strict mode, biome formatter, named exports
- Commit: conventional commits (feat:, fix:, refactor:, docs:, test:, chore:)
- Branch: feature/*, fix/*, refactor/* pattern
- Her servis kendi Dockerfile'ına sahip, root'ta docker-compose.yml ile orkestre

## Doğrulama komutları

- Frontend: `cd apps/web && pnpm lint && pnpm typecheck && pnpm test`
- Python servisleri: `cd apps/{servis} && ruff check . && ruff format --check . && pytest`
- Tüm proje: `docker compose build`

## Önemli mimari kurallar

- Her kullanıcıya ayrı n8n Docker container'ı (izolasyon)
- OAuth token'ları PostgreSQL'de pgcrypto ile şifreli (MVP), ileride Vault
- Agent, n8n'e REST API üzerinden bağlanır (doğrudan container erişimi yok)
- Container'lar n8n-isolated Docker network'ünde çalışır (internet erişimi yok)
- Kontrol katmanı VPS'lere SSH yapmaz, her düğümde node-agent çalışır
- 30 dk inaktif container → hibernation (docker stop, volume korunur)

## Referans dokümanlar

- @PROJECT.md — Tam mimari doküman (DB şeması, akışlar, maliyet)
- @BRAND.md — Renk paleti, font, logo prompt'ları
- @docs/architecture.md — Detaylı mimari diyagramlar

---

## Geliştirme durumu (son güncelleme: 2026-04-10)

### Çalışan servisler (docker compose up)
- `conduut-agent` — FastAPI agent servisi, port 8000
- `conduut-n8n` — n8n instance, port 5678
- `conduut-web` — Next.js frontend, port 3000

### Tamamlanan özellikler
- **Chat UI (SSE streaming):** `apps/web/src/app/(chat)/chat/` ve `[conversationId]/` sayfaları çalışıyor. SSE token'ları render ediliyor.
- **Agentic loop:** `apps/agent/src/agent/loop.py` — LiteLLM üzerinden Claude, tool calling destekli, MAX_TOOL_ROUNDS=5. Keep-alive ping mekanizması var (asyncio.ensure_future + shield, 2s timeout).
- **n8n araçları:** `apps/agent/src/agent/tools.py` — list, get, create, update, delete, activate, deactivate, execute workflow + list_executions
- **Konuşma geçmişi:** Firestore'da saklanıyor (`apps/agent/src/store.py`)
- **Auth:** Firebase Auth ile JWT doğrulama

### Kritik bug fix'ler (bu oturumda yapıldı)
- **SSE render sorunu:** React 18 StrictMode double-mount + `setMessages(directValue)` batching sorunu çözüldü. `[conversationId]/page.tsx`'de updater function kullanılıyor: `setMessages((prev) => prev.length > 0 ? prev : data.messages)` + `hasCachedMessages.current = true` set ediliyor.
- **Duplicate workflow sorunu:** Agent update yerine create çağırıyordu. `update_workflow` tool eklendi ve system prompt güncellendi — artık mevcut workflow varsa `update_workflow` kullanıyor.

### Agent system prompt kuralları (apps/agent/src/agent/loop.py)
- Act directly — onay sorma, hemen yap
- CREATE vs UPDATE: yeni workflow için create, mevcut için update
- update_workflow öncesi get_workflow ile mevcut yapıyı çek, merge et, tam yapıyı gönder
- Workflow ID'lerini konuşma boyunca takip et

### Bilinen sorunlar / yapılacaklar
- LLM model seçimi: varsayılan ayarlara göre değişiyor, Sonnet kullan (Opus debug için kullanıldı)
- n8n'e node ekleme: agent bazen geçersiz node tipi üretiyor (n8n node type doğrulaması yok)
- RAG pipeline henüz yok — agent n8n node şemalarını bilmiyor, LLM genel bilgisine dayanıyor
- OAuth proxy henüz implement edilmedi
- Control plane henüz implement edilmedi
- Her kullanıcıya ayrı n8n container: şu an tek paylaşık n8n instance (MVP)

### Docker / ağ notları
- MTU sorunu: Docker Desktop'ta MTU=1450 ayarlı (SSL SSLV3_ALERT_BAD_RECORD_MAC hatasını önlemek için)
- `docker-compose.yml`'de network driver_opts ile MTU set ediliyor

### Önemli dosyalar
- `apps/agent/src/agent/loop.py` — agentic loop, system prompt, keep-alive
- `apps/agent/src/agent/tools.py` — tool tanımları + executor
- `apps/agent/src/n8n_client.py` — n8n REST API client
- `apps/web/src/app/(chat)/chat/[conversationId]/page.tsx` — konuşma sayfası (SSE fix burada)
- `apps/web/src/lib/chat/sse.ts` — SSE stream parser
- `apps/web/src/lib/chat/conversation-cache.ts` — sayfa geçişinde mesaj önbelleği
