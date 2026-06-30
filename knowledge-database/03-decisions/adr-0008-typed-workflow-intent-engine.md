# ADR-0008: Typed Workflow Intent Engine

Merkez: [[index]]

Durum: KARAR GECERLI ama implementasyon GERI ALINDI (parked).
Tarih: 2026-06-05 (karar), 2026-06-07 (revert).

## 2026-06-07 Durum Guncellemesi (ONEMLI)

Bu ADR'nin ilk implementasyon slice'i (2026-06-05'te baslayan
`apps/agent/src/agent/workflow_intent` paketi) **kullanici tarafindan geri
alindi**. Kullanici birkac gun projeye bakamadigi icin yarim kalan typed intent
engine degisikliklerini tamamen revert etti.

Mevcut repo gercegi (2026-06-07):

- `workflow_intent` paketinin kaynak `.py` dosyalari repoda **yok**. Geriye
  yalnizca `apps/agent/src/agent/workflow_intent/__pycache__/` icinde stale
  `.pyc` bytecode kalintilari (schemas, profiles, renderer, service, evals,
  __init__) var. Bu kalintilar import edilmiyor ve temizlenebilir.
- `create_workflow_from_intent` tool'u `factory.py`'de **kayitli degil**.
  `WorkflowIntent`/`workflow_intent` referansi hicbir kaynak `.py` dosyasinda
  gecmiyor (git'e hic commit edilmemis).
- Aktif workflow generation yolu yine **`create_workflow_from_plan`**
  (`WorkflowPlan` action graph compiler, [[adr-0005-workflow-spec-compiler]]).
  Desteklenen aksiyonlar: `gmail.send`, `sheets.row.append`,
  `sheets.read_rows`, `core.filter`.

Yani asagidaki "Ilk Kapsam" ve "Test Yaklasimi" bolumleri **hedeflenen plani**
anlatir; su an kodda karsiligi yoktur. Bu karar gelecekte yeniden uygulanmak
uzere park edilmistir. Yeniden baslarken: ya commit edilmemis kaynak kaybi
nedeniyle sifirdan yazilacak, ya da `.pyc` bytecode'dan kismi decompile ile
profile/yapilandirma cikarilmaya calisilacak. Bilinen sorun kaydi:
[[known-issues]].

## Karar

Workflow generation ana yolu raw n8n node JSON uretiminden typed
`WorkflowIntent` engine'ine tasinir. Agent kullanici istegini `inputs`, `steps`,
`edges` ve profile `kind` degerlerinden olusan niyet grafigi olarak uretir.
Engine bu intent'i onceden tanimli profile renderer'lari, registry
`typeVersion` bilgisi ve mevcut workflow validator pipeline'i ile n8n node ve
connection payload'una cevirir.

## Gerekce

Raw n8n JSON generation gercek dunya workflow isteklerinde modelin node
parameter, operation, connection shape ve expression detaylarini yanlis
uretmesine yol aciyor. Eski action compiler daha deterministik ama her yeni
aksiyon icin compiler'a case ekledigi icin genis n8n kapsami hedefinde
surdurulebilir degil.

Typed intent engine bu iki uc arasinda durur:

- Agent is niyetini ve data flow'u generative olarak secer.
- Engine node/resource/operation profillerini deterministic render eder.
- Expression string, node id/name, position ve nested connection shape agent'a
  birakilmaz.
- Unsupported profile n8n'e side effect yapmadan hata dondurur.

## Ilk Kapsam

Ilk slice `apps/agent/src/agent/workflow_intent` paketiyle basladi:

- `schemas.py`: `WorkflowIntent`, `IntentStep`, `IntentEdge`.
- `profiles.py`: ilk 10 profile icin static metadata registry; kind, kategori,
  node type, required/optional input, output contract ve side-effect bilgisi.
- `renderer.py`: profile render ve data ref validation.
- `service.py`: compile sonucunu mevcut validation/create/readiness akisina
  baglayan payload helper.
- `factory.py`: `create_workflow_from_intent` Pydantic AI tool kaydi.
- `prompt.py`: workflow generation default yolunu intent engine'e ceken
  talimatlar.

Ilk desteklenen profile kind'lari:

- `input.webhook_form`
- `trigger.schedule`
- `ai.generate_text`
- `gmail.message.send`
- `sheets.row.append`
- `sheets.range.read`
- `transform.map_fields`
- `transform.template_text`
- `condition.if`
- `http.call_api`

## Test Yaklasimi

Her profile eklemesi unit/golden test ile gelmeli. Ilk regression seti
`apps/agent/tests/test_workflow_intent.py` icinde:

- Teklif otomasyonu:
  `input.webhook_form -> ai.generate_text -> gmail.message.send`.
- Sheets append subgraph:
  `input.webhook_form -> transform.map_fields -> sheets.row.append`.
- Unsupported profile kind negative case.
- Unknown data ref negative case.

Bu testler compile sonucunu mevcut `validate_workflow_draft_payload` pipeline'i
ile de kontrol eder. Profile registry'nin ilk 10 kind listesi de test edilir.

Ilk offline eval contract akisi eklendi:

- Fixture: `apps/agent/evals/workflow_generation/proposal_email.json`.
- Validator: `src/agent/workflow_intent/evals.py`.
- CLI: `python apps/agent/scripts/run_workflow_intent_evals.py`.

Bu runner henuz live LLM cagirmaz; fixture contract'inin desteklenen profile
kind'lari, runtime input'lari, beklenen tool'u ve yasak tool/run davranisini
statik dogrular. Sonraki fazda bu fixture'lar agent run contract'ina
baglanacak.

## Sonuclar

`create_workflow_from_plan/spec` compatibility yolu olarak kalir. Raw
`create_workflow` yalniz explicit teknik/experimental fallback veya henuz
desteklenmeyen profile icin kullanilmalidir. Yeni platform/action eklemeleri
`spec_compiler.py` buyutmek yerine intent profile registry/renderer yapisina
eklenmelidir.

Ilgili notlar: [[new-engine-plan]], [[chat-workflow-generation]],
[[agent-service]], [[n8n-registry]].
