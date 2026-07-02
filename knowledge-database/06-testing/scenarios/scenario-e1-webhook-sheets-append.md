# Senaryo E1 — Webhook → Google Sheets satır ekle

Merkez: [[scenario-bank]]

- **Zorluk:** easy
- **Kaynak (n8n.io):** https://n8n.io/workflows/1076-transfer-data-from-website-to-google-sheets
- **Capability'ler / node'lar:** Webhook (trigger), Google Sheets (`sheets.row.append`)
- **Kardeş senaryo(lar):** [[scenario-m3-webhook-http-sheets]] (aynı webhook→sheet ekseni)
- **Risk noktaları:** webhook gövdesi `$json.body.*` altında (agent `$json.*`
  yazabilir), Google Sheets v4 append resourceLocator (`documentId`/`sheetName`
  `__rl` sarımı), `resource: sheet` vs `spreadsheet` (bkz. [[known-issues]] madde 1).

## Task (agent'a verilen doğal-dil)

> Web sitemdeki iletişim formundan gelen kayıtları (ad, e-posta, mesaj)
> otomatik olarak bir Google Sheet'e satır olarak eklensin istiyorum.

## Referans yapı (yalnız bizde; agent görmez)

- **Webhook** trigger: `httpMethod: POST`, bir `path`.
- **Google Sheets**: `resource: sheet`, `operation: append`,
  `documentId` (`__rl`), `sheetName` (`__rl`), sütunlar `$json.body.ad`,
  `$json.body.email`, `$json.body.mesaj` alanlarından map'lenir.
- Bağlantı: Webhook → Google Sheets (lineer).

## Beklenen sonuç (fonksiyonel)

Webhook'a gönderilen bir kayıt, Sheet'te doğru sütunlara sahip yeni bir satır
olarak görünür. Yapı farklı olabilir; kayıt doğru düşüyorsa geçti.

## Sonuç geçmişi

| Tarih | Geçti/Kaldı | Bulunan bug → kök-neden → katman → commit → kardeş-doğrulama |
|-------|-------------|--------------------------------------------------------------|
| 2026-07-02 | KALDI → fix'lendi (uçtan-uca deferred) | Workflow kuruldu+aktif ama webhook POST → HTTP 500, execution #212 `error`, 0 node ("workflow has issues"). **Kök-neden:** googleSheets v4 append tab'ı `sheetName` yerine legacy `range:"Kayıtlar"` (`!` yok) + `columns` yok. **Katman 1 (repair.py Stage 6):** bare non-A1 `range`→`sheetName`; append `columns` yoksa `autoMapInputData`. **Katman 2 (validation):** satır-op'ta `sheetName` yoksa ModelRetry hint. Test: repair +4, validation +1, **397 passed**. Detay: [[known-issues]]. **Deferred:** append autoMap runtime'ı + kardeş (M3) uçtan-uca teyidi. **Not:** run DeepSeek profil stall'ı (ReadTimeout) ile kirlendi → koşuları `default` profille yap. |
