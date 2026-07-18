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

**Güncel durum (2026-07-19): GEÇTİ ✅ — kullanıcı kabulüyle manuel çalıştırma
varyantı.** Yeni chat'teki gerçek task "her çalıştırmamda" olarak verildiği için
`Pflac4S8KvCxhWQe` Webhook kullandı; kullanıcı bu trigger farkını ve HTML
çıktısındaki Markdown code-fence kalite farkını bu test için kabul etti.
Execution `#379` NewsAPI'den 5 haber aldı, AI çıktısında 5 başlık ve 5 link
üretti; Gmail gerçek message/thread id ve `SENT` etiketi döndürdü. Son workflow
NewsAPI, Anthropic ve Gmail credential bağlarını birlikte korudu.

Execution assessment yeni evidence sözleşmesiyle tekrar çalıştırıldığında
`functionalStatus=needs_attention`, `coverage=partial` ve
`contract_coverage_missing` korunurken Gmail `id + SENT` runtime kanıtı
`claimableOutcome=action_verified` üretti. Böylece "mail gönderildi" claim'i
kanıtlıdır; "uçtan uca bütün workflow doğrulandı" claim'i hâlâ açık değildir.
Canonical Schedule varyantı ayrıca çalıştırılmadı; bu fark kullanıcı kabulüyle
M2 kapanışında blocker sayılmadı.

| Tarih | Geçti/Kaldı | Bulunan bug → kök-neden → katman → commit → kardeş-doğrulama |
|-------|-------------|--------------------------------------------------------------|
| 2026-07-19 | GEÇTİ ✅ (kullanıcı-kabul varyantı) | Yeni workflow `Pflac4S8KvCxhWQe`; sandbox execution `#371-#376` aralığında HTTP/data-shape ve boş içerik sorunlarını side effect olmadan yakaladı, `#377/#378` passed oldu. Kullanıcı onayı sonrası tek gerçek execution `#379`: HTTP `status=ok`, 5 article; AI 5 HTML başlık/5 link; Gmail message/thread id + `SENT`. Paralel credential attach ve sonraki update'ler üç credential bağını korudu. Claim katmanı `action_verified` ile gerçek Gmail effect'ini partial AI contract'tan ayıracak şekilde düzeltildi ve `#379` offline reassessment ile doğrulandı. Trigger/code-fence farkları kullanıcı tarafından bu kapanış için kabul edildi. |
| 2026-07-18 | NEEDS_ATTENTION | Ilk real execution `#360` sandbox pass'ine ragmen upstream Code output'unda `undefined` baslik/URL uretip gercek "icerik yok" maili gonderdi. Recipient-only update full graph state'ini yeniden yazarak custom credential'lari dusurdu; paralel attach RMW yarisi iki `success` sonucuna ragmen bir bagi ezdi. Son execution `#370` Gmail `SENT` ile transport basariliydi, fakat workflow Webhook kullandi ve Gmail `emailType=text` ile Markdown gonderdi. Genel cozum: workflow-scoped atomic mutation, credential/node-id/connection preservation, committed attach verification, multi-hop placeholder guard ve intent-aware Gmail format kontrolu. Canonical Schedule + HTML rerun bekleniyor. |
