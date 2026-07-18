# ADR-0019: Workflow Assurance V1

Merkez: [[index]]

## Durum

Kabul edildi ve implemente edildi (2026-07-16). [[adr-0010-json-surface-repair-normalizer]]
ile korunan native n8n JSON yuzeyinin uzerine, M1'e ozel olmayan ortak bir
dogrulama zinciri ekler. Sandbox karari icin bkz. [[adr-0014-workflow-sandbox-test]],
servis akisi icin bkz. [[agent-service]].

## Baglam

Bir workflow'un n8n tarafinda `success` gorunmesi, is sonucunun dogru oldugunu
kanitlamiyordu. Action node'u girdiyi tuketebiliyor, write-back yanlis veya bos
identity ile calisabiliyor, HTTP transport hatasi execution sonucundan kopuk
kalabiliyor ve agent elindeki kanittan daha guclu bir basari cumlesi
kurabiliyordu. M1 tekrarlarinda ayni semantik hata ailesi birden cok noktasal
duzeltme gerektirdi; yalniz prompt veya senaryo-ozel repair kurali kalici sinir
olusturmadi.

## Karar

Assurance zinciri su sirayla calisir:

`Static semantic guard -> Sandbox V2 -> Execution assessment -> Evidence-gated claim`

1. `agent/assurance/` node contract katalogu, canonical SHA-256 fingerprint,
   workflow plan/finding modelleri ve statik semantic analiz saglar. Cycle,
   trigger back-edge, IF combinator, kesin dataflow kaybi ve Sheets identity
   sorunlari deterministik olarak ele alinir. Desteklenmeyen contract'lar
   coverage finding'i uretir.
2. Sandbox action node'larini `disabled=true` pass-through yapmak yerine
   deterministik Gmail/Sheets probe node'larina cevirir. Probe output shape'i
   gercek action'a benzer; `__conduut_probe` ledger'i action/write-back
   sayilarini, required alanlari ve identity riskini PII-safe bicimde toplar.
3. Workflow metadata'si assurance version, fingerprint, static/sandbox status,
   coverage ve finding'leri saklar; eski `test_status`/`test_findings` alanlari
   gecis icin mirror edilir. Fingerprint degisince eski sandbox kaniti gecersiz
   olur.
4. Run sonucu raw n8n `status` alanini korurken `functional_status`,
   `assessment` ve `claimable_outcome` ekler. HTTP `success=true` yalniz
   `verified` ve `no_action` icin kullanilir. Action olup zorunlu write-back
   yoksa `partial` ve `duplicate_risk=true` olur; eksik contract coverage
   `verified` uretemez.
5. Agent tool sonuclari evidence ledger'a yazilir. Final cevap claim seviyesi
   kaniti asarsa once `ModelRetry`, tekrarinda assessment'tan uretilen guvenli
   deterministik ozet kullanilir. LLM yalniz dildeki claim'i siniflandirir;
   fonksiyonel basari kararini vermez.
6. Dashboard manual ve batch side-effect run'larindan once safe preview alir.
   Firestore'daki tek kullanimlik token user id, workflow fingerprint ve input
   hash'ine baglidir; 10 dakika sonra, kullanildiginda veya workflow/input
   degistiginde reddedilir. Chat `execute_workflow` da preview sonucunu
   kullaniciya onaylatmadan tokeni tuketip gercek side effect'e gecemez.
   Production verisine otomatik canary gonderilmez.
7. Scheduled workflow'larda ilk action oncesine identity guard enjekte edilir.
   Bos/duplicate identity action'dan once durur; sifir aday temiz `[]` ile
   `no_action` yolunu korur. Activation static/sandbox assurance gate'inden
   gecmeden acilmaz.
8. Chat preview onayi model metnine veya assistant mesajindaki gecici tool
   sonucuna emanet edilmez. `user_input_request` attachment'i opaque
   `requestId`, `requestKind=workflow_run_approval` ve `workflowId` tasir; web
   cevabi bunlari `user_input_response` olarak ayri gonderir ve chat route
   authenticated user mesajina ekler. Runner yalniz son user mesajindaki
   structured karari AgentDeps'e alir. Token modele aciklanmadan, server
   tarafinda workflow'a gore tek kez tuketilir; eski conversation history'deki
   onaylar yeniden oynatilmaz. Stale/expired/consumed token ve sandbox repair
   butcesinin bitmesi ayni tur icin terminal `awaiting_user_input` siniridir.
9. Managed Google connection readiness ile custom API credential kutuphanesi
   ayri otoritelerdir. `list_credentials` yalniz custom/service API
   credential'larini listeler ve Gmail/Sheets baglantisinin kopuk olduguna
   kanit sayilamaz; workflow node'lari icin `analyze_workflow_readiness`
   otoritedir.
10. Preview approval ancak run input'u metadata schema'sina gore dogrulandiktan
    sonra tuketilir. Firestore transaction'i fingerprint/input hash eslesmeden
    tokeni silmez; boylece validation veya stale-input hatasi side effect
    baslamadan onayi yakmaz. Activation runtime-input workflow'larda bos `{}`
    yerine `None` ile sample-input sandbox yolunu kullanir. Credential nedeniyle
    build sirasinda test edilemeyen workflow'un ilk run pretest'i de sample
    yerine gercek run payload'unu kullanir.

## Rollout

`CONDUUT_WORKFLOW_ASSURANCE_MODE=observe|hybrid|enforce` kullanilir; varsayilan
`hybrid`'dir. Hybrid mod kesin cycle/dataflow/identity/stale-preview sorunlarini
bloklar; desteklenmeyen contract ve yoruma acik bulgular coverage'i dusurur.
`observe` semantik bloklari geri alabilir, fakat HTTP hata semantigi, PII-safe
assessment ve kanittan yuksek claim korumasi kalir.

## Sinirlar

- Exactly-once/outbox V1 disindadir. Gmail basarili, Sheets basarisizsa tum
  workflow otomatik tekrar edilmez; sonuc `partial` ve duplicate riski olur.
- E-posta veya isim kendiliginden unique sayilmaz; identity kullanici tarafindan
  secilmeli ve safe preflight'ta dogrulanmalidir. Row-number fallback yoktur.
- Contract katalogu ilk etapta IF, Code, Set/Edit Fields, Merge, Gmail Send ve
  Google Sheets read/update ailelerine odaklanir. Diger node'lar coverage'i
  `partial` yapar.

## Ilgili kod ve testler

- `apps/agent/src/agent/assurance/`
- `apps/agent/src/agent/sandbox.py`, `sandbox_nodes.py`
- `apps/agent/src/agent/tools/execution.py`, `workflow_runner.py`
- `apps/agent/src/agent/workflow_preview.py`, `store/workflow_previews.py`
- `apps/agent/src/agent/claim_policy.py`
- `apps/agent/src/agent/history.py`, `routes/chat.py`
- `apps/web/src/components/chat/clarification-panel.tsx`, `lib/chat/sse.ts`
- `apps/agent/src/routes/workflows.py`
- `apps/web/src/app/(dashboard)/dashboard/workflows/page.tsx`
- `apps/agent/tests/test_workflow_assurance.py` ve ilgili assurance testleri

M1 fonksiyonel oracle'i ve tekrar kosusu icin bkz.
[[scenario-m1-sheets-filter-email]].
