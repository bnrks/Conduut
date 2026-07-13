# Senaryo E3 — Zamanlı hatırlatma maili gönder

Merkez: [[scenario-bank]]

- **Zorluk:** easy
- **Kaynak (n8n.io):** https://n8n.io/workflows/6338-schedule-daily-email-reminders-from-google-sheets-with-gmail
  (bu senaryoda gerçek workflow'un yalnız *Schedule → Gmail send* alt-deseni
  kullanılır; Sheet okuma kısmı [[scenario-m1-sheets-filter-email]]'e ayrılmıştır)
- **Capability'ler / node'lar:** Schedule Trigger, Gmail (`gmail.message.send`)
- **Kardeş senaryo(lar):** [[scenario-m2-schedule-http-digest]] (aynı "schedule → gmail")
- **Risk noktaları:** Schedule Trigger interval config, Gmail send alanları
  (`sendTo`/`subject`/`message`/`emailType`), `appendAttribution=false`,
  placeholder alıcı uydurmama (gerçek alıcı = kullanıcının kendisi olmalı).

## Task (agent'a verilen doğal-dil)

> Her sabah saat 9'da bana "Günlük planını gözden geçir" diye bir hatırlatma
> e-postası gönderilsin.

## Referans yapı (yalnız bizde; agent görmez)

- **Schedule Trigger**: günlük, saat 09:00.
- **Gmail send**: `sendTo` = kullanıcının maili, sabit `subject` + `message`,
  `options.appendAttribution=false`.
- Bağlantı: Schedule Trigger → Gmail.

## Beklenen sonuç (fonksiyonel)

Her gün 09:00'da tek bir hatırlatma maili gider. Alıcı gerçek (kullanıcı);
agent alıcı adresini bilmiyorsa `request_user_input` ile sormalı, uydurmamalı.

## Sonuç geçmişi

**Güncel durum (2026-07-13): TEST EDİLMEDİ.** Yeniden baseline turunda en baştan
çalıştırılacak.

| Tarih | Geçti/Kaldı | Bulunan bug → kök-neden → katman → commit → kardeş-doğrulama |
|-------|-------------|--------------------------------------------------------------|
| — | — | — |
