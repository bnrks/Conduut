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

## Node-Specific Guidance

Registry bazi node'lar icin genel `keyParameters` bilgisinin otesinde
node-specific ornek dondurur. `n8n-nodes-base.set` / Edit Fields node'u icin
`exampleNode.parameters.assignments.assignments` dolu gelir; cunku n8n 1.121
Set node'da alan eklemek icin `mode/manual/options` tek basina yeterli degil,
field listesi `assignments.assignments` altinda olmalidir.

Ilgili notlar: [[agent-service]], [[chat-workflow-generation]].
