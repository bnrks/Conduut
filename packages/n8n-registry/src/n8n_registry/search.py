"""Node ve template arama + şema çıkarımı."""

from .models import NodeInfo, WorkflowTemplate

# Alias: kullanıcı bu kelimeleri yazarsa hangi node type'ları gösterilsin
_NODE_ALIASES: dict[str, list[str]] = {
    # Email
    "email": ["gmail", "microsoftoutlook", "smtp", "imap", "emailsendsmt"],
    "mail": ["gmail", "microsoftoutlook", "smtp", "imap"],
    "send email": ["gmail", "microsoftoutlook", "smtp"],
    # Spreadsheets
    "sheet": ["googlesheets", "airtable", "notion"],
    "spreadsheet": ["googlesheets", "airtable"],
    "excel": ["microsoftexcel", "googlesheets"],
    # Database
    "database": ["postgres", "mysql", "mongodb", "redis", "supabase"],
    "db": ["postgres", "mysql", "mongodb", "redis"],
    "sql": ["postgres", "mysql", "microsoftsql"],
    # Messaging
    "message": ["slack", "discord", "telegram", "twilio"],
    "chat": ["slack", "discord", "telegram"],
    "notify": ["slack", "discord", "telegram", "gmail"],
    "notification": ["slack", "discord", "telegram", "gmail"],
    # Files
    "file": ["googledrive", "dropbox", "s3", "ftp", "readwritefile"],
    "storage": ["googledrive", "dropbox", "s3"],
    # Triggers
    "timer": ["scheduletrigger"],
    "schedule": ["scheduletrigger"],
    "cron": ["scheduletrigger"],
    "trigger": ["scheduletrigger", "webhook", "manualtrigger"],
    # HTTP
    "http": ["httprequest"],
    "api": ["httprequest"],
    "request": ["httprequest"],
    "fetch": ["httprequest"],
    "rest": ["httprequest"],
    # Code/logic
    "code": ["code"],
    "function": ["code"],  # eski adı "Function", yeni adı "Code"
    "javascript": ["code"],
    "python": ["code"],
    "script": ["code"],
    "transform": ["set", "code"],
    # Control flow
    "condition": ["if", "switch", "filter"],
    "branch": ["if", "switch"],
    "loop": ["splitinbatches", "code"],
    "iterate": ["splitinbatches"],
    # AI
    "ai": ["openai", "anthropic", "langchain"],
    "llm": ["openai", "anthropic", "langchain"],
    "gpt": ["openai"],
    "claude": ["anthropic"],
    "chatgpt": ["openai"],
    # Counting / text processing
    "count": ["code", "set"],
    "word count": ["code"],
    "string": ["code", "set"],
    "text": ["code", "set"],
    "parse": ["code", "set"],
    "split": ["code", "splitinbatches"],
}


def _score_node(node: NodeInfo, query: str) -> int:
    q = query.lower().strip()
    name_lower = node.display_name.lower()
    type_lower = node.type_name.lower()

    # Tam eşleşmeler
    if type_lower == f"n8n-nodes-base.{q}" or type_lower == q:
        return 100
    if name_lower == q:
        return 90

    # Prefix eşleşme
    if name_lower.startswith(q):
        return 75
    if type_lower.endswith(f".{q}"):
        return 70

    # İçerik eşleşme
    if q in name_lower:
        return 55
    if q in type_lower:
        return 50
    if q in node.description.lower():
        return 30
    if q in node.category.lower():
        return 15

    # Alias kontrolü
    alias_targets = _NODE_ALIASES.get(q, [])
    for alias in alias_targets:
        if alias in type_lower or alias in name_lower:
            return 40

    return 0


def search_nodes(
    query: str,
    nodes: list[NodeInfo],
    limit: int = 8,
) -> list[NodeInfo]:
    """
    Keyword tabanlı node arama. Relevance score'a göre sıralar.
    Birden fazla kelime içeren sorgular AND semantiği ile çalışır.
    """
    terms = query.lower().split()
    scored: list[tuple[int, NodeInfo]] = []

    for node in nodes:
        if len(terms) == 1:
            score = _score_node(node, terms[0])
        else:
            # Tüm terimler için ortalama skor
            scores = [_score_node(node, t) for t in terms]
            score = sum(scores) // len(scores)
            # Herhangi bir terim 0 ise ve en az biri güçlüyse skor düşük tut
            if all(s == 0 for s in scores):
                score = 0

        if score > 0:
            scored.append((score, node))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [node for _, node in scored[:limit]]


