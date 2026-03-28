# Conduut

**Konuşarak otomasyon kur.** Conduut, işletmelerin AI agent ile sohbet ederek n8n workflow'ları oluşturmasını, yapılandırmasını ve çalıştırmasını sağlayan bir platformdur.

---

## Proje Özeti

| | |
|---|---|
| **İsim** | Conduut ("conduit" = kanal/boru, çift u ile özgün yazım) |
| **Alternatif isim** | Flowt (daha kısa ama domain sorunlu) |
| **Domain hedefleri** | conduut.com · conduut.io · conduut.dev · conduut.ai |
| **Hedef kitle** | Startup'lar ve geliştiriciler |
| **Marka tonu** | Minimalist ve şık, İngilizce (global pazar) |
| **Temel değer önerisi** | Otomasyon kurulumunda teknik bariyeri (OAuth, API, JSON) ortadan kaldırmak |

---

## Problem

İşletmeler iş akışı otomasyonlarına ihtiyaç duyuyor. Mevcut araçlar (n8n, Zapier, Make) güçlü, ancak:

- OAuth yapılandırması teknik bilgisi olmayan kullanıcılar için karmaşık
- Workflow JSON yapısını anlamak öğrenme eğrisi gerektiriyor
- Dış servis entegrasyonları (API key'ler, webhook URL'ler) hataya açık
- Bu işler için danışmanlara gereksiz yüksek paralar ödeniyor

**Conduut'un çözümü:** Kullanıcı bir AI agent ile sohbet eder. Agent ihtiyacı anlar, workflow'u oluşturur, OAuth bağlantılarını kullanıcı adına halleder ve her şeyi bir bulut ortamında çalıştırır.

---

## Mimari Genel Bakış

```
┌─────────────────────────────────────────────────────────┐
│                    Kullanıcı (Web/Mobil)                  │
│                      Chat arayüzü                        │
└──────────────────────┬──────────────────────────────────┘
                       │
                       ▼
              ┌────────────────┐
              │  API Gateway   │  Traefik / Nginx
              │  Load Balancer │  JWT, rate limit, SSL
              └───────┬────────┘
                      │
        ┌─────────────┼─────────────┐
        ▼             ▼             ▼
  ┌───────────┐ ┌───────────┐ ┌───────────┐
  │  Agent    │ │  Kontrol  │ │  OAuth    │
  │  Servisi  │ │  Katmanı  │ │  Proxy   │
  │  LLM+RAG │ │  Orkest.  │ │  Token   │
  └─────┬─────┘ └─────┬─────┘ └─────┬─────┘
        │             │             │
        └─────────────┼─────────────┘
                      │
    ┌─────────────────┼─────────────────┐
    ▼                 ▼                 ▼
┌─────────┐    ┌─────────┐      ┌─────────┐
│ VPS     │    │ VPS     │      │ VPS     │
│ Düğüm 1 │    │ Düğüm 2 │      │ Düğüm N │
│┌──┐┌──┐ │    │┌──┐┌──┐ │      │         │
││n8│││n8│ │    ││n8│││n8│ │      │  ...    │
│└──┘└──┘ │    │└──┘└──┘ │      │         │
└─────────┘    └─────────┘      └─────────┘
        │             │             │
        └─────────────┼─────────────┘
                      │
  ┌──────────┬────────┼────────┬──────────┐
  ▼          ▼        ▼        ▼          ▼
┌─────┐  ┌─────┐  ┌─────┐  ┌─────┐  ┌─────┐
│Postgre│ │Redis│  │Vault│  │MinIO│  │Prom.│
│SQL   │  │     │  │     │  │ S3  │  │Graf.│
└──────┘  └─────┘  └─────┘  └─────┘  └─────┘
```

Platform 6 katmandan oluşur:

| Katman | Sorumluluk |
|--------|------------|
| Sunum | Web/mobil chat arayüzü, kullanıcı dashboard |
| API Gateway | Yönlendirme, rate limiting, kimlik doğrulama |
| Çekirdek Servisler | Agent servisi, kontrol katmanı, OAuth proxy |
| Altyapı | Docker host'ları, container orkestrasyon |
| Veri | PostgreSQL, Redis, Vault, S3/MinIO |
| İzleme | Prometheus, Grafana, Loki |

---

## Çekirdek Servisler

### 1. Agent Servisi

Platformun beyni. Kullanıcının doğal dildeki taleplerini n8n workflow'larına dönüştürür.

