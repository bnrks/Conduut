# n8n Registry

Merkez: [[index]]

`packages/n8n-registry` n8n node bilgilerini ve workflow template'lerini agent
tool'lari icin hazirlayan lokal Python paketidir. Bu sistem klasik pgvector RAG
degil; su an tool-based knowledge yaklasimi kullaniliyor.

## Amaç

Agent'in workflow JSON uretirken node type string, typeVersion, credential tipi,
operation ve temel parameter bilgisini tahmin etmesini azaltmak.

## Ana Moduller

- `models.py`: `NodeInfo` ve `WorkflowTemplate` dataclass'lari.
- `loader.py`: `nodes.json` ve `templates.json` parse eder.
- `search.py`: keyword/alias tabanli node ve template aramasi yapar.
- `registry.py`: uygulama genelinde kullanilan `NodeRegistry` sinifi.

## Data Kaynaklari

- `data/templates.json`: n8n.io template API'sinden cekilmis workflow
  template'leri; repoda mevcut.
- `data/nodes.json`: n8n container cache'inden uretilen node schema dosyasi;
  gitignore'da.

Node schema yenileme:

```bash
python packages/n8n-registry/scripts/fetch_nodes.py
```

Template yenileme:

```bash
python packages/n8n-registry/scripts/fetch_templates.py --limit 200
```

## Runtime Yukleme

Agent startup'inda `apps/agent/src/registry.py` icinden
`registry.initialize_from_n8n(...)` cagrilir. Yukleme sirasi:

1. Explicit `nodes_path`.
2. Paket veya Docker sibling `data/nodes.json`.
3. n8n HTTP fallback.

Modern n8n'de `/types/nodes.json` endpoint'i auth istedigi icin HTTP fallback
bilincli olarak bos doner. Pratikte `nodes.json` dosyasinin uretilmis olmasi
beklenir.

## Agent Kurali

Agent system prompt'u lookup-first davranisi ister:

1. Bilinmeyen servis/node icin `search_n8n_nodes`.
2. Her node icin `get_node_schema`.
3. Kompleks workflow icin opsiyonel `find_workflow_template`.
4. Sonra `create_workflow` veya `update_workflow`.

`search_n8n_nodes` artik varsayilan olarak 20 node sonucu dondurur. Tool
opsiyonel `limit` alir; agent ilk arama yeterli degilse daha spesifik query ile
veya daha yuksek limit isteyerek tekrar arayabilir. Registry tarafinda limit
1-50 araligina clamp edilir, boylece tum `nodes.json` context'e basilmadan
ilgili aday havuzu genisletilebilir.

`loader.py` `keyParameters` cikarirken `displayOptions` gordugu her parametreyi
artik otomatik atmaz. `show/hide @version` kosullari latest/default node
version'a gore degerlendirilir; resource/operation gibi baska kosullara bagli
parametreler hala konservatif olarak disarida tutulur. Bu sayede
`@n8n/n8n-nodes-langchain.lmChatAnthropic` v1.3 gibi node'larda latest
`model` parametresi `resourceLocator` olarak schema'ya girer. `modes`,
`searchListMethod`, `loadOptionsMethod/loadOptions` ve default deger gibi
dinamik secim metadata'si kondanse edilerek agent'a tasinir. `search.py`
`exampleNode` uretirken resourceLocator default'larini n8n'in bekledigi
`{__rl, mode, value}` bicimine cevirir.

WorkflowSpec compiler pilotu registry'yi yalnizca lookup icin degil,
deterministic JSON uretimi icin de kullanir. Gmail on-demand compiler'i Webhook
ve Gmail node `typeVersion` degerlerini; Google Sheets -> Filter -> Gmail
compiler'i ise Webhook veya Schedule, Google Sheets, Filter ve Gmail
`typeVersion` degerlerini registry schema'sindan alir. Schema yoksa workflow
n8n'e yazilmaz ve tool acik hata dondurur. Bu davranis
[[adr-0005-workflow-spec-compiler]] icinde kayitlidir.

## Node-Specific Guidance

Registry bazi node'lar icin genel `keyParameters` bilgisinin otesinde
node-specific ornek dondurur. `n8n-nodes-base.set` / Edit Fields node'u icin
`exampleNode.parameters.assignments.assignments` dolu gelir; cunku n8n 1.121
Set node'da alan eklemek icin `mode/manual/options` tek basina yeterli degil,
field listesi `assignments.assignments` altinda olmalidir.

IF/Filter/Code node'lari da node-specific contract tasir. `if` ve `filter`
semalarinin `type=filter` parametresi ham `nodes.json` icinde nested rule
semasini aciklamadigi icin `get_node_schema`, dolu
`conditions.conditions`, `combinator`, filter options ve
`operator={type, operation}` iceren canonical bir `exampleNode` dondurur.
`code` node'unda ise `jsCode`, `displayOptions.language` arkasinda kaldigi icin
genel kondanse extractor tarafindan elenebilir; node-specific guidance bunu
`keyParameters` ve ornege geri ekler. JavaScript'in exact enum degeri
`javaScript`'tir; `javascript` gecersizdir. Tek-yollu satir elemede agent'a
`Filter`, gercek iki branch gerektiginde `IF`, ancak kosul node'lari yetersizse
`Code` kullanmasi onerilir.