def get_node_by_type(
    type_name: str,
    nodes: list[NodeInfo],
) -> NodeInfo | None:
    """Tam type adıyla node döner. 'gmail' gibi kısaltma da kabul eder."""
    type_lower = type_name.lower().strip()

    for node in nodes:
        if node.type_name.lower() == type_lower:
            return node
        # Kısaltma desteği: "gmail" → "n8n-nodes-base.gmail"
        suffix = node.type_name.split(".")[-1].lower()
        if suffix == type_lower:
            return node

    return None


def _set_node_example(node: NodeInfo) -> dict:
    return {
        "id": "node2",
        "name": "Edit Fields (Set)",
        "type": node.type_name,
        "typeVersion": node.type_version,
        "position": [750, 300],
        "parameters": {
            "mode": "manual",
            "assignments": {
                "assignments": [
                    {
                        "id": "message",
                        "name": "message",
                        "type": "string",
                        "value": "hello from Conduut",
                    }
                ]
            },
            "options": {},
        },
    }


def _apply_node_specific_guidance(schema: dict, node: NodeInfo) -> None:
    if node.type_name == "n8n-nodes-base.set":
        schema["usageHints"] = [
            (
                "To add or change fields with Edit Fields (Set), use "
                "parameters.assignments.assignments. Each assignment needs id, name, type, "
                "and value. Do not leave assignments empty."
            ),
            (
                "For a field named message, use an assignment like "
                "{id: 'message', name: 'message', type: 'string', value: 'hello'}."
            ),
        ]
        schema["exampleNode"] = _set_node_example(node)


def build_schema_response(node: NodeInfo) -> dict:
    """
    LLM'e gönderilecek kondanse şema dict'ini oluşturur.
    Agent bu bilgiyle node'un doğru parametrelerini üretir.
    """
    schema: dict = {
        "type": node.type_name,
        "displayName": node.display_name,
        "typeVersion": node.type_version,
        "description": node.description,
        "category": node.category,
        "isTrigger": node.is_trigger,
    }

    if node.credentials:
        schema["credentials"] = node.credentials

    if node.resources:
        schema["resources"] = node.resources

    if node.operations:
        # Tüm operasyonları tek liste olarak özetle
        all_ops: list[str] = []
        for ops in node.operations.values():
            for op in ops:
                if op not in all_ops:
                    all_ops.append(op)
        if all_ops:
            schema["operations"] = all_ops

    if node.key_properties:
        schema["keyParameters"] = node.key_properties

    # Örnek node JSON — agent bunu adapte eder
    example_params: dict = {}
    if node.resources:
        example_params["resource"] = node.resources[0]
    for res, ops in node.operations.items():
        if ops:
            example_params["operation"] = ops[0]
            break
    for prop in node.key_properties:
        name = prop.get("name")
        default = prop.get("default")
        if name and default is not None and name not in example_params:
            example_params[name] = default

    schema["exampleNode"] = {
        "id": "node1",
        "name": node.display_name,
        "type": node.type_name,
        "typeVersion": node.type_version,
        "position": [500, 300],
        "parameters": example_params,
    }

    _apply_node_specific_guidance(schema, node)

    return schema


def _score_template(template: WorkflowTemplate, query: str) -> int:
    q = query.lower().strip()
    score = 0

    if q in template.name.lower():
        score += 60
    if q in template.description.lower():
        score += 30
    for cat in template.categories:
        if q in cat.lower():
            score += 20
    for nt in template.node_types:
        if q in nt.lower():
            score += 10

    return score


def find_templates(
    query: str,
    templates: list[WorkflowTemplate],
    limit: int = 3,
) -> list[WorkflowTemplate]:
    """Keyword arama ile en alakalı workflow template'lerini döner."""
    terms = query.lower().split()
    scored: list[tuple[int, WorkflowTemplate]] = []

    for tmpl in templates:
        total = sum(_score_template(tmpl, t) for t in terms)
        if total > 0:
            scored.append((total, tmpl))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [t for _, t in scored[:limit]]


def collect_credential_types(nodes: list[NodeInfo]) -> list[dict]:
    """Tüm node'lardan referans edilen credential tiplerini toplar.

    Her tip için onu kullanan node'ların display_name'lerini (görülme sırasında,
    tekrarsız) biriktirir. Tipe göre alfabetik sıralı döner.
    """
    by_type: dict[str, list[str]] = {}
    for node in nodes:
        for cred_type in node.credentials or []:
            names = by_type.setdefault(cred_type, [])
            if node.display_name and node.display_name not in names:
                names.append(node.display_name)
    return [{"type": cred_type, "nodes": names} for cred_type, names in sorted(by_type.items())]


def build_template_response(template: WorkflowTemplate) -> dict:
    """LLM'e gönderilecek template özetini oluşturur."""
    return {
        "id": template.id,
        "name": template.name,
        "description": template.description,
        "categories": template.categories,
        "nodeTypes": template.node_types,
        "workflow": template.workflow_json,
    }
