"""n8n node şemalarını ve workflow template'lerini yükler."""

import json
import logging
from pathlib import Path
from typing import Any

from .models import CredentialTypeInfo, NodeInfo, WorkflowTemplate

log = logging.getLogger(__name__)

_TRIGGER_GROUPS = {"trigger"}
_TRIGGER_NAME_SUFFIXES = ("trigger", "Trigger")


def _is_trigger(raw: dict[str, Any]) -> bool:
    group = raw.get("group", [])
    if isinstance(group, list):
        if any(g.lower() == "trigger" for g in group):
            return True
    name: str = raw.get("name", "")
    return name.lower().endswith("trigger") or name.lower().endswith("triggers")


def _extract_version(raw: dict[str, Any]) -> int:
    """En yüksek typeVersion'ı döner."""
    v = raw.get("version", raw.get("defaultVersion", 1))
    if isinstance(v, list):
        return max(v) if v else 1
    if isinstance(v, (int, float)):
        return int(v)
    return 1


def _extract_credentials(raw: dict[str, Any]) -> list[str]:
    creds = raw.get("credentials", [])
    if not isinstance(creds, list):
        return []
    return [c["name"] for c in creds if isinstance(c, dict) and "name" in c]


def _extract_category(raw: dict[str, Any]) -> str:
    codex = raw.get("codex", {})
    if isinstance(codex, dict):
        cats = codex.get("categories", [])
        if cats:
            return cats[0]
    return "Core"


def _extract_resources_and_ops(
    properties: list[dict],
) -> tuple[list[str], dict[str, list[str]]]:
    """resource/operation property'lerinden kaynakları ve operasyonları çıkarır."""
    resources: list[str] = []
    operations: dict[str, list[str]] = {}

    resource_prop = next((p for p in properties if p.get("name") == "resource"), None)
    operation_prop = next((p for p in properties if p.get("name") == "operation"), None)

    if resource_prop:
        opts = resource_prop.get("options", [])
        resources = [o["value"] for o in opts if isinstance(o, dict) and "value" in o]

    if operation_prop:
        opts = operation_prop.get("options", [])
        # displayOptions koşuluna göre gruplama denemiyoruz — flat liste yeterli
        all_ops = [o["value"] for o in opts if isinstance(o, dict) and "value" in o]
        if resources:
            # İlk kaynak altına koy (genel gösterim)
            for res in resources:
                operations[res] = all_ops
        else:
            operations["default"] = all_ops

    return resources, operations


def _as_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None


def _version_condition_matches(condition: Any, version: int | float) -> bool:
    current = _as_float(version)
    if current is None:
        return False

    if isinstance(condition, dict):
        raw_ops = condition.get("_cnd")
        if not isinstance(raw_ops, dict):
            raw_ops = condition
        for op, expected in raw_ops.items():
            expected_number = _as_float(expected)
            if expected_number is None:
                return False
            if op in {"eq", "equals"} and current != expected_number:
                return False
            if op in {"neq", "notEquals"} and current == expected_number:
                return False
            if op == "gte" and current < expected_number:
                return False
            if op == "gt" and current <= expected_number:
                return False
            if op == "lte" and current > expected_number:
                return False
            if op == "lt" and current >= expected_number:
                return False
        return True

    expected = _as_float(condition)
    return expected is not None and current == expected


def _version_conditions_match(values: Any, version: int | float) -> bool:
    if isinstance(values, list):
        return any(_version_condition_matches(value, version) for value in values)
    return _version_condition_matches(values, version)


def _display_options_match_latest(prop: dict, version: int | float) -> bool:
    display_options = prop.get("displayOptions")
    if not isinstance(display_options, dict):
        return True

    show = display_options.get("show")
    if isinstance(show, dict):
        if any(key != "@version" for key in show):
            return False
        version_show = show.get("@version")
        if version_show is None or not _version_conditions_match(version_show, version):
            return False

    hide = display_options.get("hide")
    if isinstance(hide, dict):
        version_hide = hide.get("@version")
        if version_hide is not None and _version_conditions_match(version_hide, version):
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
        condensed = {
            "name": mode.get("name"),
            "displayName": mode.get("displayName"),
            "type": mode.get("type"),
        }
        type_options = _extract_type_options_metadata(mode.get("typeOptions"))
        if type_options:
            condensed["typeOptions"] = type_options
        result.append({key: value for key, value in condensed.items() if value is not None})
    return result


