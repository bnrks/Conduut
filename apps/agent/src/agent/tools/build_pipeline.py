"""Workflow build pipeline: normalize -> repair -> apply runtime inputs -> validate.

Wraps the core validators in ``src.agent.validation`` and raises ``ModelRetry`` on
failure. Renamed from ``tools/validation.py`` to disambiguate from the core
``agent/validation.py`` library it builds on (they are layered, not duplicated)."""

from typing import Any

import structlog
from pydantic_ai import ModelRetry

from src.agent.assurance import analyze_workflow_semantics, inject_schedule_identity_guards
from src.agent.repair import repair_workflow
from src.agent.schemas import WorkflowInputField, WorkflowNode, dump_workflow_nodes
from src.agent.tools.runtime_inputs import (
    _apply_runtime_inputs_to_nodes,
    _infer_runtime_input_schema,
    _normalized_input_schema,
)
from src.agent.validation import (
    _iter_connection_targets,
    normalize_workflow_connections,
    normalize_workflow_nodes,
    validate_workflow_payload,
)
from src.config import settings

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
    _raise_workflow_assurance_errors(normalized_nodes, normalized_connections)
    return normalized_nodes, normalized_connections


def _validated_runtime_workflow(
    nodes: list[WorkflowNode],
    connections: dict[str, Any] | None,
    input_schema: list[WorkflowInputField] | None = None,
    *,
    fallback_connections: dict[str, Any] | None = None,
    infer_missing_connections: bool = True,
) -> tuple[list[WorkflowNode], dict[str, Any], list[WorkflowInputField]]:
    normalized_nodes = normalize_workflow_nodes(nodes)
    node_dicts = dump_workflow_nodes(normalized_nodes)
    runtime_schema = _normalized_input_schema(input_schema)
    if input_schema is None and not runtime_schema:
        runtime_schema = _infer_runtime_input_schema(node_dicts)

    # Canonicalize connection shape/aliases, then deterministically repair the
    # compact JSON the model wrote (boilerplate, linear wiring, AI sub-node
    # ports, runtime-input expressions) before applying runtime inputs.
    source_connections = connections if connections is not None else fallback_connections
    normalized_connections = normalize_workflow_connections(
        source_connections or {}, normalized_nodes
    )
    node_dicts, normalized_connections, _repairs = repair_workflow(
        node_dicts,
        normalized_connections,
        runtime_fields={field.name for field in runtime_schema},
        infer_missing_connections=infer_missing_connections,
    )

    _apply_runtime_inputs_to_nodes(node_dicts, runtime_schema)
    node_dicts, normalized_connections = inject_schedule_identity_guards(
        node_dicts, normalized_connections
    )
    normalized_nodes = [WorkflowNode.model_validate(node) for node in node_dicts]
    normalized_connections = normalize_workflow_connections(
        normalized_connections, normalized_nodes
    )
    _normalize_conduut_webhook_methods(normalized_nodes)
    _normalize_webhook_response_modes(normalized_nodes, normalized_connections)
    _raise_workflow_validation_errors(normalized_nodes, normalized_connections)
    _raise_workflow_assurance_errors(normalized_nodes, normalized_connections)
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


def _raise_workflow_assurance_errors(
    normalized_nodes: list[WorkflowNode],
    normalized_connections: dict[str, Any],
) -> None:
    report = analyze_workflow_semantics(normalized_nodes, normalized_connections)
    mode = str(settings.workflow_assurance_mode or "hybrid").strip().lower()
    if mode not in {"observe", "hybrid", "enforce"}:
        mode = "hybrid"

    if report.findings:
        log.info(
            "workflow_assurance_findings",
            mode=mode,
            fingerprint=report.fingerprint,
            findings=[finding.as_log_dict() for finding in report.findings],
        )
    if mode == "observe":
        return

    enforced_findings = report.findings if mode == "enforce" else report.blocking_findings
    if not enforced_findings:
        return

    log.warning(
        "workflow_assurance_failed",
        mode=mode,
        fingerprint=report.fingerprint,
        findings=[finding.as_log_dict() for finding in enforced_findings],
    )
    details = "\n".join(f"- {finding.message}" for finding in enforced_findings)
    raise ModelRetry(
        "Workflow semantic assurance failed. Fix these graph/dataflow issues before retrying:\n"
        f"{details}"
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
