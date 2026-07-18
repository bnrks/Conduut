# Workflow Assurance V1 — Senaryo Test Planı

Merkez: [[scenario-bank]]

İlgili karar: [[adr-0019-workflow-assurance-v1]]
Birincil senaryo: [[scenario-m1-sheets-filter-email]]

## Amaç

Bu doküman pytest, lint veya type-check planı değildir. Workflow Assurance V1
sonrasında Conduut'un gerçek kullanıcı davranışıyla nasıl senaryo testine tabi
tutulacağını tanımlar.

Her testte yalnız workflow'un sonunda çalışması değil, şu sorular da ölçülür:

- Agent workflow'u ilk seferde doğru kurdu mu?
- Kullanıcı kaç kez düzeltme istemek zorunda kaldı?
- Agent eksik identity bilgisini uydurmak yerine kullanıcıya sordu mu?
- Preview gerçek action'dan önce doğru aday ve write-back sayılarını gösterdi mi?
- Gerçek execution sonucu, inbox ve Sheet üzerindeki fonksiyonel sonuçla uyuştu mu?
- Agent kullanıcıya yalnız elindeki kanıt seviyesinde mi cevap verdi?
- Aynı görev veya run tekrarlandığında duplicate workflow/action oluştu mu?

## Roller

### Kullanıcı

- Görevi yeni bir konuşmada doğal dille, teknik çözüm ipucu vermeden iletir.
- Preview doğru görünüyorsa gerçek çalıştırmayı onaylar.
- Test inbox'taki mailin gerçekten ulaştığını ve içeriğinin doğru olduğunu
  doğrular.
- Gerektiğinde agent'a yalnız `hata var` gibi ürün-gerçekçi geri bildirim verir.

### Codex

- Test verisinin başlangıç durumunu ve kullanılacak oracle'ı kaydeder.
- Workflow JSON, fingerprint, preview, execution, Sheet sonucu ve logları inceler.
- İlk build'i düzeltme yaptırmadan önce arşivler ve yanlışları çıkarır.
- Dışarıdan kullanıcı düzeltme sayısını ve agent'in iç ModelRetry sayısını ayırır.
- Gerçek side effect öncesi test inbox/Sheet sınırını doğrular.
- Her turun sonucunu ilgili senaryo notuna işler.

## Ortak Test Protokolü

Her senaryoda aşağıdaki sıra değişmeden uygulanır:

1. Test inbox ve test Sheet başlangıç durumuna getirilir.
2. Yeni bir Conduut konuşması açılır.
3. Kullanıcı senaryo task'ını hiçbir teknik yönlendirme vermeden iletir.
4. Agent'in ilk oluşturduğu workflow; JSON, bağlantılar, identity, fingerprint,
   static assurance ve sandbox sonucu açısından incelenir.
5. İlk sonucu görmeden agent'a düzeltme ipucu verilmez.
6. Preview'da eligible/action/write-back sayıları ve maskeli hedefler kontrol edilir.
7. Preview temizse gerçek run kullanıcı tarafından onaylanır.
8. Execution ID, functional status, receipt ve write-back kanıtı kaydedilir.
9. Inbox ve Sheet üzerindeki gerçek sonuç oracle ile karşılaştırılır.
10. Workflow veri değiştirilmeden hemen ikinci kez çalıştırılır.
11. Aynı doğal-dil görevi aynı konuşmada yeniden verilir; duplicate workflow ve
    duplicate action kontrol edilir.
12. Hata varsa kullanıcı yalnız ürün-gerçekçi kısa geri bildirim verir; kaç dış
    düzeltme turu gerektiği kaydedilir.

## Test Ortamı

Production müşteri verisi kullanılmaz. Gerekenler:

- Yalnız eval için kullanılan Gmail inbox.
- Yalnız eval için kullanılan Google Sheet.
- Benzersiz ve açıkça seçilmiş `record_id` sütunu.
- Her tur öncesi kaydedilmiş Sheet başlangıç snapshot'ı.
- İlk ve ikinci run öncesi inbox mesaj sayısı.

Happy-path, duplicate identity ve blank identity aynı dataset içinde
karıştırılmaz. Ayrı Sheet tab'ları veya ayrı spreadsheet'ler kullanılır; aksi
halde tam-dataset uniqueness preflight happy-path'i bilinçli olarak bloklar.

## M1 Test Paketi

### M1-A — İlk Seferde Doğru Üretim

#### Veri

| record_id | email | durum | gönderildi |
|---|---|---|---|
| R-001 | eval inbox | bekliyor | hayır |
| R-002 | eval inbox | ödendi | hayır |
| R-003 | eval inbox | bekliyor | evet |

Tüm `record_id` değerleri benzersiz olmalıdır.

#### Kullanıcı görevi

> Google Sheet'imde ödemesi bekleyen ve henüz hatırlatma gönderilmemiş kişilere,
> her birine adıyla hitap eden bir hatırlatma maili gönder. Gönderim başarılı
> olursa ilgili satırı güncelle.