**LLM seçimi:** Claude Sonnet API (function calling + JSON üretim tutarlılığı).

**RAG pipeline:** n8n'in 400+ node'unun JSON şemaları, parametre gereksinimleri ve örnek workflow'ları bir vektör veritabanında (pgvector veya Qdrant) tutulur. Kullanıcının isteğine göre sadece ilgili node dokümanları prompt'a eklenir.

**Akış:**
```
Kullanıcı mesajı
    → Intent detection (ne yapmak istiyor?)
    → RAG: ilgili n8n node şemalarını çek
    → Workflow generation (tam n8n JSON üret)
    → Credential setup (OAuth akışı başlat)
    → Deploy & test (n8n API ile yükle, test çalıştır)
```

**Agent tool'ları:**

| Tool | Açıklama |
|------|----------|
| `create_workflow` | n8n API üzerinden workflow oluşturur |
| `update_workflow` | Mevcut workflow'u günceller |
| `activate_workflow` | Workflow'u aktif eder |
| `deactivate_workflow` | Workflow'u durdurur |
| `list_workflows` | Kullanıcının workflow'larını listeler |
| `execute_workflow` | Tek seferlik test çalıştırır |
| `get_executions` | Çalışma geçmişini getirir |
| `initiate_oauth` | OAuth proxy'den bağlantı URL'i ister |
| `check_credentials` | Bağlı servislerin durumunu kontrol eder |
| `get_user_context` | Kullanıcının container bilgisini getirir |

**n8n Node Registry (RAG için):**
```python
NODE_REGISTRY = {
    "googleSheets": {
        "type": "n8n-nodes-base.googleSheets",
        "credential_type": "googleSheetsOAuth2Api",
        "operations": ["append", "read", "update", "delete"],
        "required_fields": {
            "append": ["sheetId", "range", "values"],
            "read": ["sheetId", "range"],
        },
        "example_json": { ... },
    },
    # ... 400+ node
}
```

### 2. Kontrol Katmanı (Control Plane)

Kullanıcı container'larının tüm yaşam döngüsünü yönetir.

**Alt servisler:**
- **Container provisioner** — Oluştur, sil, taşı
- **Placement engine** — Hangi VPS düğümüne yerleştir?
- **Health monitor** — Container sağlık kontrolleri (30sn aralık)
- **Hibernation manager** — 30dk inaktif → uyku, kullanıcı gelince uyandır

**Kilit tasarım kararı:** Kontrol katmanı VPS'lere doğrudan SSH yapmaz. Her VPS'te bir `node-agent` çalışır ve kontrol katmanıyla gRPC/WebSocket üzerinden haberleşir. Node-agent, Docker SDK ile container komutlarını yerel olarak çalıştırır.

**Placement algoritması:**
```python
score = (available_capacity * 0.5) + (low_error_rate * 0.3) + (region_match * 0.2)
```

**Container yaşam döngüsü:**
```
Kayıt → Uygun VPS seç → Docker container oluştur → DB'ye kaydet → Aktif
    ↓ (30dk inaktif)
  Uyku modu (container durur, volume korunur)
    ↓ (kullanıcı gelir)
  Uyandır (aynı veya farklı VPS'te)
    ↓ (üyelik biterse)
  Sil
```

### 3. OAuth Proxy

Platform genelinde tüm OAuth akışlarını merkezi olarak yönetir.

**Neden merkezi:**
- Her servis için tek bir OAuth App kaydı yeterli
- Callback URL'ler platformun kendi domain'inde
- Token yönetimi (refresh, revoke) merkezi
- Kullanıcı teknik detayla uğraşmaz

**Desteklenen servisler:** Google (Gmail, Sheets, Drive, Calendar), Slack, Notion, GitHub, Discord, Telegram, Airtable ve daha fazlası.

**OAuth akışı:**
```
1. Agent → OAuth proxy'den URL iste
2. Proxy → state token (user_id + service + nonce) ile URL üret
3. Kullanıcı → linke tıklar, consent screen'de izin verir
4. Dış servis → callback ile auth code gönderir
5. Proxy → code'u access + refresh token'a çevirir
6. Proxy → token'ı Vault'a yazar
7. Proxy → n8n container'a REST API ile credential enjekte eder
8. Kullanıcı → başarı sayfasına yönlendirilir
```

**Token refresh:** Saatlik cron job, süresi 1 saat içinde dolacak token'ları otomatik yeniler. Başarısız olursa status → expired, agent kullanıcıya yeniden bağlantı ister.

---

