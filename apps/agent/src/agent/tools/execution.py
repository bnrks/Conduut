"""Execution result summarization helpers."""

from typing import Any

from src.agent.schemas import (
    WorkflowOutputField,
    WorkflowResultPresentation,
    WorkflowResultPresentationField,
    WorkflowRunResultData,
)
from src.agent.tools.common import _preview_value

_MAX_OUTPUT_NODES = 4
_MAX_OUTPUT_ITEMS = 3
_TECHNICAL_OUTPUT_KEYS = {
    "headers",
    "params",
    "query",
    "webhookUrl",
    "executionMode",
}
_TECHNICAL_NODE_TYPES = {
    "n8n-nodes-base.webhook",
    "n8n-nodes-base.respondToWebhook",
}


def _node_type_by_name(workflow: dict[str, Any] | None) -> dict[str, str]:
    if not workflow:
        return {}
    nodes = workflow.get("nodes")
    if not isinstance(nodes, list):
        return {}
    return {
        str(node.get("name")): str(node.get("type"))
        for node in nodes
        if isinstance(node, dict) and node.get("name") and node.get("type")
    }


def _strip_technical_output(value: Any) -> Any | None:
    if isinstance(value, dict):
        cleaned = {
            str(key): _strip_technical_output(item)
            for key, item in value.items()
            if key not in _TECHNICAL_OUTPUT_KEYS
        }
        cleaned = {key: item for key, item in cleaned.items() if item not in ({}, [], None, "")}
        if cleaned == {"body": {"source": "conduut_test"}}:
            return None
        if cleaned == {"source": "conduut_test"}:
            return None
        return cleaned or None
    if isinstance(value, list):
        cleaned_list = [_strip_technical_output(item) for item in value]
        cleaned_list = [item for item in cleaned_list if item not in ({}, [], None, "")]
        return cleaned_list or None
    return value


def _visible_response_body(response: dict[str, Any] | None) -> Any | None:
    if not response:
        return None
    return _strip_technical_output(response.get("body"))


def _first_result_item(body: Any) -> Any:
    if isinstance(body, list):
        return body[0] if body else None
    return body


def _resolve_presentation(
    response: dict[str, Any] | None,
    output_schema: list[WorkflowOutputField],
    *,
    title: str | None = None,
) -> WorkflowResultPresentation | None:
    if not output_schema:
        return None
    item = _first_result_item(_visible_response_body(response))
    if not isinstance(item, dict):
        return None
    fields: list[WorkflowResultPresentationField] = []
    for field in output_schema:
        value = item.get(field.name)
        if value in (None, ""):
            continue
        fields.append(
            WorkflowResultPresentationField(
                label=field.label,
                format=field.format,
                value=value,
            )
        )
    if not fields:
        return None
    return WorkflowResultPresentation(title=title, fields=fields)


