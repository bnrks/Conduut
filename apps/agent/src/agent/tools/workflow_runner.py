"""Workflow run preparation and execution helpers."""

from collections.abc import AsyncIterator
from copy import deepcopy
from typing import Any
from uuid import uuid4

import structlog

from src import n8n_client, store
from src.agent.artifacts import build_gmail_workflow_artifacts, build_sheets_workflow_artifacts
from src.agent.schemas import (
    WorkflowBatchRowResultData,
    WorkflowBatchRunResultData,
    WorkflowRunResultData,
)
from src.agent.tools.common import _response_preview
from src.agent.tools.constants import _MANUAL_TRIGGER_TYPE, _WEBHOOK_TRIGGER_TYPE
from src.agent.tools.execution import _summarize_execution
from src.agent.tools.readiness import (
    analyze_workflow_readiness_payload,
    attach_unambiguous_reuse_candidates,
)
from src.agent.tools.runtime_inputs import (
    _validated_workflow_input,
    _workflow_input_schema_from_metadata,
)
from src.agent.tools.workflow_helpers import (
    _conduut_webhook_path,
    _webhook_type_version,
    _workflow_trigger_nodes,
)

log = structlog.get_logger()

_FAILED_RUN_STATUSES = {"error", "failed"}
_MAX_BATCH_ROWS = 50
BatchProgressPayload = dict[str, Any] | WorkflowBatchRowResultData | WorkflowBatchRunResultData


async def run_workflow_with_input(
    workflow: dict[str, Any],
    *,
    user_id: str,
    input_payload: dict[str, Any] | None = None,
) -> WorkflowRunResultData:
    workflow_id = str(workflow.get("id") or "")
    log.info("workflow_run_started", workflow_id=workflow_id)
    metadata = await store.get_workflow_metadata(user_id, workflow_id)
    input_schema = _workflow_input_schema_from_metadata(metadata)
    validated_input, missing = _validated_workflow_input(input_schema, input_payload)
    if missing:
        labels = [field.label for field in input_schema if field.name in missing]
        log.warning(
            "workflow_run_missing_input",
            workflow_id=workflow_id,
            missing=missing,
        )
        raise ValueError(f"Missing required workflow input: {', '.join(labels or missing)}")

    workflow, path = await _prepare_workflow_for_conduut_run(workflow, user_id=user_id)
    result = await _run_prepared_webhook_workflow(
        workflow,
        path=path,
        input_payload=validated_input,
        metadata=metadata,
    )
    log.info(
        "workflow_run_finished",
        workflow_id=workflow_id,
        execution_id=result.executionId,
        status=result.status,
        failed_node=result.failedNode,
        error=result.error,
    )
    return result


async def run_workflow_batch_with_input(
    workflow: dict[str, Any],
    *,
    user_id: str,
    rows: list[dict[str, Any]],
) -> WorkflowBatchRunResultData:
    final_result: WorkflowBatchRunResultData | None = None
    async for event, payload in iter_workflow_batch_with_input(
        workflow,
        user_id=user_id,
        rows=rows,
    ):
        if event == "completed" and isinstance(payload, WorkflowBatchRunResultData):
            final_result = payload
    if final_result is None:
        raise ValueError("Batch run did not produce a result.")
    return final_result


