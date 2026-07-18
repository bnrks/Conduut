"""Deterministic runtime guards injected into scheduled side-effect workflows."""

import json
import re
from collections import deque
from typing import Any

_SCHEDULE = "n8n-nodes-base.scheduleTrigger"
_GMAIL = "n8n-nodes-base.gmail"
_SHEETS = "n8n-nodes-base.googleSheets"
_GUARD_PREFIX = "[Conduut] Validate identity"


def _targets(connections: dict[str, Any], source: str) -> list[str]:
    connection = connections.get(source)
    main = connection.get("main") if isinstance(connection, dict) else None
    result: list[str] = []
    if isinstance(main, list):
        for group in main:
            if isinstance(group, list):
                result.extend(
                    str(item.get("node"))
                    for item in group
                    if isinstance(item, dict) and item.get("node")
                )
    return result


def _downstream_sheets_key(
    start: str, nodes_by_name: dict[str, dict[str, Any]], connections: dict[str, Any]
) -> str | None:
    queue = deque(_targets(connections, start))
    seen: set[str] = set()
    while queue:
        name = queue.popleft()
        if name in seen:
            continue
        seen.add(name)
        node = nodes_by_name.get(name, {})
        parameters = node.get("parameters") if isinstance(node.get("parameters"), dict) else {}
        if node.get("type") == _SHEETS and str(parameters.get("operation") or "").lower() in {
            "update",
            "appendorupdate",
        }:
            columns = (
                parameters.get("columns") if isinstance(parameters.get("columns"), dict) else {}
            )
            matching = columns.get("matchingColumns")
            if isinstance(matching, list) and len(matching) == 1 and str(matching[0]).strip():
                return str(matching[0]).strip()
        queue.extend(_targets(connections, name))
    return None


def _guard_code(key: str) -> str:
    encoded = json.dumps(key, ensure_ascii=False)
    return (
        f"const key = {encoded};\n"
        "const items = $input.all();\n"
        "const seen = new Set();\n"
        "for (const item of items) {\n"
        "  const value = item.json?.[key];\n"
        "  if (value === undefined || value === null || String(value).trim() === '') {\n"
        "    throw new Error(`Conduut identity guard: ${key} is empty`);\n"
        "  }\n"
        "  const identity = String(value);\n"
        "  if (seen.has(identity)) {\n"
        "    throw new Error(`Conduut identity guard: duplicate ${key}`);\n"
        "  }\n"
        "  seen.add(identity);\n"
        "}\n"
        "return items;"
    )


def inject_schedule_identity_guards(
    nodes: list[dict[str, Any]], connections: dict[str, Any]
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Place a unique/nonblank identity guard before Gmail in scheduled chains."""

    if not any(node.get("type") == _SCHEDULE for node in nodes):
        return nodes, connections
    nodes_by_name = {str(node.get("name")): node for node in nodes if node.get("name")}
    for gmail_name, gmail in list(nodes_by_name.items()):
        parameters = gmail.get("parameters") if isinstance(gmail.get("parameters"), dict) else {}
        operation = str(parameters.get("operation") or "send").lower()
        if gmail.get("type") != _GMAIL or operation != "send":
            continue
        key = _downstream_sheets_key(gmail_name, nodes_by_name, connections)
        if not key:
            continue
        safe_key = re.sub(r"[^A-Za-z0-9_-]+", "-", key).strip("-")[:32] or "key"
        guard_name = f"{_GUARD_PREFIX}: {safe_key}"
        if guard_name in nodes_by_name:
            continue
        position = gmail.get("position") if isinstance(gmail.get("position"), list) else [0, 0]
        guard = {
            "id": f"conduut-identity-{safe_key}",
            "name": guard_name,
            "type": "n8n-nodes-base.code",
            "typeVersion": 2,
            "position": [int(position[0]) - 220, int(position[1])],
            "parameters": {"mode": "runOnceForAllItems", "jsCode": _guard_code(key)},
        }
        rewired = False
        for source, connection in connections.items():
            if source == guard_name or not isinstance(connection, dict):
                continue
            main = connection.get("main")
            if not isinstance(main, list):
                continue
            for group in main:
                if not isinstance(group, list):
                    continue
                for target in group:
                    if isinstance(target, dict) and target.get("node") == gmail_name:
                        target["node"] = guard_name
                        rewired = True
        if not rewired:
            continue
        connections[guard_name] = {"main": [[{"node": gmail_name, "type": "main", "index": 0}]]}
        nodes.append(guard)
        nodes_by_name[guard_name] = guard
    return nodes, connections
