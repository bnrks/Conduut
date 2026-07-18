"""Small, explicit output contracts used by static dataflow checks.

Contracts intentionally describe only properties that Conduut can rely on. A
dynamic contract means the node type is understood but its fields depend on
runtime input/configuration. Missing contracts stay visible as shadow findings.
"""

from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Mapping


class OutputShape(StrEnum):
    PASSTHROUGH = "passthrough"
    KNOWN = "known"
    DYNAMIC = "dynamic"


@dataclass(frozen=True, slots=True)
class NodeContract:
    shape: OutputShape
    fields: frozenset[str] = frozenset()
    side_effect: bool = False
    mutation: bool = False
    identity_required: bool = False

    @property
    def pass_through(self) -> bool:
        return self.shape is OutputShape.PASSTHROUGH

    def field_is_available(self, field: str) -> bool | None:
        """Return True/False when provable, otherwise None for dynamic output."""

        if self.shape is OutputShape.DYNAMIC:
            return None
        if self.shape is OutputShape.PASSTHROUGH:
            return None
        return field in self.fields


_DYNAMIC_TYPES = {
    "n8n-nodes-base.code",
    "n8n-nodes-base.function",
    "n8n-nodes-base.functionItem",
    "n8n-nodes-base.googleSheets",
    "n8n-nodes-base.httpRequest",
    "n8n-nodes-base.merge",
    "n8n-nodes-base.set",
    "n8n-nodes-base.webhook",
}

_PASSTHROUGH_TYPES = {
    "n8n-nodes-base.filter",
    "n8n-nodes-base.if",
    "n8n-nodes-base.noOp",
    "n8n-nodes-base.scheduleTrigger",
}


def output_contract(node: Mapping[str, Any]) -> NodeContract | None:
    """Resolve the conservative output contract for one configured node."""

    node_type = str(node.get("type") or "")
    parameters = node.get("parameters")
    params = parameters if isinstance(parameters, Mapping) else {}

    if node_type == "n8n-nodes-base.gmail":
        resource = str(params.get("resource") or "message").lower()
        operation = str(params.get("operation") or "send").lower()
        if resource == "message" and operation == "send":
            # Gmail send replaces the business item with the provider receipt.
            return NodeContract(
                OutputShape.KNOWN,
                frozenset({"id", "threadId", "labelIds"}),
                side_effect=True,
                mutation=True,
            )
        return NodeContract(OutputShape.DYNAMIC)

    if node_type == "n8n-nodes-base.googleSheets":
        operation = str(params.get("operation") or "").lower()
        if operation in {"update", "appendorupdate", "append"}:
            return NodeContract(
                OutputShape.DYNAMIC,
                side_effect=True,
                mutation=True,
                identity_required=operation in {"update", "appendorupdate"},
            )
        return NodeContract(OutputShape.DYNAMIC)

    if node_type in _PASSTHROUGH_TYPES:
        return NodeContract(OutputShape.PASSTHROUGH)
    if node_type in _DYNAMIC_TYPES:
        return NodeContract(OutputShape.DYNAMIC)
    return None
