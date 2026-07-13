# Senaryo M1 — Sheet oku → koşula göre süz → mail at

Merkez: [[scenario-bank]]

- **Zorluk:** medium
- **Kaynak (n8n.io):** https://n8n.io/workflows/6338-schedule-daily-email-reminders-from-google-sheets-with-gmail
- **Capability'ler / node'lar:** Schedule Trigger, Google Sheets (`sheets.range.read`),
  IF / Filter, Gmail (`gmail.message.send`)
- **Kardeş senaryo(lar):** [[scenario-h1-cold-outreach-status]] (read→filter→send çekirdeği)
- **Risk noktaları:** Sheets v4 read (`sheetName` vs serbest `range` — bkz.
  [[known-issues]] madde 1), IF/Filter koşul şeması ve `typeVersion`, per-item
  Gmail expression'ları (`$json.Email`, `$json.Name`), items üzerinde döngü semantiği.

## Task (agent'a verilen doğal-dil)

> Google Sheet'imdeki "Pending" durumundaki kişilere, her birine adıyla hitap
> eden bir hatırlatma e-postası gönder.

## Referans yapı (yalnız bizde; agent görmez)

- **Schedule Trigger** (veya manuel) → **Google Sheets read** (`resource: sheet`,
  `operation: read`, `documentId`, `sheetName`).
- **IF**: `Status == "Pending"`.
- **Gmail send**: `sendTo = {{$json.Email}}`, `message` içinde `{{$json.Name}}`.
- Bağlantı: Trigger → Sheets read → IF (true) → Gmail.

## Beklenen sonuç (fonksiyonel)

Yalnızca "Pending" satırlarına, kişinin adıyla kişiselleştirilmiş birer mail
gider. Süzme + per-row expression doğruysa geçti.

## Sonuç geçmişi

**Güncel durum (2026-07-13): TEST EDİLMEDİ.** Önceki, not tablosuna işlenmemiş
denemeler mevcut kod tabanı için kabul kanıtı sayılmayacak; yeniden baseline
turunda en baştan çalıştırılacak.

| Tarih | Geçti/Kaldı | Bulunan bug → kök-neden → katman → commit → kardeş-doğrulama |
|-------|-------------|--------------------------------------------------------------|
| — | — | — |
