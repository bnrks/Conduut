# ADR-0010: Tek JSON Yüzeyi + Onarıcı Normalizer

Merkez: [[index]]

## Durum

Kabul edildi (2026-06-14). [[adr-0009-workflow-graph-compiler]]'i model yüzeyi
açısından **gevşetir/değiştirir**: graph compiler artık modele sunulan tercih
edilen builder değil, dahili bir kütüphanedir. ADR-0005/0009'daki compiler
mantığı silinmez; reuse edilir.

## Bağlam

ADR-0009 ile `create_workflow_from_graph` (WorkflowGraph IR) tercih edilen
builder yapıldı. Ancak canlı kullanımda agent (güçlü bir reasoning modeli olan
gpt-5 dahil) sürekli IR'ı **atlayıp** ham `create_workflow` JSON yoluna kaydı ve
üç klasik hatayı üretti: (1) langchain chat-model sub-node'unu `main` akışına
bağlama → boş AI mail, (2) `{{input.x}}` (n8n'de geçersiz), (3) webhook girdisini
`$json.body.x` yerine `$json.x` okuma.

Kök-neden (2026-06-13 statik analizi): modele **girişte** native n8n JSON verip
(registry node şemaları + pretraining JSON) **çıkışta** pretraining'inde hiç
olmayan bir IR (`kind`/`attached_to`/`role`/`{ref:'input.x'}`) ürettiriyorduk.
Belirsizlik altında model bildiği yola (ham JSON) geriliyor. IR ayrıca "yarım"
bir soyutlama: yalnızca ~14 curated kind için gerçek; kalan ~795 node
`n8n:<type>` ile zaten ham JSON. Yani A→B (ham ver, IR iste) asimetrisi modelin
prior'ıyla çatışıyordu. Detay: [[known-issues]].

## Karar

Modele **tek ve doğal bir yüzey** verilir: **kompakt n8n JSON**. Hatalar
reddedilmek yerine deterministik olarak **onarılır**.

1. **Tek builder.** Model yalnızca `create_workflow` / `update_workflow` görür.
   `create_workflow_from_graph` / `_from_plan` / `_from_spec` tool kayıtları
   `factory.py`'den kaldırıldı. Compiler modülleri (`graph_compiler.py`,
   `spec_compiler.py`, `blocks.py`) iç kütüphane + test olarak kalır.
2. **Kompakt JSON kontratı.** `WorkflowNode`'da `id`/`typeVersion`/`position`
   opsiyonel; model `name`/`type`/`parameters` yazar, gerisini Conduut doldurur.
   `connections` lineer akışta atlanabilir (sıra → wiring).
