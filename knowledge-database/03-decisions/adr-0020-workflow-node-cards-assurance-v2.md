# ADR-0020: Workflow/Node Cards ve Deterministik Assurance V2

Merkez: [[index]]

## Durum

Kabul edildi ve implemente edildi (2026-07-23). Native n8n JSON yuzeyi
[[adr-0010-json-surface-repair-normalizer]] ile korunur; bu karar retrieval
bilgisini ve correctness otoritesini ayri fakat ayni node kontratlarina bagli
iki katman olarak ekler. V1 assurance'in devamidir:
[[adr-0019-workflow-assurance-v1]].

## Baglam

Agent node adini bulsa bile exact `typeVersion + resource + operation`
baglamindaki nested parametreleri, item sekillerini ve side-effect
postcondition'larini yeterince bilmiyordu. Community template'leri pattern
kaynagi olabilir, fakat raw JSON; secret, pinned data, Code govdesi, embedded
prompt, eski node version'i ve prompt-injection riski tasir. Ayrica n8n
`status=success`, Gmail receipt veya sandbox gecisi tek basina Sheet
write-back'i ve ikinci-run idempotency'sini kanitlamaz.

## Karar

1. `packages/n8n-registry` community workflow'lari once sanitize eder ve
   `WorkflowCard` uretir. Raw snapshot `generated/raw/` altinda kalir; agent
   image/data yoluna ve tool sonucuna girmez. Search sonucu compact card'dir;
   agent top-10 icinden en fazla uc detail card okuyabilir.
2. Node bilgisi `nodeType + typeVersion + resource + operation` anahtarina
   kosullanan contract card'dir. Loader ayni node icindeki tum resource'a bagli
   `operation` selector'larini ve `displayOptions` kosullarini degerlendirir.
   Ambiguous lookup ilk contract'i secmez; gecerli resource/operation
   seceneklerini dondurur.
3. Artifact build komutu
   `python packages/n8n-registry/scripts/build_cards.py` olur. Ciktilar
   `workflow_cards.jsonl`, operation-card bazli `node_cards.jsonl`,
   `retrieval.sqlite` ve hash/version bilgili `registry_manifest.json`'dir.
   Generated dosyalar gitignore'dadir. `CONDUUT_WORKFLOW_CARD_RETRIEVAL_MODE`
   `auto|observe|hybrid|enforce` kabul eder; `auto` production'da enforce,
   diger ortamlarda observe olur. Enforce modunda hem manifest `n8nVersion`
   degeri hem de `CONDUUT_N8N_VERSION` acikca verilmelidir; `nodes.json`
   dahil eksik, bozuk, hash uyumsuz veya surum uyumsuz artifact startup'i
   durdurur. Observe fallback readiness'i gecemeyen card corpus'unu package
   default path'inden tekrar yuklemez; card retrieval kapanir ve legacy registry
   yuzeyi acik warning ile devam eder.
4. Agent lookup sirasi `search_workflow_cards(limit=10) ->
   get_workflow_card(max=3) -> search_n8n_nodes/get_node_schema ->
   get_node_contract(exact) -> create/update` olur. Legacy
   `find_workflow_template` model tool yuzeyinden kalkar; registry alias'i raw
   workflow vermeden geriye uyumluluk icin kalir.
5. Google Sheets write build'i managed connection ile gercek header satirini
   cozer. `documentId`, `sheetName`, `columns.value`, `matchingColumns` veya
   live header uyusmazsa workflow n8n'e yazilmaz. Kritik Gmail/Sheets
   side-effect operation contract'i unsupported/ambiguous ise build fail-closed
   olur.
6. `OracleContract` kaydedilecek/execute edilecek workflow JSON'u, deterministic
   assurance analizi ve exact node contract hash'lerinden uretilir. Action,
   write-back, identity, cardinality, expected receipt, postcondition, coverage
   ve claim scope ayni typed modelde tutulur.
7. Sandbox `ProbeEvidence` uretir. Contract-covered yolun basari kararini LLM
   judge vermez. Basit Filter/IF status-loop'unda projected write-back filtre
   state'ine uygulanir; ikinci tur icin `0 eligible / 0 action / 0 write-back`
   kanitlanamazsa preview gecmez.
