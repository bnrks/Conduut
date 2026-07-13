# Senaryo E2 — Gelen mailleri Google Sheet'e logla

Merkez: [[scenario-bank]]

- **Zorluk:** easy
- **Kaynak (n8n.io):** https://n8n.io/workflows/3319-add-new-incoming-emails-to-a-google-sheets-spreadsheet-as-a-new-row
- **Capability'ler / node'lar:** Gmail Trigger, Google Sheets (`sheets.row.append`)
- **Kardeş senaryo(lar):** [[scenario-e1-webhook-sheets-append]] (aynı "trigger → sheet append")
- **Risk noktaları:** external trigger (Conduut kendisi tetikleyemez → yapı +
  readiness üzerinden yargılanır, agent "çalıştırdım" dememeli), Gmail çıktısı →
  Sheet sütun map'i, Sheets v4 append şeması.

## Task (agent'a verilen doğal-dil)

> Gelen kutuma düşen her yeni e-postanın gönderenini, konusunu ve tarihini bir
> Google Sheet'e otomatik kaydet.

## Referans yapı (yalnız bizde; agent görmez)

- **Gmail Trigger**: yeni mail polling.
- **Google Sheets**: `resource: sheet`, `operation: append`, sütunlar
  `From`, `Subject`, `Date` (Gmail node çıktısındaki `$json.from`, `$json.subject`,
  `$json.date` benzeri alanlardan).
- Bağlantı: Gmail Trigger → Google Sheets.

## Beklenen sonuç (fonksiyonel)

Yeni bir mail geldiğinde Sheet'e gönderen/konu/tarih içeren satır eklenir. Gmail
Trigger external event olduğu için manuel testte yapı doğruluğu + credential
readiness'i yargılanır; agent gerçek event gelmeden "çalıştı" iddiasında bulunmamalı.

## Sonuç geçmişi

**Güncel durum (2026-07-13): TEST EDİLMEDİ.** Yeniden baseline turunda en baştan
çalıştırılacak.

| Tarih | Geçti/Kaldı | Bulunan bug → kök-neden → katman → commit → kardeş-doğrulama |
|-------|-------------|--------------------------------------------------------------|
| — | — | — |
