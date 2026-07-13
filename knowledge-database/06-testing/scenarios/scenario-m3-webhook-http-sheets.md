# Senaryo M3 — Webhook → HTTP → normalize → Sheet'e yaz

Merkez: [[scenario-bank]]

- **Zorluk:** medium
- **Kaynak (n8n.io):** https://n8n.io/workflows/13207-route-measurement-data-from-a-webhook-to-google-sheets-email-or-custom-js
- **Capability'ler / node'lar:** Webhook, Set/Edit Fields, Google Sheets
  (`sheets.row.append`), (opsiyonel Gmail dalı)
- **Kardeş senaryo(lar):** [[scenario-e1-webhook-sheets-append]] (webhook→sheet)
- **Risk noktaları:** webhook gövdesi `$json.body.*`, Set node
  `assignments.assignments` formatı (boş Set reddedilir), çok-çıkışlı dallanma,
  Sheets v4 append şeması.

## Task (agent'a verilen doğal-dil)

> Cihazlarımdan webhook ile gelen ölçüm verilerini temizleyip düzenli sütunlarla
> bir Google Sheet'e kaydet.

## Referans yapı (yalnız bizde; agent görmez)

- **Webhook** trigger (`POST`).
- **Set/Edit Fields**: gelen gövdeyi temiz alanlara normalize eder
  (`$json.body.*` → adlandırılmış sütunlar).
- **Google Sheets**: `resource: sheet`, `operation: append`.
- Bağlantı: Webhook → Set → Google Sheets.

## Beklenen sonuç (fonksiyonel)

Webhook'a gelen ham ölçüm, normalize edilip Sheet'e düzenli sütunlarla yazılır.
Set normalizasyonu + append doğruysa geçti.

## Sonuç geçmişi

**Güncel durum (2026-07-13): TEST EDİLMEDİ.** Yeniden baseline turunda en baştan
çalıştırılacak.

| Tarih | Geçti/Kaldı | Bulunan bug → kök-neden → katman → commit → kardeş-doğrulama |
|-------|-------------|--------------------------------------------------------------|
| — | — | — |
