"""Classify and safely probe outbound side-effect (action) nodes.

A side-effect node performs an external action when it runs (sends an email,
writes a row, posts a message, mutating HTTP). Known actions are replaced with
expression-aware Set nodes that expose a PII-redacted probe ledger and emulate
the real action's output shape. Unknown actions remain disabled and are marked
as partial coverage; they are never executed by the sandbox.
"""

import json
from dataclasses import dataclass
from typing import Any

_HTTP_REQUEST_NODE_TYPE = "n8n-nodes-base.httpRequest"
_GMAIL_NODE_TYPE = "n8n-nodes-base.gmail"
_SHEETS_NODE_TYPE = "n8n-nodes-base.googleSheets"

# Read-only HTTP methods never mutate remote state.
_SAFE_HTTP_METHODS = {"GET", "HEAD", "OPTIONS"}
# Gmail operations that only read (everything else — send/reply/create — mutates).
_GMAIL_READ_OPERATIONS = {"get", "getall", "search"}
# Google Sheets operations that mutate the spreadsheet.
_SHEETS_WRITE_OPERATIONS = {"append", "update", "appendorupdate", "delete", "clear"}

# Nodes whose default operation is always an outbound action.
_ALWAYS_SIDE_EFFECT_TYPES = {
    "n8n-nodes-base.slack",
    "n8n-nodes-base.emailSend",
    "n8n-nodes-base.telegram",
    "n8n-nodes-base.discord",
    "n8n-nodes-base.googleDrive",
    "n8n-nodes-base.notion",
    "n8n-nodes-base.airtable",
}

_PROBE_PREFIX = "__conduut_probe"


@dataclass(frozen=True)
class ActionProbe:
    name: str
    kind: str
    covered: bool
    original_type: str


def _operation(node: dict[str, Any]) -> str:
    parameters = node.get("parameters")
    if not isinstance(parameters, dict):
        return ""
    return str(parameters.get("operation") or "").lower()


def is_side_effect_node(node: dict[str, Any]) -> bool:
    node_type = str(node.get("type") or "")
    if node_type == _HTTP_REQUEST_NODE_TYPE:
        parameters = node.get("parameters") if isinstance(node.get("parameters"), dict) else {}
        method = str(parameters.get("method") or "GET").upper()
        return method not in _SAFE_HTTP_METHODS
    if node_type == _GMAIL_NODE_TYPE:
        # Default operation is "send"; anything not in the read set mutates.
        return (_operation(node) or "send") not in _GMAIL_READ_OPERATIONS
    if node_type == _SHEETS_NODE_TYPE:
        return _operation(node) in _SHEETS_WRITE_OPERATIONS
    return node_type in _ALWAYS_SIDE_EFFECT_TYPES


def find_action_nodes(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [node for node in nodes if isinstance(node, dict) and is_side_effect_node(node)]


def _expression_body(value: Any) -> str:
    """Convert an n8n value/expression into a JavaScript expression body."""

    if isinstance(value, str):
        stripped = value.strip()
        if stripped.startswith("={{") and stripped.endswith("}}"):
            return stripped[3:-2].strip()
        if stripped.startswith("="):
            return stripped[1:].strip()
    return json.dumps(value, ensure_ascii=False, default=str)


def _assignment(name: str, value: Any, value_type: str = "string") -> dict[str, Any]:
    return {
        "id": f"conduut-{len(name)}-{name.replace('.', '-')[:32]}",
        "name": name,
        "type": value_type,
        "value": value,
    }


def _replace_with_set_probe(
    node: dict[str, Any],
    assignments: list[dict[str, Any]],
    probe_assignments: list[dict[str, Any]],
) -> None:
    assignments.extend(probe_assignments)
    node["type"] = "n8n-nodes-base.set"
    node["typeVersion"] = 3.4
    node["parameters"] = {
        "mode": "manual",
        "duplicateItem": False,
        "assignments": {"assignments": assignments},
        "includeOtherFields": False,
        "options": {},
    }
    node.pop("credentials", None)
    node.pop("disabled", None)


def _gmail_probe(node: dict[str, Any]) -> bool:
    parameters = node.get("parameters") if isinstance(node.get("parameters"), dict) else {}
    if (_operation(node) or "send") != "send":
        return False
    send_to = parameters.get("sendTo", "")
    subject = parameters.get("subject", "")
    message = parameters.get("message", "")
    assignments = [
        _assignment("id", "conduut-sandbox-message"),
        _assignment("threadId", "conduut-sandbox-thread"),
        _assignment("labelIds", '={{ ["SENT"] }}', "array"),
    ]
    _replace_with_set_probe(
        node,
        assignments,
        [
            _assignment(_PROBE_PREFIX, "gmail_send"),
            _assignment(f"{_PROBE_PREFIX}_target", send_to),
            _assignment(f"{_PROBE_PREFIX}_subject", subject),
            _assignment(f"{_PROBE_PREFIX}_message", message),
        ],
    )
    return True


def _sheets_update_probe(node: dict[str, Any]) -> bool:
    parameters = node.get("parameters") if isinstance(node.get("parameters"), dict) else {}
    if _operation(node) not in {"update", "appendorupdate"}:
        return False
    columns = parameters.get("columns") if isinstance(parameters.get("columns"), dict) else {}
    values = columns.get("value") if isinstance(columns.get("value"), dict) else {}
    matching = columns.get("matchingColumns")
    if not isinstance(matching, list):
        matching = []
    assignments = [
        _assignment(str(key), value, "string") for key, value in values.items() if str(key).strip()
    ]
    probe_assignments = [
        _assignment(_PROBE_PREFIX, "sheets_update"),
        _assignment(f"{_PROBE_PREFIX}_matching_columns", json.dumps(matching)),
    ]
    for index, column in enumerate(matching):
        column_name = str(column)
        probe_assignments.extend(
            [
                _assignment(f"{_PROBE_PREFIX}_matching_key_{index}", column_name),
                _assignment(
                    f"{_PROBE_PREFIX}_matching_value_{index}",
                    values.get(column_name, f"={{ $json[{json.dumps(column_name)}] }}"),
                ),
            ]
        )
    _replace_with_set_probe(
        node,
        assignments,
        probe_assignments,
    )
    return True


def replace_action_nodes_with_probes(nodes: list[dict[str, Any]]) -> list[ActionProbe]:
    """Replace supported actions with safe probes and disable unsupported ones."""

    probes: list[ActionProbe] = []
    for node in nodes:
        if not isinstance(node, dict) or not is_side_effect_node(node):
            continue
        name = str(node.get("name") or "")
        node_type = str(node.get("type") or "")
        covered = False
        kind = "unsupported_action"
        if node_type == _GMAIL_NODE_TYPE:
            covered = _gmail_probe(node)
            kind = "gmail_send" if covered else kind
        elif node_type == _SHEETS_NODE_TYPE:
            covered = _sheets_update_probe(node)
            kind = "sheets_update" if covered else kind
        if not covered:
            node["disabled"] = True
        probes.append(ActionProbe(name=name, kind=kind, covered=covered, original_type=node_type))
    return probes


def neutralize_action_nodes(nodes: list[dict[str, Any]]) -> list[str]:
    """Set ``disabled=True`` on every side-effect node in place.

    n8n skips a disabled node (it acts as a pass-through), so the node performs
    no external action during the test run. Returns the neutralized node names.
    """

    neutralized: list[str] = []
    for node in nodes:
        if isinstance(node, dict) and is_side_effect_node(node):
            node["disabled"] = True
            neutralized.append(str(node.get("name") or ""))
    return neutralized
