# Senaryo H3 — Zamanlı site kontrol → koşullu uyarı maili

Merkez: [[scenario-bank]]

- **Zorluk:** hard
- **Kaynak (n8n.io):** https://n8n.io/workflows/5067-website-monitoring-scheduling-and-email-alerts-template
- **Capability'ler / node'lar:** Schedule Trigger, HTTP Request, IF, Gmail
  (`gmail.message.send`)
- **Kardeş senaryo(lar):** [[scenario-m2-schedule-http-digest]] (schedule→http)
- **Risk noktaları:** HTTP Request "hata durumunda durma / tam yanıt döndürme"
  seçenekleri (`onError`/`fullResponse`), IF'in HTTP yanıtına (statusCode) göre
  dallanması, yalnız-hata dalının doğru portla (IF false/true) Gmail'e bağlanması,
  `{{$json.statusCode}}` expression'ı.

## Task (agent'a verilen doğal-dil)

> Belirlediğim web sitesini düzenli aralıklarla kontrol et; site çöktüğünde ya da
> erişilemediğinde bana uyarı maili at.

## Referans yapı (yalnız bizde; agent görmez)

- **Schedule Trigger** (ör. 5 dk).
- **HTTP Request**: hedef url, hata durumunda akışı kesmeyip yanıtı döndürecek
  şekilde (`onError: continueRegularOutput` / full response).
- **IF**: `statusCode != 200` (veya request başarısız).
- **Gmail send**: yalnız "site down" dalında uyarı maili.
- Bağlantı: Schedule → HTTP → IF → (down dalı) Gmail.

## Beklenen sonuç (fonksiyonel)

Site erişilebilirken mail gitmez; erişilemez/hata olduğunda uyarı maili gelir.
Dallanma doğru dalı tetikliyorsa geçti.

## Sonuç geçmişi

| Tarih | Geçti/Kaldı | Bulunan bug → kök-neden → katman → commit → kardeş-doğrulama |
|-------|-------------|--------------------------------------------------------------|
| — | — | — |
