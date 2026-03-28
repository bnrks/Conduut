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