## Altyapı

### Container İzolasyonu (Her kullanıcı için)

```bash
docker run -d \
  --name n8n-${USER_SHORT_ID} \
  --cpus=0.5 --memory=256m --memory-swap=512m \
  --pids-limit=100 \
  --network n8n-isolated \           # İnternet erişimi yok
  --security-opt no-new-privileges \
  --cap-drop ALL \
  --read-only \
  --tmpfs /tmp:rw,size=100m \
  -v n8n-data-${USER_SHORT_ID}:/home/node/.n8n \
  -e N8N_API_KEY=${API_KEY} \
  -e N8N_ENCRYPTION_KEY=${ENC_KEY} \
  -e WEBHOOK_URL=https://webhooks.conduut.com/${USER_SHORT_ID} \
  -p ${PORT}:5678 \
  n8nio/n8n:latest
```

### Webhook Yönlendirme

```
Dış servis → https://webhooks.conduut.com/{user_short_id}/{webhook_path}
    → Webhook Proxy (her düğümde)
    → Doğru kullanıcının n8n container'ı
```

Webhook proxy, container uyku modundaysa önce uyandırır, sonra isteği forward eder.

### Ağ İzolasyonu

```
VPS Düğümü
├── n8n-isolated network (internal, birbirini göremez)
│   ├── n8n container #1
│   ├── n8n container #2
│   └── n8n container #N
└── n8n-external network
    ├── Webhook Proxy
    └── Node Agent
```

### Otomatik Ölçekleme

- %80 dolulukta yeni VPS düğümü otomatik provision
- %20 altında boş düğümleri decommission (min 2 düğüm)
- Her 5 dakikada kontrol

---

## Veritabanı Şeması (PostgreSQL)

```sql
-- Kullanıcılar
CREATE TABLE users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email VARCHAR(255) UNIQUE NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    plan_tier VARCHAR(20) DEFAULT 'free',
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- VPS düğümleri
CREATE TABLE nodes (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    hostname VARCHAR(255) NOT NULL,
    ip_address INET NOT NULL,
    region VARCHAR(50) DEFAULT 'eu-central',
    total_cpu INT NOT NULL,
    total_memory_mb INT NOT NULL,
    allocated_cpu INT DEFAULT 0,
    allocated_memory_mb INT DEFAULT 0,
    max_containers INT DEFAULT 50,
    current_containers INT DEFAULT 0,
    status VARCHAR(20) DEFAULT 'active'
);

-- Kullanıcı container'ları
CREATE TABLE containers (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID REFERENCES users(id) ON DELETE CASCADE,
    node_id UUID REFERENCES nodes(id),
    container_id VARCHAR(64),
    container_name VARCHAR(100),
    port INT NOT NULL,
    n8n_api_key VARCHAR(255),
    status VARCHAR(20) DEFAULT 'creating',
    cpu_limit FLOAT DEFAULT 0.5,
    memory_limit_mb INT DEFAULT 256,
    volume_path VARCHAR(500),
    last_activity_at TIMESTAMPTZ DEFAULT NOW(),
    hibernated_at TIMESTAMPTZ
);

-- OAuth credential'lar
CREATE TABLE credentials (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID REFERENCES users(id) ON DELETE CASCADE,
    service_name VARCHAR(50) NOT NULL,
    service_account VARCHAR(255),
    access_token_vault_key VARCHAR(255),
    refresh_token_vault_key VARCHAR(255),
    token_expires_at TIMESTAMPTZ,
    scopes TEXT[],
    status VARCHAR(20) DEFAULT 'active'
);

-- Abonelikler
CREATE TABLE subscriptions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID REFERENCES users(id) ON DELETE CASCADE,
    plan_tier VARCHAR(20) NOT NULL,
    max_workflows INT NOT NULL,
    max_executions_monthly INT NOT NULL,
    price_monthly_cents INT NOT NULL,
    status VARCHAR(20) DEFAULT 'active',
    current_period_start TIMESTAMPTZ NOT NULL,
    current_period_end TIMESTAMPTZ NOT NULL,
    stripe_subscription_id VARCHAR(255)
);

-- Kullanım takibi
CREATE TABLE usage_tracking (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID REFERENCES users(id) ON DELETE CASCADE,
    month DATE NOT NULL,
    workflow_count INT DEFAULT 0,
    execution_count INT DEFAULT 0,
    agent_message_count INT DEFAULT 0,
    UNIQUE(user_id, month)
);
```

---