8. Execution assessment immutable `workflowData` snapshot'ini tercih eder.
   Snapshot yoksa current workflow yalniz context fallback'tir ve whole-run
   `verified` acamaz. Gmail her item icin `id + SENT` receipt ister. Sheets
   write-back managed `read_range` ile bounded `A1:ZZ500` okumasinda identity
   ve beklenen degeri yeniden gormeden `run_verified` acmaz.
9. Derived, PII-bounded `ExecutionEvidenceEnvelope` user-scoped
   `execution_evidence` koleksiyonuna `executionId + evidenceHash` anahtariyla
   append-only yazilir. Ayni kanit yeniden inspect edilirse yeni kayit
   uretilmez. n8n raw execution source-of-truth olmaya devam eder.
10. Partial side effect sonrasi otomatik retry/compensation ilk kosuda durur;
    reconciliation preview ve acik kullanici onayi gerekir. Final claim gate'e
    ek olarak runner cümle bazli stream buffer kullanir; kaniti asan cümle
    token olarak yayinlanmadan deterministic guvenli ozetle degisir.

## V1 Kapsami

Tam contract/assurance odagi Google Sheets, Gmail, Filter, IF, Code,
Set/Edit Fields ve Merge'dir. Diger side-effect node'lar desteklenene kadar
kritik yolda fail-closed veya partial coverage kalir. Harici vector database ve
embedding yoktur; SQLite FTS5 + metadata filter baseline'i kullanilir.

## Kabul

- Registry card/contract, sanitization, FTS ve ambiguity testleri gecmelidir.
- Contextless execution `verified` olamaz.
- `2 action / 0 write-back` `partial` kalir ve otomatik retry yapamaz.
- Sheets write-back remote read ile dogrulanmadan whole-run claim acilmaz.
- Read-after-write expected row resolver dinamik n8n expression'larini literal
  metin olarak karsilastirmaz; write node'un immutable execution output'undaki
  resolved kolon degerini kullanir. Configured sabit degerler output'a gore
  gevsetilmez.
- Claim policy ihlalinde output validator model retry baslatmaz. Stream ve final
  gate ayni deterministic safe evidence summary'yi kullanir; dahili critic
  metni ve reddedilen ara taslak kullanici mesaj yuzeyine cikmaz.
- H1 sandbox'i `2/2/2`, identity/value esligi ve projected `0/0/0` kaniti
  istemelidir. Canli ilk/ikinci run kabulü ayrica acik kullanici onayi ister;
  kod/test implementasyonu canli H1'i kendiliginden "gecti" yapmaz.

## Ilk corpus ve runtime devreye alma notu (2026-07-23)

Generated card artifact'lerinin tek fiziksel kaynagi
`packages/n8n-registry/data` olarak kalir. Local agent bu yolu repo
ancestor'larindan cozer; Docker build ayni artifact'leri `/app/data` altina
kopyalar. Compose n8n ve manifest compatibility default'u `1.121.3` olarak
birlikte pinlenir.

Ilk kontrollu snapshot 497 gecerli Community Workflow Card ve current schema'dan
7.727 Node Card icerir. H1 template `4214` hedefli retrieval'da top-1'dir.
Community corpus'unun tamami tek seferde runtime startup'inda cekilmez;
`fetch_templates.py --all --resume` ile offline/incremental indirilir ve
`build_cards.py --n8n-version 1.121.3` ile immutable manifest/index yeniden
uretilir. Erişilemeyen detail ID'leri failed olarak kaydedilir; bos card kabul
edilmez. Community detail envelope'u native `workflow.workflow` katmanina
acilir; parametresi bosaltilmis template'lerde exact operation uydurulmadan
node type/name kaynakli inferred capability/role/risk tutulur. Build seed
sanitize corpus'u raw snapshot ile ID bazinda merge eder.

Ilgili notlar: [[n8n-registry]], [[agent-service]],
[[chat-workflow-generation]], [[scenario-h1-cold-outreach-status]].