Ilgili notlar: [[agent-service]], [[chat-workflow-generation]].

## Workflow/Node Cards V2 (2026-07-23)

[[adr-0020-workflow-node-cards-assurance-v2]] ile registry klasik tek-schema
lookup'undan iki asamali card retrieval'a genisletildi:

- `cards.py` raw community workflow'u modele tasimadan isim/ozet/intent,
  kontrollu keyword, service/capability, topology/node role, credential type,
  identity/idempotency, side-effect/risk, cardinality/rerun invariant ve
  compatibility metadata'si cikarir. Code govdesi, embedded prompt, pinned data,
  credential id/name ve workflow JSON tool sonucuna girmez; prompt-injection
  benzeri community aciklamalari temizlenir.
- `loader.py` node contract'ini exact
  `type + typeVersion + resource + operation` baglaminda uretir. Ayni node
  icindeki birden fazla operation selector'i resource `displayOptions`'ina gore
  birlestirilir. Bu duzeltme Gmail v2.1 `message.send` contract'inin yanlislikla
  ilk draft selector'iyle kaybolmasini onler. Dynamic UI `hide` kosulu
  (`sheetName` bos gibi) statik operation parametresini silmez.
- `get_node_contract` ambiguous istekte ilk schema'yi secmez;
  `availableResources`/`availableOperations` dondurur. Contract; required/
  optional nested paths, enum/default, credential, input/output cardinality,
  branch/lineage, side-effect/retry/identity, dynamic resolver, valid/invalid
  ornek, pitfall ve validator rule ID'lerini tasir.
- `fts.py` local SQLite FTS5 indexidir. Workflow search compact sonuc ve
  service/capability/risk metadata filter'i verir; detail ayri lookup'tur.
- `scripts/build_cards.py` mevcut `nodes.json + templates.json` uzerinden
  `workflow_cards.jsonl`, operation-card `node_cards.jsonl`,
  `retrieval.sqlite`, `registry_manifest.json` uretir. Manifest artifact ve
  node-schema SHA-256 hash'leri ile opsiyonel n8n version'ini tasir.
- `fetch_templates.py` resume edilebilir. Untrusted raw snapshot
  `packages/n8n-registry/generated/raw/` altinda kalir; agent Docker data
  yuzeyine alinmaz.

### Community corpus refresh ve runtime readiness (2026-07-23)

Community ingestion artik uc kullanim seklini destekler:

```powershell
# Hedefli corpus parcasi
python packages/n8n-registry/scripts/fetch_templates.py --all --query "cold email outreach Gmail Google Sheets status" --resume

# Ilk N listing
python packages/n8n-registry/scripts/fetch_templates.py --limit 500 --resume

# Tum Community corpus'unu kaldigi yerden indir
python packages/n8n-registry/scripts/fetch_templates.py --all --resume

# Sanitize card'lari ve FTS index'i mevcut n8n surumune gore yeniden uret
python packages/n8n-registry/scripts/build_cards.py --n8n-version 1.121.3
```

`--all` Community API'nin `totalWorkflows` degerini izler; `--query` API'nin
server-side `search` filtresini kullanir. Detail endpoint'i 400/404 veren
template ID'leri bos/yaniltici card'a donusturulmez, manifest `failedIds`
alanina yazilir. Resume sirasinda eski sifir-node card'lar atomik olarak
temizlenip yeniden denenir.

Community detail response'undaki dis `workflow` nesnesi node katalog ozeti,
icteki `workflow.workflow` ise native n8n JSON'udur. Extractor native katmani
acar; aksi halde card node count dolu gorunurken `nodeTypes`, services ve
topology bos kalir. Bazi Community template'leri parametreleri bosaltilmis
native JSON dondurur. Bu durumda exact operation uydurulmaz; node adi + node
type uzerinden inferred action/write-back role, capability, side-effect ve risk
uretilir. Exact parametre otoritesi yine Node Card'dir.

`build_cards.py` checked-in sanitize seed corpus ile raw snapshot'i ID bazinda
birlestirir; raw kayit daha guncelse seed'i override eder. Boylece incremental
raw snapshot eski seed card'lari dusurmez.

2026-07-23 ilk hazir corpus snapshot'i Community tarafindaki 10.908 listing'in
hepsini degil, hedefli H1 aramasi ile ilk 500 listing'i kapsar: 497 gecerli
Workflow Card, 6 failed detail ve 0 sifir-node card. Current n8n `1.121.3`
schema refresh'i 7.727 operation-aware Node Card uretmistir. H1 sorgusunda
template `4214` (`Cold Email Outreach with Gmail and Google Sheets Status
Tracking`) FTS sonucunda birinci gelir; card 6 node, 5 edge,
`send_email/read_sheet/update_sheet_rows/scheduled_run`, action ve write-back
rolleri ile `high` risk tasir. Corpus generated/ignored artifact'tir; buyutme
offline ve incremental yapilir, raw snapshot agent/model yuzeyine acilmaz.

Agent tool sirasi artik `search_workflow_cards(limit=10)`, en fazla uc
`get_workflow_card`, sonra exact `get_node_contract` ve native JSON
create/update'tir. Eski `find_workflow_template` model yuzeyinden kalkti;
registry compatibility alias'i sanitize card dondurur.
