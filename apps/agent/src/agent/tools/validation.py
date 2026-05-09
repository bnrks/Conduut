"""Workflow validation and normalization helpers for tool inputs."""

from typing import Any

import structlog
from pydantic_ai import ModelRetry

from src.agent.schemas import WorkflowInputField, WorkflowNode, dump_workflow_nodes
from src.agent.tools.runtime_inputs import (
    _apply_runtime_inputs_to_nodes,
    _infer_runtime_input_schema,
    _normalized_input_schema,
)
from src.agent.validation import (
    normalize_workflow_connections,
    normalize_workflow_nodes,
    validate_workflow_payload,
)

log = structlog.get_logger()


def _validated_workflow(
    nodes: list[WorkflowNode],
    connections: dict[str, Any],
) -> tuple[list[WorkflowNode], dict[str, Any]]:
    normalized_nodes = normalize_workflow_nodes(nodes)
    normalized_connections = normalize_workflow_connections(connections, normalized_nodes)
    _normalize_conduut_webhook_methods(normalized_nodes)
    _normalize_webhook_response_modes(normalized_nodes, normalized_connections)
    _raise_workflow_validation_errors(normalized_nodes, normalized_connections)
    return normalized_nodes, normalized_connections


def _validated_runtime_workflow(
    nodes: list[WorkflowNode],
    connections: dict[str, Any],
    input_schema: list[WorkflowInputField] | None = None,
) -> tuple[list[WorkflowNode], dict[str, Any], list[WorkflowInputField]]:
    normalized_nodes = normalize_workflow_nodes(nodes)
    node_dicts = dump_workflow_nodes(normalized_nodes)
    runtime_schema = _normalized_input_schema(input_schema)
    if input_schema is None and not runtime_schema:
        runtime_schema = _infer_runtime_input_schema(node_dicts)
    _apply_runtime_inputs_to_nodes(node_dicts, runtime_schema)
    normalized_nodes = [WorkflowNode.model_validate(node) for node in node_dicts]
    normalized_connections = normalize_workflow_connections(connections, normalized_nodes)
    _normalize_conduut_webhook_methods(normalized_nodes)
    _normalize_webhook_response_modes(normalized_nodes, normalized_connections)
    _raise_workflow_validation_errors(normalized_nodes, normalized_connections)
    return normalized_nodes, normalized_connections, runtime_schema


def _raise_workflow_validation_errors(
    normalized_nodes: list[WorkflowNode],
    normalized_connections: dict[str, Any],
) -> None:
    errors = validate_workflow_payload(normalized_nodes, normalized_connections)
    if errors:
        log.warning(
            "workflow_validation_failed",
            errors=errors,
            node_types=[node.type for node in normalized_nodes],
            connection_sources=list(normalized_connections.keys()),
        )
        details = "\n".join(f"- {error}" for error in errors)
        raise ModelRetry(
            "Workflow validation failed. Fix these issues before retrying:\n"
            f"{details}\n\n"
            "If these errors require information the user did not provide, call "
            "request_user_input with one concise question instead of inventing values."
        )


def _normalize_webhook_response_modes(
    nodes: list[WorkflowNode],
    connections: dict[str, Any],
) -> None:
    respond_node_names = {
        node.name for node in nodes if node.type == "n8n-nodes-base.respondToWebhook"
    }
    if not respond_node_names:
        return

    for node in nodes:
        if node.type != "n8n-nodes-base.webhook":
            continue
        connection = connections.get(node.name)
        targets = list(_iter_connection_targets(connection))
        if any(target.get("node") in respond_node_names for target in targets):
            node.parameters["responseMode"] = "responseNode"


def _normalize_conduut_webhook_methods(nodes: list[WorkflowNode]) -> None:
    for node in nodes:
        if node.type != "n8n-nodes-base.webhook":
            continue
        node.parameters.setdefault("multipleMethods", False)
        node.parameters.setdefault("httpMethod", "POST")


def _iter_connection_targets(value: Any):
    if isinstance(value, dict):
        if "node" in value:
            yield value
        for nested in value.values():
            yield from _iter_connection_targets(nested)
    elif isinstance(value, list):
        for nested in value:
            yield from _iter_connection_targets(nested)
