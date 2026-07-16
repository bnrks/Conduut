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

**Güncel durum (2026-07-16): GEÇTİ ✅.** Yeni baştan verilen task ile üretilen
workflow `1je2tNOr2F50rNbw`, `Europe/Istanbul` timezone'unda günlük 13:45'e
ayarlandı. Execution `#300`, 2026-07-16 13:45:32 Türkiye saatinde trigger oldu;
Schedule ve Gmail node'ları hatasız tamamlandı, Gmail çıktısı gerçek message/thread
ID ile `SENT` etiketi döndürdü. Operasyonel not: önceki denemelerden
`VN8xNT2hS17Mff63` (22:20) ve `8qjMaZLy9wSyNutJ` (22:35) workflow'ları da
hâlâ aktif; test sonucunu etkilemiyor fakat kullanıcı onayı olmadan kapatılmadı.

| Tarih | Geçti/Kaldı | Bulunan bug → kök-neden → katman → commit → kardeş-doğrulama |
|-------|-------------|--------------------------------------------------------------|
| 2026-07-16 | GEÇTİ ✅ | Task yeniden verildi ve yeni `Günlük Plan Hatırlatma - 13:45` workflow'u (`1je2tNOr2F50rNbw`) oluşturuldu. Workflow aktif, `settings.timezone=Europe/Istanbul`, Schedule kuralı `days / 13:45`, Gmail `message/send`, credential bağlı ve `appendAttribution=false`. Execution `#300` `2026-07-16T10:45:32.040Z` = `13:45:32 Europe/Istanbul` anında `mode=trigger`, `status=success`, `finished=true` oldu. Schedule 1 item, Send Email 1 item üretti; `lastNodeExecuted=Send Email`, iki node'da ve run seviyesinde hata yok. Gmail çıktısı message/thread ID ve `labelIds=[SENT]` içeriyor. n8n logundaki `N3MD03PpRP66J9zF` Gmail Trigger uyarıları başka bir workflow'a ait ve E3 kabul sonucunu etkilemiyor. |
| 2026-07-15 | KALDI → düzeltme uygulandı, final rerun bekliyor | Workflow `VN8xNT2hS17Mff63` doğru `Schedule → Gmail` yapısında ve aktif görünmesine rağmen execution listesi boştu. Aktif workflow'a yapılan `PUT` n8n cron kaydını siliyor; readiness aynı Gmail credential'ını tekrar attach ederek son deactivate/activate onarımını da bozuyordu. Ayrıca workflow timezone'u yoktu ve agent saati yanlış biçimde UTC'ye çevirdi; n8n varsayılanı `America/New_York` idi. Genel düzeltme: aynı managed credential için no-op, gerçek aktif `PUT` sonrası `deactivate → activate`, açık `Europe/Istanbul` workflow/instance timezone'u, Schedule interval validator ve execution kanıtı prompt guard'ı. Kardeş trigger kanıtı `[conduut-test] Schedule lifecycle proof` tam bu lifecycle ile 23:05'te execution `#295` `success` üretti; çıktı `schedule lifecycle proof`. E3 aktif + 22:20 + `Europe/Istanbul`; aynı credential no-op'u `updatedAt` değerini değiştirmedi. Exact Gmail gönderimi sonraki 22:20'de doğrulanmalı. |
| 2026-07-15 | Timezone bilgisinin agent'a aktarımı güçlendirildi | Agent yalnız genel bir "explicit timezone" kuralı gördüğü için hâlâ "sistem UTC ise" diye spekülasyon yapabiliyordu. Etkin `CONDUUT_WORKFLOW_TIMEZONE` artık system instruction'a gerçek değeriyle ekleniyor; mevcut workflow'da `settings.timezone` otorite kabul ediliyor ve create/update sonucu etkin timezone'u modele döndürüyor. |
