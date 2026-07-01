# Senaryo H1 — Sheet oku → süz → mail → satırı "Sent" yaz

Merkez: [[scenario-bank]]

- **Zorluk:** hard
- **Kaynak (n8n.io):** https://n8n.io/workflows/4214-cold-email-outreach-with-gmail-and-google-sheets-status-tracking
- **Capability'ler / node'lar:** Google Sheets (`sheets.range.read` + `sheets.range.update`),
  Filter/IF, Gmail (`gmail.message.send`)
- **Kardeş senaryo(lar):** [[scenario-h2-lead-outreach]] — **birincil kardeş**
  (aynı read→filter→send→update-status deseni, farklı yüzey). Genellik guard'ının
  canlı örneği: H1'de bulunan bir Sheets-update/column-map düzeltmesi H2'yi de geçirmeli.
- **Risk noktaları:** **Sheets v4 update kolon eşlemesi** (`dataMode`/`values` →
  v4 `columns` + `matchingColumns`) — [[known-issues]] madde 1'in "reddet"/
  ModelRetry alanı; yanlış eşleşme **yanlış satıra yazar** = veri bozulması.
  Ayrıca per-row döngü, mail sonrası write-back ile tekrar-gönderim engelleme.

## Task (agent'a verilen doğal-dil)

> Sheet'imdeki henüz mail atılmamış potansiyel müşterilere sırayla tanıtım maili
> gönder ve her gönderdikten sonra o satırı "Gönderildi" olarak işaretle ki
> tekrar mail gitmesin.

## Referans yapı (yalnız bizde; agent görmez)

- **Google Sheets read** (`resource: sheet`, `operation: read`).
- **Filter/IF**: `Status != "Sent"` (veya boş).
- **Gmail send**: `sendTo = {{$json.Email}}`, kişiselleştirilmiş gövde.
- **Google Sheets update**: `operation: update` / `appendOrUpdate`,
  `columns` + `matchingColumns` (ör. `Email` veya `row_number` ile eşleşme),
  `Status = "Sent"`.
- Bağlantı: (Trigger) → Sheets read → Filter → Gmail → Sheets update.

## Beklenen sonuç (fonksiyonel)

Yalnız gönderilmemiş satırlara mail gider ve o satırlar "Gönderildi" olur;
ikinci çalıştırmada aynı kişilere tekrar mail gitmez. **Kritik:** update doğru
satırı güncellemeli (matchingColumns doğru olmalı).

## Sonuç geçmişi

| Tarih | Geçti/Kaldı | Bulunan bug → kök-neden → katman → commit → kardeş-doğrulama |
|-------|-------------|--------------------------------------------------------------|
| — | — | — |
