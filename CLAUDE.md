# Conduut

Conduut, kullanıcıların AI agent ile sohbet ederek n8n workflow'ları oluşturmasını sağlayan bir platformdur.

---

## CLAUDE.md Güncelleme Kuralı

**Her önemli değişiklikten sonra bu dosyayı güncelle.** Yeni özellik, bug fix, mimari karar veya yapılacaklar listesindeki herhangi bir değişiklik sonrası ilgili bölümü güncelle. Amaç: bir sonraki oturumda nereden kaldığımızı hemen anlayabilmek.

---

## Oturum Başlangıç Protokolü (Knowledge Database)

Bu projenin kalıcı hafızası `knowledge-database/` Obsidian vault'unda tutulur.
`index.md` aşağıda otomatik olarak yüklenir (hub/harita). Her yeni oturumda:

1. Aşağıdaki `@knowledge-database/index.md` haritasını oku.
2. Görevle ilgili notu/notları `index.md`'deki linklerden seç ve **iş yapmadan önce** aç
   (ör. mimari için [[system-architecture]], agent için [[agent-service]], kararlar için ilgili `adr-*`).
3. Sonra göreve özgü kaynak dosyaları aç.

**Hafıza güncelleme kuralı (zorunlu):** Önemli bir değişiklik, mimari karar, feature,
bug fix veya test sonucu sonrası ilgili `knowledge-database` notunu **aynı görevde** güncelle.
Gerekirse yeni not aç ve Obsidian wikilink (`[[not-adı]]`) ile `index.md`'ye bağla.
Yeni ADR'leri mevcut yanlış yazımlı `03-desicions/` klasörüne ekle (klasörü yeniden adlandırma).
Notlar Türkçe öncelikli, teknik tanımlayıcılar İngilizce.

@knowledge-database/index.md

---

## Proje yapısı (gerçek durum)

```
conduut/
├── apps/
│   ├── web/                 ← Next.js 14+ frontend (App Router) ✅ ÇALIŞIYOR
│   ├── agent/               ← Agent servisi (Python, FastAPI)    ✅ ÇALIŞIYOR
│   ├── control-plane/       ← Container orkestrasyon             ❌ YAPILMADI
│   ├── oauth-proxy/         ← Merkezi OAuth yönetimi             ❌ YAPILMADI
│   └── node-agent/          ← Her VPS'te çalışan container yön.  ❌ YAPILMADI
├── packages/
│   ├── n8n-registry/        ← n8n node şemaları, tool-based RAG  ✅ ÇALIŞIYOR
│   └── shared/              ← Ortak tipler, utils, config        ❌ YAPILMADI
├── infra/
│   ├── docker/              ← Dockerfile'lar (apps/ altında şimdilik)
│   ├── traefik/             ← API gateway config                 ❌ YAPILMADI
│   └── monitoring/          ← Prometheus, Grafana, Loki          ❌ YAPILMADI
├── brand/                   ← Logo, renk paleti, font dosyaları
├── docs/                    ← Mimari dokümanlar
└── scripts/                 ← Yardımcı scriptler
```

---

## Teknoloji kararları

- Frontend: Next.js 14+, App Router, Tailwind CSS, TypeScript
- Backend servisleri: Python 3.12+, FastAPI, async/await
- Veritabanı: Firestore (MVP) → PostgreSQL 16 + pgvector (RAG için gerekli)
- Cache: Redis 7 (henüz kullanılmıyor)
- Container runtime: Docker, Docker Compose
- API gateway: Traefik (henüz kullanılmıyor, doğrudan portlar açık)
- LLM: LiteLLM üzerinden çoklu provider (Anthropic, OpenAI, Gemini, Groq, OpenRouter)
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

- Her kullanıcıya ayrı n8n Docker container'ı (izolasyon) — **şu an tek shared instance, MVP**
- OAuth token'ları PostgreSQL'de pgcrypto ile şifreli (MVP), ileride Vault
- Agent, n8n'e REST API üzerinden bağlanır (doğrudan container erişimi yok)
- Container'lar n8n-isolated Docker network'ünde çalışır (internet erişimi yok)
- Kontrol katmanı VPS'lere SSH yapmaz, her düğümde node-agent çalışır
- 30 dk inaktif container → hibernation (docker stop, volume korunur)

## Referans dokümanlar

- @PROJECT.md — Tam mimari doküman (DB şeması, akışlar, maliyet)
- @BRAND.md — Renk paleti, font, logo prompt'ları

---

## Geliştirme durumu (son güncelleme: 2026-04-13)

### Çalışan servisler (docker compose up)
- `conduut-agent` — FastAPI agent servisi, port 8000
- `conduut-n8n` — n8n instance, port 5678
- `conduut-web` — Next.js frontend, port 3000

---

### ✅ Tamamlanan özellikler

