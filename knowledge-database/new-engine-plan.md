# Typed Workflow Intent Engine Planı

## Summary
Conduut workflow generation ana yolunu raw n8n JSON üretiminden çıkarıp typed intent + operation profile engine yapısına taşıyacağız. Agent yalnızca kullanıcı niyetini ve step graph’ını üretecek; engine bu intent’i önceden tanımlı node/operation modelleriyle deterministic n8n JSON’a çevirecek.

Bu plan uygulanana kadar mevcut `create_workflow_from_plan/spec` ve raw `create_workflow` yolları korunacak, fakat yeni ana yol `create_workflow_from_intent` olacak. Plan Mode nedeniyle bu tur knowledge database dosyasına yazmadım; kaydedilecek ana note hedefi: `knowledge-database/03-desicions/adr-0008-typed-workflow-intent-engine.md`.

2026-06-05 implementasyon baslangici: karar [[adr-0008-typed-workflow-intent-engine]]
olarak kaydedildi. `apps/agent/src/agent/workflow_intent` paketi, ilk profile
renderer seti, `create_workflow_from_intent` tool kaydi, prompt guncellemesi ve
ilk unit/golden testler eklendi. Ikinci slice'ta `profiles.py` metadata
registry'si ve offline eval fixture validator/CLI runner eklendi. Bu not artik
planin genis hedefini tutar; guncel karar ve kod kapsami icin ADR notu birincil
referanstir.

## Key Changes

- Yeni intent DSL:
  - `WorkflowIntent`: `inputs`, `steps`, `edges`, `runPolicy`
  - `IntentStep`: `id`, `kind`, `inputs`, `config`
  - `DataRef`: `input.company_email`, `step.proposal.text`, `item.email`
  - `TemplateValue`: sabit metin + ref interpolation desteği
  - `WorkflowIntentInputField`: mevcut `WorkflowInputField` ile uyumlu kalacak

- Yeni engine:
  - `create_workflow_from_intent(name, intent)` tool’u eklenecek.
  - Engine sırası: intent validate -> profile resolve -> data refs validate -> render -> existing workflow validator -> n8n create/readback -> metadata/readiness.
  - Agent raw node parameter, n8n expression, credential field veya connection shape üretmeyecek.
  - Raw `create_workflow` sadece explicit teknik kullanıcı isteği veya experimental fallback için kalacak.

- Operation profile registry:
  - Her profile şunları tanımlayacak: `kind`, required/optional inputs, output contract, credential/capability, side-effect level, n8n render function, semantic validator.
  - Generic node’lar raw açılmayacak. HTTP/Code/Set şu typed profillere bölünecek:
    - HTTP: `http.call_api`, `http.fetch_json`, internal AI için `ai.generate_text`
    - Code: yalnız `code.safe_transform` veya deterministic transform template’leri
    - Set: `transform.map_fields`, `transform.template_text`

- İlk 10 profile:
  1. `input.webhook_form`
  2. `trigger.schedule`
  3. `ai.generate_text`
  4. `gmail.message.send`
  5. `sheets.row.append`
  6. `sheets.range.read`
  7. `transform.map_fields`
  8. `transform.template_text`
  9. `condition.if`
  10. `http.call_api`

- Kenarda duracak ilk 30 hedef profile:
  1. `input.webhook_form`
  2. `trigger.schedule`
  3. `ai.generate_text`
  4. `gmail.message.send`
  5. `gmail.message.search`
  6. `gmail.message.get`
  7. `gmail.message.reply`
  8. `gmail.message.label`
  9. `sheets.spreadsheet.create`
  10. `sheets.sheet.create`
  11. `sheets.range.read`
  12. `sheets.range.update`
  13. `sheets.row.append`
  14. `slack.message.send`
  15. `outlook.message.send`
  16. `notion.database.create_page`
  17. `airtable.record.create`
  18. `calendar.event.create`
  19. `drive.file.upload`
  20. `drive.file.search`
  21. `http.call_api`
  22. `http.fetch_json`
  23. `webhook.respond`
  24. `transform.map_fields`
  25. `transform.template_text`
  26. `code.safe_transform`
  27. `condition.if`
  28. `condition.switch`
  29. `loop.for_each`
  30. `merge.combine`