def _extract_execution_outputs(
    execution: dict[str, Any],
    *,
    workflow: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    data = execution.get("data") if isinstance(execution.get("data"), dict) else {}
    result_data = data.get("resultData", {}) if isinstance(data, dict) else {}
    run_data = result_data.get("runData") if isinstance(result_data, dict) else None
    if not isinstance(run_data, dict):
        return []

    node_types = _node_type_by_name(workflow)
    outputs: list[dict[str, Any]] = []
    for node_name, runs in run_data.items():
        node_type = node_types.get(str(node_name))
        if node_type in _TECHNICAL_NODE_TYPES:
            continue
        if not isinstance(runs, list) or not runs:
            continue
        latest_run = runs[-1] if isinstance(runs[-1], dict) else {}
        node_data = latest_run.get("data") if isinstance(latest_run, dict) else None
        main_outputs = node_data.get("main") if isinstance(node_data, dict) else None
        if not isinstance(main_outputs, list):
            continue

        items: list[Any] = []
        visible_item_count = 0
        for output_index in main_outputs:
            if not isinstance(output_index, list):
                continue
            for item in output_index:
                if len(items) >= _MAX_OUTPUT_ITEMS:
                    continue
                if isinstance(item, dict) and "json" in item:
                    cleaned = _strip_technical_output(item.get("json"))
                else:
                    cleaned = _strip_technical_output(item)
                if cleaned not in ({}, [], None, ""):
                    visible_item_count += 1
                    items.append(_preview_value(cleaned))
        if items:
            outputs.append(
                {
                    "nodeName": str(node_name),
                    "itemCount": visible_item_count,
                    "items": items,
                }
            )

    return outputs[-_MAX_OUTPUT_NODES:]


_MAX_ERROR_DETAIL = 300


def _combined_error_message(error: dict[str, Any]) -> str | None:
    """Combine n8n's generic `message` with the actionable `description`.

    HTTP node errors put the useful detail (e.g. the API's response text) in
    `description`; the bare `message` ("Bad request") is not enough to act on.
    """

    pieces: list[str] = []
    for key in ("message", "description"):
        value = error.get(key)
        if not isinstance(value, str):
            continue
        text = value.strip()
        if not text:
            continue
        if len(text) > _MAX_ERROR_DETAIL:
            text = f"{text[:_MAX_ERROR_DETAIL]}..."
        if text not in pieces:
            pieces.append(text)
    parameter_name = _error_parameter_name(error)
    if parameter_name:
        pieces.append(f"Parameter: {parameter_name}")
    return " — ".join(pieces) or None


def _error_parameter_name(error: dict[str, Any]) -> str | None:
    """Extract n8n's actionable missing/invalid parameter identifier.

    Node execution errors commonly keep it under ``extra.parameterName``;
    older/newer node implementations may expose it directly or in ``context``.
    """

    for container in (error, error.get("extra"), error.get("context")):
        if not isinstance(container, dict):
            continue
        value = container.get("parameterName")
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _summarize_execution(
    execution: dict[str, Any],
    *,
    response: dict[str, Any] | None = None,
    full_response: dict[str, Any] | None = None,
    workflow: dict[str, Any] | None = None,
    output_schema: list[WorkflowOutputField] | None = None,
) -> WorkflowRunResultData:
    status = execution.get("status") or ("success" if execution.get("finished") else "unknown")
    execution_id = str(execution.get("id", "")) or None
    data = execution.get("data") if isinstance(execution.get("data"), dict) else {}
    result_data = data.get("resultData", {}) if isinstance(data, dict) else {}
    error = result_data.get("error") if isinstance(result_data, dict) else None
    outputs = _extract_execution_outputs(execution, workflow=workflow)
    visible_response = _visible_response_body(response)
    if visible_response not in ({}, [], None, "") and not outputs:
        outputs = [
            {
                "nodeName": "Output",
                "itemCount": 1,
                "items": [_preview_value(visible_response)],
            }
        ]
    failed_node = None
    error_message = None
    if isinstance(error, dict):
        failed_node = (
            error.get("node", {}).get("name") if isinstance(error.get("node"), dict) else None
        )
        error_message = _combined_error_message(error)
    output_count = sum(int(output.get("itemCount") or 0) for output in outputs)
    summary = "Workflow run completed."
    if output_count:
        summary = f"Workflow run completed with {output_count} output item(s)."
    if status in {"error", "failed"} or error_message:
        summary = f"Workflow execution failed: {error_message or 'Unknown error'}"
    presentation = None
    if status not in {"error", "failed"} and not error_message:
        presentation_source = full_response if full_response is not None else response
        presentation = _resolve_presentation(presentation_source, output_schema or [])
    return WorkflowRunResultData(
        workflowId=str(execution.get("workflowId", "")),
        executionId=execution_id,
        status=str(status),
        summary=summary,
        failedNode=failed_node,
        error=error_message,
        response=response if status in {"error", "failed"} or error_message else None,
        outputs=outputs,
        presentation=presentation,
    )