## Credential Depolama

### MVP: PostgreSQL + pgcrypto

```sql
CREATE EXTENSION IF NOT EXISTS pgcrypto;

INSERT INTO credentials (user_id, service_name, encrypted_tokens)
VALUES ('usr_id', 'google',
    pgp_sym_encrypt(
        '{"access_token":"ya29...","refresh_token":"1//0e..."}',
        current_setting('app.encryption_key')
    )
);
```

### Ölçekleme sonrası: HashiCorp Vault (KV v2)

```
secret/users/{user_id}/
├── credentials/{service}/
│   ├── access_token
│   ├── refresh_token
│   └── scopes
└── n8n/
    ├── api_key
    ├── encryption_key
    └── webhook_secret

secret/platform/
├── oauth/{service}/client_secret
├── stripe/api_key
├── jwt/signing_key
└── llm/anthropic_api_key
```

**Erişim politikaları:**
- `agent-policy`: Sadece okuma (credential var mı? active mi?)
- `oauth-proxy-policy`: Okuma + yazma (token yaz, güncelle)
- `admin-policy`: Tam erişim

---

## Gelir Modeli

| Plan | Fiyat/Ay | Workflow | Execution/Ay | Bağlı Servis | Container |
|------|----------|----------|--------------|--------------|-----------|
| Free | $0 | 2 | 500 | 2 | 0.25 CPU, 128 MB |
| Starter | $15 | 10 | 5.000 | 5 | 0.5 CPU, 256 MB |
| Pro | $39 | 50 | 25.000 | Sınırsız | 1 CPU, 512 MB |
| Enterprise | Custom | Sınırsız | Sınırsız | Sınırsız | Dedicated VPS |

### Maliyet Hesaplaması

- Hetzner CX31 (4 vCPU, 8 GB RAM) ≈ €10/ay
- Bir sunucuya ~16 aktif Starter kullanıcı sığar
- Kullanıcı başı altyapı maliyeti ≈ $0.70/ay
- Starter plan geliri: $15/ay → brüt marj: ~%95
- Hibernation ile aktif kullanıcı oranı ~%30 → kapasite 3x artar

---

## Teknoloji Stack

| Bileşen | Teknoloji | Gerekçe |
|---------|-----------|---------|
| Frontend | Next.js + Tailwind | SSR, hızlı geliştirme |
| Agent Servisi | Python (FastAPI) | Async, LLM SDK desteği |
| Kontrol Katmanı | Python (FastAPI) | Aynı ekosistem, async |
| OAuth Proxy | Python (FastAPI) | HTTP client desteği |
| API Gateway | Traefik | Docker native, otomatik SSL |
| Container Runtime | Docker + Docker Compose | Basitlik, başlangıç için yeterli |
| Veritabanı | PostgreSQL 16 | ACID, JSON desteği, pgvector |
| Cache | Redis 7 | Hız, pub/sub, session |
| Secret Mgmt | pgcrypto (MVP) → Vault (ölçek) | Kademeli karmaşıklık |
| Nesne Depolama | MinIO (self-hosted S3) | Maliyet, S3 uyumluluk |
| İzleme | Prometheus + Grafana | Açık kaynak, esnek |
| Log Yönetimi | Loki + Promtail | Grafana ile entegre |
| CI/CD | GitHub Actions | Basit, ücretsiz |
| Hosting | Hetzner Cloud | Fiyat/performans |
| LLM | Claude Sonnet API | Function calling, JSON tutarlılığı |
| Vektör DB | pgvector veya Qdrant | RAG pipeline için |

---

## Güvenlik

| Katman | Önlem |
|--------|-------|
| Ağ | Container'lar arası izolasyon (Docker internal network), VPS'ler arası VPN |
| Uygulama | JWT auth, RBAC, input validation |
| Veri | pgcrypto/Vault ile şifreli credential, PostgreSQL SSL, Redis AUTH |
| Container | CPU/RAM limitleri, capability kaldırma, read-only filesystem |
| Transit | Tüm iletişim TLS 1.3 |
| n8n | Her container'ın kendi encryption_key'i |

---

## Geliştirme Yol Haritası

### Faz 1 — MVP (2-3 ay)
- Temel chat arayüzü (Next.js)
- Agent ile basit workflow oluşturma (Google Sheets, Gmail, Slack)
- Tek VPS, Docker Compose ile container yönetimi
- OAuth bağlantı akışı (Google, Slack)
- Starter plan + Stripe entegrasyonu
- pgcrypto ile credential depolama

