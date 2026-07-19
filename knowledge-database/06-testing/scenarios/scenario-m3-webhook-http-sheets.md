# Senaryo M3 — Webhook → HTTP → normalize → Sheet'e yaz

Merkez: [[scenario-bank]]

- **Zorluk:** medium
- **Kaynak (n8n.io):** https://n8n.io/workflows/13207-route-measurement-data-from-a-webhook-to-google-sheets-email-or-custom-js
- **Capability'ler / node'lar:** Webhook, Set/Edit Fields, Google Sheets
  (`sheets.row.append`), (opsiyonel Gmail dalı)
- **Kardeş senaryo(lar):** [[scenario-e1-webhook-sheets-append]] (webhook→sheet)
- **Risk noktaları:** webhook gövdesi `$json.body.*`, Set node
  `assignments.assignments` formatı (boş Set reddedilir), çok-çıkışlı dallanma,
  Sheets v4 append şeması.

## Task (agent'a verilen doğal-dil)

> Cihazlarımdan webhook ile gelen ölçüm verilerini temizleyip düzenli sütunlarla
> bir Google Sheet'e kaydet.

## Referans yapı (yalnız bizde; agent görmez)

- **Webhook** trigger (`POST`).
- **Set/Edit Fields**: gelen gövdeyi temiz alanlara normalize eder
  (`$json.body.*` → adlandırılmış sütunlar).
- **Google Sheets**: `resource: sheet`, `operation: append`.
- Bağlantı: Webhook → Set → Google Sheets.

## Beklenen sonuç (fonksiyonel)

Webhook'a gelen ham ölçüm, normalize edilip Sheet'e düzenli sütunlarla yazılır.
Set normalizasyonu + append doğruysa geçti.

## Sonuç geçmişi

**Güncel durum (2026-07-19): GEÇTİ ✅.** Yeni workflow
`iYOMbsf7VUmfoVSU` aktif. İlk dış webhook execution `#382`, Sheet başlıkları
Türkçe (`Cihaz Adı`, `Sıcaklık`...) iken node mapping/schema anahtarları İngilizce
(`cihaz_adi`, `sicaklik`...) kaldığı için Google Sheets node'unda
`Column names were updated after the node's setup` hatasıyla durdu. Kullanıcı
yalnız hatayı bildirdi; agent `list_executions` + `inspect_execution` ile kök
nedeni buldu, workflow'u yerinde güncelledi ve yeniden aktive etti. İkinci dış
webhook execution `#384` başarıyla tamamlandı; Google Sheets node çıktısı yedi
sütunun tamamını doğru değerlerle döndürdü (`Sensör-1`, `23.5`, `65`, `1013`,
`120`, `İstanbul`, `2025-01-15 14:30`). Bu gerçek append kanıtıyla M3 geçti.

**Önceki başarısız koşu:** Workflow `YJEk1macGLuzYuAN` içindeki Google Sheets v4.7 append
node'u spreadsheet kimliğini `documentId` yerine top-level `sheetId` alanına
yazdı. n8n önce boş Document locator nedeniyle
`Can not get sheet 'From List' with a value of ''`, ardından Document listeleme
yolunda 403 `Forbidden` verdi. Aynı Google credential'ı `documentId` kullanan
execution `#352` ve `#356` içinde başarılı olduğundan birincil kök neden OAuth
scope değil, yanlış node parametre şeklidir.

Sandbox clone execution `#380`, append node'unu desteklenmeyen action olarak
disable ettiği halde partial coverage sonucunu başarı kanıtı gibi taşıdı; gerçek
workflow hiç çalışmamışken agent aktivasyonu veri yazma başarısı olarak anlattı.
Düzeltme bu nedenle hem Sheets v4 şemasını hem assurance/claim sınırını kapsar:

- Repair, non-empty ve non-numeric legacy `sheetId` string'ini deterministik
  biçimde `documentId`'ye taşır; numeric tab gid belirsizliği validation'a kalır.
- Validation tüm Sheets row operasyonlarında dolu `documentId` + `sheetName`
  ister ve çakışan legacy/current document kimliklerini reddeder.
- Sandbox, Sheets append satırını yan etkisiz probe ile doğrular; partial
  coverage artık `sandbox_passed` claim evidence üretmez.
- Aktivasyon ayrı `workflow_activated` kanıtıdır; gerçek execution veya effect
  kanıtı olmadan “veri Sheet'e yazılıyor/yazılacak” iddiasını açmaz.

Kod regresyon suiti geçti. Yeni workflow üretimi doğru `documentId` locator'ını
taşıdı ve gerçek webhook execution'ında Google Sheets append doğrulandı.
Yeni agent image'i 2026-07-19'da bu kaynaklarla başarıyla build edildi, fakat
container M3'ten bağımsız mevcut `groq` optional dependency eksikliği nedeniyle
startup'ta durdu; bu yüzden canlı rerun başlatılamadı (bkz. [[known-issues]]).

| Tarih | Geçti/Kaldı | Bulunan bug → kök-neden → katman → commit → kardeş-doğrulama |
|-------|-------------|--------------------------------------------------------------|
| 2026-07-19 | KALDI | `sheetId` spreadsheet kimliği `documentId`'ye taşınmadı + append sandbox coverage dışı kaldı + aktivasyon run kanıtı sanıldı → repair/validation + Sandbox V2 + claim policy → commit yok → unit/regresyon yeşil, M3 canlı rerun ve kardeş senaryo bekliyor |
| 2026-07-19 | GEÇTİ ✅ | Yeni `iYOMbsf7VUmfoVSU` doğru `documentId` ile üretildi → ilk live `#382` Türkçe Sheet başlığı / İngilizce mapping uyumsuzluğuyla kaldı → agent execution'ı kendi inceleyip mapping/schema'yı düzeltti → ikinci live `#384` yedi sütunla başarılı append yaptı. Sandbox `#381` remote header drift'ini kaçırdı; düzeltme sonrası `#383` gerçek run başarılı olduğu halde `required_field_empty` verdi ve aktivasyon claim retry'ı future-write ifadesini tamamen kapatmadı; bunlar M3 fonksiyonel kabulünden ayrı assurance takip bulgularıdır. |
