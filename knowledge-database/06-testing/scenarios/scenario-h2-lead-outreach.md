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

**Güncel durum (2026-07-13): TEST EDİLMEDİ.** Yeniden baseline turunda en baştan
çalıştırılacak.

| Tarih | Geçti/Kaldı | Bulunan bug → kök-neden → katman → commit → kardeş-doğrulama |
|-------|-------------|--------------------------------------------------------------|
| — | — | — |
