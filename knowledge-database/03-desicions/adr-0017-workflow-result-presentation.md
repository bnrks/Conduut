# ADR 0017: Workflow Sonuç Sunumu (build-time output schema)

Merkez: [[index]]

## Durum

Accepted - 2026-06-28. Implementasyon + review tamam (subagent-driven, 7 task +
final review + 1 Important fix). Backend 386 passed (5 ön-mevcut Windows-tmp),
ruff temiz; frontend tsc 0 / lint 0. **Canlı uçtan-uca doğrulama bekliyor
(manuel)** — n8n + agent + web açıkken veri-döndüren bir workflow ile.

## Bağlam

Bir workflow Conduut **chat**'ten çalıştırıldığında sonuç güzel görünüyor: agent'ın
LLM'i ham çıktıyı doğal dile çeviriyor (narrator var). Ama **workflows dashboard**'undan
çalıştırıldığında narrator yok — `_summarize_execution` ham `outputs`'u üretiyor ve
`dashboard/workflows/page.tsx` bunu doğrudan `<pre>{JSON.stringify(...)}</pre>` olarak
basıyor. Sonuç teknik, çirkin JSON; "kullanıcı n8n/JSON bilmek zorunda değil" değer
önermesini ihlal ediyor. Eksik olan "güzelleştirme" değil, sonucu **anlamlandıran katman**.

## Karar

