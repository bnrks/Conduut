# Senaryo H2 — Lead'leri oku → New süz → kişiselleştir → mail (H1 kardeşi)

Merkez: [[scenario-bank]]

- **Zorluk:** hard
- **Kaynak (n8n.io):** https://n8n.io/workflows/6083-lead-outreach-automation-with-google-sheets-gmail-and-n8n-workflow
- **Capability'ler / node'lar:** Google Sheets (`sheets.range.read` + `sheets.range.update`),
  Filter/IF, Gmail (`gmail.message.send`)
- **Kardeş senaryo(lar):** [[scenario-h1-cold-outreach-status]] — **birincil kardeş**.
  Bu senaryo bilerek H1 ile aynı desendedir (read→filter→send→update) ama farklı
  yüzey (lead/şirket alanları). **Genellik guard rolü:** H1'de yapılan bir düzeltme
  BURADA da geçmezse fix use-case'e band-aid'dir, genelleştirilmelidir.
- **Risk noktaları:** H1 ile aynı — Sheets v4 update kolon eşlemesi
  (`columns` + `matchingColumns`), per-lead kişiselleştirme expression'ları
  (`{{$json.Name}}`, `{{$json.Company}}`), döngü.

## Task (agent'a verilen doğal-dil)

> Lead listemdeki "New" durumundaki her lead'e, ismini ve şirketini kullanan
> kişiselleştirilmiş bir tanıtım maili gönder ve gönderdiklerimi işaretle.

## Referans yapı (yalnız bizde; agent görmez)

- **Google Sheets read** (tüm lead'ler).
- **Filter**: `Status == "New"`.
- **Gmail send**: `sendTo = {{$json.Email}}`, gövdede `{{$json.Name}}` +
  `{{$json.Company}}`.
- **Google Sheets update**: `Status = "Contacted"`, `columns` + `matchingColumns`.
- Bağlantı: (Trigger) → Sheets read → Filter → Gmail → Sheets update.

## Beklenen sonuç (fonksiyonel)

Yalnız "New" lead'lere ad+şirket ile kişiselleştirilmiş mail gider ve satır
durumları güncellenir. H1 ile birlikte kullanılır: ikisi de aynı fix'le geçmeli.

## Sonuç geçmişi

**Güncel durum (2026-07-25): GEÇTİ / KAPALI.** Sistemik guard sonrasında
workflow `qx1hRmK5O6EJu052` kuruldu. Sandbox repair zinciri execution `428` ve
`429` bulgularını düzeltti; execution `430` full coverage ile geçti. Aktivasyon
öncesi clone execution `431` ve paralel preview execution `432` de
`2 eligible / 2 action / 2 write-back` kanıtladı. Gerçek workflow execution
`433` transport/execution success, `2/2/2`, iki effect verification, remote
Sheet read-back ve `Postconditions: Yes` ile kullanıcı tarafından kabul edildi.

| Tarih | Geçti/Kaldı | Bulunan bug → kök-neden → katman → commit → kardeş-doğrulama |
|-------|-------------|--------------------------------------------------------------|
| 2026-07-25 | Geçti / Kapalı | Workflow `qx1hRmK5O6EJu052`, real execution `433`: yalnız iki `New` lead işlendi; iki action ve iki Sheet write-back doğrulandı. Remote `Sayfa1!A1:ZZ500` read-back postcondition'ları doğruladı ve UI `run_verified` gösterdi. `AI Agent` için `contract_coverage_missing` yalnız non-blocking shadow uyarıdır; runtime action/write-back kanıtını geçersiz kılmaz. Kullanıcı canlı sonucu kabul ederek H2'yi kapattı. Ayrı bir ikinci gerçek `0/0/0` execution kaydı alınmadı; bu kontrol gelecekteki regresyon turunda tekrar edilebilir. |
| 2026-07-25 | Kaldı | Filter 2 eligible item üretti; Split In Batches v3 output 0 (`done`) üzerinden body bağlandı ve feedback edge'i yoktu. AI/Gmail/Sheets update hiç çalışmadı. İlk test credential eksikliğiyle skip edildi; readiness sonucu test readiness gibi sunuldu. Activation repair sonrası gelen HTTP 500 / zero-item sonuç yanlış `no_action` sayıldı. Registry port contract'i, validation/assurance, sandbox oracle, readiness/claim ayrımı ve persisted test-policy v2 uygulandı. Canlı side effect yeniden koşulmadı; H1 kardeş doğrulaması ayrıca bekliyor. |

### Yeniden kabul oracle'i

Kapanış kanıtı real execution `433` için `2 eligible / 2 action /
2 write-back`, Gmail ve Sheet effect verification ile aynı iki Sheet satırında
`Contacted` remote read-after-write postcondition'ıdır. Yalnız n8n
`status=success`, activation başarısı veya sandbox `no_action` H2 geçişi
değildir. İkinci gerçek `0/0/0` koşusu bu kapanışta ayrıca kaydedilmedi; tekrar
gönderim/idempotency regresyon turunda yeniden doğrulanmalıdır.
