# ADR-0009: WorkflowGraph IR ve Genel Graph Compiler

Merkez: [[index]]

## Durum

Kabul edildi (2026-06-10). [[adr-0005-workflow-spec-compiler]]'in dogal
genellestirmesi; onu gecersiz kilmaz, superset olur.

## Baglam

[[adr-0005-workflow-spec-compiler]] ile gelen `WorkflowPlan`/`WorkflowSpec`
compiler'i sadece Gmail, Google Sheets ve filter action'larini destekliyordu.
n8n'in en yogun kullanilan dugumleri (HTTP Request, AI Agent + sub-node'lar,
Code, Edit Fields/Set, IF, Switch, Merge) compiler kapsami disindaydi. Bu tur
istekler `create_workflow` raw n8n JSON fallback'ine dusuyor, agent uzun JSON
uretmeye calisirken `MAX_MODEL_REQUESTS` limitine takilip cokuyordu (orn. "AI
agent iceren workflow" denemesi tamamlanamadi). Ozellikle AI Agent'in `main`
disi baglanti portlari (`ai_languageModel`, `ai_tool`, `ai_memory`) elle
uretilmesi cok zor.

Beklenti: agent yine **basit bir sema** yazsin; arkada onu tam calisan n8n JSON
worklfow'a ceviren genel, genisletilebilir bir semantic katman olsun.

## Karar

`WorkflowPlan`'in dar, lineer action-listesi yerine bir **graph IR**
(`WorkflowGraph`) ve tek bir **genel compiler** (`graph_compiler.py`)
benimsenir. Dort temel tasarim karari:

1. **Hibrit cozunurluk:** curated declarative `Block` registry (saglam, ozenli)
   + bilinmeyen dugumler icin generic `n8n:<exact-type>` fallback. Compiler her
   iki yolda da boilerplate'i **her zaman** kendisi sahiplenir.
2. **Rol etiketli node IR + compiler port cikarimi:** agent dugumleri `kind` ve
   (sub-node icin) `attached_to`/`role` ile yazar; basit `edges` listesi `on`
   ipucu tasir (`true`/`false`). Compiler kesin n8n portlarini (`main`,
   true/false `main[0]`/`main[1]`, `ai_languageModel`, `ai_tool`, ...) cikarir.
   AI sub-node'lari icin baglanti **ters yondedir** (model -> agent), bunu da
   compiler kurar.
3. **Declarative data registry:** her curated dugum bir `Block` verisi
   (`kind`, `n8n_type`, fallback `type_version`, `static` paramlar, `ParamRule`
   eslemeleri, `output_ports`, `sub_ports`, opsiyonel `builder`). Yeni populer
   dugum eklemek = yeni `Block` girdisi (+ gerekiyorsa adli builder), yeni
   compiler kodu degil. `ROLE_PORTS` global haritasi rol->port varsayilanini
   verir, generic fallback'te de gecerlidir.
4. **Hibrit katalog kesfi:** sistem prompt'unda curated `kind` kataloğu hep
   bulunur (yaygin yol icin ekstra round-trip yok); uzun kuyruk icin mevcut
   `search_n8n_nodes` -> `get_node_schema` -> `n8n:<type>` akisi kullanilir.

### IR sekli (`schemas.py`)

- `GraphNode`: `{id, kind, name?, params, attached_to?, role?}`.
- `GraphEdge`: `{source, target, on?}`.
- `WorkflowGraph`: `{trigger: GraphNode, nodes: [...], edges: [...], inputs: [...]}`.
- `WorkflowPlan` artik bu graph'in lineer ozel hali (superset iliskisi).

### Compiler hatlari (`graph_compiler.py`)

- **resolve:** her `kind` -> curated `Block` veya generic resolver.
- **params/builders:** `ParamRule` ile duz eslemeler + zengin paramlar icin
  adli builder'lar (`set_fields`, `if_conditions`, `filter_conditions`, `code`,
  `http_request`, `ai_agent`, `chat_model`, `gmail_send`, `sheets_read`,
  `sheets_append`).
- **topology:** `edges` + `output_ports` -> `main` baglantilari; `attached_to`
  + rol -> ters yonlu `ai_*` baglantilari.
- **boilerplate:** `typeVersion` registry'den (yoksa block fallback), pozisyon
  auto-layout, webhook `path`/`webhookId`, resourceLocator (`__rl`), expression
  sozdizimi.
- **expression ref'leri:** `{ref:'input.x'}`, `{ref:'item.y'}`, `{ref:'json.y'}`
  ve yeni `{ref:'node.<id>.field'}` (iki gecisli isim cozumu ile).
- **runtime inputs:** mevcut `_validated_runtime_workflow` yeniden kullanilir;
  Gmail `to/subject/message` runtime alanlari korunur.
- **validation:** mevcut `validate_workflow_payload` -> hata olursa structured
  error + fallback ipucu; readiness ile eksik credential attachment'lari.

### Yeni tool ve tercih sirasi

Yeni `create_workflow_from_graph` tool'u eklenir ve **tercih edilen** builder
olur. Sira: `create_workflow_from_graph` -> `create_workflow_from_plan`
(lineer Gmail/Sheets/filter) -> raw `create_workflow`/`update_workflow` (son
care). `WorkflowPlan`/`WorkflowSpec` compiler'i geriye donuk uyumluluk icin
korunur.

### Ilk curated kapsam

Trigger: `manual`, `webhook`/`on_demand`, `schedule`, `chat`. Core:
`http_request`, `set`/`edit_fields`, `if`, `filter`, `code`, `merge`, `no_op`.
AI: `ai_agent`, `openai_chat`, `anthropic_chat`, `memory_buffer`. Entegrasyon:
`gmail.send`, `sheets.read_rows`, `sheets.row.append`.

## Sonuclar

- Agent artik AI Agent dahil populer dugumler icin uzun JSON yazmak zorunda
  degil; cokme (max request) riski belirgin azalir.
- Deterministik compiler golden testlerle dogrulanir (`test_graph_compiler.py`:
  http linear, if-branch, AI agent port wiring, set fields, generic fallback,
  node ref, hata yollari).
- Yeni dugum eklemek dusuk maliyetli (data girdisi). Generic fallback uzun
  kuyrugu best-effort kapsar; validation hatali ciktiyi agent'a geri bildirir.
- 2026-06-10 canli test bulgusu: agent AI task'inde `openai_chat`'i ai_agent'a
  baglamak yerine bagimsiz ana-node yazdi; chat model `main` akista calismadigi
  icin AI hic uretmedi, Gmail bos mail atti. Duzeltme: `Block.sub_only` bayragi
  (chat model/memory/tool) + compiler guard (sub-node ana akista/edge'de
  gorulurse `WorkflowGraphCompileError`) + prompt'ta "AI/LLM = ai_agent zorunlu"
  kurali. Test: `test_chat_model_as_main_node_is_rejected`.
- Sinirlamalar (V1): chat-model `model` resourceLocator basit `list` modunda;
  `sheets.row.append` graph modunda auto Set uretmez (gerekiyorsa once `set`);
  generic sub-node portu `ROLE_PORTS` varsayilanina dayanir. Bunlar iteratif
  iyilestirilecek.

## Ilgili

- [[adr-0005-workflow-spec-compiler]] — daraltilmis IR/compiler temeli.
- [[adr-0006-platform-capability-layer]] — n8n-bypass platform action'lari.
- [[adr-0008-typed-workflow-intent-engine]] — park edilmis alternatif yol.
- [[agent-service]], [[n8n-registry]], [[chat-workflow-generation]].