### Faz 2 — Olgunlaşma (3-4 ay)
- Daha fazla servis desteği (Notion, Discord, Telegram, Airtable)
- Otomatik hibernation ve wake-up
- Çoklu VPS düğümü desteği + placement engine
- Workflow template kütüphanesi
- Kullanım dashboard'u
- RAG pipeline optimizasyonu

### Faz 3 — Ölçekleme (4-6 ay)
- Kubernetes'e geçiş
- Vault'a geçiş
- Enterprise planı (dedicated kaynaklar)
- Marketplace (kullanıcılar workflow paylaşır)
- Webhook güvenilirlik (retry, dead letter queue)
- Multi-region desteği

### Faz 4 — Platform (6+ ay)
- Açık API (3. parti entegrasyon)
- White-label çözüm
- On-premise deployment seçeneği
- Advanced analytics ve workflow önerileri

---

## İsim ve Marka Kararları

### Neden "Conduut"?

| Kriter | Skor | Açıklama |
|--------|------|----------|
| Hatırlanabilirlik | 8/10 | 7 harf, 2 hece |
| Telaffuz | 7/10 | "kon-DUUT" |
| Anlam bağı | 10/10 | Conduit = kanal/boru, otomasyon metaforu |
| Özgünlük | 10/10 | Google'da sıfır sonuç |
| Domain uygunluğu | 10/10 | .com .io .dev .ai hepsi muhtemelen uygun |
| SEO | 10/10 | Sıfır rakip, ilk günden tek sonuç |
| Trademark riski | 8/10 | Conduent (BPO) ile fonetik benzerlik var ama farklı sektör |

**Alternatif:** Flowt (5 harf, tek hece, "flow" bağı güçlü ama flowt.io dolu, flowt.com park edilmiş, SEO'da "flow" kalabalığı var)

**Logo konsepti:** Çift "uu" harfi → iki paralel boru/kanal simgesi olarak kullanılabilir.

### Domain stratejisi

1. Öncelik: `conduut.com` (ana site)
2. Yedek: `conduut.io` veya `conduut.dev`
3. Koruma: Mümkünse hepsini al (yıllık toplam ~$50)

---

## Redis Key Yapısı

```
session:{session_id}           → { user_id, created_at }          TTL: 24h
container:{user_short_id}      → { host, port, status, api_key }  TTL: 5min
oauth_state:{state_token}      → { user_id, service }             TTL: 10min
conversation:{conv_id}         → { messages[], context }          TTL: 2h
ratelimit:{user_id}:{endpoint} → count                            TTL: 1min
health:{container_id}          → { status, cpu, memory }          TTL: 30s
```

---

## İzleme ve Alerting

**Toplanan metrikler:**
- `platform_active_users_total`
- `platform_containers_total{status}`
- `platform_agent_requests_total`
- `node_cpu_usage_percent{node_id}`
- `container_workflow_executions_total{user_id}`
- `oauth_token_refresh_total{service, status}`

**Alert kuralları:**
- Container RAM > %90 → 5dk sürekli → alert
- Düğüm doluluk > %85 → 10dk → yeni VPS provision
- OAuth refresh hata oranı artar → alert + agent bildirim
- Agent p95 latency > 10s → alert

---

## Dosya Yapısı (Planlanan)

```
conduut/
├── README.md
├── PROJECT.md              ← Bu dosya
├── docker-compose.yml
├── apps/
│   ├── web/                ← Next.js frontend
│   ├── agent/              ← Agent servisi (FastAPI)
│   ├── control-plane/      ← Kontrol katmanı (FastAPI)
│   ├── oauth-proxy/        ← OAuth proxy (FastAPI)
│   └── node-agent/         ← Her VPS'te çalışan agent
├── packages/
│   ├── n8n-registry/       ← Node şemaları + RAG veri
│   └── shared/             ← Ortak tipler, utils
├── infra/
│   ├── docker/             ← Dockerfile'lar
│   ├── traefik/            ← Gateway yapılandırması
│   └── monitoring/         ← Prometheus, Grafana, Loki
├── scripts/
│   ├── provision-node.sh
│   ├── extract-n8n-nodes.py
│   └── seed-db.sql
└── docs/
    ├── architecture.md
    ├── oauth-flow.md
    └── api-reference.md
```

---

## Lisans

TBD

---

*Bu doküman, projenin planlama aşamasında oluşturulmuştur. Mimari kararlar geliştirme sürecinde güncellenecektir.*