## Implementation Plan

- Agent backend’te yeni paket oluştur:
  - `src/agent/workflow_intent/schemas.py`
  - `src/agent/workflow_intent/profiles.py`
  - `src/agent/workflow_intent/renderer.py`
  - `src/agent/workflow_intent/validator.py`
  - `src/agent/workflow_intent/service.py`

Durum: `schemas.py`, `profiles.py`, `renderer.py`, `service.py` eklendi.
`validator.py` henuz ayri dosya degil; data ref ve profile validation su an
renderer/evals icinde duruyor. Sonraki refactor'da semantic validator ayri
module tasinacak.

- `spec_compiler.py` büyütülmeyecek. Mevcut `WorkflowPlan` compiler geçici compatibility yolu olarak kalacak; yeni profile renderer ayrı modülde olacak.

- `factory.py` içine `create_workflow_from_intent` tool’u eklenecek. Prompt güncellenecek:
  - Default workflow generation: `create_workflow_from_intent`
  - `validate_workflow_draft` ve raw JSON yolu: experimental/technical fallback
  - Agent her workflow için önce profile kind seçer, sonra typed intent üretir.

- Renderer kuralları:
  - Expression string’lerini sadece engine üretir.
  - Node id/name/position/connection shape engine tarafından oluşturulur.
  - Her step output contract üretir; sonraki step yalnız contract’taki field’lara ref verebilir.
  - Gmail send gibi side-effect profile’lar credential/readiness akışına aynı şekilde bağlanır.
  - `ai.generate_text`, n8n’de HTTP Request node olarak internal LLM endpoint’e render edilir.

- Unsupported akış davranışı:
  - Intent içinde unsupported `kind` varsa n8n workflow oluşturulmaz.
  - Agent kullanıcıya “bu aksiyon henüz güvenilir desteklenmiyor” der.
  - Experimental raw draft yalnız user açıkça teknik/deneysel mod isterse kullanılabilir.

## Test Plan

- Her profile eklenirken zorunlu test seti:
  - input model validation
  - output contract validation
  - render edilen n8n node parametreleri
  - credential/capability requirement
  - expression/data ref mapping
  - negative case: eksik required input

- Engine golden tests:
  - teklif maili: `input.webhook_form -> ai.generate_text -> gmail.message.send`
  - sheet log: `input.webhook_form -> gmail.message.send -> sheets.row.append`
  - sheet filter mail: `trigger.schedule -> sheets.range.read -> condition.if -> gmail.message.send`
  - API fetch mail: `http.fetch_json -> transform.map_fields -> gmail.message.send`

- n8n compatibility tests:
  - Docker n8n’e workflow create
  - created workflow readback
  - node count, connection shape, parameters, credential requirements kontrolü
  - side-effect node’lar run edilmez; create/readback ile sınırlı kalır

- Agent eval runner:
  - `apps/agent/evals/workflow_generation/*.yaml` prompt fixture’ları
  - runner: `python apps/agent/scripts/run_workflow_evals.py`
  - Her eval contract şunları assert eder: expected profile kinds, required runtime inputs, no raw n8n JSON, no activation/run, no unsupported fallback.
  - İlk eval seti 10 gerçek kullanıcı prompt’u içerecek; teklif otomasyonu birinci fixture olacak.

- CI ayrımı:
  - Unit/golden tests her commit’te.
  - n8n compatibility tests isteğe bağlı veya nightly.
  - live LLM evals manuel veya nightly; flaky kabul edilip semantic contract ile ölçülecek.

## Assumptions and Defaults

- “Node model” pratikte “node + resource + operation profile” olarak uygulanacak; Gmail tek aile olacak ama `send/search/get/reply` ayrı profile contract taşıyacak.
- İlk hedef 100 node değil, kaliteli 10 profile; sonra 20-30 profile’a telemetry ve gerçek test prompt’larına göre genişleme.
- Generic HTTP/Code/Set raw olarak agent’e açılmayacak; typed profile yoksa unsupported sayılacak.
- Knowledge database güncellemesi uygulama turunda yapılacak: yeni ADR eklenecek, `index.md`, `chat-workflow-generation`, `agent-service`, `n8n-registry` notları bu karara bağlanacak.