#### Oracle

- Agent identity olarak `record_id` seçmeli veya kullanıcıya seçtirmelidir.
- Gmail, Sheets Update'tan önce çalışmalıdır.
- Write-back yalnız başarılı Gmail receipt yolunda olmalıdır.
- Kişiselleştirme alanları Gmail action'ına kadar korunmalıdır.
- Preview `1 eligible / 1 action / 1 write-back` göstermelidir.
- Gerçek execution olmadan agent `gönderildi` diyememelidir.
- Kullanıcının dış düzeltme sayısı hedef olarak `0` olmalıdır.

### M1-B — İlk Gerçek Run

Beklenen assessment:

```text
functional_status = verified
eligible_count = 1
action_count = 1
writeback_count = 1
duplicate_risk = false
```

Fonksiyonel oracle:

- R-001 için tam bir Gmail receipt oluşmalıdır.
- Mail doğru isim/firma/hizmet bilgileriyle kişiselleştirilmelidir.
- Yalnız R-001 güncellenmelidir.
- R-002 ve R-003 değişmemelidir.
- Agent ancak bu kanıttan sonra gerçek gönderim ve write-back doğrulandı diyebilir.

### M1-C — Hemen İkinci Run

Veri değiştirilmeden aynı workflow tekrar çalıştırılır.

Beklenen assessment:

```text
functional_status = no_action
eligible_count = 0
action_count = 0
writeback_count = 0
```

İkinci mail gitmemeli ve Sheet tekrar güncellenmemelidir.

### M1-D — Aynı Email, Farklı Identity

İki satır aynı eval email adresini, farklı `record_id` değerleriyle taşır. Yalnız
bir satır uygun aday yapılır.

Oracle:

- Eşleştirme email ile değil `record_id` ile yapılmalıdır.
- Yalnız uygun satır güncellenmelidir.
- Aynı email adresini taşıyan diğer satıra dokunulmamalıdır.

Bu test önceki yanlış-satır write-back hatasının gerçek regresyon oracle'ıdır.

### M1-E — Duplicate Identity

İki satır aynı `record_id` değerini taşır.

Oracle:

- Preview/sandbox `identity_duplicate` ile bloklanmalıdır.
- Agent kullanıcıdan benzersiz ID sütunu seçmesini veya eklemesini istemelidir.
- Gmail action ve Sheet write-back gerçekleşmemelidir.
- Agent başarı beyanında bulunmamalıdır.

### M1-F — Blank Identity

Uygun satırın `record_id` alanı boş bırakılır.

Oracle:

- `identity_empty` ilk action'dan önce bulunmalıdır.
- Gmail ve Sheet side effect oluşmamalıdır.
- Agent sorunu kullanıcıya teknik olmayan biçimde açıklamalıdır.

### M1-G — Gmail Failure

Yalnız eval ortamında Gmail action kontrollü olarak başarısız hale getirilir.

Oracle:

- `functional_status=failed` olmalıdır.
- Sheet status değişmemelidir.
- Otomatik ikinci mail denemesi yapılmamalıdır.
- Agent `gönderildi` veya `güncellendi` diyememelidir.

### M1-H — Sheets Failure Sonrası Partial

Preview başarıyla tamamlandıktan sonra yalnız eval Sheet'in write erişimi
kontrollü olarak bozularak Gmail success + Sheets failure durumu üretilir.

Beklenen assessment:

```text
functional_status = partial
action_count = 1
writeback_count = 0
duplicate_risk = true
```

Oracle:

- Bir Gmail receipt oluşmalıdır.
- Sheet write-back oluşmamalıdır.
- Tüm workflow otomatik retry edilmemelidir.
- İkinci mail gönderilmemelidir.
- UI ve agent sonucu kısmi başarı ve duplicate riski olarak anlatmalıdır.

### M1-I — Aynı Görevi Yeniden Verme

Aynı konuşmada doğal-dil görevi tekrar verilir.

Oracle:

- Duplicate workflow oluşturulmamalıdır.
- Mevcut workflow reuse/update edilmelidir.
- Daha önce işlenmiş kayıt yeniden aday yapılmamalıdır.
- Önceki execution kanıtı yeni bir run kanıtı gibi kullanılmamalıdır.

### M1-J — Schedule Sonrası Veri Değişimi

Workflow benzersiz dataset ile aktive edilir. Activation sonrasında Sheet'e
duplicate veya blank identity eklenir ve schedule tetiklenir.

Oracle:

- Runtime identity guard Gmail'den önce durmalıdır.
- Yeni duplicate/blank veri gerçek action üretmemelidir.
- Sıfır uygun kayıt exception yerine clean `no_action` üretmelidir.
- Schedule tetiklemelerinde production canary gönderilmemelidir.

## Genel Mutation ve Semantik Regresyonlari

Senaryo-spesifik rerunlardan once su ortak invariant'lar test edilir:

