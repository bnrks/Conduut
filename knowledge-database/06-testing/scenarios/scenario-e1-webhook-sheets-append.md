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

**Güncel durum (2026-07-13): GEÇTİ ✅.** Mevcut kod tabanında yeniden baseline
edildi. Aşağıdaki 2026-07-02 koşuları yalnız tarihsel bulgu olarak korunur.

| Tarih | Geçti/Kaldı | Bulunan bug → kök-neden → katman → commit → kardeş-doğrulama |
|-------|-------------|--------------------------------------------------------------|
| 2026-07-13 | **GEÇTİ** ✅ — küçük URL sunum hatası | Agent workflow `jnaF9rQvckjOhGcX` (`İletişim Formu → Google Sheets`) oluşturup aktive etti. Yapı `Webhook (POST, path=contact-form) → Google Sheets append → Respond`; `Ad`, `E-posta`, `Mesaj` alanları sırasıyla `$json.body.ad`, `.email`, `.mesaj` ile eşlendi. Gerçek webhook execution `#261` ve `#262` `status=success`; kullanıcı Sheet'e doğru kayıt düştüğünü doğruladı. Fonksiyonel oracle geçti. **Kalan hata:** agent POST için yanlış host'lu link verdi; local kullanıcıya doğru URL `http://localhost:6180/webhook/contact-form` olmalıydı. Bu, workflow doğruluğunu değil kullanıcıya sunulan runtime endpoint bilgisini etkiliyor. |
| 2026-07-13 | BLOKE — senaryo çalışmadı | Temiz baseline için `agent` + `web` güncel worktree'den build edildi. `conduut-agent` başlangıçta `provider_factory.py` içindeki `GroqModel` importunda `ModuleNotFoundError: No module named 'groq'` / `ImportError: install pydantic-ai-slim[groq]` ile exit 1 oldu; web agent health dependency'si nedeniyle başlayamadı. `apps/agent/pyproject.toml` yalnız genel `pydantic-ai` dependency'sini içeriyor, fakat provider factory Groq sınıflarını eager import ediyor. Workflow üretimi ve E1 webhook/Sheets oracle'ı henüz çalıştırılmadı; güncel durum TEST EDİLMEDİ. |
| 2026-07-02 | KALDI (1. tur) → fix | Workflow kuruldu+aktif ama webhook POST → HTTP 500, execution #212 `error`, 0 node ("workflow has issues"). **Kök-neden:** googleSheets v4 append tab'ı `sheetName` yerine legacy `range:"Kayıtlar"` (`!` yok). **repair.py Stage 6:** bare non-A1 `range`→`sheetName`; append `columns` yoksa `autoMapInputData`. **validation:** satır-op'ta `sheetName` yoksa ModelRetry hint. Test: repair +4, validation +1. Detay: [[known-issues]]. |
| 2026-07-02 | KALDI (2. tur) → fix + ampirik teyit | sheetName fix'i sonrası chat'ten yeniden kuruldu → pre-flight geçti (Webhook+Sheets execute), ama Sheets runtime `Could not get parameter: columns.schema`. **Kök-neden:** Set node'suz akışta model `columns`'u `value.mappingValues[]` + `schema` yok diye yazdı. **Ampirik zemin:** test workflow columns'u kanonik v4'e (`value` map + synth `schema`) çevrilip çalıştırıldı → execution #217 `success`, satır düştü. **repair.py:** `_normalize_sheets_columns_shape` (mappingValues flatten + schema synth). Suite **401 passed**. **Kalan:** agent'ın gerçek üretim yolundan chat rebuild ile uçtan-uca geçiş (repair canlı). |
| 2026-07-02 | (ara) dedup-404 bug | "sil ve baştan yap" (aynı chat) → agent silinmiş workflow id'sini dedup'ta okuyup `GET /workflows/<id>` 404 → `create_workflow` loop'a girip generic hata. Ayrı genel bug: `_dedup_existing_workflow` 404'te fresh create'e düşer. Suite **405 passed**. Detay: [[known-issues]]. |
| 2026-07-02 | **GEÇTİ** ✅ (uçtan uca) | Yeni sohbette E1 verildi → agent workflow `D3SLKbZgCSabvnvS` kurdu, **repair canlıda ateşlendi** (`normalized googleSheets column mapping` + `wrapped sheetName` loglarda), model yine yanlış columns şekli yazdı ama repair düzeltti. **Webhook POST → 200, execution #220 `status: success`**, satır düştü, 0 hata. Genel fix'ler agent'ın gerçek üretim yolunda çalışıyor. |
