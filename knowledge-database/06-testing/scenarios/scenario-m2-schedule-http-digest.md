# Senaryo M2 — Zamanlı HTTP/RSS çek → formatla → mail

Merkez: [[scenario-bank]]

- **Zorluk:** medium
- **Kaynak (n8n.io):** https://n8n.io/workflows/6223-send-scheduled-rss-news-digest-emails-with-formatted-html-in-gmail
- **Capability'ler / node'lar:** Schedule Trigger, HTTP Request, Set/Code,
  Gmail (`gmail.message.send`)
- **Kardeş senaryo(lar):** [[scenario-e3-schedule-gmail-reminder]] (schedule→gmail),
  [[scenario-h3-website-monitor-alert]] (schedule→http)
- **Risk noktaları:** HTTP Request node parametreleri (method/url), Code/Set ile
  HTML/özet üretimi ve expression bağlama, Gmail `emailType: html`.

## Task (agent'a verilen doğal-dil)

> Her sabah belirlediğim bir haber kaynağından son başlıkları çekip, güzel
> biçimlenmiş bir özet e-postayı bana gönder.

## Referans yapı (yalnız bizde; agent görmez)

- **Schedule Trigger** (günlük).
- **HTTP Request**: `GET`, RSS/API url.
- **Code** (veya XML + Set): gelen öğelerden HTML başlık listesi kurar.
- **Gmail send**: `emailType: html`, gövde = üretilen HTML.
- Bağlantı: Schedule → HTTP → Code → Gmail.

## Beklenen sonuç (fonksiyonel)

Her sabah kaynaktan çekilen başlıkları içeren biçimli bir özet mail gelir.
Kaynak/biçim farklı olabilir; içerik çekilip maille gidiyorsa geçti.

## Sonuç geçmişi

**Güncel durum (2026-07-13): TEST EDİLMEDİ.** Yeniden baseline turunda en baştan
çalıştırılacak.

| Tarih | Geçti/Kaldı | Bulunan bug → kök-neden → katman → commit → kardeş-doğrulama |
|-------|-------------|--------------------------------------------------------------|
| — | — | — |