def _extract_key_properties(properties: list[dict], version: int | float) -> list[dict]:
    """Latest/default node version'a uyan top-level parametreleri döner."""
    result = []
    for prop in properties:
        if prop.get("name") in ("resource", "operation"):
            # Zaten resources/operations'da var
            continue
        if not _display_options_match_latest(prop, version):
            continue
        condensed = {
            "name": prop.get("name"),
            "displayName": prop.get("displayName"),
            "type": prop.get("type"),
            "required": prop.get("required", False),
            "default": prop.get("default"),
        }
        if prop.get("type") == "options" and "options" in prop:
            condensed["options"] = [o.get("value") for o in prop["options"] if isinstance(o, dict)]
        type_options = _extract_type_options_metadata(prop.get("typeOptions"))
        if type_options:
            condensed["typeOptions"] = type_options
        modes = _extract_modes_metadata(prop.get("modes"))
        if modes:
            condensed["modes"] = modes
        result.append(condensed)

    selected = result[:8]
    selected_names = {prop.get("name") for prop in selected}
    for prop in result[8:]:
        if prop.get("type") == "resourceLocator" and prop.get("name") not in selected_names:
            selected.append(prop)
    return selected


def _parse_node(raw: dict[str, Any]) -> NodeInfo | None:
    type_name: str = raw.get("name", "")
    if not type_name:
        return None

    display_name: str = raw.get("displayName", type_name)
    description: str = raw.get("description", "")
    properties: list[dict] = raw.get("properties", [])
    if not isinstance(properties, list):
        properties = []

    version = _extract_version(raw)
    resources, operations = _extract_resources_and_ops(properties)
    key_props = _extract_key_properties(properties, version)

    node = NodeInfo(
        type_name=type_name,
        display_name=display_name,
        description=description,
        type_version=version,
        credentials=_extract_credentials(raw),
        category=_extract_category(raw),
        is_trigger=_is_trigger(raw),
        resources=resources,
        operations=operations,
        key_properties=key_props,
    )
    node.search_text = f"{display_name} {description} {type_name}".lower()
    return node


def parse_nodes_json(data: Any) -> list[NodeInfo]:
    """
    n8n /types/nodes.json çıktısını parse eder.
    Hem list hem dict ({"data": [...]}) formatını destekler.
    """
    if isinstance(data, dict):
        # {"data": [...]} veya {"nodes": [...]} formatı
        raw_list = data.get("data") or data.get("nodes") or []
    elif isinstance(data, list):
        raw_list = data
    else:
        log.warning("nodes.json unexpected format: %s", type(data))
        return []

    # Parse all, then deduplicate keeping highest typeVersion per type_name
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
    """
    n8n instance'ından node type şemalarını çekmeye çalışır.

    Strateji (sırayla):
    1. /home/node/.cache/n8n/public/types/nodes.json — container cache (en güvenilir)
       Bu dosya docker cp ile alınıp data/nodes.json olarak kaydedilir.
       Bkz: scripts/fetch_nodes.py
    2. /types/nodes.json HTTP endpoint — auth gerektiriyor (modern n8n), skip edilir.

    Pratikte: bu fonksiyon çağrıldığında data/nodes.json zaten var olmalı.
    Yoksa boş registry ile devam edilir (fallback mode).
    """
    # n8n'in /types/nodes.json endpoint'i modern versiyonlarda auth gerektiriyor.
    # Bu nedenle HTTP fetch'i atlıyor, data/ dizininden yüklenmesini bekliyoruz.
    # Bkz: registry.py -> initialize_from_n8n -> load_from_files
    log.debug("fetch_nodes_from_n8n skipped (use load_from_files with docker cp output)")
    return []


