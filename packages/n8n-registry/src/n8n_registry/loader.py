"""n8n node schemas and workflow cards loader."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from .cards import (
    extract_node_card,
    extract_workflow_card,
    load_workflow_cards_jsonl,
    workflow_template_from_card,
)
from .models import CredentialTypeInfo, NodeContract, NodeInfo, WorkflowCard, WorkflowTemplate

log = logging.getLogger(__name__)

_SUPPORTED_DISPLAY_OPTION_KEYS = {"@version", "resource", "operation"}
_OAUTH_PROP_SIGNATURES = {
    "oauthTokenData",
    "grantType",
    "authUrl",
    "accessTokenUrl",
    "authQueryParameters",
}


def _is_trigger(raw: dict[str, Any]) -> bool:
    group = raw.get("group", [])
    if isinstance(group, list) and any(str(item).lower() == "trigger" for item in group):
        return True
    name = str(raw.get("name") or "")
    return name.lower().endswith("trigger") or name.lower().endswith("triggers")


def _as_number(value: Any) -> float | int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return value
    if isinstance(value, str):
        try:
            parsed = float(value)
        except ValueError:
            return None
        return int(parsed) if parsed.is_integer() else parsed
    return None


def _extract_version(raw: dict[str, Any]) -> int | float:
    version = raw.get("version", raw.get("defaultVersion", 1))
    if isinstance(version, list):
        numeric_versions = [item for item in (_as_number(v) for v in version) if item is not None]
        return max(numeric_versions) if numeric_versions else 1
    numeric = _as_number(version)
    return numeric if numeric is not None else 1


def _extract_credentials(raw: dict[str, Any]) -> list[str]:
    credentials = raw.get("credentials", [])
    if not isinstance(credentials, list):
        return []
    return [
        str(item["name"]) for item in credentials if isinstance(item, dict) and item.get("name")
    ]


def _extract_category(raw: dict[str, Any]) -> str:
    codex = raw.get("codex", {})
    if isinstance(codex, dict):
        categories = codex.get("categories", [])
        if categories:
            return str(categories[0])
    return "Core"


def _version_condition_matches(condition: Any, version: int | float) -> bool:
    current = _as_number(version)
    if current is None:
        return False
    if isinstance(condition, dict):
        raw_ops = condition.get("_cnd")
        if not isinstance(raw_ops, dict):
            raw_ops = condition
        for operator, expected in raw_ops.items():
            expected_number = _as_number(expected)
            if expected_number is None:
                return False
            if operator in {"eq", "equals"} and current != expected_number:
                return False
            if operator in {"neq", "notEquals"} and current == expected_number:
                return False
            if operator == "gte" and current < expected_number:
                return False
            if operator == "gt" and current <= expected_number:
                return False
            if operator == "lte" and current > expected_number:
                return False
            if operator == "lt" and current >= expected_number:
                return False
        return True
    expected_number = _as_number(condition)
    return expected_number is not None and current == expected_number


def _version_conditions_match(values: Any, version: int | float) -> bool:
    if isinstance(values, list):
        return any(_version_condition_matches(value, version) for value in values)
    return _version_condition_matches(values, version)


def _string_condition_matches(values: Any, current: str | None) -> bool:
    if current is None:
        return False
    if isinstance(values, list):
        return any(str(value) == current for value in values)
    return str(values) == current


def _display_branch_matches(
    branch: dict[str, Any],
    *,
    version: int | float,
    resource: str | None,
    operation: str | None,
) -> bool:
    for key, values in branch.items():
        if key == "@version":
            if not _version_conditions_match(values, version):
                return False
            continue
        if key == "resource":
            if not _string_condition_matches(values, resource):
                return False
            continue
        if key == "operation":
            if not _string_condition_matches(values, operation):
                return False
            continue
        return False
    return True


def _display_options_match(
    prop: dict[str, Any],
    *,
    version: int | float,
    resource: str | None = None,
    operation: str | None = None,
) -> bool:
    display_options = prop.get("displayOptions")
    if not isinstance(display_options, dict):
        return True

    show = display_options.get("show")
    if isinstance(show, dict):
        if any(key not in _SUPPORTED_DISPLAY_OPTION_KEYS for key in show):
            return False
        if not _display_branch_matches(
            show, version=version, resource=resource, operation=operation
        ):
            return False

    hide = display_options.get("hide")
    if isinstance(hide, dict):
        # Unknown hide dependencies (for example ``sheetName`` being empty) are
        # dynamic UI state. They must not erase an otherwise valid operation
        # parameter from the static contract.
        if not any(key not in _SUPPORTED_DISPLAY_OPTION_KEYS for key in hide):
            if _display_branch_matches(
                hide, version=version, resource=resource, operation=operation
            ):
                return False

    return True


def _extract_type_options_metadata(type_options: Any) -> dict[str, Any]:
    if not isinstance(type_options, dict):
        return {}
    metadata: dict[str, Any] = {}
    for key in ("loadOptionsMethod", "loadOptionsDependsOn", "searchListMethod", "searchable"):
        if key in type_options:
            metadata[key] = type_options[key]
    if "loadOptions" in type_options:
        metadata["loadOptions"] = True
    return metadata


def _extract_modes_metadata(modes: Any) -> list[dict[str, Any]]:
    if not isinstance(modes, list):
        return []
    result: list[dict[str, Any]] = []
    for mode in modes:
        if not isinstance(mode, dict):
            continue
        condensed: dict[str, Any] = {
            "name": mode.get("name"),
            "displayName": mode.get("displayName"),
            "type": mode.get("type"),
        }
        type_options = _extract_type_options_metadata(mode.get("typeOptions"))
        if type_options:
            condensed["typeOptions"] = type_options
        result.append({key: value for key, value in condensed.items() if value is not None})
    return result


def _extract_key_properties(
    properties: list[dict[str, Any]],
    *,
    version: int | float,
    resource: str | None = None,
    operation: str | None = None,
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for prop in properties:
        name = prop.get("name")
        if name in {"resource", "operation"}:
            continue
        if not _display_options_match(
            prop,
            version=version,
            resource=resource,
            operation=operation,
        ):
            continue
        condensed: dict[str, Any] = {
            "name": name,
            "displayName": prop.get("displayName"),
            "type": prop.get("type"),
            "required": prop.get("required", False),
            "default": prop.get("default"),
        }
        if prop.get("type") == "options" and isinstance(prop.get("options"), list):
            condensed["options"] = [
                option.get("value")
                for option in prop["options"]
                if isinstance(option, dict) and option.get("value") is not None
            ]
        type_options = _extract_type_options_metadata(prop.get("typeOptions"))
        if type_options:
            condensed["typeOptions"] = type_options
        modes = _extract_modes_metadata(prop.get("modes"))
        if modes:
            condensed["modes"] = modes
        result.append(condensed)

    selected = result[:8]
    selected_names = {str(prop.get("name") or "") for prop in selected}
    for prop in result[8:]:
        if (
            prop.get("type") == "resourceLocator"
            and str(prop.get("name") or "") not in selected_names
        ):
            selected.append(prop)
    return selected


def _visible_option_values(
    options: Any,
    *,
    version: int | float,
    resource: str | None = None,
    operation: str | None = None,
) -> list[str]:
    if not isinstance(options, list):
        return []
    values: list[str] = []
    for option in options:
        if not isinstance(option, dict):
            continue
        value = option.get("value")
        if value is None:
            continue
        if _display_options_match(
            option,
            version=version,
            resource=resource,
            operation=operation,
        ):
            values.append(str(value))
    ordered: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        ordered.append(value)
    return ordered


def _extract_resources_and_ops(
    properties: list[dict[str, Any]],
    *,
    version: int | float,
) -> tuple[list[str], dict[str, list[str]]]:
    resources: list[str] = []
    operations: dict[str, list[str]] = {}

    resource_props = [
        prop for prop in properties if isinstance(prop, dict) and prop.get("name") == "resource"
    ]
    operation_props = [
        prop for prop in properties if isinstance(prop, dict) and prop.get("name") == "operation"
    ]

    for resource_prop in resource_props:
        if not _display_options_match(resource_prop, version=version):
            continue
        resources.extend(_visible_option_values(resource_prop.get("options"), version=version))
    resources = list(dict.fromkeys(resources))

    if resources:
        for resource in resources:
            visible: list[str] = []
            for operation_prop in operation_props:
                if not _display_options_match(
                    operation_prop,
                    version=version,
                    resource=resource,
                ):
                    continue
                visible.extend(
                    _visible_option_values(
                        operation_prop.get("options"),
                        version=version,
                        resource=resource,
                    )
                )
            if visible:
                operations[resource] = list(dict.fromkeys(visible))
    else:
        visible = []
        for operation_prop in operation_props:
            if not _display_options_match(operation_prop, version=version):
                continue
            visible.extend(_visible_option_values(operation_prop.get("options"), version=version))
        if visible:
            operations["default"] = list(dict.fromkeys(visible))

    return resources, operations


def _contract_key(
    type_name: str,
    type_version: int | float,
    *,
    resource: str | None,
    operation: str | None,
) -> str:
    parts = [type_name, f"v{type_version}"]
    if resource:
        parts.append(f"resource={resource}")
    if operation:
        parts.append(f"operation={operation}")
    return "|".join(parts)


def _build_node_contracts(
    type_name: str,
    properties: list[dict[str, Any]],
    *,
    type_version: int | float,
    resources: list[str],
    operations: dict[str, list[str]],
) -> list[NodeContract]:
    contexts: list[tuple[str | None, str | None]] = []
    if operations:
        if resources:
            for resource in resources:
                for operation in operations.get(resource, []) or [None]:
                    contexts.append((resource, operation))
        else:
            for operation in operations.get("default", []) or [None]:
                contexts.append((None, operation))
    elif resources:
        contexts.extend((resource, None) for resource in resources)
    else:
        contexts.append((None, None))

    contracts: list[NodeContract] = []
    seen_keys: set[str] = set()
    for resource, operation in contexts:
        contract = NodeContract(
            key=_contract_key(
                type_name,
                type_version,
                resource=resource,
                operation=operation,
            ),
            type_name=type_name,
            type_version=type_version,
            resource=resource,
            operation=operation,
            key_properties=_extract_key_properties(
                properties,
                version=type_version,
                resource=resource,
                operation=operation,
            ),
        )
        search_tokens = [type_name, resource or "", operation or ""]
        search_tokens.extend(str(prop.get("name") or "") for prop in contract.key_properties)
        contract.search_text = " ".join(token for token in search_tokens if token).lower()
        if contract.key in seen_keys:
            continue
        seen_keys.add(contract.key)
        contracts.append(contract)

    if not contracts:
        contracts.append(
            NodeContract(
                key=_contract_key(type_name, type_version, resource=None, operation=None),
                type_name=type_name,
                type_version=type_version,
                key_properties=_extract_key_properties(properties, version=type_version),
            )
        )

    return contracts


def _parse_node(raw: dict[str, Any]) -> NodeInfo | None:
    type_name = str(raw.get("name") or "").strip()
    if not type_name:
        return None
    properties = raw.get("properties")
    if not isinstance(properties, list):
        properties = []
    type_version = _extract_version(raw)
    resources, operations = _extract_resources_and_ops(properties, version=type_version)
    contracts = _build_node_contracts(
        type_name,
        properties,
        type_version=type_version,
        resources=resources,
        operations=operations,
    )
    node = NodeInfo(
        type_name=type_name,
        display_name=str(raw.get("displayName") or type_name),
        description=str(raw.get("description") or ""),
        type_version=type_version,
        credentials=_extract_credentials(raw),
        category=_extract_category(raw),
        is_trigger=_is_trigger(raw),
        resources=resources,
        operations=operations,
        key_properties=list(contracts[0].key_properties),
        contracts=contracts,
    )
    node.card = extract_node_card(node)
    node.search_text = (
        node.card.search_text if node.card else f"{node.display_name} {node.type_name}".lower()
    )
    return node


def parse_nodes_json(data: Any) -> list[NodeInfo]:
    """Parse n8n /types/nodes.json output."""
    if isinstance(data, dict):
        raw_list = data.get("data") or data.get("nodes") or []
    elif isinstance(data, list):
        raw_list = data
    else:
        log.warning("nodes.json unexpected format: %s", type(data))
        return []

    by_type: dict[str, NodeInfo] = {}
    for raw in raw_list:
        if not isinstance(raw, dict):
            continue
        node = _parse_node(raw)
        if not node:
            continue
        existing = by_type.get(node.type_name)
        if existing is None or node.type_version > existing.type_version:
            by_type[node.type_name] = node

    nodes = list(by_type.values())
    log.info("Loaded %d unique nodes from nodes.json", len(nodes))
    return nodes


async def fetch_nodes_from_n8n(base_url: str) -> list[NodeInfo]:
    """The modern n8n endpoint requires auth; use the local nodes.json artifact instead."""
    log.debug("fetch_nodes_from_n8n skipped for %s (use scripts/fetch_nodes.py)", base_url)
    return []


def load_nodes_from_file(path: str | Path) -> list[NodeInfo]:
    source = Path(path)
    if not source.exists():
        log.warning("nodes.json not found at %s", path)
        return []
    try:
        data = json.loads(source.read_text(encoding="utf-8"))
        return parse_nodes_json(data)
    except Exception as exc:
        log.warning("Failed to load nodes.json from %s: %s", path, exc)
        return []


def _template_from_record(item: dict[str, Any]) -> WorkflowTemplate:
    card = extract_workflow_card(item)
    template = workflow_template_from_card(card)
    template.id = item.get("id", card.id)
    template.name = str(item.get("name") or card.name)
    template.description = str(item.get("description") or card.description)
    template.categories = list(card.categories)
    template.node_types = list(card.node_types)
    template.workflow_json = {}
    template.card = card
    template.search_text = card.search_text
    return template


def load_templates_from_file(path: str | Path) -> list[WorkflowTemplate]:
    """Load either legacy templates.json or the new sanitized card array."""
    source = Path(path)
    if not source.exists():
        log.info("templates.json not found at %s — skipping", path)
        return []
    try:
        data = json.loads(source.read_text(encoding="utf-8"))
        if not isinstance(data, list):
            data = data.get("templates", data.get("data", []))
        templates: list[WorkflowTemplate] = []
        seen_ids: set[int | str] = set()
        for item in data:
            if not isinstance(item, dict):
                continue
            item_id = item.get("id")
            if item_id is not None and item_id in seen_ids:
                continue
            if item_id is not None:
                seen_ids.add(item_id)
            if "summary" in item and "fingerprint" in item and "workflow" not in item:
                card = WorkflowCard(
                    id=item.get("id", ""),
                    name=str(item.get("name") or "Untitled"),
                    summary=str(item.get("summary") or ""),
                    description=str(item.get("description") or item.get("summary") or ""),
                    categories=list(item.get("categories") or []),
                    node_types=list(item.get("nodeTypes") or []),
                    services=list(item.get("services") or []),
                    operations=list(item.get("operations") or []),
                    trigger_types=list(item.get("triggerTypes") or []),
                    risk_flags=list(item.get("riskFlags") or []),
                    node_count=int(item.get("nodeCount") or 0),
                    trigger_count=int(item.get("triggerCount") or 0),
                    fingerprint=str(item.get("fingerprint") or ""),
                    source_url=str(item.get("sourceUrl") or ""),
                    search_text="",
                )
                card.search_text = " ".join(
                    [
                        card.name,
                        card.summary,
                        card.description,
                        *card.categories,
                        *card.node_types,
                        *card.services,
                        *card.operations,
                    ]
                ).lower()
                templates.append(workflow_template_from_card(card))
                continue
            templates.append(_template_from_record(item))
        log.info("Loaded %d templates from %s", len(templates), path)
        return templates
    except Exception as exc:
        log.warning("Failed to load templates from %s: %s", path, exc)
        return []


def load_workflow_templates_from_jsonl(path: str | Path) -> list[WorkflowTemplate]:
    cards = load_workflow_cards_jsonl(path)
    templates = [workflow_template_from_card(card) for card in cards]
    log.info("Loaded %d workflow cards from %s", len(templates), path)
    return templates


def _credential_is_oauth(name: str, extends: list[str], properties: list[dict[str, Any]]) -> bool:
    if "oauth" in name.lower():
        return True
    if any("oauth" in value.lower() for value in extends):
        return True
    property_names = {str(prop.get("name") or "") for prop in properties if isinstance(prop, dict)}
    return bool(property_names & _OAUTH_PROP_SIGNATURES)


def _icon_url_value(raw_icon: Any) -> str:
    if isinstance(raw_icon, dict):
        return str(raw_icon.get("light") or raw_icon.get("dark") or "")
    return str(raw_icon or "")


def _parse_credential_type(raw: dict[str, Any]) -> CredentialTypeInfo | None:
    name = str(raw.get("name") or "")
    if not name:
        return None
    extends = raw.get("extends") or []
    if not isinstance(extends, list):
        extends = [extends]
    extends = [str(item) for item in extends]
    properties = raw.get("properties") or []
    if not isinstance(properties, list):
        properties = []
    return CredentialTypeInfo(
        name=name,
        display_name=str(raw.get("displayName") or name),
        icon_url=_icon_url_value(raw.get("iconUrl")),
        documentation_url=str(raw.get("documentationUrl") or ""),
        properties=properties,
        extends=extends,
        generic_auth=bool(raw.get("genericAuth")),
        is_oauth=_credential_is_oauth(name, extends, properties),
    )


def parse_credentials_json(data: Any) -> list[CredentialTypeInfo]:
    if isinstance(data, dict):
        raw_list = data.get("data") or data.get("credentials") or []
    elif isinstance(data, list):
        raw_list = data
    else:
        log.warning("credentials.json unexpected format: %s", type(data))
        return []
    by_name: dict[str, CredentialTypeInfo] = {}
    for raw in raw_list:
        if not isinstance(raw, dict):
            continue
        parsed = _parse_credential_type(raw)
        if parsed:
            by_name[parsed.name] = parsed
    log.info("Loaded %d credential types from credentials.json", len(by_name))
    return list(by_name.values())


def load_credentials_from_file(path: str | Path) -> list[CredentialTypeInfo]:
    source = Path(path)
    if not source.exists():
        log.warning("credentials.json not found at %s", path)
        return []
    try:
        data = json.loads(source.read_text(encoding="utf-8"))
        return parse_credentials_json(data)
    except Exception as exc:
        log.warning("Failed to load credentials.json from %s: %s", path, exc)
        return []