async def iter_workflow_batch_with_input(
    workflow: dict[str, Any],
    *,
    user_id: str,
    rows: list[dict[str, Any]],
) -> AsyncIterator[tuple[str, BatchProgressPayload]]:
    workflow_id = str(workflow.get("id") or "")
    batch_run_id = str(uuid4())
    log.info("workflow_batch_run_started", workflow_id=workflow_id, batch_run_id=batch_run_id)

    if not rows:
        raise ValueError("Batch run requires at least one row.")
    if len(rows) > _MAX_BATCH_ROWS:
        raise ValueError(f"Batch run supports up to {_MAX_BATCH_ROWS} rows.")

    metadata = await store.get_workflow_metadata(user_id, workflow_id)
    input_schema = _workflow_input_schema_from_metadata(metadata)
    if not input_schema:
        raise ValueError("Batch run requires a workflow input schema.")

    workflow, path = await _prepare_workflow_for_conduut_run(workflow, user_id=user_id)
    results: list[WorkflowBatchRowResultData] = []
    succeeded = 0
    failed = 0
    skipped = 0
    total_rows = len(rows)

    yield (
        "started",
        {
            "workflowId": workflow_id,
            "batchRunId": batch_run_id,
            "totalRows": total_rows,
        },
    )

    for index, row in enumerate(rows, start=1):
        row_number = _batch_row_number(row, fallback=index)
        yield (
            "row_started",
            {
                "rowNumber": row_number,
                "index": index,
                "totalRows": total_rows,
            },
        )
        raw_input = row.get("input") if isinstance(row, dict) else None
        validated_input, missing = _validated_workflow_input(input_schema, raw_input)
        if missing:
            labels = [field.label for field in input_schema if field.name in missing]
            skipped += 1
            row_result = WorkflowBatchRowResultData(
                rowNumber=row_number,
                status="skipped",
                error=f"Missing required workflow input: {', '.join(labels or missing)}",
            )
            results.append(row_result)
            yield "row_finished", row_result
            continue

        try:
            row_result = await _run_prepared_webhook_workflow(
                workflow,
                path=path,
                input_payload=validated_input,
                metadata=metadata,
            )
        except Exception as exc:
            failed += 1
            log.warning(
                "workflow_batch_row_error",
                workflow_id=workflow_id,
                batch_run_id=batch_run_id,
                row_number=row_number,
                error_type=type(exc).__name__,
                error=str(exc),
            )
            row_result_data = WorkflowBatchRowResultData(
                rowNumber=row_number,
                status="failed",
                error=str(exc),
            )
            results.append(row_result_data)
            yield "row_finished", row_result_data
            continue

        row_status = "failed" if row_result.status in _FAILED_RUN_STATUSES else "success"
        if row_status == "failed":
            failed += 1
        else:
            succeeded += 1
        results.append(
            WorkflowBatchRowResultData(
                rowNumber=row_number,
                status=row_status,
                executionId=row_result.executionId,
                summary=row_result.summary,
                error=row_result.error,
                artifacts=row_result.artifacts,
            )
        )
        yield "row_finished", results[-1]

    status = _batch_status(succeeded=succeeded, failed=failed, skipped=skipped)
    log.info(
        "workflow_batch_run_finished",
        workflow_id=workflow_id,
        batch_run_id=batch_run_id,
        status=status,
        succeeded=succeeded,
        failed=failed,
        skipped=skipped,
    )
    yield (
        "completed",
        WorkflowBatchRunResultData(
            workflowId=workflow_id,
            batchRunId=batch_run_id,
            status=status,
            totalRows=total_rows,
            succeeded=succeeded,
            failed=failed,
            skipped=skipped,
            results=results,
        ),
    )


async def _prepare_workflow_for_conduut_run(
    workflow: dict[str, Any],
    *,
    user_id: str,
) -> tuple[dict[str, Any], str]:
    workflow_id = str(workflow.get("id") or "")
    workflow, converted_trigger = await ensure_conduut_runnable_workflow(workflow)
    readiness = await analyze_workflow_readiness_payload(workflow, user_id=user_id)
    # Explicit run: auto-attach a single deterministic host-matched saved
    # credential so "create -> Run" works without a separate chat confirmation.
    await attach_unambiguous_reuse_candidates(
        workflow_id, user_id, readiness.get("reuse_candidates", [])
    )
    webhook_nodes = readiness["webhook_nodes"]
    if not webhook_nodes:
        log.warning("workflow_run_not_testable", workflow_id=workflow_id)
        raise ValueError("Only webhook-triggered workflows can run from Conduut now.")

    if converted_trigger and workflow.get("active"):
        log.info("workflow_run_deactivating_for_trigger_patch", workflow_id=workflow_id)
        await n8n_client.deactivate_workflow(workflow_id)
        workflow["active"] = False
    if not workflow.get("active"):
        log.info("workflow_run_activating_workflow", workflow_id=workflow_id)
        await n8n_client.activate_workflow(workflow_id)
    path = webhook_nodes[0].get("parameters", {}).get("path")
    if not path:
        log.warning("workflow_run_missing_webhook_path", workflow_id=workflow_id)
        raise ValueError("Webhook path missing.")
    return workflow, str(path)


