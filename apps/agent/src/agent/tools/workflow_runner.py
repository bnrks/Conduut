"""Workflow run preparation and execution helpers."""

from copy import deepcopy
from typing import Any
from uuid import uuid4

from src import n8n_client, store
from src.agent.schemas import WorkflowRunResultData
from src.agent.tools.common import _response_preview
from src.agent.tools.constants import _MANUAL_TRIGGER_TYPE, _WEBHOOK_TRIGGER_TYPE
from src.agent.tools.execution import _summarize_execution
from src.agent.tools.readiness import analyze_workflow_readiness_payload
from src.agent.tools.runtime_inputs import (
    _validated_workflow_input,
    _workflow_input_schema_from_metadata,
)
from src.agent.tools.workflow_helpers import (
    _conduut_webhook_path,
    _webhook_type_version,
    _workflow_trigger_nodes,
)


async def run_workflow_with_input(
    workflow: dict[str, Any],
    *,
    user_id: str,
    input_payload: dict[str, Any] | None = None,
) -> WorkflowRunResultData:
    workflow_id = str(workflow.get("id") or "")
    metadata = await store.get_workflow_metadata(user_id, workflow_id)
    input_schema = _workflow_input_schema_from_metadata(metadata)
    validated_input, missing = _validated_workflow_input(input_schema, input_payload)
    if missing:
        labels = [field.label for field in input_schema if field.name in missing]
        raise ValueError(f"Missing required workflow input: {', '.join(labels or missing)}")

    workflow, converted_trigger = await ensure_conduut_runnable_workflow(workflow)
    readiness = await analyze_workflow_readiness_payload(workflow, user_id=user_id)
    webhook_nodes = readiness["webhook_nodes"]
    if not webhook_nodes:
        raise ValueError("Only webhook-triggered workflows can run from Conduut now.")

    if converted_trigger and workflow.get("active"):
        await n8n_client.deactivate_workflow(workflow_id)
        workflow["active"] = False
    if not workflow.get("active"):
        await n8n_client.activate_workflow(workflow_id)
    path = webhook_nodes[0].get("parameters", {}).get("path")
    if not path:
        raise ValueError("Webhook path missing.")

    webhook_response = await n8n_client.call_webhook(str(path), validated_input)
    response = _response_preview(webhook_response)
    if webhook_response.status_code >= 400:
        return WorkflowRunResultData(
            workflowId=workflow_id,
            status="error",
            summary="Workflow webhook returned an error response.",
            error=webhook_response.text[:500],
            response=response,
        )

    executions = await n8n_client.list_executions(workflow_id=workflow_id, limit=1)
    if not executions:
        return WorkflowRunResultData(
            workflowId=workflow_id,
            status="triggered",
            summary="Workflow trigger was accepted. n8n has not exposed execution details yet.",
            response=response,
        )

    detail = await n8n_client.get_execution_detail(executions[0].id)
    return _summarize_execution(detail, response=response, workflow=workflow)


def _workflow_with_conduut_webhook_trigger(workflow: dict[str, Any]) -> dict[str, Any] | None:
    if _workflow_trigger_nodes(workflow, _WEBHOOK_TRIGGER_TYPE):
        return None

    nodes = workflow.get("nodes")
    if not isinstance(nodes, list):
        return None

    converted_nodes = deepcopy(nodes)
    workflow_id = str(workflow.get("id") or "")
    for node in converted_nodes:
        if not isinstance(node, dict) or node.get("type") != _MANUAL_TRIGGER_TYPE:
            continue

        node_id = str(node.get("id") or "")
        node["type"] = _WEBHOOK_TRIGGER_TYPE
        node["typeVersion"] = _webhook_type_version()
        node["webhookId"] = str(uuid4())
        node["parameters"] = {
            "httpMethod": "POST",
            "path": _conduut_webhook_path(workflow_id, node_id),
            "responseMode": "lastNode",
            "options": {},
        }
        converted = dict(workflow)
        converted["nodes"] = converted_nodes
        converted["connections"] = deepcopy(workflow.get("connections") or {})
        return converted

    return None


def _webhook_node_accepts_post(node: dict[str, Any]) -> bool:
    parameters = node.get("parameters")
    if not isinstance(parameters, dict):
        return False
    methods = parameters.get("httpMethod")
    if parameters.get("multipleMethods") is True:
        if isinstance(methods, list):
            return any(str(method).upper() == "POST" for method in methods)
        return str(methods or "").upper() == "POST"
    return str(methods or "GET").upper() == "POST"


def _workflow_with_post_webhook_trigger(workflow: dict[str, Any]) -> dict[str, Any] | None:
    webhook_nodes = _workflow_trigger_nodes(workflow, _WEBHOOK_TRIGGER_TYPE)
    if not webhook_nodes:
        return None
    if all(_webhook_node_accepts_post(node) for node in webhook_nodes):
        return None

    converted = dict(workflow)
    converted_nodes = deepcopy(workflow.get("nodes") or [])
    for node in converted_nodes:
        if not isinstance(node, dict) or node.get("type") != _WEBHOOK_TRIGGER_TYPE:
            continue
        if _webhook_node_accepts_post(node):
            continue
        parameters = node.setdefault("parameters", {})
        parameters["multipleMethods"] = False
        parameters["httpMethod"] = "POST"
    converted["nodes"] = converted_nodes
    converted["connections"] = deepcopy(workflow.get("connections") or {})
    return converted


async def ensure_conduut_runnable_workflow(
    workflow: dict[str, Any],
) -> tuple[dict[str, Any], bool]:
    converted = _workflow_with_conduut_webhook_trigger(workflow)
    converted = converted or _workflow_with_post_webhook_trigger(workflow)
    if not converted:
        return workflow, False

    workflow_id = str(workflow.get("id") or "")
    if not workflow_id:
        return workflow, False

    updated = await n8n_client.update_workflow(
        workflow_id=workflow_id,
        name=str(workflow.get("name") or "Workflow"),
        nodes=converted.get("nodes") or [],
        connections=converted.get("connections") or {},
        settings=workflow.get("settings") if isinstance(workflow.get("settings"), dict) else None,
    )
    refreshed = await n8n_client.get_workflow(updated.id)
    return refreshed, True
