# ADR 0001: Shared n8n MVP

Merkez: [[index]]

## Durum

Accepted for MVP.

## Baglam

`PROJECT.md` hedef mimaride her kullanici icin ayri n8n Docker container'i,
control-plane ve node-agent ongorur. Mevcut kodda bu sistemler yok.

## Karar

MVP'de tum kullanicilar tek shared n8n instance uzerinden calisir:

- Docker service: `conduut-n8n`.
- Agent config: `CONDUUT_N8N_URL`.
- API client: `apps/agent/src/n8n_client.py`.
- Workflow routes: `apps/agent/src/routes/workflows.py`.

## Sonuclar

Avantajlar:

- Gelistirme basit.
- Agent workflow generation ve dashboard davranisi hizli test edilir.
- Control plane beklenmeden urun akisi denenebilir.

Riskler:

- Kullanici izolasyonu yok.
- Workflow ownership/filtering yok.
- Credential ve execution verileri kullanicilar arasi ayrilmiyor.
- Production icin uygun degil.

## Sonraki Adim

Per-user isolation baslarken `n8n_client.py` kullanici/container context'i
alacak sekilde genisletilmeli ve workflow route'lari user ownership bilgisini
zorunlu kilmali.

Ilgili notlar: [[system-architecture]], [[agent-service]], [[known-issues]].