"Anlam"ı **build zamanında** üret (agent workflow'un amacını zaten biliyor), bir kez
metadata'ya yaz, her run'da **deterministik + sıfır run-time maliyet** ile render et.
`input_schema`'nın birebir simetriği.

Reddedilen alternatifler: **B (run-time LLM narrator)** — batch'te satır başına LLM
çağrısı (≤50) yüzünden elendi; **C (LLM'siz akıllı renderer)** — "güzel ama anlamlı
değil" olduğu için yalnız fallback olarak kalır (presentation yoksa ham JSON `<details>`).

### Eşleme sözleşmesi (kritik)

**Sonuç, isimli üst-seviye alanlar olarak döner; `output_schema` o alanları isimle
etiketler/formatlar.** Agent `output_schema=[price, currency]` derse, son responding
node tam `{price, currency}` döndürür. Resolver basit: `item[field.name]`. Bu, "veri
şekli n8n'de, sunum Conduut'ta" ilkesinin sonucu — gerekirse agent sona Set/Edit
Fields node ekler. **Serbest JSON-path eşleme YOK** (kırılgan).

### Veri modeli + akış

- **`WorkflowOutputField`** (`schemas.py`): `name`, `label`, `format` ∈
  {text, longtext, number, currency, datetime, url, email, boolean, list} (varsayılan
  text). `WorkflowInputField`'in aynası.
- **Üretim:** `create_workflow`/`update_workflow`'a opsiyonel `output_schema` parametresi
  (model yüzeyinde tool arg). `_normalized_output_schema` deterministik temizler (trim,
  dedup, boş etiketi name'den insanlaştır, geçersiz format → text, salvage ile alanı
  düşürmeden).
- **Depolama:** `resources.output_schema` (top-level alan değil — `test_status` deseni).
  `save_workflow_output_metadata` oku-birleştir yapar; **iki yönlü koruma**: build
  `test_status`'u ezmez, sandbox'ın sonraki `save_workflow_test_status` yazması
  `output_schema`'yı ezmez (her ikisi de mevcut `resources`'u kopyalar).
- **Run-time çözümleme:** `_resolve_presentation(response, output_schema)` webhook
  gövdesini şemaya göre `WorkflowResultPresentation {title, fields:[{label,format,value}]}`
  yapısına çözer. `title` V1'de hep None (model alanı genişletilebilirlik için var).
  Gövde liste → ilk item; non-dict → presentation None; None/"" alanlar atlanır; hiç
  alan çözülmezse veya şema boşsa None; **yalnız non-error run'da** üretilir.
- **Endpoint:** run endpoint `presentation`'ı response dict'ine ekler
  (`model_dump(exclude_none=True)` ya da None); BFF şeffaf proxy olduğu için frontend'e
  aynen akar.
- **Frontend:** `WorkflowResultView` + `formatResultValue` format-duyarlı render
  (currency→Intl USD, datetime→yerel, url→link, email→mailto, boolean→✓/✗, list→çip,
  longtext→paragraf; bilinmeyen→`asText`, hiçbir yol ham object'i React child basmaz).
  Ham `outputs` JSON "Ham veriyi gör" `<details>` altına iner; presentation yoksa
  bugünkü fallback + boş-durum mesajı.

## Final review'da bulunan + düzeltilen Important

Presentation, `_response_preview` ile **kırpılmış** webhook gövdesinden çözülüyordu
(`_preview_value`: string >1200 char, list →3 öğe, dict →12 anahtar). Sonuç: 12.
anahtardan sonraki **declared alan sessizce düşüyor**, `longtext` kırpılıyor, `list`
3 öğeye iniyordu — yani feature'ın tam da zengin-veri formatlarını bozuyordu. Skaler
(BTC fiyatı) için etkisizdi ama declared-alan garantisini zedeliyordu. **Fix:**
`common._response_full` (kırpmasız gövde) eklendi; `_summarize_execution(full_response=)`
presentation'ı tam gövdeden çözer, preview yalnız `outputs`/error gösterimi için kalır.
Backward-compatible (`full_response=None` → eski davranış). (commit `af7420f`)

## Bilinen V1 sınırlamaları (kabul edildi, ertelendi)

- **currency hardcoded USD** — TRY/EUR tutarı `$` ile render eder; dinamik para birimi
  alanı ertelendi. (Türkçe ürün için ileride düzeltilmeli.)
- **datetime epoch parse etmez** — ISO string çalışır; sayısal epoch ham gösterilir.
- **Sticky output_schema** — `merge_*` anahtarı yalnız set eder, silmez; data-döndüren
  bir workflow salt-yan-etkiye dönüşürse eski şema kalır (zararsız: isim eşleşmezse
  resolver None döner). `output_schema=[]` ile temizleme ileride.
- **Teknik anahtar çakışması** — `_strip_technical_output` `query/headers/params/
  webhookUrl/executionMode` anahtarlarını siler; bu adlarla bir alan çözülmez.
- **Çok-satır liste→tablo**, **batch per-row presentation**, **kullanıcı etiket
  düzenleme** — kapsam dışı (V1 tek-item kart, tek run).

## Eklenen/değişen

- Backend: `agent/tools/output_schema.py` (**yeni**: model normalize + `save_workflow_output_metadata`),
  `schemas.py` (`WorkflowOutputField`, `WorkflowResultPresentation(Field)`,
  `WorkflowRunResultData.presentation`), `tools/execution.py` (`_resolve_presentation`,
  `_first_result_item`, `_summarize_execution(output_schema=, full_response=)`),
  `tools/workflow_runner.py` (metadata'dan okuma + `full_response` thread),
  `tools/common.py` (`_parse_response_body`, `_response_full`), `tools/factory.py`
  (her iki closure'a `output_schema` + kaydetme), `tools/prompt.py` (kural),
  `routes/workflows.py` (response'a `presentation`).
- Frontend: `types/workflow.ts` (presentation tipleri),
  `components/dashboard/workflow-result-view.tsx` (**yeni**),
  `dashboard/workflows/page.tsx` (modal: presentation kartı + ham JSON fallback).

## Sonuç

TDD, subagent-driven (7 task, her biri spec+quality review; haiku/sonnet tier-seçimli;
final whole-branch review opus). Final review en yüksek-riskli seam'i (resources merge
/ test_status iki-yönlü koruma) doğru buldu; tek Important (preview-truncation) yakalandı
ve düzeltildi.

Spec: `docs/superpowers/specs/2026-06-28-workflow-result-presentation-design.md`.
Plan: `docs/superpowers/plans/2026-06-28-workflow-result-presentation.md`.