def load_nodes_from_file(path: str | Path) -> list[NodeInfo]:
    """Daha önce kaydedilmiş nodes.json dosyasından yükler."""
    p = Path(path)
    if not p.exists():
        log.warning("nodes.json not found at %s", path)
        return []
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return parse_nodes_json(data)
    except Exception as exc:
        log.warning("Failed to load nodes.json from %s: %s", path, exc)
        return []


def load_templates_from_file(path: str | Path) -> list[WorkflowTemplate]:
    """
    Yerel templates.json dosyasından template'leri yükler.
    fetch_templates.py tarafından üretilen format:
    [{"id": N, "name": ..., "description": ..., "categories": [...],
      "nodeTypes": [...], "workflow": {...}}]
    """
    p = Path(path)
    if not p.exists():
        log.info("templates.json not found at %s — skipping", path)
        return []
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        if not isinstance(data, list):
            data = data.get("templates", data.get("data", []))
        templates: list[WorkflowTemplate] = []
        seen_ids: set = set()
        for item in data:
            if not isinstance(item, dict):
                continue

            # Deduplication — aynı template iki kez yüklenmesin
            item_id = item.get("id")
            if item_id is not None:
                if item_id in seen_ids:
                    continue
                seen_ids.add(item_id)

            # fetch_templates.py çıktısı: nodeTypes key'i var
            node_types: list[str] = item.get("nodeTypes", [])
            # Fallback: workflow.nodes'tan çek
            if not node_types:
                wf_nodes = item.get("workflow", {}).get("nodes", [])
                node_types = list(
                    {n.get("type", "") for n in wf_nodes if isinstance(n, dict) and n.get("type")}
                )

            categories: list[str] = [
                c.get("name", "") if isinstance(c, dict) else str(c)
                for c in item.get("categories", [])
            ]

            name = item.get("name", "Untitled")
            description = item.get("description", "")
            t = WorkflowTemplate(
                id=item.get("id", 0),
                name=name,
                description=description,
                categories=categories,
                node_types=list(filter(None, node_types)),
                workflow_json=item.get("workflow", {}),
            )
            t.search_text = (
                f"{name} {description} {' '.join(categories)} {' '.join(node_types)}"
            ).lower()
            templates.append(t)
        log.info("Loaded %d templates from %s", len(templates), path)
        return templates
    except Exception as exc:
        log.warning("Failed to load templates from %s: %s", path, exc)
        return []


_OAUTH_PROP_SIGNATURES = {
    "oauthTokenData",
    "grantType",
    "authUrl",
    "accessTokenUrl",
    "authQueryParameters",
}


def _credential_is_oauth(name: str, extends: list[str], properties: list[dict]) -> bool:
    if "oauth" in name.lower():
        return True
    if any("oauth" in str(item).lower() for item in extends):
        return True
    prop_names = {p.get("name") for p in properties if isinstance(p, dict)}
    return bool(prop_names & _OAUTH_PROP_SIGNATURES)


def _icon_url_value(raw_icon: Any) -> str:
    """n8n iconUrl is a string or a {light,dark} object — return the light path."""
    if isinstance(raw_icon, dict):
        return str(raw_icon.get("light") or raw_icon.get("dark") or "")
    return str(raw_icon or "")


def _parse_credential_type(raw: dict[str, Any]) -> CredentialTypeInfo | None:
    name = raw.get("name", "")
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
        display_name=raw.get("displayName", name),
        icon_url=_icon_url_value(raw.get("iconUrl")),
        documentation_url=str(raw.get("documentationUrl") or ""),
        properties=properties,
        extends=extends,
        generic_auth=bool(raw.get("genericAuth")),
        is_oauth=_credential_is_oauth(name, extends, properties),
    )


def parse_credentials_json(data: Any) -> list[CredentialTypeInfo]:
    """Parse n8n credentials.json (list, or {"data": [...]}) into CredentialTypeInfo."""
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
    """Load credential type definitions from a saved credentials.json file."""
    p = Path(path)
    if not p.exists():
        log.warning("credentials.json not found at %s", path)
        return []
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return parse_credentials_json(data)
    except Exception as exc:
        log.warning("Failed to load credentials.json from %s: %s", path, exc)
        return []
