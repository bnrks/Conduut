"""Sanitized registry card extraction and JSONL helpers."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict
from pathlib import Path
from typing import Any, Iterable

from .models import NodeCard, NodeInfo, WorkflowCard, WorkflowTemplate

_HTML_TAG_RE = re.compile(r"<[^>]+>")
_MARKDOWN_IMAGE_RE = re.compile(r"!\[[^\]]*]\([^)]+\)")
_MARKDOWN_LINK_RE = re.compile(r"\[([^\]]+)]\([^)]+\)")
_OBSIDIAN_EMBED_RE = re.compile(r"@\[([^\]]+)]\([^)]+\)")
_WHITESPACE_RE = re.compile(r"\s+")

_CODE_NODE_SUFFIXES = {"code", "function", "functionitem"}
_AI_NODE_PREFIXES = ("@n8n/n8n-nodes-langchain.",)
_TRIGGER_SUFFIXES = ("trigger", "webhook")
_CONTROL_SUFFIXES = {"filter", "if", "merge", "switch"}
_TRANSFORM_SUFFIXES = {"code", "function", "functionitem", "set"}
_WRITEBACK_SUFFIXES = {"googlesheets", "airtable", "notion", "postgres", "mysql"}
_SIDE_EFFECT_OPERATIONS = {
    "add",
    "append",
    "appendorupdate",
    "create",
    "delete",
    "insert",
    "reply",
    "send",
    "trash",
    "update",
    "upload",
}
_KEYWORD_RE = re.compile(r"[A-Za-zÀ-ž0-9_]{3,}")
_PROMPT_INJECTION_RE = re.compile(
    r"\b(?:ignore|disregard|override)\b.{0,80}\b(?:instruction|prompt|system)\b|"
    r"\b(?:system prompt|you are chatgpt|act as an? (?:assistant|agent))\b",
    re.IGNORECASE,
)


def _ordered_unique(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        normalized = value.strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        ordered.append(normalized)
    return ordered


def _sanitize_text(value: Any, *, limit: int = 1200) -> str:
    if not value:
        return ""
    text = str(value)
    text = _MARKDOWN_IMAGE_RE.sub(" ", text)
    text = _MARKDOWN_LINK_RE.sub(r"\1", text)
    text = _OBSIDIAN_EMBED_RE.sub(r"\1", text)
    text = _HTML_TAG_RE.sub(" ", text)
    text = text.replace("`", " ")
    text = _WHITESPACE_RE.sub(" ", text).strip()
    if len(text) <= limit:
        return text
    clipped = text[: limit - 1].rstrip()
    return f"{clipped}…"


def _sanitize_untrusted_description(value: Any, *, limit: int = 1600) -> str:
    text = _sanitize_text(value, limit=limit)
    return _PROMPT_INJECTION_RE.sub("[removed untrusted instruction]", text)


def _summary_from_description(description: str) -> str:
    if not description:
        return ""
    first_block = description.split(". ")[0].strip()
    if first_block:
        return _sanitize_text(first_block, limit=280)
    return _sanitize_text(description, limit=280)


def _node_suffix(type_name: str) -> str:
    suffix = type_name.split(".")[-1].strip()
    return suffix or type_name.strip()


def _is_trigger_type(type_name: str) -> bool:
    lowered = _node_suffix(type_name).lower()
    return lowered.endswith(_TRIGGER_SUFFIXES)


def _template_source_url(template_id: int | str) -> str:
    if template_id in ("", None):
        return ""
    return f"https://n8n.io/workflows/{template_id}"


def _canonical_fingerprint(payload: dict[str, Any]) -> str:
    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _extract_categories(raw_categories: Any) -> list[str]:
    categories: list[str] = []
    if not isinstance(raw_categories, list):
        return categories
    for item in raw_categories:
        if isinstance(item, dict):
            categories.append(_sanitize_text(item.get("name") or "", limit=120))
        else:
            categories.append(_sanitize_text(item, limit=120))
    return _ordered_unique(categories)


def _extract_node_types(record: dict[str, Any], workflow: dict[str, Any]) -> list[str]:
    discovered: list[str] = []
    for node in workflow.get("nodes", []) if isinstance(workflow, dict) else []:
        if isinstance(node, dict):
            node_type = str(node.get("type") or "").strip()
            if node_type:
                discovered.append(node_type)
    if discovered:
        return _ordered_unique(discovered)
    raw_node_types = record.get("nodeTypes") or []
    return _ordered_unique(str(item).strip() for item in raw_node_types if str(item).strip())


def _extract_operations(workflow: dict[str, Any]) -> list[str]:
    operations: list[str] = []
    nodes = workflow.get("nodes", []) if isinstance(workflow, dict) else []
    for node in nodes:
        if not isinstance(node, dict):
            continue
        node_type = str(node.get("type") or "").strip()
        if not node_type:
            continue
        suffix = _node_suffix(node_type)
        parameters = node.get("parameters")
        if not isinstance(parameters, dict):
            continue
        resource = parameters.get("resource")
        operation = parameters.get("operation")
        if isinstance(resource, str) and isinstance(operation, str):
            operations.append(f"{suffix}:{resource}.{operation}")
            continue
        if isinstance(operation, str):
            operations.append(f"{suffix}:{operation}")
            continue
        if isinstance(resource, str):
            operations.append(f"{suffix}:{resource}")
    return _ordered_unique(operations)


def _workflow_nodes(workflow: dict[str, Any]) -> list[dict[str, Any]]:
    nodes = workflow.get("nodes") if isinstance(workflow, dict) else None
    return [node for node in (nodes or []) if isinstance(node, dict)]


def _resolve_native_workflow(record: dict[str, Any]) -> dict[str, Any]:
    """Unwrap the Community detail envelope to the native n8n workflow."""

    workflow = record.get("workflow")
    if not isinstance(workflow, dict):
        return {}
    nested = workflow.get("workflow")
    if isinstance(nested, dict) and isinstance(nested.get("nodes"), list):
        return nested
    return workflow


def _node_role(node: dict[str, Any]) -> str:
    node_type = str(node.get("type") or "")
    suffix = _node_suffix(node_type).lower()
    parameters = node.get("parameters") if isinstance(node.get("parameters"), dict) else {}
    operation = str(parameters.get("operation") or "").casefold()
    node_name = str(node.get("name") or "").casefold()
    if _is_trigger_type(node_type):
        return "trigger"
    if suffix in _CONTROL_SUFFIXES:
        return "control"
    if suffix in _TRANSFORM_SUFFIXES:
        return "transform"
    if suffix in _WRITEBACK_SUFFIXES and operation in _SIDE_EFFECT_OPERATIONS:
        return "writeback"
    if operation in _SIDE_EFFECT_OPERATIONS:
        return "action"
    if suffix in _WRITEBACK_SUFFIXES and re.search(
        r"\b(?:append|insert|log|mark|update|write)\b", node_name
    ):
        return "writeback"
    if suffix == "gmail" and re.search(r"\b(?:reply|send)\b", node_name):
        return "action"
    return "step"


def _extract_node_roles(workflow: dict[str, Any]) -> list[dict[str, str]]:
    return [
        {
            "name": _sanitize_text(
                node.get("name") or _node_suffix(str(node.get("type") or "")), limit=120
            ),
            "type": str(node.get("type") or ""),
            "role": _node_role(node),
        }
        for node in _workflow_nodes(workflow)
        if node.get("type")
    ]


def _extract_node_versions(workflow: dict[str, Any]) -> list[dict[str, Any]]:
    versions: list[dict[str, Any]] = []
    for node in _workflow_nodes(workflow):
        node_type = str(node.get("type") or "").strip()
        version = node.get("typeVersion")
        if node_type:
            versions.append({"type": node_type, "typeVersion": version})
    return versions


def _extract_credentials(workflow: dict[str, Any]) -> list[str]:
    credentials: list[str] = []
    for node in _workflow_nodes(workflow):
        configured = node.get("credentials")
        if isinstance(configured, dict):
            credentials.extend(str(key) for key in configured if str(key).strip())
    return _ordered_unique(credentials)


def _extract_identity_strategy(workflow: dict[str, Any]) -> dict[str, Any]:
    keys: list[str] = []
    for node in _workflow_nodes(workflow):
        parameters = node.get("parameters") if isinstance(node.get("parameters"), dict) else {}
        columns = parameters.get("columns") if isinstance(parameters.get("columns"), dict) else {}
        matching = columns.get("matchingColumns")
        if isinstance(matching, list):
            keys.extend(str(item) for item in matching if str(item).strip())
    keys = _ordered_unique(keys)
    return {
        "fields": keys,
        "source": "matchingColumns" if keys else "unspecified",
    }


def _extract_side_effects(workflow: dict[str, Any]) -> list[str]:
    effects: list[str] = []
    for node in _workflow_nodes(workflow):
        suffix = _node_suffix(str(node.get("type") or "node"))
        suffix_folded = suffix.casefold()
        node_name = str(node.get("name") or "").casefold()
        parameters = node.get("parameters") if isinstance(node.get("parameters"), dict) else {}
        operation = str(parameters.get("operation") or "").strip()
        if operation.casefold() in _SIDE_EFFECT_OPERATIONS:
            effects.append(f"{suffix}:{operation}")
            continue
        if suffix_folded in _WRITEBACK_SUFFIXES and re.search(
            r"\b(?:append|insert|log|mark|update|write)\b", node_name
        ):
            effects.append(f"{suffix}:update:inferred")
        elif suffix_folded == "gmail" and re.search(r"\b(?:reply|send)\b", node_name):
            effects.append(f"{suffix}:send:inferred")
    return _ordered_unique(effects)


def _extract_capabilities(
    operations: list[str],
    side_effects: list[str],
    workflow: dict[str, Any],
) -> list[str]:
    tokens = " ".join([*operations, *side_effects]).casefold()
    capabilities: list[str] = []
    for needle, capability in (
        ("gmail:message.send", "send_email"),
        ("gmail:send", "send_email"),
        ("googlesheets:sheet.read", "read_sheet"),
        ("googlesheets:sheet.append", "append_sheet_rows"),
        ("googlesheets:sheet.update", "update_sheet_rows"),
        ("googlesheets:update", "update_sheet_rows"),
        ("webhook", "receive_webhook"),
        ("scheduletrigger", "scheduled_run"),
    ):
        if needle in tokens:
            capabilities.append(capability)
    for node in _workflow_nodes(workflow):
        suffix = _node_suffix(str(node.get("type") or "")).casefold()
        node_name = str(node.get("name") or "").casefold()
        if suffix == "googlesheets" and re.search(r"\b(?:fetch|get|load|pull|read)\b", node_name):
            capabilities.append("read_sheet")
        if suffix == "scheduletrigger":
            capabilities.append("scheduled_run")
    return _ordered_unique(capabilities)


def _extract_topology(workflow: dict[str, Any], roles: list[dict[str, str]]) -> dict[str, Any]:
    connections = workflow.get("connections")
    edge_count = 0
    if isinstance(connections, dict):
        for outputs in connections.values():
            main = outputs.get("main") if isinstance(outputs, dict) else None
            if not isinstance(main, list):
                continue
            edge_count += sum(len(branch) for branch in main if isinstance(branch, list))
    return {
        "nodeCount": len(roles),
        "edgeCount": edge_count,
        "roleCounts": {
            role: sum(1 for item in roles if item["role"] == role)
            for role in ("trigger", "control", "transform", "action", "writeback", "step")
        },
    }


def _controlled_keywords(*values: str) -> list[str]:
    words: list[str] = []
    for value in values:
        words.extend(match.group(0).casefold() for match in _KEYWORD_RE.finditer(value))
    return _ordered_unique(words)[:32]


def _extract_risk_flags(node_types: list[str]) -> list[str]:
    flags: list[str] = []
    suffixes = {_node_suffix(type_name).lower() for type_name in node_types}
    if suffixes & _CODE_NODE_SUFFIXES:
        flags.append("code")
    if any(type_name.startswith(_AI_NODE_PREFIXES) for type_name in node_types):
        flags.append("ai")
    if "httprequest" in suffixes:
        flags.append("http")
    if "webhook" in suffixes:
        flags.append("webhook")
    if "scheduletrigger" in suffixes:
        flags.append("schedule")
    return flags


def extract_workflow_card(record: dict[str, Any]) -> WorkflowCard:
    workflow = _resolve_native_workflow(record)

    node_types = _extract_node_types(record, workflow)
    categories = _extract_categories(record.get("categories"))
    description = _sanitize_untrusted_description(record.get("description") or "", limit=1600)
    summary = _summary_from_description(description)
    services = _ordered_unique(_node_suffix(type_name) for type_name in node_types)
    operations = _extract_operations(workflow)
    node_roles = _extract_node_roles(workflow)
    node_versions = _extract_node_versions(workflow)
    credentials = _extract_credentials(workflow)
    identity_strategy = _extract_identity_strategy(workflow)
    side_effects = _extract_side_effects(workflow)
    capabilities = _extract_capabilities(operations, side_effects, workflow)
    trigger_types = _ordered_unique(
        _node_suffix(type_name) for type_name in node_types if _is_trigger_type(type_name)
    )
    node_count = len(workflow.get("nodes", [])) if isinstance(workflow.get("nodes"), list) else 0
    trigger_count = len(trigger_types)
    risk_flags = _extract_risk_flags(node_types)
    risk_level = "high" if side_effects or {"code", "http"} & set(risk_flags) else "low"
    idempotency_strategy = {
        "kind": "identity_writeback"
        if identity_strategy["fields"] and side_effects
        else "unspecified",
        "rerunExpected": "no_action" if identity_strategy["fields"] and side_effects else "unknown",
    }
    content_hash = _canonical_fingerprint(
        {
            "nodeVersions": node_versions,
            "operations": operations,
            "roles": node_roles,
            "topology": _extract_topology(workflow, node_roles),
        }
    )
    keywords = _controlled_keywords(
        str(record.get("name") or ""),
        description,
        " ".join(categories),
        " ".join(services),
        " ".join(capabilities),
    )
    card = WorkflowCard(
        id=record.get("id", ""),
        name=_sanitize_text(record.get("name") or "Untitled", limit=200) or "Untitled",
        summary=summary,
        description=description,
        fetched_at=str(record.get("fetchedAt") or record.get("fetched_at") or ""),
        content_hash=content_hash,
        intents=[summary] if summary else [],
        keywords=keywords,
        categories=categories,
        node_types=node_types,
        node_versions=node_versions,
        services=services,
        capabilities=capabilities,
        operations=operations,
        trigger_types=trigger_types,
        topology=_extract_topology(workflow, node_roles),
        node_roles=node_roles,
        credential_requirements=credentials,
        identity_strategy=identity_strategy,
        idempotency_strategy=idempotency_strategy,
        side_effects=side_effects,
        risk_level=risk_level,
        risk_flags=risk_flags,
        cardinality_invariants=(
            ["action_count equals writeback_count"]
            if any(item["role"] == "action" for item in node_roles)
            and any(item["role"] == "writeback" for item in node_roles)
            else []
        ),
        rerun_invariants=(
            ["second run produces no action"]
            if idempotency_strategy["rerunExpected"] == "no_action"
            else []
        ),
        compatibility={"status": "unchecked", "authority": "current_node_schema"},
        validation={"status": "not_run"},
        sandbox={"status": "not_run"},
        confidence=0.75 if workflow else 0.4,
        node_count=node_count,
        trigger_count=trigger_count,
        source_url=str(record.get("sourceUrl") or _template_source_url(record.get("id", ""))),
    )
    search_tokens = [
        card.name,
        card.summary,
        card.description,
        *card.categories,
        *card.node_types,
        *card.services,
        *card.capabilities,
        *card.operations,
        *card.trigger_types,
        *card.keywords,
    ]
    card.search_text = _sanitize_text(" ".join(search_tokens), limit=4000).lower()
    card.fingerprint = _canonical_fingerprint(
        {
            "id": str(card.id),
            "name": card.name,
            "summary": card.summary,
            "description": card.description,
            "categories": card.categories,
            "node_types": card.node_types,
            "services": card.services,
            "operations": card.operations,
            "trigger_types": card.trigger_types,
            "risk_flags": card.risk_flags,
            "node_count": card.node_count,
            "trigger_count": card.trigger_count,
            "source_url": card.source_url,
            "content_hash": card.content_hash,
        }
    )
    return card


def workflow_card_to_dict(card: WorkflowCard) -> dict[str, Any]:
    return asdict(card)


def workflow_card_from_dict(data: dict[str, Any]) -> WorkflowCard:
    payload = dict(data)
    return WorkflowCard(
        id=payload.get("id", ""),
        name=str(payload.get("name") or "Untitled"),
        summary=str(payload.get("summary") or ""),
        description=str(payload.get("description") or ""),
        source=str(payload.get("source") or "n8n_community"),
        fetched_at=str(payload.get("fetched_at") or payload.get("fetchedAt") or ""),
        content_hash=str(payload.get("content_hash") or payload.get("contentHash") or ""),
        intents=list(payload.get("intents") or []),
        keywords=list(payload.get("keywords") or []),
        categories=list(payload.get("categories") or []),
        node_types=list(payload.get("node_types") or payload.get("nodeTypes") or []),
        node_versions=list(payload.get("node_versions") or payload.get("nodeVersions") or []),
        services=list(payload.get("services") or []),
        capabilities=list(payload.get("capabilities") or []),
        operations=list(payload.get("operations") or []),
        trigger_types=list(payload.get("trigger_types") or payload.get("triggerTypes") or []),
        topology=dict(payload.get("topology") or {}),
        node_roles=list(payload.get("node_roles") or payload.get("nodeRoles") or []),
        credential_requirements=list(
            payload.get("credential_requirements") or payload.get("credentialRequirements") or []
        ),
        input_fields=list(payload.get("input_fields") or payload.get("inputFields") or []),
        output_fields=list(payload.get("output_fields") or payload.get("outputFields") or []),
        identity_strategy=dict(
            payload.get("identity_strategy") or payload.get("identityStrategy") or {}
        ),
        idempotency_strategy=dict(
            payload.get("idempotency_strategy") or payload.get("idempotencyStrategy") or {}
        ),
        side_effects=list(payload.get("side_effects") or payload.get("sideEffects") or []),
        risk_level=str(payload.get("risk_level") or payload.get("riskLevel") or "low"),
        risk_flags=list(payload.get("risk_flags") or payload.get("riskFlags") or []),
        cardinality_invariants=list(
            payload.get("cardinality_invariants") or payload.get("cardinalityInvariants") or []
        ),
        rerun_invariants=list(
            payload.get("rerun_invariants") or payload.get("rerunInvariants") or []
        ),
        compatibility=dict(payload.get("compatibility") or {}),
        validation=dict(payload.get("validation") or {}),
        sandbox=dict(payload.get("sandbox") or {}),
        confidence=float(payload.get("confidence") or 0.0),
        node_count=int(payload.get("node_count") or payload.get("nodeCount") or 0),
        trigger_count=int(payload.get("trigger_count") or payload.get("triggerCount") or 0),
        fingerprint=str(payload.get("fingerprint") or ""),
        source_url=str(payload.get("source_url") or payload.get("sourceUrl") or ""),
        search_text=str(payload.get("search_text") or payload.get("searchText") or ""),
    )


def workflow_template_from_card(card: WorkflowCard) -> WorkflowTemplate:
    template = WorkflowTemplate(
        id=card.id,
        name=card.name,
        description=card.description,
        categories=list(card.categories),
        node_types=list(card.node_types),
        workflow_json={},
        card=card,
    )
    template.search_text = card.search_text
    return template


def extract_node_card(node: NodeInfo) -> NodeCard:
    flattened_operations: list[str] = []
    for resource, operations in node.operations.items():
        for operation in operations:
            if resource == "default":
                flattened_operations.append(operation)
            else:
                flattened_operations.append(f"{resource}.{operation}")
    card = NodeCard(
        type_name=node.type_name,
        display_name=node.display_name,
        description=node.description,
        type_version=node.type_version,
        category=node.category,
        is_trigger=node.is_trigger,
        credentials=list(node.credentials),
        resources=list(node.resources),
        operations=_ordered_unique(flattened_operations),
        contract_keys=[contract.key for contract in node.contracts],
        default_contract_key=(node.contracts[0].key if node.contracts else None),
    )
    search_tokens = [
        card.display_name,
        card.description,
        card.type_name,
        card.category,
        *card.resources,
        *card.operations,
    ]
    card.search_text = _sanitize_text(" ".join(search_tokens), limit=2400).lower()
    return card


def legacy_template_response(card: WorkflowCard) -> dict[str, Any]:
    return {
        "id": card.id,
        "name": card.name,
        "description": card.summary or card.description,
        "summary": card.summary,
        "categories": list(card.categories),
        "nodeTypes": list(card.node_types),
        "services": list(card.services),
        "operations": list(card.operations),
        "triggerTypes": list(card.trigger_types),
        "riskFlags": list(card.risk_flags),
        "nodeCount": card.node_count,
        "triggerCount": card.trigger_count,
        "fingerprint": card.fingerprint,
        "sourceUrl": card.source_url,
    }


def workflow_search_response(card: WorkflowCard) -> dict[str, Any]:
    return {
        "id": card.id,
        "name": card.name,
        "summary": card.summary,
        "intents": list(card.intents),
        "keywords": list(card.keywords),
        "services": list(card.services),
        "capabilities": list(card.capabilities),
        "triggerTypes": list(card.trigger_types),
        "riskLevel": card.risk_level,
        "nodeCount": card.node_count,
        "fingerprint": card.fingerprint,
    }


def workflow_card_response(card: WorkflowCard) -> dict[str, Any]:
    return {
        **workflow_search_response(card),
        "source": card.source,
        "fetchedAt": card.fetched_at,
        "contentHash": card.content_hash,
        "description": card.description,
        "categories": list(card.categories),
        "nodeTypes": list(card.node_types),
        "nodeVersions": list(card.node_versions),
        "operations": list(card.operations),
        "topology": dict(card.topology),
        "nodeRoles": list(card.node_roles),
        "credentialRequirements": list(card.credential_requirements),
        "inputFields": list(card.input_fields),
        "outputFields": list(card.output_fields),
        "identityStrategy": dict(card.identity_strategy),
        "idempotencyStrategy": dict(card.idempotency_strategy),
        "sideEffects": list(card.side_effects),
        "riskFlags": list(card.risk_flags),
        "cardinalityInvariants": list(card.cardinality_invariants),
        "rerunInvariants": list(card.rerun_invariants),
        "compatibility": dict(card.compatibility),
        "validation": dict(card.validation),
        "sandbox": dict(card.sandbox),
        "confidence": card.confidence,
        "triggerCount": card.trigger_count,
        "sourceUrl": card.source_url,
    }


def write_json_atomic(path: str | Path, payload: Any) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = destination.with_suffix(f"{destination.suffix}.tmp")
    tmp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp_path.replace(destination)


def append_workflow_card_jsonl(path: str | Path, card: WorkflowCard) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(workflow_card_to_dict(card), ensure_ascii=False, sort_keys=True))
        handle.write("\n")


def load_workflow_cards_jsonl(path: str | Path) -> list[WorkflowCard]:
    source = Path(path)
    if not source.exists():
        return []
    cards: list[WorkflowCard] = []
    with source.open("r", encoding="utf-8") as handle:
        for line in handle:
            stripped = line.strip()
            if not stripped:
                continue
            cards.append(workflow_card_from_dict(json.loads(stripped)))
    return cards


def load_json_file(path: str | Path) -> dict[str, Any]:
    source = Path(path)
    if not source.exists():
        return {}
    return json.loads(source.read_text(encoding="utf-8"))
