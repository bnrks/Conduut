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
   `verified` uretemez. Bununla birlikte node-specific runtime effect verifier
   gercek side effect'i kanitlarsa `action_verified` ara claim seviyesi
   kullanilir: Gmail `message.send` icin basarili node run'i yaninda non-empty
   message `id` ve `labelIds` icinde `SENT` zorunludur. Bu seviye "mail
   gonderildi" iddiasini destekler, "tum workflow dogrulandi" iddiasini
   desteklemez; `functional_status=needs_attention` ve partial coverage korunur.
5. Agent tool sonuclari evidence ledger'a yazilir. Final cevap claim seviyesi
   kaniti asarsa once `ModelRetry`, tekrarinda assessment'tan uretilen guvenli
   deterministik ozet kullanilir. LLM yalniz dildeki claim'i siniflandirir;
   fonksiyonel basari kararini vermez.
   Claim uyumlulugu duz bir sayisal merdiven degildir: `no_action` kaniti action
   claim'ini, `action_verified` kaniti da whole-run claim'ini acamaz. Acik
   compatibility matrix kullanilir. `action_verified` evidence kaydi effect
   turunu da tasir (`gmail_message_sent`); Gmail kaniti Sheets/status update
   claim'ini acamaz. Bu effect-scope `run_verified` icin de gecerlidir: whole-run
   claim'i acik olsa bile spesifik action claim'i ayni run'da kayitli effect'i
   gerektirir. Final cevap yalniz ayni turdaki en son execution/inspect
   evidence kaydiyla yetkilendirilir; eski bir run'in action kaniti daha yeni
   `no_action` veya baska execution sonucunu override etmez.
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
11. Sandbox semantic guard yalniz action sinirindaki bos degeri kontrol etmez;
    covered action'a kadar calismis tum upstream ancestor output'larini tarar.
    Structured `undefined`/`null`/missing placeholder satirlari ve resolve
    olmamis n8n expression'lari, sonraki AI adimi bunlari duzgun gorunen fallback
    metne cevirse bile side effect oncesinde deterministik `needs_attention`
    uretir. Finding node adlariyla sinirlidir; business payload loglanmaz.
12. Gmail probe resolved `emailType` degerini de ledger'a alir. LLM judge,
    formatted/styled digest veya newsletter niyetini delivery mode ile
    karsilastirir; `emailType=text` icinde ham Markdown'i rendered HTML basarisi
    saymaz. Gmail normalizer eski `bodyContentType=text/html` girdisini
    `emailType=html` olarak korur.
13. Google Sheets `append` artık unsupported/disabled action olarak geçmez.
    `defineBelow` mapping değerleri Set probe assignment'larına çevrilir;
    `autoMapInputData` için incoming alanlar korunur. Ledger kolon listesini ve
    satırın tamamen boş olup olmadığını PII-safe şekilde denetler. Yalnız
    `coverage=full` sandbox sonucu `sandbox_passed` evidence üretir; partial
    coverage bir başarı iddiasını açmaz.
14. Aktivasyon execution kanıtından ayrıdır. `activate_workflow` yalnız
    `workflow_activated` evidence kaydeder ve `run_verified=false` döner.
    Claim policy workflow'un aktif olduğunu söylemeye izin verir; gerçek bir
    execution/effect kanıtı olmadan Sheet'e veri yazıldığı veya yazılacağı
    iddiasına izin vermez. Bu sınırın canlı kaynağı M3'tür:
    [[scenario-m3-webhook-http-sheets]].

15. IF v2+ koşulları side effect öncesinde fail-closed doğrulanır.
    `parameters.conditions.conditions` dolu bir rule listesi olmalı ve her
    rule `operator={type, operation}` nesnesi taşımalıdır. n8n'in sessizce
    kabul edip yanlış branch'e yönlendirebildiği `operator="equals"` gibi string
    şekiller build pipeline'da `ModelRetry` ile reddedilir.
16. Çoklu-item akışlarında action parametrelerinin item lineage'i korunur.
    Side-effect node'u item-scoped (`$json` / `$('Node').item`) alanlarla aynı
    anda doğrudan non-trigger predecessor için `$('Node').first()` kullanırsa static
    assurance bunu blocking `side_effect_direct_first_reference` finding'i sayar.
    Böylece farklı AI çıktılarının bütün alıcılarda ilk item ile ezilmesi gerçek
    gönderimden önce durur; singleton trigger referansları kapsam dışında kalır.
17. Sandbox, güvenle çözülebilen tek-rule string `equals` IF koşullarında gerçek
    branch output'unu predicate ile karşılaştırır. True branch'te eşleşmeyen veya
    false branch'te eşleşen item görülürse side-effect preview/onay aşamasına
    geçmeden `needs_attention` üretir. Karmaşık veya tip semantiği belirsiz
    predicate'ler yanlış pozitif üretmemek için bu dar runtime audit'in dışındadır.
18. Native JSON filtrelemesi agent-facing schema ve build validation'da birlikte
    fail-closed korunur. Tek-yollu elemede `Filter` tercih edilir ve Filter v2+
    IF ile ayni non-empty rule/operator-object kontratini tasir. Code v2'ye
    fallback edilirse exact `language="javaScript"` ile dolu `jsCode` gerekir;
    `javascript` gibi n8n UI display condition'ini bozan enum degerleri workflow
    yazilmadan reddedilir. Registry IF/Filter icin canonical nested condition,
    Code icin contextual extractor'dan dusen `jsCode` ornegini acikca dondurur.
    Condition rule'unda `leftValue`, binary operator'larda ayrica `rightValue`
    gerekir; unary empty/existence/boolean operator'lari sag operandsiz kalabilir.

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
  Google Sheets read/update/append ailelerine odaklanir. Diger node'lar coverage'i
  `partial` yapar.
- Runtime IF predicate audit'i V1'de yalnız tek-rule, doğrudan `$json` string
  `equals` koşullarını kapsar; karmaşık expression, çoklu rule ve diğer operator
  aileleri static shape validation ile korunur fakat branch semantiği replay
  edilmez.

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

## V2 ile genisleme (2026-07-23)

Bu ADR'nin static/sandbox/execution/claim zinciri korunur; correctness
otoritesi typed shared `OracleContract`, operation-aware Node Card hash'leri,
immutable execution evidence, Sheets read-after-write ve sentence-buffered
stream claim gate ile genisletilmistir. Full contract-covered sandbox yolunda
LLM judge basari karari vermez. Partial side effect sonrasi ilk real run'dan
itibaren auto-retry kapanir. Ayrintili karar:
[[adr-0020-workflow-node-cards-assurance-v2]].