#### Agent Servisi (`apps/agent/src/`)
- **Agentic loop** (`agent/loop.py`) — LiteLLM üzerinden çoklu LLM, tool calling, SSE streaming, MAX_TOOL_ROUNDS=8, keep-alive ping (asyncio + shield, 2s timeout)
- **n8n araçları** (`agent/tools.py`) — list, get, create, update, delete, activate, deactivate, execute workflow + list_executions + **3 yeni registry tool** (search_n8n_nodes, get_node_schema, find_workflow_template) + Pydantic-free workflow JSON validator
- **n8n Node Registry** (`packages/n8n-registry/`) — n8n node şema yükleme, keyword search, schema extraction. Startup'ta `/types/nodes.json` endpoint'inden otomatik yüklenir. 100 workflow template (n8n.io API) hazır.
- **n8n client** (`n8n_client.py`) — Async HTTPX, tam CRUD + execution API
- **Konuşma geçmişi** (`store.py`) — Firestore: conversations, messages, LLMSettings, ProviderConnection, favorites
- **Auth** (`auth.py`) — Firebase ID token doğrulama
- **LLM ayarları API** — Provider ekleme, model listeleme, API key doğrulama, favorites

#### Web Frontend (`apps/web/src/`)
- **Chat UI** — `/chat/` (yeni konuşma) + `/chat/[conversationId]/` (devam), SSE token-by-token render
- **Conversation sidebar** — Konuşma listesi, geçmişe navigasyon
- **Model/provider seçici** — Anthropic, OpenAI, Gemini, Groq, OpenRouter, favorites
- **Workflow dashboard** (`/dashboard/workflows/`) — Liste, arama, activate/deactivate toggle, delete (optimistic update)
- **Auth sayfaları** — Login, register, forgot-password, AuthGuard (protected/guest routes)
- **API bridge layer** — Next.js API routes agent servisine proxy yapıyor

#### Düzeltilen bug'lar (geçmiş oturumlar)
- **SSE render sorunu:** React 18 StrictMode double-mount + setMessages batching sorunu — updater function + `hasCachedMessages.current` ile çözüldü (`[conversationId]/page.tsx`)
- **Duplicate workflow sorunu:** Agent update yerine create çağırıyordu — `update_workflow` tool eklendi, system prompt güncellendi

#### Docker / Ağ
- MTU=1450 (SSL SSLV3_ALERT_BAD_RECORD_MAC hatasını önlemek için)
- `docker-compose.yml`'de `driver_opts` ile MTU set ediliyor
- Agent build context `./apps/agent` → `.` (root) olarak değiştirildi (`packages/n8n-registry` erişimi için)

---

### ❌ Yapılmadı / Eksik

#### Kritik (production blocker)

| # | Özellik | Açıklama |
|---|---------|----------|
| 1 | ~~**RAG Pipeline**~~ → **Tool-based Knowledge** ✅ | `packages/n8n-registry/` oluşturuldu. Agent startup'ta n8n'den `/types/nodes.json` çekiyor. `search_n8n_nodes`, `get_node_schema`, `find_workflow_template` tool'ları eklendi. RAG (pgvector) ihtiyaç duyulursa Faz 2'de eklenecek. |
| 2 | **Per-user n8n izolasyonu** | Şu an tek shared n8n instance — herkes aynı n8n'i kullanıyor. Control plane + per-user container gerekiyor |
| 3 | **OAuth Proxy** | Kullanıcı adına credential bağlantı akışı hiç yok (`apps/oauth-proxy/` başlanmadı) |
| 4 | **Control Plane** | Container lifecycle yönetimi yok (`apps/control-plane/` başlanmadı) |
| 5 | **Node Agent** | Her VPS'te çalışacak agent yok (`apps/node-agent/` başlanmadı) |

#### Orta öncelik

| # | Özellik | Açıklama |
|---|---------|----------|
| 6 | ~~**n8n node type doğrulaması**~~ ✅ | `tools.py`'de `_validate_workflow_nodes()` eklendi. create/update çağrısından önce node type format, trigger varlığı, id uniqueness kontrolü. Hata varsa LLM'e geri gönderilir. |
| 7 | **Dashboard: Settings sayfası** | Stub var, LLM provider verification UI eksik |
| 8 | **Dashboard: Connections sayfası** | Stub var, OAuth bağlantı yönetimi UI yok |
| 9 | **Dashboard: Usage sayfası** | Stub var, kullanım metrikleri UI yok |

#### Düşük öncelik

| # | Özellik | Açıklama |
|---|---------|----------|
| 10 | **Marketing sayfası** | Hiç yapılmamış |
| 11 | **Monitoring** | Prometheus + Grafana + Loki yok |
| 12 | **Stripe entegrasyonu** | Ödeme sistemi yok |
| 13 | **Temizlik** | `apps/agent/apps/` ve `apps/web/apps/` boş iç-içe dizinler silinmeli |

---

### Yol haritası

```
Faz 1 — Kalite ✅              → packages/n8n-registry + tool-based knowledge + agent entegrasyonu
Faz 2 — Dashboard tamamlama   → Settings, Connections, Usage sayfaları
Faz 3 — İzolasyon             → Control plane + node agent + per-user container
Faz 4 — OAuth                 → OAuth proxy + Google/Slack/Notion flow
Faz 5 — Production            → Monitoring + Stripe + Marketing sayfası
```

