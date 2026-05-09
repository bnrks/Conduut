"""Workflow reference and trigger helpers."""

from typing import Any
from uuid import uuid4

from src.agent.tools.constants import _WEBHOOK_TRIGGER_TYPE
from src.registry import registry


def _workflow_trigger_nodes(workflow: dict[str, Any], node_type: str) -> list[dict[str, Any]]:
    nodes = workflow.get("nodes")
    if not isinstance(nodes, list):
        return []
    return [node for node in nodes if isinstance(node, dict) and node.get("type") == node_type]


def _conduut_webhook_path(workflow_id: str, node_id: str | None = None) -> str:
    source = "-".join(item for item in (workflow_id, node_id) if item)
    safe = "".join(char if char.isalnum() else "-" for char in source).strip("-").lower()
    return f"conduut-run-{safe or uuid4().hex[:12]}"


def _webhook_type_version() -> int | float:
    schema = registry.get_node_schema(_WEBHOOK_TRIGGER_TYPE)
    if isinstance(schema, dict) and isinstance(schema.get("typeVersion"), int | float):
        return schema["typeVersion"]
    return 2.1
