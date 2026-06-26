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

## Geliştirme durumu (son güncelleme: 2026-06-24)

### Çalışan servisler (docker compose up)
- `conduut-agent` — FastAPI agent servisi, port 8000
- `conduut-n8n` — n8n instance, port 5678
- `conduut-web` — Next.js frontend, port 3000

---

### ✅ Tamamlanan özellikler

#### Agent Servisi (`apps/agent/src/`)
- **Pydantic AI runner** (`agent/runner.py`) — Eski custom `loop.py` agentic loop **kaldırıldı**; artık Pydantic AI `Agent` kullanılıyor. SSE streaming (token/tool_call/attachment/done), keep-alive ping (asyncio task + 2s queue timeout), `MAX_MODEL_REQUESTS=12`, `MAX_TOOL_CALLS=32`. LLM provider seçimi `provider_factory.py` üzerinden. `loop.py` artık sadece `runner.run`'a yönlendiren ince kabuk.
- **Tool paketi** (`agent/tools/`) — Tek dosya değil, paket: `factory.py` (Pydantic AI tool kayıtları + agent kurulumu), `prompt.py` (system prompt), `spec_compiler.py` (WorkflowPlan/Spec → n8n JSON compiler), `validation.py` + `../validation.py` (node/connection normalize + `validate_workflow_payload`, hata→`ModelRetry`), `readiness.py` (credential/readiness analizi), `runtime_inputs.py` (runtime input şeması + webhook expression), `workflow_runner.py` (tekil + batch run), `execution.py` (execution özetleme).
- **Workflow üretimi — tek JSON yüzeyi + repair** (ADR-0010, 2026-06-14): Model yalnızca `create_workflow`/`update_workflow` görür ve **kompakt n8n JSON** yazar (`name`/`type`/`parameters`; `id`/`typeVersion`/`position`/`webhookId` ve lineer `connections` opsiyonel). Deterministik `agent/repair.py` boilerplate doldurur, lineer wiring çıkarır, AI sub-node'u `ai_*` porta taşır, `{{input.x}}`/`$json.x`→`$json.body.x` onarır ("onar-ya-da-reddet"; belirsizi `validate_workflow_payload` emniyet ağı reddeder). IR tool'ları (`create_workflow_from_graph/_plan/_spec`) **model yüzeyinden kaldırıldı**; `graph_compiler.py`/`spec_compiler.py`/`blocks.py` dahili kütüphane + test olarak kalır. typeVersion'lar **registry'den** çekilir. Hat: normalize → repair → apply_runtime_inputs → validate.
- **Graph compiler** (`agent/tools/graph_compiler.py` + `blocks.py`) — Curated declarative `Block` registry (HTTP, Set/Edit Fields, IF, Filter, Code, Merge, AI Agent + openai/anthropic chat model + memory, Gmail, Sheets) + bilinmeyen node'lar için generic `n8n:<exact-type>` fallback. Compiler connection topolojisini (main, true/false, `ai_*` ters portları), typeVersion, pozisyon, webhookId, resourceLocator, expression ve runtime input'u **her zaman kendisi** sahiplenir. Rol etiketli sub-node'lar (`attached_to`+`role`) → `ai_languageModel`/`ai_tool`/`ai_memory` portları. Ref'ler: `{ref:'input.x'}`, `{ref:'item.y'}`, `{ref:'node.<id>.field'}`. (bkz. ADR-0009)
- **Platform aksiyon katmanı** (`platforms/`) — `run_platform_action` tool'u ile **n8n'siz** direkt platform API çağrısı (Gmail/Sheets). Tek seferlik iş = platform action; tekrarlayan/zamanlanmış/tetiklenen = workflow. (bkz. ADR-0006)
- **n8n Node Registry** (`packages/n8n-registry/`) — node şema yükleme, keyword search, schema extraction. Startup'ta `/types/nodes.json`'dan yüklenir. 100 workflow template hazır. Agent emin olmadığı node için `search_n8n_nodes` → `get_node_schema` akışını izler.
- **n8n client** (`n8n_client.py`) — Async HTTPX, tam CRUD + execution API
- **Konuşma geçmişi** (`store.py`) — Firestore: conversations, messages, LLMSettings, ProviderConnection, favorites, workflow metadata (input_schema/resources), artifacts
- **OAuth (Google)** (`oauth/google.py`, `routes/connections.py`, `routes/credentials.py`) — Gmail/Sheets için Conduut-managed Google OAuth broker (bkz. ADR-0003)
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

### Son oturum özeti (2026-06-08) — Nerede kaldık

**Mevcut mimari (kod incelendi):** Agent katmanı 2026-04-13'ten beri büyük ölçüde evrildi:
- Custom agentic loop → **Pydantic AI runner** (`agent/runner.py`).
- `tools.py` tek dosya → **`tools/` paketi**.
- **WorkflowPlan/Spec compiler** eklendi (ADR-0005): agent ham JSON yerine semantik şema üretiyor, deterministik compiler n8n JSON'a çeviriyor. Ham JSON artık fallback.
- **`run_platform_action`** ile n8n-bypass direkt platform aksiyonları (ADR-0006).
- **Batch run** (ADR-0007), Google OAuth broker (ADR-0003) aktif.
- `agent/workflow_intent/` **boş** — typed intent engine (ADR-0008) park edildi, aktif yol WorkflowPlan compiler.

**Tespit edilen darboğaz (2026-06-08):** Compiler sadece Gmail + Sheets + filter action'larını destekliyordu. Yoğun kullanılan node'lar (HTTP Request, AI Agent, Code, Edit Fields/Set, IF, Merge) ham JSON fallback'e düşüyor, agent uzun JSON yazarken `MAX_MODEL_REQUESTS` limitine takılıp çöküyordu. → **2026-06-10'da çözüldü (aşağıya bakın).**

---

### Son oturum özeti (2026-06-26) — Predefined credential library (ADR-0015)

**Bağlam:** ADR-0012 credential kütüphanesi yalnızca generic HTTP auth tiplerini destekliyordu (`httpHeaderAuth` vb.). n8n'in predefined tipleri (`openAiApi`, `anthropicApi`, `githubApi` vb.) farklı mekanizma kullanıyor: `predefinedCredentialType` ile doğrudan node'a bağlanıyor, `genericAuthType` yolundan geçmiyor. Sonuç: her workflow kurulumunda aynı OpenAI key'i tekrar tekrar isteniyor, cross-workflow reuse yoktu.