---

### Son oturum özeti (2026-04-13) — Nerede kaldık

**Ne yaptık:** Agent'ın n8n workflow üretimindeki halüsinasyon sorununu çözdük. Agent artık node şemalarını runtime'da lookup ediyor.

**Oluşturulan `packages/n8n-registry/` paketi:**
- `src/n8n_registry/models.py` — `NodeInfo` ve `WorkflowTemplate` dataclass'ları
- `src/n8n_registry/loader.py` — nodes.json + templates.json parse (deduplication dahil)
- `src/n8n_registry/search.py` — keyword search, alias sistemi (`"function"` → `["code"]` vb.), schema extraction
- `src/n8n_registry/registry.py` — `NodeRegistry` singleton sınıfı
- `scripts/fetch_nodes.py` — `docker cp conduut-n8n:/home/node/.cache/n8n/public/types/nodes.json` ile çeker (HTTP 401 sorunu nedeniyle)
- `scripts/fetch_templates.py` — n8n.io API'den template indirir
- `data/templates.json` — 100 gerçek workflow template (commit'lendi)
- `data/nodes.json` — 807 unique node şeması (gitignore'da, `fetch_nodes.py` ile üretilir)

**Agent entegrasyonu:**
- `apps/agent/src/registry.py` — startup singleton
- `apps/agent/src/agent/tools.py` — `search_n8n_nodes`, `get_node_schema`, `find_workflow_template` tool'ları + `_validate_workflow_nodes()` validator
- `apps/agent/src/agent/loop.py` — hard-coded `_NODE_TEMPLATES` kaldırıldı, lookup-first system prompt, MAX_TOOL_ROUNDS=8
- `apps/agent/src/main.py` — startup'ta `initialize_registry()` çağrısı
- `apps/agent/Dockerfile` — build context root'a alındı, n8n-registry paketi kurulumu eklendi
- `docker-compose.yml` — agent build context `.` (root) olarak güncellendi

**Önemli teknik not — nodes.json nasıl yenilenir:**
```bash
# n8n container çalışırken:
python packages/n8n-registry/scripts/fetch_nodes.py
# Çıktı: packages/n8n-registry/data/nodes.json (gitignore'da)
# Docker build'de data/ dizini /app/data/ olarak kopyalanır
```

**Test durumu:** Kullanıcı henüz test etmedi. "Kelime sayma workflow" testi yapılacak.
**Sonraki adım:** Test et → çalışıyorsa Faz 2 (Dashboard) veya Faz 3 (İzolasyon) devam et.

---

### Agent system prompt kuralları (`apps/agent/src/agent/loop.py`)
- Act directly — onay sorma, hemen yap
- CREATE vs UPDATE: yeni workflow için `create_workflow`, mevcut için `update_workflow`
- `update_workflow` öncesi `get_workflow` ile mevcut yapıyı çek, merge et, tam yapıyı gönder
- Workflow ID'lerini konuşma boyunca takip et

### n8n node registry kuralları
- Agent her bilinmeyen node için `search_n8n_nodes` → `get_node_schema` → `create_workflow` akışını izler
- `nodes.json` agent startup'ta n8n `/types/nodes.json`'dan çekilir, dosyaya kaydedilmez (runtime)
- Templates: `packages/n8n-registry/data/templates.json` — `fetch_templates.py` ile güncellenir
- Nodes: `packages/n8n-registry/scripts/fetch_nodes.py` ile yerel kayıt yapılabilir
- Template sayısı artırmak için: `python packages/n8n-registry/scripts/fetch_templates.py --limit 200`

### Önemli dosyalar
- `apps/agent/src/agent/loop.py` — agentic loop, system prompt, keep-alive
- `apps/agent/src/agent/tools.py` — tool tanımları + executor + workflow validator
- `apps/agent/src/registry.py` — NodeRegistry singleton (n8n'den startup'ta yüklenir)
- `apps/agent/src/n8n_client.py` — n8n REST API client
- `apps/agent/src/store.py` — Firestore veri katmanı
- `packages/n8n-registry/src/n8n_registry/registry.py` — NodeRegistry sınıfı
- `packages/n8n-registry/src/n8n_registry/loader.py` — nodes.json + templates.json parse
- `packages/n8n-registry/src/n8n_registry/search.py` — keyword search + schema extraction
- `packages/n8n-registry/scripts/fetch_nodes.py` — n8n'den node şemalarını çeker
- `packages/n8n-registry/scripts/fetch_templates.py` — n8n.io'dan template'leri indirir
- `apps/web/src/app/(chat)/chat/[conversationId]/page.tsx` — konuşma sayfası (SSE fix burada)
- `apps/web/src/lib/chat/sse.ts` — SSE stream parser
- `apps/web/src/lib/chat/conversation-cache.ts` — sayfa geçişinde mesaj önbelleği
- `apps/web/src/app/(dashboard)/dashboard/workflows/page.tsx` — workflow dashboard
