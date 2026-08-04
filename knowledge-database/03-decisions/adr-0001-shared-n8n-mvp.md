# ADR 0001: Shared n8n MVP

Merkez: [[index]]

## Durum

Accepted for local/dev MVP; production successor ADR-0022 (2026-08-03).

## Baglam

Ilk hedef mimari her kullanici icin ayri Conduut-managed n8n Docker container'i,
control-plane ve node-agent ongoruyordu. Bu hedef
[[adr-0022-customer-owned-n8n]] ile customer-owned n8n production modeline
degisti. Mevcut kod halen shared n8n kullanir.

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

BYO gecisinde `n8n_client.py` global settings yerine `N8nTarget` alacak sekilde
genisletilmeli; authenticated `user_id` customer-owned instance'a cozulmeli ve
workflow/credential/execution route'lari `(instance_id, object_id)` ownership
bilgisini zorunlu kilmalidir. Shared provider production fallback'i olamaz.

Ilgili notlar: [[system-architecture]], [[customer-owned-n8n]],
[[adr-0022-customer-owned-n8n]], [[agent-service]], [[known-issues]].
