"""Classify n8n nodes as outbound side-effect (action) nodes.

A side-effect node performs an external action when it runs (sends an email,
writes a row, posts a message, mutating HTTP). The sandbox test neutralizes
these (sets ``disabled=true``) so a test run produces no real external effect.
"""

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