**Karar (ADR-0015):** Mevcut `users/{uid}/credentials` koleksiyonuna `match_kind: "host" | "type"` ayrımı eklendi (varsayılan `"host"` — geri uyumlu, migrasyon yok). Predefined tipler `match_kind="type"` ile kaydediliyor; host zorunlu değil; bağlanırken `generic_auth_type=None` (n8n direkt `credentials.{type}` wiring'i yapar). OAuth2 tabanli predefined tipler (Google, Slack OAuth vb.) katalogdan **ayıklanıyor** (`is_oauth_type_name` + `schema_is_oauth`) — Connections katmanı değişmedi.

**Eklenen/değişen (backend):** `agent/credential_catalog.py` (**yeni**: `build_catalog` OAuth-ayıklamalı + `friendly_label`, `match_credentials_by_type`, `parse_schema_fields` taşındı, `fetch_credential_fields`). `routes/credentials.py` (`GET /catalog`, `GET /catalog/{type}/schema` OAuth 422, `POST /credentials` `match_kind` türetimi). `tools/readiness.py` (predefined tipler için type-matched kütüphane önce bakılıyor, `matchKind` taşıyor). `tools/factory.py` (`add_service_credential` yeni tool). `tools/prompt.py` (predefined tip tespiti → önce `list_credentials`, yoksa `add_service_credential`). `store.CustomCredential` (`match_kind` alanı). **336 passed; ruff temiz.**

**Frontend:** `service-credential-picker.tsx` (**yeni**: aranabilir katalog → dinamik alanlar). `/dashboard/credentials` çift mod (Servis seçici + Custom HTTP). `credential-auth-methods.ts` → `serviceMethodFromFields`. Chat kartı `match_kind` gönderiyor. **tsc temiz, eslint 0 hata.**

**Kavramsal ayrım (değişmez):** Connections = Conduut'un hem n8n'de hem serviste doğrudan erişimi olan servisler (Google Gmail/Sheets, `direct_api_enabled`, ADR-0006). Credentials = yalnızca n8n içinde kullanılan sırlar (openAiApi vb.). Bu ADR yalnızca Credentials tarafını genişletti.

**Bekleyen:** Canlı uçtan-uca doğrulama (Step 4, manuel): dashboard'dan OpenAI credential ekle → AI workflow → type-matched reuse → ikinci workflow'da öneri; OAuth tiplerinin katalogda görünmediğini doğrula. (bkz. [[adr-0015-predefined-credential-library]])

---

### Son oturum özeti (2026-06-24) — DeepSeek tier bake-off branch + ucuz model araştırması

**Bağlam:** İsteklerin çoğu MEDIUM tier'a (Claude Sonnet 4.6, $3/$15) düşüyor → maliyet yüksek. Kullanıcı ucuz alternatif istedi. **deep-research harness** ile DeepSeek V4 / Qwen 3.6 / 3.7 araştırıldı (23 kaynak, 25 adversarial doğrulama). Sonuç: en güçlü ucuz aday **DeepSeek V4 Pro** (first-party OpenAI-uyumlu API, tool calls + JSON, ~7x/17x ucuz, OpenRouter dışı). Risk: tool-call reliability kanıtı zayıf (tekil GitHub issue #1244 ~%11 plain-text-tool-call), bağımsız benchmark yok → canlı bake-off şart. Tüm bulgular: [[model-cost-research-2026-06]].

**Karar/uygulama:** Kullanıcı DeepSeek tarafını denemeye karar verdi. Branch: **`feature/deepseek-tier-bakeoff`**. Yeni **`deepseek` model profili** (provider=`deepseek`, first-party):
- Router + **SIMPLE → `deepseek-v4-flash`**; **MEDIUM + HARD → `deepseek-v4-pro`**. Thinking ilk bake-off'ta kapalı (DeepSeek OpenAI-uyumlu endpoint `openai_reasoning_effort` almıyor; Pro/Flash seçimi yeteneği belirler). Secondary'ler de DeepSeek (saf bake-off; secondary runtime'da henüz kullanılmıyor).
- Bu branch'te `CONDUUT_MODEL_PROFILE` default'u **`deepseek`** (config.py) → `docker compose up` direkt DeepSeek çalışır.

**Eklenen/değişen (TDD):** `config.py` (`deepseek_api_key` + `_PROVIDER_KEY_ATTR` + default profil `deepseek`), `provider_factory.py` (`SUPPORTED_PROVIDERS`+`deepseek`, `DEEPSEEK_BASE_URL=https://api.deepseek.com`, `build_model` case → `OpenAIChatModel`+`OpenAIProvider(base_url=...)`, `normalize_model_name` deepseek prefix), `model_registry.py` (`PROFILE_DEEPSEEK`). Testler: `test_config`/`test_provider_factory`/`test_model_registry`'ye deepseek case'leri; `test_runner` Sonnet-thinking testi profili açıkça `default`'a pin'ler. **299 passed (5 Windows-tmp alakasız); ruff temiz.**

**Canlı doğrulandı:** DeepSeek `/models` → `200`, model ID'leri tam olarak `deepseek-v4-flash` + `deepseek-v4-pro` (config doğru, key + base_url çalışıyor). API key `apps/agent/.env`'de zaten ekli (`CONDUUT_DEEPSEEK_API_KEY`).

**Ölçüm araçları (eklendi):** `runner.py` → `agent_run_finished` artık token usage logluyor (`input_tokens`/`output_tokens`/`cache_read_tokens`/`model_requests`/`usage_tool_calls`, `result.usage()` try/except'li). `scripts/analyze_bakeoff_logs.py` → `logs/agent/conduut-agent.jsonl`'i modele göre gruplayıp reliability (fail rate+tipleri) / build kalitesi (`workflow_repaired`+sandbox) / maliyet (token+tahmini USD) raporlar; `--since <bugün>` ile bake-off run'larını izole eder. Sonnet baz çizgisi (mevcut log): 31 run, %3.1 fail, 17 run'da 100 repair.

**Canlı bulgu + fix (2026-06-24 ilk koşu):** SIMPLE görevler flash yerine pro'ya gitti. Kök neden: **DeepSeek V4 varsayılan thinking ON, thinking modu forced tool_choice'u reddediyor** (`400 "Thinking mode does not support this tool_choice"`); router `output_type` (structured output→forced tool_choice) kullanınca her seferinde MEDIUM'a fallback ediyordu. **Fix:** `build_model_settings` deepseek için `{"extra_body": {"thinking": {"type": "disabled"}}}` gönderiyor (canlı kanıt: forced tool_choice extra_body'siz 400, ile 200). Ayrıca **log redaction bug'ı:** token alanları "token" substring'i yüzünden `[REDACTED]` oluyordu → `tok_in`/`tok_out`/`tok_cache_read`/`tok_cache_write` olarak yeniden adlandırıldı. **301 passed, ruff temiz.** Detay: [[model-cost-research-2026-06]] §7.

**Thinking display fix (2026-06-24, kural: flash OFF / pro ON):** thinking tüm tier'larda kapalıyken DeepSeek-pro reasoning'i normal mesaj `content`'i olarak yazıp chat balonuna sızdırıyordu (Sonnet'te thinking ON → panel'e gidiyordu). Canlı kanıt: thinking OFF → ThinkingPart=0/TOKEN=1016; ON → ThinkingPart=1906/TOKEN=1576 (pydantic-ai DeepSeek `reasoning_content`→ThinkingPart→mevcut `ThinkingPanel`). **Karar:** router+SIMPLE (flash) thinking OFF (forced tool_choice/hız), MEDIUM+HARD (pro) **thinking ON** (`create_agent` `output_type=str`→auto tool_choice, güvenli). `model_registry.py` `_DS_ON` eklendi. **301 passed, ruff temiz.** Restart sonrası pro reasoning panele gider; cost rakamları (§8) thinking-OFF baseline.

**Bekleyen:** Agent restart sonrası SIMPLE görevleri tekrar koş (artık flash'a gitmeli). Canlı bake-off — 5-10 gerçek senaryo, `analyze_bakeoff_logs.py --since <bugün>` ile ölç: (a) tool-call hata/retry oranı (DeepSeek #1244 riski), (b) build başarı oranı, (c) gerçek token/blended maliyet. İyiyse ADR-0015 olarak kalıcılaştır. (Henüz commit edilmedi.) DeepSeek hesap bakiyesini takip et (ilk istekte 402 görüldü).

---

### Son oturum özeti (2026-06-23) — Workflow sandbox test + self-repair (ADR-0014)

**Soru → karar:** Agent workflow oluşturduktan sonra execution hatası alırsa kendini düzeltmiyordu (build-zamanı sadece yapısal `repair.py`+validate vardı; runtime self-healing yoktu). Kullanıcı tespiti: hatayı görmek için çalıştırmak gerek ama çalıştırmak gerçek yan etki üretir (mail gider). Brainstorm → spec → plan → TDD inline uygulama (9 task). (bkz. [[adr-0014-workflow-sandbox-test]])

**Çözüm:** Build'in son adımında **yan-etkisiz sandbox test** — aksiyon node'ları (`disabled=true` ile nötralize, n8n atlar) hariç gerçek veri yolu klon bir workflow'da çalışır, **her durumda silinir**. 3 katmanlı geçme: (a) node hatası, (b) nötralize node'a giden üst-çıktı boş mu (deterministik), (c) **LLM yargısı** (sabit Gemini Flash, `research.py` deseni). Başarısız + bütçe içinde → **`ModelRetry`** ile model `update_workflow` ile düzeltir (en fazla 2 deneme, `ctx.deps.workflow_test_attempts`); bütçe dolunca `test_status="needs_attention"`, agent dürüstçe bildirir. Otomatik tetikleme `create_workflow`/`update_workflow` sonunda (readiness temiz + not-awaiting). Harness hatası build'i bloklamaz.

**Eklenen/değişen:** `agent/sandbox.py` (**yeni**: `run_sandbox_test`, `SandboxTestResult`, örnek girdi, test-klonu, boş-çıktı, `_run_judge_llm` izole), `agent/sandbox_nodes.py` (**yeni**: sınıflandırıcı + `neutralize_action_nodes`), `agent/tools/sandbox_gate.py` (**yeni**: `_test_and_gate`), `store.save_workflow_test_status`, `schemas.AgentDeps.workflow_test_attempts`, `tools/factory.py` (`_should_run_sandbox_test`+wiring, `retries=2→4`), `tools/prompt.py` (kural). **294 passed (5 Windows-tmp hatası alakasız); ruff temiz.** Spec/plan yerel (`docs/superpowers/`, gitignored).

**Canlı doğrulama + test-before-execute (2026-06-23):** `run_sandbox_test` gerçek n8n'e karşı doğrudan kanıtlandı (boş→fail+bulgu, sağlıklı→pass; HTTP node `disabled`, klonlar silindi). **Canlı chat akışında kapsama boşluğu bulundu:** workflow credential-blocked create → attach → doğrudan `execute` olunca sandbox **hiç tetiklenmiyordu** (logda 0 sandbox olayı, 2 ardışık görev). → **test-before-execute** eklendi: `execute_workflow`, `test_status != "passed"` ise (`_needs_pretest`) gerçek çalıştırmadan önce sandbox testini koşar; başarısızsa `_test_and_gate` (ModelRetry/self-repair), tükenirse execution **bloklanır**; `except ModelRetry: raise`. **Not:** o görevlerdeki asıl hata Gmail OAuth token süresi dolmuş idi — sandbox'ın disable ettiği node'un auth hatası, V1 non-goal (yakalanmaz). **Bekleyen:** test-before-execute'in data-transform senaryosunda canlı doğrulaması; frontend `test_status` rozeti ayrı follow-up.

---

### Son oturum özeti (2026-06-21) — Agent-yönetimli credential + web research (ADR-0013)

**Karar/uygulama:** Agent bir API'nin auth şemasını Gemini grounding ile araştırıp **secret'sız taslak credential** oluşturur; kullanıcı secret'ı chat'te veya dashboard'da sonra doldurur; finalize'da n8n credential oluşup node'a bağlanır. Secret asla agent/LLM'den geçmez. (bkz. [[adr-0013-agent-managed-credentials]], [[agent-managed-credentials-design]]) Brainstorm → spec → plan → TDD inline uygulama (11 task).

**Web search spike'ı:** Conduut agent'ının web search'ü yoktu; Pydantic AI 1.88 `WebSearchTool` ile eklenebilir olduğu doğrulandı. **Decoupled Gemini grounding provider-bağımsız** (Claude ana model + Gemini research tool kanıtlandı). Token: Gemini ~75 input vs Anthropic ~16k → research için **sabit Gemini Flash** seçildi.

**Eklenen/değişen (backend):** `agent/research.py` (**yeni**: `AuthResearchResult` + `credential_type_for_scheme` + Gemini grounding agent + `research_api_auth` cache'li), `store.py` (`ApiAuthCache` + global `api_auth_cache/{host}` CRUD; `CustomCredential` draft alanları `status`/`auth_config`/`secret_fields`/`source_url`/`pending_*` + `save_draft_credential` + `finalize_draft_credential`), `config.py` (`research_model`), `tools/credentials.py` (`prepare_api_credential_payload` research→draft→secret-only kart), `tools/factory.py` (`prepare_api_credential` tool), `tools/common.py` (`_credential_draft_instruction`), `routes/credentials.py` (`POST /credentials/{id}/finalize` `_build_n8n_data`+create+attach; GET list `status`), `schemas.py` (`CredentialRequestData.draftId`/`sourceUrl`), `prompt.py` (prepare + Conduut-farkındalık). **256 passed (5 Windows-tmp, alakasız); ruff temiz.**

**Frontend:** BFF `api/credentials/[credentialId]/finalize`, `credential-request.tsx` draft kartı (secret-only + kaynak notu), `credential-form.tsx` `secretOnly` modu, dashboard "Tamamlanmamış" rozeti + "Tamamla". **tsc temiz, eslint 0 hata.**

**Canlı doğrulandı (2026-06-21/22):** Gemini `output_type`+`WebSearchTool` kombinasyonu çalışıyor (api-ninjas → `X-Api-Key`, structured output; free-text fallback gerekmedi). Uçtan-uca: chat "api-ninjas'tan söz çek → mail" → `prepare_api_credential` → secret-only kart → finalize → n8n cred + attach → çalıştır → **mail geldi**. Cache hit doğrulandı. Dashboard "Tamamla" kartı görüldü.

**Test sırasında bulunup düzeltilen 3 entegrasyon bug'ı:** (1) **çift kart** — readiness (ADR-0012 manuel kart) + `prepare_api_credential` (draft kart) aynı node için iki kart açıyordu → readiness artık HTTP Request node'larını prepare akışına devrediyor (`research_candidates`, manuel kart emit etmez); reuse-match yalnız `ready` credential'lara bakar (draft attach edilemez). (2) **boş mail** — n8n HTTP **dizi** cevabını item'lara böldüğü için `$json[0].quote` boş çözülüyordu → `repair.py` Stage 5b `$json[0].field`→`$json.field` (HTTP-fed/HTTP-referenced; Code dizileri dokunulmaz) + prompt kuralı. (3) **prompt çelişkisi** — "email content" örneği bizzat `$json[0]` gösteriyordu (agent oradan öğrenmiş) → `$json.quote` düzeltildi. (bkz. [[known-issues]])

### Son oturum özeti (2026-06-19) — Custom (HTTP) credential kütüphanesi (ADR-0012)

**Karar/uygulama:** Kullanıcılar OAuth dışındaki "normal" credential'ları (HTTP node auth tipleri) Conduut'ta kaydedip HTTP Request node'larında kullanabilir. Brainstorm → spec → plan → TDD uygulama. (bkz. [[adr-0012-custom-http-credentials]])

**Mimari:** Secret yalnızca n8n credential store'unda (write-only; n8n public API `GET /credentials`→405, geri okunamaz); secret-olmayan metadata (`label`, `credential_type`, `host`, `n8n_credential_id`) per-user Firestore `users/{uid}/credentials`'te. V1 tipleri: `httpHeaderAuth`, `httpBasicAuth`, `httpQueryAuth`, `httpCustomAuth` (OAuth2/predefined kapsam dışı). Eşleştirme **host'a göre deterministik** (yalnız `n8n-nodes-base.httpRequest`); bağlama **onay-önce** (agent `request_user_input` ile sorar → `attach_credential`). Host outbound library/kart için **zorunlu**.

**Eklenen/değişen (backend):** `agent/credential_types.py` (**yeni**: katalog + `normalize_host` + `match_credentials`), `agent/tools/credentials.py` (**yeni**: `list_credentials_payload`/`attach_credential_payload`), `store.py` (`CustomCredential` + CRUD), `n8n_client.attach_credential_to_workflow` (`generic_auth_type` param → `authentication`/`genericAuthType` wiring), `routes/credentials.py` (POST library create+optional attach, GET, GET `/types`, DELETE `/{id}`), `schemas.py` (`CredentialTypeOption` + `CredentialRequestData.allowedTypes`/`host`), `tools/readiness.py` (genericCredentialType tespiti + host-match `reuse_candidates` + tip-seçicili kart; cross-workflow reuse köprüsü HTTP custom için kullanılmaz), `tools/factory.py` (`list_credentials`+`attach_credential` tool'ları, create/update sonucuna `credential_suggestions`), `tools/common.py` (`_credential_suggestion_instruction`), `tools/prompt.py` (HTTP auth kuralları). **235 passed (5 hata Windows tmp-izni, alakasız); ruff temiz.**

**Frontend:** `/dashboard/credentials` sayfası + nav (`navigation.ts`), `credential-request.tsx` (tip seçici + host + Custom JSON), BFF `api/credentials/types` + `api/credentials/[credentialId]` (DELETE). **tsc temiz, eslint 0 hata.**

**UX katmanı (2026-06-19b):** Kullanıcı n8n tip adlarını (httpHeaderAuth vb.) **hiç görmez**. Frontend düz-dil "auth method" modeli (`lib/credential-auth-methods.ts`: "API key / token" varsayılan, "Username & password", + Gelişmiş "URL'de key"/"Custom") → n8n `credential_type`+`data`'ya çevirir (backend değişmez). Paylaşılan `components/credentials/credential-form.tsx` hem chat kartı hem dashboard'da. Chat'te agent şemayı kendisi seçer (prompt: key/token→httpHeaderAuth, user+pass→httpBasicAuth, emin değilse tek düz-dil soru) → kart sadece secret ister; header adı/Bearer "Gelişmiş"te. "API key / token" → `{name:Authorization, value:"Bearer <key>"}` (özel header/prefiks Gelişmiş'te). Detay: [[adr-0012-custom-http-credentials]] "Kullanici Yuzeyi".

**Bekleyen:** Canlı uçtan-uca test (n8n + agent + web açık): dashboard'dan "API key / token" credential ekle (host `httpbin.org`) → "httpbin.org'a istek at" workflow'u → `credential_suggestions` → onay → `attach_credential` → node'da `genericAuthType`+`credentials` dolu; eşleşmesiz host → düz-dil kart. Eski `workflow_credentials` koleksiyonu deprecate (migrasyon yok).

### Son oturum özeti (2026-06-18b) — Conduut-yönetimli 3-kademe model + routing (ADR-0011)

**Karar/uygulama:** BYO-provider (kullanıcının kendi LLM key'ini bağlaması) **kaldırıldı**; modeller artık Conduut'un kendi anahtarlarıyla merkezi. Router isteği kademeye sınıflandırır; her kademe sabit model + thinking ayarı kullanır. (bkz. [[adr-0011-conduut-managed-tiered-models]])

**Profiller (`CONDUUT_MODEL_PROFILE`=default|gpt):** default → Router/Basit thinking kapalı, Orta=Sonnet adaptive+medium, Zor=Gemini 3 Pro level HIGH; **her kademe 2.tercih=GPT** (native OpenAI). `gpt` profili tüm kademeleri OpenAI yapar (tek-switch). Model id'leri ve thinking dict'leri `model_registry.py`'de model-başına sabit (asla runtime'da model adından türetilmez).
- Router: `gpt-5-mini` (off; eski `gemini-2.5-flash-lite` router rolünde 429/503 ile güvenilmez çıktı, router patlayınca her şey MEDIUM'a düşüyordu) · Basit: `claude-haiku-4-5-20251001` (off) · Orta: `claude-sonnet-4-6` (adaptive+medium) · Zor: `gemini-3.1-pro-preview` (HIGH). 2.tercihler: `gpt-5-mini`/`gpt-5.4`/`gpt-5.4`. **Model id'leri canlı `/models` ile doğrulandı (2026-06-19): `gemini-3-pro`→`gemini-3.1-pro-preview`, `claude-haiku-4-5`→`claude-haiku-4-5-20251001` düzeltildi.**

**Backend:** yeni `agent/model_registry.py` (Tier/ModelChoice/profiller/resolve), `agent/router.py` (`classify_tier`, hata→MEDIUM). `provider_factory.build_model_settings` provider-aware thinking olarak yeniden yazıldı (`ThinkingSpec`: anthropic_thinking+effort / google_thinking_config level|budget / openai_reasoning_effort); pydantic-ai 1.88.0 anahtarları paketten doğrulandı. `build_model` korundu (Conduut key'iyle). `runner.run` imzasından `settings` çıktı → classify→resolve→build→run + **per-tier UsageLimits** + tier'ı assistant mesajına yazar. `routes/chat.py` `ChatRequest` sadeleşti (`extra=ignore`, eski FE alanlarını yutar). `routes/settings.py`+`favorites.py` ve store BYO fonksiyon/dataclass'ları (LLMSettings, ProviderConnection, get/save_llm_settings, providers, favorites) **silindi**. `config.py`'ye `model_profile`+`*_api_key`+`key_for_provider`. **207 passed, ruff temiz.** (Korundu: OAuth/Gmail/Sheets, auth, crypto, tools/.)

**Frontend:** provider/model seçici UI (chat-input dropdown'ları), `use-model-selector` hook, settings "Assistant Connections" tab'ı, `/api/settings/llm`+`/api/settings/favorites` BFF route'ları **kaldırıldı**; chat artık sadece `{content, conversation_id}` gönderir. **tsc temiz, eslint 0 hata.**

**Escalation (Faz 2, bekliyor):** repair/validate reddi (`UnexpectedModelBehavior`) veya request-limit (`UsageLimitExceeded`) → effort yükselt → GPT 2.tercih → üst tier. Streaming-replay + n8n yan-etki çoğaltması nedeniyle bayrak (`CONDUUT_ENABLE_TIER_ESCALATION`) arkasında, buffered (yalnız ilk başarılı deneme flush) eklenecek.

**Bekleyen:** `.env` anahtarları eklendi + model-id'leri canlı doğrulandı (2026-06-19). Kalan: 5-kademe bake-off (canlı n8n) + `CONDUUT_MODEL_PROFILE=gpt` flip testi + escalation Faz 2. Detay: [[adr-0011-conduut-managed-tiered-models]].

### Son oturum özeti (2026-06-18) — Canlı test: gpt-5 yavaşlığı + Sheets resourceLocator onarımı

**Bağlam:** İlk canlı uçtan-uca test senaryosu çalıştırıldı: "her çalıştırmada BTC/USD fiyatını API'den çek → tarih/saat ile Sheets'e yaz" (agent Sheet'i `run_platform_action` ile kendi oluşturdu). İki ayrı bulgu:

**1. "Aşırı yavaş agent" — kök neden: gpt-5 latency, Conduut değil.** Canlı log analizi (`logs/agent/conduut-agent.jsonl`): tek workflow kurulumunda **OpenAI gpt-5 çağrıları 12 adet, toplam ~716 sn (ort. 60 sn, max 194 sn)**; n8n REST çağrıları toplam 13 sn (<1 sn/çağrı), registry 0.2 sn, Sheets/OAuth <1.5 sn. Yani duvar-saatinin ~%98'i model "düşünmesi". Agent ayrıca basit workflow için ~12 keşif turu atıyor (3× search_n8n_nodes, 3× get_node_schema) → her tur bir gpt-5 çağrısı. Ek olarak hata sonrası `MAX_MODEL_REQUESTS=12` limitine takılıp kendini düzeltemedi. **Aksiyon önerisi (uygulanmadı):** workflow-kurma döngüsünü hızlı modele al (gpt-4o-mini / hızlı Claude); reasoning modelini çok-turlu tool döngüsünde kullanma. (Not: root `.env`'de `CONDUUT_N8N_URL=:5980` latent yanlış; çalışan process default `:6180` kullanıyor — performansla ilgisiz, ayrı temizlik.)

**2. Execution hatası — Sheets resourceLocator (kalıcı fix, TDD).** Üretilen workflow n8n'de `Can not get sheet 'undefined' with a value of 'undefined'` ile patladı. Kök neden: model `googleSheets` node'unun `documentId`/`sheetName`'ini **düz string** yazıyor; n8n v4.7 bunları `{__rl, mode, value}` resourceLocator bekliyor. Compiler'lar (`graph_compiler`/`spec_compiler` `_sheet_locator`) bunu sarıyordu ama ADR-0010 IR'ı yüzeyden çıkarınca **repair bu mantığı miras almamıştı**. → `repair.py`'ye **Stage 6: resourceLocator normalizasyonu** eklendi (`_RESOURCE_LOCATOR_FIELDS` tablosu; googleSheets documentId=id, sheetName=name; URL değer → mode=url; zaten `__rl` olan dokunulmaz). TDD: `test_repair.py`'ye 3 test, **repair suite 19 passed; repair+validation+tools 95 passed; ruff temiz.** **Sınırlama:** sadece googleSheets kapsanıyor; Gmail/Drive vb. diğer RL alanları gerekirse tabloya eklenir. **Canlı uçtan-uca doğrulama bekliyor** (workflow yeniden kurulup execute edilmeli). Detay: [[adr-0010-json-surface-repair-normalizer]], [[known-issues]].

### Son oturum özeti (2026-06-14) — Tek JSON yüzeyi + onarıcı normalizer (ADR-0010)

**Karar:** 06-13'teki kök-neden bulgusunun (modele girişte native JSON verip çıkışta pretraining'inde olmayan IR ürettirme çatışması) çözümü brainstorm'da seçildi: **A→A** — modele tek ve doğal yüzey ver (kompakt n8n JSON), hataları **reddetmek yerine deterministik onar**. Plan onaylanıp uygulandı.

**Uygulanan (feature/json-surface-repair):**
- `schemas.py` — `WorkflowNode`'da `id`/`typeVersion`/`position` opsiyonel (kompakt JSON).
- `agent/repair.py` (**yeni**) — `repair_workflow`: boilerplate doldur → lineer wiring çıkar → sub-node'u `ai_*` porta taşı (tek-agent; çok-agent belirsizse reddet) → `{{input.x}}`→trigger body expr, trigger'a bağlı node'da deklare input için `$json.x`→`$json.body.x` (Code jsCode dahil). "Onar-ya-da-reddet"; belirsizi `validate_workflow_payload` reddeder. Her onarım loglanır.
- `tools/validation.py` — `_validated_runtime_workflow` hattına repair eklendi (normalize → **repair** → apply_runtime_inputs → validate); `connections` opsiyonel.
- `tools/factory.py` — `create_workflow_from_graph/_plan/_spec` **tool kayıtları kaldırıldı**; `create_workflow`/`update_workflow` docstring'leri tek-yüzey + kompakt-JSON olarak güncellendi. Compiler modülleri dahili kaldı.
- `tools/prompt.py` — tek-yüzey süreci + 2 kanonik **worked example** (teklif senaryosu: webhook+AI Agent+ai_languageModel+Gmail+runtime input; lineer).
- Testler — `test_repair.py` (9 unit), `test_tools.py` (+1 uçtan-uca pipeline testi: kompakt+bozuk payload → onarılır, reddedilmez). **180 passed** (5 hata `tmp_path` Windows izni, alakasız); ruff temiz.

**Sonraki adım:** Canlı agent + n8n ile "firmalara teklif" senaryosunu test et (n8n şu an kapalı). Detay: [[adr-0010-json-surface-repair-normalizer]], [[known-issues]].

---

### Son oturum özeti (2026-06-13) — Neden agent graph compiler'ı atlıyor? (kök-neden + tool steer)

**Bağlam:** 06-11/06-12'de boş/yanlış AI mail için üç ham-yol bug'ı (langchain main-wiring, `{{input.x}}`, `$json.body` atlama) bulunup ikisi deterministik guard'a, biri prompt kuralına bağlanmıştı. Bu oturumda asıl meta-soru araştırıldı: **agent neden tercih edilen `create_workflow_from_graph`'ı atlayıp ham `create_workflow` kullanıyor?**

**Önemli düzeltme:** Önceki notlar bug'ları "gpt-4o-mini"ye atıyordu — yanlış. 06-12 build'i (`HJXIBudaUl5ZU9Gp`) konuşma metadata'sına göre **gpt-5 (thinking medium)** idi. Yani üç hatayı güçlü bir reasoning modeli bile üretti; "daha güçlü model öner" tavsiyesi geçersiz.

**Kök-neden (statik analiz):** Model gücü değil, **pretraining-önyargısı vs. Conduut'a-özgü soyutlama** çatışması. 4 rakip create tool'u var; ham n8n JSON modelin pretraining'inde bol, WorkflowGraph IR (`kind`/`attached_to`/`role`/`{ref:'input.x'}`) yalnızca bu repoda. Karar anındaki yönlendirme zayıftı: Pydantic AI `@agent.tool` docstring'i LLM'e tool description olarak gider, ama ham `create_workflow`/`update_workflow` docstring'leri tek satırlık ve nötrdü → karar noktasında ham yol eşit görünüp pretraining önyargısı kazanıyordu.

**Aksiyon:** Ham `create_workflow` ve `update_workflow` docstring'leri "Last-resort fallback only" olarak yeniden yazıldı (`factory.py`); `create_workflow_from_graph`'a yönlendiriyor ve üç klasik hatayı (ai_* port, `$json.body.<field>`, `{{input.x}}` yasak) modelin gerçekten okuduğu yere — tool description'a — koyuyor. **36 test geçti (validation + graph_compiler), ruff temiz.** Docstring inert; validation davranışı değişmedi.

**Beklemede:** (1) body-path için deterministik guard (webhook'a doğrudan bağlı node'larda declared input'u `.body`'siz okuyan `$json.<field>`'i yakalayan, düşük-yanlış-pozitif) tasarlandı ama n8n offline olduğu için uçtan uca doğrulanamadı — canlı n8n ile eklenecek. (2) OpenAI API key rotasyonu (geçmiş oturumda plaintext sızdı). Detay: [[known-issues]].

---

### Son oturum özeti (2026-06-11) — Langchain sub-node guard (boş AI mail fix)

**Sorun:** "Firmalara otomatik teklif" senaryosunda mail gövdesi boş gidiyordu (sadece başlık "Teklif" fallback'i). Sistematik debugging ile root cause bulundu: agent (gpt-4o-mini) graph compiler'ı **atlayıp** ham `create_workflow` JSON yolunu kullandı ve langchain chat-model sub-node'unu (`lmChatOpenAi`) düz `main` akışına bağladı (`Webhook → OpenAI Chat Model → Code → Gmail`). Langchain sub-node'ları main I/O'ya sahip değildir; main akışta hiçbir çıktı üretmez → Code `$json.text`=undefined → Gmail `message` boş. Canlı n8n karşı örneği: aynı oturumda `3XskIaDrFUFUEcpv` doğru kurulmuştu (model `ai_languageModel` portundan AI Agent'a bağlı).

**Çözüm (defense-in-depth, kalıcı kök-neden fix, TDD ile):**
- `apps/agent/src/agent/validation.py` — iki yeni guard: (1) `_is_langchain_ai_subnode` (`lm`/`memory`/`embeddings`/`outputParser`/`textSplitter`/`retriever`/`tool` prefiksleri, `agent`/`chainLlm`/`chatTrigger` hariç) `main` bağlantısında yakalar; (2) `_validate_input_expressions` ham JSON'daki geçersiz `{{input.x}}` ifadelerini yakalar (`input` n8n değişkeni değil → boş çözülür). İkisi de `_validated_runtime_workflow` → `ModelRetry`, yani `create_workflow`/`update_workflow` ham yolunda zorlayıcı.
- `apps/agent/src/agent/tools/prompt.py` — "Node rules"a ham JSON yolu için langchain sub-node + ai_* port kuralı eklendi.
- `apps/agent/tests/test_workflow_validation.py` — 5 yeni test. **Tam suite: 170 passed (5 hata Windows tmp-izni, alakasız); ruff temiz.** Her iki guard gerçek bozuk payload'larda (1jbY wiring, TJ1B `{{input.x}}`) `_validated_runtime_workflow` üzerinden kanıtlandı.

**İki ayrı ham-yol bug'ı, aynı kök-neden:** Agent (gpt-4o-mini) `create_workflow_from_graph`'i atlayıp ham `create_workflow` kullandığında (a) langchain modeli main akışa bağlıyor (1jbY → boş gövde) **veya** (b) geçersiz `{{input.x}}` yazıyor (TJ1B/3Xsk → kişiselleştirme çalışmaz). Graph compiler ikisini de imkânsız kılar. **Not:** Bozuk workflow'lar (`1jbYOquxyrLtxTOk` vb.) silinmedi; agent yeniden kurarsa guard'lar doğru yapıyı zorlar. gpt-4o-mini build için tutarsız → daha güçlü model önerilir. Detay: [[known-issues]], [[adr-0009-workflow-graph-compiler]].

---

### Son oturum özeti (2026-06-10) — Graph compiler (ADR-0009)

**Ne yaptık:** 2026-06-08 darboğazını çözen genel, genişletilebilir graph compiler'ı tasarlayıp (brainstorming → tasarım onayı) implemente ettik.

**Eklenen/değişen kod:**
- `apps/agent/src/agent/schemas.py` — `GraphNode`, `GraphEdge`, `WorkflowGraph` IR tipleri.
- `apps/agent/src/agent/tools/blocks.py` — **yeni**, declarative `Block` + `ParamRule` registry, `ROLE_PORTS`, `BLOCKS` (curated kind kataloğu).
- `apps/agent/src/agent/tools/graph_compiler.py` — **yeni**, tek genel compiler: resolve (curated/generic) → params/builders → topology (main + true/false + ters `ai_*` portları) → boilerplate (typeVersion/layout/webhookId/`__rl`/expression) → validation. `compile_workflow_graph` + `create_workflow_from_graph_payload`.
- `apps/agent/src/agent/tools/factory.py` — `create_workflow_from_graph` tool'u (tercih edilen builder, plan'dan önce).
- `apps/agent/src/agent/tools/prompt.py` — graph-first süreç + kompakt curated kind kataloğu + `n8n:<type>` fallback talimatı.
- `apps/agent/tests/test_graph_compiler.py` — **yeni**, 8 golden test (http linear, if-branch, AI agent port wiring, set fields, generic fallback, node ref, hata yolları). **Hepsi geçiyor; ruff temiz; tam suite 164 passed** (5 hata Windows tmp-izni, alakasız).

**Mimari kararlar (4 temel):** hibrit cozunurluk (curated block + generic `n8n:` fallback), rol etiketli IR + compiler port cikarimi, declarative data registry, hibrit katalog kesfi. Detay: [[adr-0009-workflow-graph-compiler]].

**Sınırlamalar (V1, iteratif):** chat-model `model` basit `list` resourceLocator; `sheets.row.append` graph modunda auto Set üretmez; generic sub-node portu `ROLE_PORTS` varsayılanına dayanır. AI Agent için langchain node typeVersion'ları registry'de yoksa block fallback değeri kullanılır.

**Sonraki adım:** Canlı n8n ile uçtan uca test (AI agent + model içeren workflow import → execute). Çalışırsa curated kataloğu genişlet (Switch, SplitInBatches/loop, daha fazla AI tool/memory) veya Faz 2 (Dashboard).

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

### Agent system prompt kuralları (`apps/agent/src/agent/tools/prompt.py`)
- Act directly — onay sorma, hemen yap
- Kullanıcı n8n/node/webhook terminolojisi bilmek zorunda değil; doğal dilden intent çıkar
- Eksik **business** bilgisi için `request_user_input` (tek seferde tek alan, step-by-step); teknik node seçimini sorma. Placeholder/uydurma değer **yasak**
- Tek seferlik aksiyon → `run_platform_action`; tekrarlayan/zamanlanmış → workflow
- Workflow üretimi → tek yüzey `create_workflow`/`update_workflow` ile **kompakt n8n JSON** (name/type/parameters; boilerplate ve lineer connections opsiyonel). `agent/repair.py` boilerplate'i doldurur ve klasik hataları onarır (ADR-0010). IR builder'lar (graph/plan/spec) artık model yüzeyinde yok.
- Trigger seçimi: `scheduleTrigger` **yalnızca** kullanıcı açıkça tekrarlayan/zamanlı çalışma istediğinde ("her sabah", "her saat"); aksi halde (düz "X kur" istekleri) **Webhook trigger** (POST) — Conduut chat'ten çalıştırıp test edebilsin. İstenmeyen schedule **ekleme** (2026-06-19, prompt.py). Çalıştır-yolu schedule trigger'ı test-edemiyor (manual/webhook→webhook'a çevrilir; schedule çevrilmez, zamanlamayı bozar); schedule'lı workflow'u test-çalıştırma ayrı feature (b)
- CREATE vs UPDATE: yeni için `create_workflow`, mevcut için önce `get_workflow` sonra `update_workflow` (tam yapı)
- Bilinmeyen node için `search_n8n_nodes` → `get_node_schema`, sonra build
- Workflow ID'lerini konuşma boyunca takip et

### n8n node registry kuralları
- Agent her bilinmeyen node için `search_n8n_nodes` → `get_node_schema` → `create_workflow` akışını izler
- `nodes.json` agent startup'ta n8n `/types/nodes.json`'dan çekilir, dosyaya kaydedilmez (runtime)
- Templates: `packages/n8n-registry/data/templates.json` — `fetch_templates.py` ile güncellenir
- Nodes: `packages/n8n-registry/scripts/fetch_nodes.py` ile yerel kayıt yapılabilir
- Template sayısı artırmak için: `python packages/n8n-registry/scripts/fetch_templates.py --limit 200`

### Önemli dosyalar
- `apps/agent/src/agent/runner.py` — Pydantic AI runner, SSE stream, geçmiş→ModelMessage dönüşümü, keep-alive. **`run` artık `settings` almaz**: `classify_tier`→`resolve(tier)`→`build_model`+per-tier `build_model_settings`→per-tier `UsageLimits`; tier'ı assistant mesajına yazar (ADR-0011)
- `apps/agent/src/agent/model_registry.py` — **Conduut-yönetimli kademe kayıt defteri**: `Tier`/`ModelChoice`/`TierConfig`/`ModelProfile`, `PROFILE_DEFAULT`+`PROFILE_GPT`, `resolve(tier, secondary=)`, `router_choice()`. Model id'leri + `ThinkingSpec` model-başına sabit; `CONDUUT_MODEL_PROFILE` ile seçilir (ADR-0011)
- `apps/agent/src/agent/router.py` — `classify_tier`: ucuz sınıflandırıcı (Flash-Lite, thinking off) isteği SIMPLE/MEDIUM/HARD'a atar; hata→MEDIUM (ADR-0011)
- `apps/agent/src/agent/loop.py` — ince kabuk (`runner.run`'a yönlendirir)
- `apps/agent/src/agent/tools/factory.py` — Pydantic AI tool kayıtları + `create_agent`
- `apps/agent/src/agent/tools/prompt.py` — system prompt
- `apps/agent/src/agent/repair.py` — **onarıcı normalizer** (`repair_workflow`): kompakt JSON → boilerplate doldur + lineer wiring + sub-node `ai_*` port + `$json.body`/`{{input.x}}` onarımı + e-posta node'larında `options.appendAttribution=false` (n8n "sent automatically with n8n" footer'ını kapatır) + **resourceLocator normalizasyonu** (googleSheets `documentId`/`sheetName` düz string → `{__rl, mode, value}`; aksi halde n8n value/mode'u undefined okur, "Can not get sheet 'undefined'" hatası) + **webhook `responseMode=lastNode`** (varsayılan "onReceived" anında ack'leyip execution verisi döndürmüyor → "n8n'den cevap gelmedi"; lastNode senkron sonuç döndürür) (ADR-0010, tek JSON yüzeyinin kalbi)
- `apps/agent/src/agent/tools/graph_compiler.py` — WorkflowGraph → n8n JSON compiler (curated + generic, port çıkarımı, ADR-0009; **artık dahili kütüphane**, model yüzeyinde değil)
- `apps/agent/src/agent/tools/blocks.py` — declarative `Block`/`ParamRule` registry + `BLOCKS` curated kind kataloğu + `ROLE_PORTS`
- `apps/agent/src/agent/tools/spec_compiler.py` — WorkflowPlan/Spec → n8n JSON compiler (⚠️ 977 satır, refactor edilecek; graph_compiler helper'ları buradan reuse eder)
- `apps/agent/src/agent/schemas.py` — WorkflowGraph/Plan/Spec/Node IR, attachment ve AgentDeps tipleri
- `apps/agent/tests/test_graph_compiler.py` — graph compiler golden testleri
- `apps/agent/tests/test_repair.py` — repair motoru unit testleri (boilerplate, wiring, ai_* port, expression onarımı)
- `apps/agent/src/agent/research.py` — API auth araştırma motoru: sabit Gemini Flash + grounding (provider-bağımsız), `research_api_auth` (paylaşımlı `api_auth_cache`'li), `AuthResearchResult`, `credential_type_for_scheme`. Grounding `_run_grounding_research` arkasında (testable) (ADR-0013)
- `apps/agent/src/agent/sandbox.py` — **sandbox test motoru** (ADR-0014): `run_sandbox_test` (klonla→nötralize→çalıştır→değerlendir→sil), `SandboxTestResult`, örnek-girdi, test-klonu, boş-çıktı kontrolü, LLM yargısı (`_run_judge_llm` izole, sabit Gemini Flash). Build'in son adımında yan-etkisiz test
- `apps/agent/src/agent/sandbox_nodes.py` — aksiyon-node sınıflandırıcı (`is_side_effect_node`: gmail send/sheets write/slack/HTTP non-GET...) + `neutralize_action_nodes` (`disabled=true`) (ADR-0014)
- `apps/agent/src/agent/tools/sandbox_gate.py` — `_test_and_gate`: test'i koşar, başarısızsa `ModelRetry` ile self-repair (en fazla 2 deneme, `workflow_test_attempts` bütçesi), bütçe dolunca `needs_attention`; harness hatası build'i bloklamaz. `create_workflow`/`update_workflow` (build sonrası) + `execute_workflow` (test-before-execute, `_needs_pretest`) üzerinden tetiklenir (ADR-0014)
- `apps/agent/src/agent/credential_catalog.py` — predefined credential katalog motoru: `build_catalog` (OAuth ayıklama + friendly_label), `match_credentials_by_type`, `parse_schema_fields`, `fetch_credential_fields`; n8n registry + schema endpoint üzerinden çalışır (ADR-0015)
- `apps/agent/src/agent/credential_types.py` — custom HTTP credential V1 tip kataloğu + `normalize_host` + `match_credentials` (host eşleştirme) (ADR-0012)
- `apps/agent/src/agent/tools/credentials.py` — `list_credentials_payload` (secret yok, host-eşleşme bayraklı) + `attach_credential_payload` (ownership doğrular, generic auth wiring) (ADR-0012)
- `apps/agent/src/routes/credentials.py` — custom credential kütüphanesi route'ları (POST create/attach, GET, GET `/types`, DELETE `/{id}`) (ADR-0012)
- `apps/web/src/app/(dashboard)/dashboard/credentials/page.tsx` — credential yönetim sayfası (ekle/sil, tip seçici + host)
- `apps/agent/src/agent/tools/validation.py` + `agent/validation.py` — node/connection normalize + validate + ModelRetry
- `apps/agent/src/agent/tools/runtime_inputs.py` — runtime input şeması + webhook expression
- `apps/agent/src/agent/tools/workflow_runner.py` — tekil + batch workflow run
- `apps/agent/src/platforms/actions.py` — n8n'siz direkt platform aksiyonları (Gmail/Sheets)
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
