"""Stable semantic fingerprints for normalized workflow definitions."""

import hashlib
import json
from collections.abc import Mapping, Sequence
from typing import Any

from src.agent.schemas import WorkflowNode

_NODE_VOLATILE_KEYS = {
    "id",
    "position",
    "webhookId",
}
_TIMESTAMP_KEYS = {
    "createdAt",
    "updatedAt",
    "created_at",
    "updated_at",
    "timestamp",
    "timestamps",
}


def _plain_node(node: WorkflowNode | Mapping[str, Any]) -> dict[str, Any]:
    if isinstance(node, WorkflowNode):
        return node.model_dump(exclude_none=True)
    return dict(node)


def _semantic_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): _semantic_value(nested)
            for key, nested in value.items()
            if str(key) not in _TIMESTAMP_KEYS
        }
    if isinstance(value, list):
        return [_semantic_value(nested) for nested in value]
    if isinstance(value, tuple):
        return [_semantic_value(nested) for nested in value]
    return value


def _semantic_node(node: WorkflowNode | Mapping[str, Any]) -> dict[str, Any]:
    value = _plain_node(node)
    for key in _NODE_VOLATILE_KEYS:
        value.pop(key, None)
    return _semantic_value(value)


def workflow_semantic_fingerprint(
    nodes: Sequence[WorkflowNode | Mapping[str, Any]],
    connections: Mapping[str, Any] | None,
    settings: Mapping[str, Any] | None = None,
) -> str:
    """Hash behavior-affecting node/config/graph data, excluding volatile UI metadata."""

    semantic_nodes = [_semantic_node(node) for node in nodes]
    semantic_nodes.sort(
        key=lambda node: (
            str(node.get("name") or "") if isinstance(node, dict) else "",
            str(node.get("type") or "") if isinstance(node, dict) else "",
        )
    )
    payload = {
        "nodes": semantic_nodes,
        "connections": _semantic_value(dict(connections or {})),
        "settings": _semantic_value(dict(settings or {})),
    }
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def workflow_fingerprint(workflow: Mapping[str, Any]) -> str:
    """Stable package-level fingerprint for an n8n workflow payload."""

    nodes = workflow.get("nodes")
    connections = workflow.get("connections")
    settings = workflow.get("settings")
    return workflow_semantic_fingerprint(
        nodes if isinstance(nodes, Sequence) and not isinstance(nodes, str | bytes) else [],
        connections if isinstance(connections, Mapping) else {},
        settings if isinstance(settings, Mapping) else {},
    )
