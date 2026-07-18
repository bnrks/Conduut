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
| 2026-07-18 | Chat onay regresyonu geçti; M1 ikinci-run `no_action` bekliyor | Yeni workflow `ngIf7SQuk7u2qDUR` için preview yalnız bir `user_input_request` üretti; structured onay sonraki turda tek denemede execution `#356`yı başlattı. Sonuç `verified`, full coverage, `1 eligible = 1 action = 1 write-back`, duplicate risk yok; onay/claim retry döngüsü görülmedi. Bu yeni workflow'un hemen ikinci çalıştırması henüz loglarda yok. |
| 2026-07-18 | İlk gerçek run geçti; ikinci-run `no_action` bekliyor | Workflow `Ju5pPQJA6GicB31o`, execution `#352`: `verified`, full coverage, `1 eligible = 1 action = 1 write-back`, duplicate risk yok. Preview sırasında erken yazılan "onaylıyorum" frontend concurrent-send guard'ında sessizce düştü; composer kilidi ve awaiting-approval claim-retry kısa devresi eklendi. |

## Workflow Assurance V1 regresyon oracle'i

Tam kullanıcı-davranışı test protokolü ve M1-A...M1-J varyasyonları için bkz.
[[workflow-assurance-scenario-test-plan]].

[[adr-0019-workflow-assurance-v1]] sonrasi M1 yalniz n8n raw `success` ile
gecmis sayilmaz. Kontrollu eval Sheet ve test inbox ile asagidaki fonksiyonel
kanitlar birlikte aranir:

- `#320`, `#323` ve `#327` snapshot'lari regression fixture'i olarak korunur;
  ilk ikisi action/write-back uyusmazliginda `partial` olur. Gercek `#327`
  kaydinda count ve receipt'ler eslesse de Update Status, Gmail'den once
  calistigi icin birlesik sonuc `writeback_before_action` ile
  `needs_attention` olur; raw/count basarisi Gmail failure postcondition'ini
  tek basina kanitlamaz.
- Duplicate veya bos matching identity, Gmail action'indan once bloklanir;
  e-posta ve isim otomatik unique kabul edilmez.
- Kisisellestirme alanlari Gmail action'ina kadar item-linking korunarak ulasir;
  Gmail sonrasinda kaybolan `$json.*` alaniyla Sheets update kurulamaz.
- Ilk kontrollu run oracle'i: `1 eligible = 1 mail receipt = 1 write-back`.
- Hemen ikinci run oracle'i: `0 eligible = 0 mail = 0 update = no_action`.
- Gmail failure'da status guncellenmez. Sheets failure sonrasi tum workflow
  otomatik retry edilmez; sonuc `partial`, `duplicate_risk=true` olur.

Bu bolum mevcut sonuc tablosunu gecmis saymaz; canli eval yapildiginda tarihli
satir ayrica eklenmelidir. Production musteri kayitlarina otomatik canary
gonderilmez.

### 2026-07-16 kontrollu Sandbox V2 turu

Calisan lokal n8n'de gercek M1 workflow'u (`lMn05J3Id9l4NcbQ`) action
node'lari probe'a cevrilerek kosuldu; Gmail veya Sheet side effect uretilmedi,
gecici clone `finally` ile silindi. Harness `coverage=full` ile
`1 eligible = 1 action probe = 1 write-back probe` sayilarini cikardi, fakat
tam upstream read dataset'inde secilen matching identity duplicate oldugu icin
`identity_duplicate` finding'i uretti ve sonucu `needs_attention` olarak
blokladi. Bu, e-posta alaninin yalniz uygun kayitlar arasinda tek gorunmesine
dayanarak unique kabul edilemeyecegini canli olarak dogruladi.

### 2026-07-18 chat onay ve connection-loop hardening

Canli M1 denemesinde Sheets managed Connection bagli oldugu halde agent'in bos
custom credential listesini "Sheets bagli degil" diye yorumladigi ve preview
tokeni chat turlari arasinda kayboldugu icin ayni calistirma iznini birden cok
kez sordugu goruldu. Uygulama katmaninda structured preview approval,
managed-vs-custom credential otorite ayrimi ve sandbox terminal repair siniri
eklendi. Unit/regresyon kontrolleri gecmistir; bu degisiklik sonrasi gercek M1
scenario turu henuz kosulmamistir ve **TEST EDILMEDI** kabul edilir. Sonraki
canli turda tek onay karti -> tek preview token tuketimi -> tek execution ve
ikinci kosuda `no_action` oracle'i ayrica dogrulanmalidir.

### 2026-07-18 gerçek execution #352

Workflow `Ju5pPQJA6GicB31o` icin safe preview `1 eligible = 1 action = 1
write-back` buldu; kullanicinin structured `Approve run` cevabindan sonra
execution `#352` raw `success`, `functional_status=verified`, `coverage=full`,
`duplicate_risk=false` ile tamamlandi. Mail receipt ve `record_id=R-001`
write-back birlikte dogrulandi. Bu kanit ilk-run M1 fonksiyonel oracle'ini
gecirir. Hemen ikinci run henuz yapilmadigi icin idempotency/`no_action`
oracle'i acik kalir.

Ayni turda kullanici, assistant stream tamamlanmadan once "onayliyorum" yazdi;
backend'de buna ait `/api/chat/send` veya agent run yoktur. UI composer aktif
gorunmesine ragmen `handleSend` concurrent gonderimi sessizce reddedip alani
temizliyordu. Ayrica preview attachment'i 22:28:19'da emit edildikten sonra
claim validator `ModelRetry` uretmis ve final onay panelini 22:29:05'e kadar
geciktirmisti. Composer artik agent typing sirasinda disabled; awaiting approval
durumunda claim validator retry yerine deterministic preview ozeti dondurur.

### 2026-07-18 onay akışı canlı regresyonu ve execution #356

Kullanıcı görevi yeniden vererek yeni workflow `ngIf7SQuk7u2qDUR`u oluşturdu.
`şimdi çalıştır` turu (`b4890aa105184a41b73f4a53ea3f474f`) tek preview
`user_input_request` üretti ve `attempts=1`, `recovered=no` ile kullanıcı
cevabını bekledi. Structured `Approve run` turu
(`8fd3940772ac4ee585824bd2ef14a8f8`) ikinci bir izin istemeden execution
`#356`yı çalıştırdı; sonuç `functional_status=verified`, `coverage=full`,
`1 eligible = 1 action = 1 write-back`, `duplicate_risk=false` oldu. Önceki
concurrent-send/claim-retry kaynaklı çift izin hissi bu canlı turda tekrarlanmadı.

Bu tur yeniden oluşturulan workflow'un ilk gerçek çalışmasıdır. Dolayısıyla M1
idempotency kabulü için aynı workflow'un veri değiştirilmeden hemen ikinci kez
çalıştırılıp `0 eligible = 0 action = 0 write-back = no_action` üretmesi hâlâ
gereklidir.
