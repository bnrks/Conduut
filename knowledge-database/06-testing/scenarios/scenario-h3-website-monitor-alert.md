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

**Güncel durum (2026-07-25): GEÇTİ ✅ (kullanıcı kabulü).** Sistemik guard
sonrası yeni agent build doğru HTTP status/error kontratıyla üretildi. Kullanıcı
n8n editöründen manuel çalıştırdı; sağlıklı-site dalı gerçek execution ile
doğrulandı. Erişim-hatası dalı ayrıca canlı hata enjekte edilerek koşulmadı,
ancak gerekli HTTP hata politikası ve alert wiring'i workflow JSON'unda mevcut.

| Tarih | Geçti/Kaldı | Bulunan bug → kök-neden → katman → commit → kardeş-doğrulama |
|-------|-------------|--------------------------------------------------------------|
| 2026-07-25 | KALDI ❌ | Workflow `Kme7UBPjfNX7CLsg`; sandbox `434` ilk IF schema hatasından sonra `435` geçti. Manual `436` sağlıklı sitede `statusCode` üretilmediği halde alert maili gönderdi; manual `437` erişilemeyen domainde `Check Website` `ENOTFOUND` ile durdu ve IF'e ulaşmadı. Kök neden: HTTP status-condition için `fullResponse` + `neverError` + transport `onError` kontratı yoktu ve sandbox eksik-status yanlış alarmını başarı saydı. Katman: genel `validation.py` dataflow guard + `sandbox.py` fail-closed runtime finding + regresyon testleri. Canlı tekrar ve kardeş M2 doğrulaması bekliyor; commit yok. |
| 2026-07-25 | GEÇTİ ✅ | Yeni workflow `GdxzW5oBvhUgMSZ4` aktif, `settings.timezone=Europe/Istanbul`, Schedule her 8 saat. HTTP node `options.response.response.fullResponse=true`, `neverError=true`, top-level `onError=continueRegularOutput`; IF `statusCode != 200` true portu yalnız Gmail `Send Alert`'e bağlı. Kullanıcının n8n editöründen başlattığı manual execution `440` success: `Check Site` output'u `statusCode=200`, IF output sayıları true=`0`, false=`1`, `Send Alert` çalışmadı. Sağlıklı site için yanlış alarm yok; kullanıcı sonucu kabul etti. Erişim-hatası dalı bu kabul koşusunda ayrıca canlı enjekte edilmedi. |