async def _run_prepared_webhook_workflow(
    workflow: dict[str, Any],
    *,
    path: str,
    input_payload: dict[str, Any],
    metadata: store.WorkflowMetadata | None,
) -> WorkflowRunResultData:
    workflow_id = str(workflow.get("id") or "")
    webhook_response = await n8n_client.call_webhook(str(path), input_payload)
    response = _response_preview(webhook_response)
    if webhook_response.status_code >= 400:
        execution_result = await _latest_workflow_execution_result(
            workflow,
            response=response,
            metadata=metadata,
        )
        if execution_result is not None:
            log.warning(
                "workflow_run_webhook_error_with_execution_detail",
                workflow_id=workflow_id,
                status_code=webhook_response.status_code,
                execution_id=execution_result.executionId,
                failed_node=execution_result.failedNode,
                error=execution_result.error,
                response=response,
            )
            return execution_result

        log.warning(
            "workflow_run_webhook_error",
            workflow_id=workflow_id,
            status_code=webhook_response.status_code,
            response=response,
        )
        return WorkflowRunResultData(
            workflowId=workflow_id,
            status="error",
            summary="Workflow webhook returned an error response.",
            error=webhook_response.text[:500],
            response=response,
        )

    execution_result = await _latest_workflow_execution_result(
        workflow,
        response=response,
        metadata=metadata,
    )
    if execution_result is None:
        log.info("workflow_run_triggered_without_execution_detail", workflow_id=workflow_id)
        return WorkflowRunResultData(
            workflowId=workflow_id,
            status="triggered",
            summary="Workflow trigger was accepted. n8n has not exposed execution details yet.",
            response=response,
        )

    log.info(
        "workflow_run_finished",
        workflow_id=workflow_id,
        execution_id=execution_result.executionId,
        status=execution_result.status,
        failed_node=execution_result.failedNode,
        error=execution_result.error,
    )
    return execution_result


async def _latest_workflow_execution_result(
    workflow: dict[str, Any],
    *,
    response: Any,
    metadata: store.WorkflowMetadata | None,
) -> WorkflowRunResultData | None:
    workflow_id = str(workflow.get("id") or "")
    executions = await n8n_client.list_executions(workflow_id=workflow_id, limit=1)
    if not executions:
        return None

    detail = await n8n_client.get_execution_detail(executions[0].id)
    result = _summarize_execution(detail, response=response, workflow=workflow)
    result.artifacts = [
        *build_gmail_workflow_artifacts(
            workflow_id=workflow_id,
            execution_id=result.executionId,
            outputs=result.outputs,
        ),
        *build_sheets_workflow_artifacts(
            workflow_id=workflow_id,
            execution_id=result.executionId,
            outputs=result.outputs,
            metadata=metadata,
        ),
    ]
    return result


def _batch_row_number(row: dict[str, Any], *, fallback: int) -> int:
    try:
        row_number = int(row.get("rowNumber", fallback))
    except (TypeError, ValueError, AttributeError):
        return fallback
    return row_number if row_number > 0 else fallback


def _batch_status(*, succeeded: int, failed: int, skipped: int) -> str:
    if failed == 0 and skipped == 0:
        return "completed"
    if succeeded > 0:
        return "completed_with_errors"
    return "failed"


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
    manual_trigger_conversion = _workflow_with_conduut_webhook_trigger(workflow)
    converted = manual_trigger_conversion or _workflow_with_post_webhook_trigger(workflow)
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
    log.info(
        "workflow_runnable_trigger_patched",
        workflow_id=workflow_id,
        converted_manual_trigger=manual_trigger_conversion is not None,
    )
    return refreshed, True