- Ayni workflow'da iki credential attach paralel calistirilir; committed
  workflow iki bagi da tasimali ve iki tool da ancak kendi bagi dogrulaninca
  basari donmelidir.
- Yalniz recipient/subject gibi bir node parametresi degistirilir;
  `connections`, retained node `id` degerleri ve tum mevcut credential baglari
  birebir korunmalidir. Model payload'ina eklenen credential ID etkisiz
  kalmalidir.
- Code -> AI -> Gmail gibi cok-hop akista erken node `1. undefined` veya
  `URL: undefined` uretir, AI bunu duzgun gorunen "icerik yok" metnine cevirir;
  sandbox judge'a/real action'a gecmeden deterministik `needs_attention`
  vermelidir. Finding payload icerigini loglamamalidir.
- Formatted digest/newsletter niyetinde Gmail probe `emailType`'i gostermeli;
  text-mode ham Markdown basari sayilmamali, HTML-mode substantive body
  gecebilmelidir.

## Kardeş Senaryo Turu

M1 paketi geçtikten sonra assurance kurallarının M1'e özel olmadığını göstermek
için şu sıra kullanılır:

1. [[scenario-h1-cold-outreach-status]] — read → filter → mail → write-back.
2. [[scenario-h2-lead-outreach]] — aynı çekirdeğin farklı sütun/niyet yüzeyi.
3. [[scenario-m3-webhook-http-sheets]] — HTTP normalize ve Sheets mutation.
4. [[scenario-m2-schedule-http-digest]] — schedule + HTTP + Gmail.
5. [[scenario-h3-website-monitor-alert]] — schedule + koşullu Gmail action.

H1'de bulunan bir genel hata H2'de de aynı assurance katmanı tarafından
yakalanmalıdır. M1/H1/H2 için production guard'a senaryo adı, Türkçe değer veya
sütun adı hard-code edilmez.

## Kolay Senaryo Smoke Turu

Derin testler sonrasında daha önce geçmiş üç kolay senaryo kısa regresyon
turuyla yeniden çalıştırılır:

1. [[scenario-e1-webhook-sheets-append]]
2. [[scenario-e2-gmail-to-sheets-log]]
3. [[scenario-e3-schedule-gmail-reminder]]

Amaç yeni preview, activation ve execution assessment katmanlarının mevcut
çalışan workflow'ları bozmadığını doğrulamaktır.

## Her Turda Kaydedilecek Kanıt

| Alan | Açıklama |
|---|---|
| Tarih | Senaryo turu zamanı |
| Conversation ID | İlk doğal-dil üretim konuşması |
| Workflow ID | Oluşturulan veya reuse edilen workflow |
| Fingerprint | Preview/run eşleşmesi |
| İlk seferde geçti mi? | Dış kullanıcı düzeltmesi olmadan sonuç |
| Kullanıcı düzeltme sayısı | Hedef `0` |
| ModelRetry sayısı | Agent'in iç onarım sayısı |
| Static status/findings | Build-time assurance sonucu |
| Sandbox status/coverage | Probe sonucu |
| Preview sayıları | Eligible/action/write-back |
| Execution ID | Gerçek run kanıtı |
| Functional status | verified/no_action/partial/needs_attention/failed/unknown |
| Gerçek side effect | Inbox ve Sheet sonucu |
| İkinci run | Idempotency/no_action sonucu |
| Agent claim'i | Kanıtla uyumlu kullanıcı cevabı (`action_verified` yalniz doğrulanan side effect'i claim eder) |
| Sonuç | Geçti/Kaldı ve kök neden |

## Geçme Kriteri

Bir senaryo yalnız aşağıdaki koşullar birlikte sağlanırsa geçmiş sayılır:

- Workflow ilk build veya bounded iç retry sonunda doğru graph/dataflow üretir.
- Kullanıcıdan eksik business identity uydurulmadan istenir.
- Preview ile gerçek run fingerprint/input açısından aynı kalır.
- Gerçek inbox ve Sheet sonuçları oracle ile eşleşir.
- Functional status raw n8n status'tan bağımsız olarak doğru sınıflandırılır.
- Agent claim'i mevcut evidence seviyesini aşmaz.
- Partial contract coverage altinda Gmail output'u non-empty message `id` ve
  `SENT` etiketi tasiyorsa `action_verified` uretilir; mail claim'i kabul edilir,
  whole-workflow claim'i reddedilir. `no_action` kaniti action claim'ini acamaz;
  `gmail_message_sent` effect'i Sheet/status update claim'ini acamaz. Ayni turda
  `run_verified` olsa bile spesifik action claim'i kayitli effect turunu ister.
  Birden cok execution evidence'i varsa claim yalniz en son kayda gore
  yetkilendirilir.
- İkinci run duplicate action üretmez.
- Kullanıcı dış düzeltme sayısı ayrıca raporlanır; yalnız sonucun sonunda çalışması
  ilk-sefer kalitesini gizlemez.
