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
   - **resourceLocator normalizasyonu (Stage 6, 2026-06-18 eklendi):** bazı
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

## İlgili

[[adr-0009-workflow-graph-compiler]], [[adr-0005-workflow-spec-compiler]],
[[adr-0004-parameterized-workflow-inputs]], [[known-issues]], [[agent-service]].