3. **Onarıcı normalizer** (`apps/agent/src/agent/repair.py`). Hat:
   normalize → **repair** → apply_runtime_inputs → validate. Repair
   "onar-ya-da-reddet" ilkesiyle çalışır:
   - **Her zaman onar (tek doğru yorum):** boilerplate doldurma; lineer wiring;
     tek-agent varsa sub-node'u `main`'den alıp `ai_*` porta bağlama;
     `{{input.x}}`→`$('<trigger>').first().json.body.x`; trigger'a doğrudan bağlı
     node'da deklare input için `$json.x`→`$json.body.x` (Code jsCode dahil).
   - **Reddet (belirsiz/eksik):** repair dokunmaz; mevcut
     `validate_workflow_payload` emniyet ağı `ModelRetry` ile reddeder (çok-agent
     belirsizliği, trigger yok, bilinmeyen type, boş zorunlu içerik).
   - **E-posta attribution (2026-06-17 eklendi):** e-posta gönderen node'lar
     (`gmail` message send/reply, `emailSend`) `options.appendAttribution=false`
     alır → n8n'in "This email was sent automatically with n8n" footer'ı kapanır.
     Sadece model açıkça bir değer vermemişse set edilir (açık seçim korunur).
   - **googleSheets şema upgrade'i (Stage 6, 2026-07-01 eklendi):** model
     googleSheets satır operasyonlarını (read/update/append...) sık sık **v4-öncesi
     zihinsel modelle** yazıyor: `resource: "spreadsheet"` + `spreadsheetId` +
     `range: "Tab!A:F"`. Kurulu v4.7 node'da bu **runtime'da crash**: node router'ı
     `resource: "spreadsheet"`'i yalnız `create`/`delete` implement eden modüle
     yönlendirir, `read`/`update` → `undefined` → `Cannot read properties of
     undefined (reading 'execute')`. Deterministik upgrade: `resource: "spreadsheet"`
     + satır-op → `resource: "sheet"`; `spreadsheetId`(str) → `documentId`;
     `range: "Tab!..."` → `sheetName: "Tab"` (v4 read/update serbest A1 range almaz;
     tab = `!`'ten önceki literal, leading `=` sıyrılır). `!` içermeyen range belirsiz
     (çıplak tab mı, çıplak A1 aralığı mı) → dokunulmaz, validation'a düşer. Bu stage
     RL sarma'dan (Stage 7) **önce** çalışır ki yeni `documentId`/`sheetName` string'leri
     `__rl` nesnesine sarılsın. Belirsizlik (create/delete iki resource'ta da var) yüzünden
     `create`/`delete` **auto-convert edilmez** (gerçek "delete spreadsheet" korunur).
     **Sınırlama (bilinçli):** update'in kolon-eşlemesi (`dataMode`/`values` → v4
     `columns`+`matchingColumns`) onarılmaz; doğru eşleşen-kolonu yeniden kurmak
     belirsizdir (yanlış tahmin **yanlış satıra yazar** = veri bozulması), o yüzden
     "reddet" tarafına bırakılır: `validation._validate_google_sheets_node` (2026-07-01
     eklendi) update/appendOrUpdate'te `columns`/`matchingColumns` yoksa hedef v4
     şekli gösteren `ModelRetry` ipucuyla reddeder (bkz. [[known-issues]] madde 1).
     Kaynak: 2026-07-01 "Sipariş Onay Maili" testi
     (kullanıcı log incelemesi); üç Sheets node'u da bu şemayla üretilmiş, aktive
     edilen workflow ilk Read'de patlıyordu. Detay: [[known-issues]].
   - **resourceLocator normalizasyonu (Stage 7, 2026-06-18 eklendi):** bazı
     node alanları n8n'de `{"__rl": True, "mode", "value"}` nesnesi bekler ama
     model doğal olarak düz string yazar; n8n bunu value/mode=undefined okur
     (`Can not get sheet 'undefined' ...` runtime hatası). `_RESOURCE_LOCATOR_FIELDS`
     tablosuna göre sarılır (`googleSheets` documentId=id, sheetName=name; URL
     değer → mode=url; zaten `__rl` olan veya string olmayan dokunulmaz). Compiler'lar
     (`graph_compiler`/`spec_compiler` `_sheet_locator`) bunu hep yapıyordu; IR
     yüzeyden çıkınca repair miras almamıştı — ilk canlı BTC→Sheets testinde
     açığa çıktı. **Sınırlama:** şimdilik yalnız googleSheets; Gmail/Drive vb.
     gerekirse tabloya eklenir (bilinmeyen RL alanı validation'a düşer).
4. **Few-shot.** `prompt.py`'ye 2-3 kanonik kompakt-JSON worked example eklendi
   (teklif senaryosu: webhook + AI Agent + ai_languageModel + Gmail + runtime
   input; basit lineer). Few-shot = "geçici finetune": hedef formatın prior'ını
   in-context verir.

## Gerekçe

- Modeli en güçlü olduğu dilde (n8n JSON) tutar; A→A tutarlılığı.
- ADR-0009 yatırımı korunur (port/typeVersion/expression sahiplenme mantığı
  repair'e taşınır; `ROLE_PORTS`, validation guard'ları, runtime expr reuse).
- "Onar > reddet" ModelRetry turlarını azaltır → eski `MAX_MODEL_REQUESTS`
  darboğazını da hafifletir.
- Her onarım loglanır → ölçüm + ileride finetune için `(ham JSON, onarılmış JSON,
  repairs)` corpus'u birikir.

## Sonuçlar

- Pozitif: tek yüzey, daha az model-format sürtünmesi; üç klasik bug deterministik
  kapanır; mevcut testler + 9 repair unit testi + 1 uçtan-uca pipeline testi yeşil.
- Negatif/risk: repair n8n semantiğini taşır (bakım yükü); sessiz yanlış-onarım
  riski → yalnızca tek-doğru-yorum onarılır, belirsiz reddedilir, hepsi loglanır.
- Geri alınabilir: IR tool kayıtları geri eklenebilir (compiler modülleri yerinde).

## Düzeltme katman hiyerarşisi (addendum 2026-07-01)

Model-çıktısı hatalarını düzeltirken **kanıt-kapılı** bir katman sırası izlenir;
yeni bir bug en **ucuz doğru** katmandan girer, üst katmana ancak alt katmanın
yetmediği **kanıtlanınca** çıkılır. "Her tuhaflık için prompt" anti-pattern'i
bilinçli olarak reddedilir.

1. **`repair.py` (deterministik)** — tek doğru yorum varsa. Bedava, sessiz, tüm
   modeller, 0 token. Varsayılan hedef.
2. **`validation.py` + ModelRetry** — belirsiz ama tespit + tarif edilebilirse
   (fix modelin semantik bilgisini ister, ör. hangi kolon eşleşir). Sadece
   tetiklenince 1 retry; 0 duran token. İpucu hedef şekli birebir göstermeli.
3. **`few_shots` (ayrı modül, seçmeli enjekte)** — 1 & 2 kanıtlanmış şekilde
   toparlamıyorsa **veya** desen çok sıksa. Her istekte duran token → pahalı;
   bu yüzden görev/node-type'a göre **seçerek** enjekte edilir (istek başı token
   doğrusal artmaz). Kanonik kompakt-JSON worked example'lar; diğer platformlara
   da örnek havuzu; loglanan repair corpus'uyla birlikte ileride finetune seti →
   model prior'ı öğrenince few-shot'lar emekli olur ("geçici finetune").
4. **Prompt kuralı** — sadece kesişen genel ilke; en pahalı/en zayıf sinyal, son çare.

**Uygulama durumu (2026-07-01):** googleSheets için Katman 1 (Stage 6 sheets
şema upgrade) + Katman 2 (`_validate_google_sheets_node` update column-map
kontrolü) kullanıldı. Katman 3 (`few_shots` modülü + Sheets-update örneği)
**ertelendi**: önce validation+ModelRetry'ın modeli canlıda toparlatıp
toparlatamadığı gözlenecek; toparlamıyorsa eklenir. Detay: [[known-issues]] madde 1.

**Güncelleme (2026-07-02, senaryo-bankası E1):** Stage 6 genişletildi — bare
`range` (`!` yok) A1 notasyonu değilse (`_A1_RANGE_RE`) tab adı sayılıp
`sheetName`'e taşınır (gerçek A1 aralığı validation'a bırakılır); `append` +
`columns` yoksa `autoMapInputData` default'u yazılır. Katman 2: validation artık
tüm satır-op'larında (yalnız update değil) eksik `sheetName`'i reddeder. Kaynak:
E1 (webhook→Sheets append) build+aktif ama runtime "workflow has issues" ile hiç
çalışmadı. Detay: [[known-issues]] E1 alt-başlığı, [[scenario-bank]].

**Güncelleme (2026-07-19, senaryo-bankası M3):** Model spreadsheet kimliğini
legacy top-level `sheetId` alanına yazdığında n8n v4.7 `documentId` locator'ı boş
kalıyor. `sheetId` non-empty, non-numeric string ise tek doğru yorum olarak
`documentId`'ye taşınır ve sonraki resourceLocator stage'inde `mode=id` ile
sarılır. Numeric-only değer tab gid olabileceğinden sessizce dönüştürülmez.
Validation bütün row operasyonlarında dolu `documentId` + `sheetName` ister;
current `documentId` ile farklı legacy `spreadsheetId`/`sheetId` birlikteyse
yanlış spreadsheet'e yazma riski nedeniyle payload reddedilir. Canlı kök neden
ve rerun durumu için bkz. [[scenario-m3-webhook-http-sheets]].

## İlgili

[[adr-0009-workflow-graph-compiler]], [[adr-0005-workflow-spec-compiler]],
[[adr-0004-parameterized-workflow-inputs]], [[known-issues]], [[agent-service]].
