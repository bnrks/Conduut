"""Workflows router — n8n workflow'larını listeler ve yönetir."""

import json
from typing import Any, Literal

import structlog
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from src import n8n_client, store
from src.agent.assurance import workflow_fingerprint
from src.agent.sandbox import use_n8n_client as sandbox_use_n8n_client
from src.agent.schemas import (
    WorkflowBatchRowResultData,
    WorkflowBatchRunResultData,
    WorkflowRunAssessment,
)
from src.agent.tools import (
    _input_schema_payload,
    _workflow_input_schema_from_metadata,
    analyze_workflow_readiness_payload,
    iter_workflow_batch_with_input,
    run_workflow_batch_with_input,
    run_workflow_with_input,
)
from src.agent.workflow_preview import (
    consume_workflow_preview,
    preview_workflow_batch,
    preview_workflow_run,
    workflow_requires_preview,
)
from src.auth import get_user_id
from src.n8n_provider import N8nClientFactory, N8nInstanceResolver, N8nProviderError, error_detail

router = APIRouter()
log = structlog.get_logger()
resolver = N8nInstanceResolver()
client_factory = N8nClientFactory()


class WorkflowRunRequest(BaseModel):
    input: dict[str, Any] = Field(default_factory=dict)
    source: Literal["dashboard", "agent"] = "dashboard"
    previewToken: str | None = None


class WorkflowBatchRunRowRequest(BaseModel):
    rowNumber: int = Field(gt=0)
    input: dict[str, Any] = Field(default_factory=dict)


class WorkflowBatchRunOptions(BaseModel):
    continueOnError: bool = True


class WorkflowBatchRunRequest(BaseModel):
    rows: list[WorkflowBatchRunRowRequest] = Field(min_length=1, max_length=50)
    source: Literal["dashboard"] = "dashboard"
    options: WorkflowBatchRunOptions = Field(default_factory=WorkflowBatchRunOptions)
    previewToken: str | None = None


class WorkflowAdoptRequest(BaseModel):
    inputSchema: list[dict[str, Any]] = Field(default_factory=list)


def _sse(event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


def _provider_http_error(exc: N8nProviderError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=error_detail(exc))


async def _request_n8n(request: Request, user_id: str):
    request_state = getattr(request, "state", None)
    request_headers = getattr(request, "headers", {})
    request_id = getattr(request_state, "request_id", None) or request_headers.get("x-request-id")
    context = await resolver.resolve(user_id, request_id=request_id)
    client = await client_factory.for_request_context(context)
    return context, client


async def _ensure_workflow_mutation_allowed(
    user_id: str,
    workflow_id: str,
    *,
    instance_id: str,
    ownership: str,
    action: str,
) -> store.WorkflowMetadata | None:
    metadata = await _get_workflow_metadata(
        user_id,
        workflow_id,
        instance_id=instance_id,
    )
    if ownership == "customer_owned" and metadata is None:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "workflow_adoption_required",
                "message": (
                    f"This workflow exists in your n8n instance but has not been adopted into "
                    f"Conduut yet. It is read-only until you adopt it, so it can't be {action}."
                ),
            },
        )
    return metadata


def _workflow_drift_reason(
    metadata: store.WorkflowMetadata | None,
    workflow: dict[str, Any],
    *,
    instance_id: str,
) -> str | None:
    if metadata is None:
        return None
    baseline = metadata.resources.get("workflow_baseline")
    if not isinstance(baseline, dict):
        return None
    expected_instance_id = str(baseline.get("instance_id") or "")
    if expected_instance_id and expected_instance_id != instance_id:
        return "This workflow baseline belongs to a different n8n instance."
    expected_updated_at = str(baseline.get("workflow_updated_at") or "")
    current_updated_at = str(workflow.get("updatedAt") or "")
    if expected_updated_at and current_updated_at and expected_updated_at != current_updated_at:
        return "This workflow changed in n8n after Conduut last synced it."
    expected_fingerprint = str(baseline.get("workflow_fingerprint") or "")
    current_fingerprint = workflow_fingerprint(workflow)
    if expected_fingerprint and expected_fingerprint != current_fingerprint:
        return "This workflow structure changed in n8n after Conduut last synced it."
    return None


def _workflow_drift_error(drift_reason: str) -> HTTPException:
    return HTTPException(
        status_code=409,
        detail={
            "code": "workflow_drift_detected",
            "message": drift_reason,
        },
    )


async def _get_workflow_metadata(
    user_id: str,
    workflow_id: str,
    *,
    instance_id: str,
) -> store.WorkflowMetadata | None:
    return await store.get_workflow_metadata(
        user_id,
        workflow_id,
        instance_id=instance_id,
    )


async def _refresh_workflow_baseline(
    user_id: str,
    workflow_id: str,
    *,
    instance_id: str,
    client,
) -> None:
    metadata = await _get_workflow_metadata(
        user_id,
        workflow_id,
        instance_id=instance_id,
    )
    if metadata is None:
        return
    workflow = await client.get_workflow(workflow_id)
    resources = dict(metadata.resources)
    resources["workflow_baseline"] = {
        "instance_id": instance_id,
        "workflow_fingerprint": workflow_fingerprint(workflow),
        "workflow_updated_at": str(workflow.get("updatedAt") or ""),
    }
    await store.save_workflow_metadata(
        user_id,
        workflow_id,
        input_schema=metadata.input_schema,
        resources=resources,
        instance_id=instance_id,
    )


def _assessment_payload(assessment: WorkflowRunAssessment) -> dict[str, Any]:
    return {
        "transport_ok": assessment.transportOk,
        "execution_ok": assessment.executionOk,
        "coverage": assessment.coverage,
        "eligible_count": assessment.eligibleCount,
        "action_count": assessment.actionCount,
        "writeback_count": assessment.writebackCount,
        "postconditions_verified": assessment.postconditionsVerified,
        "duplicate_risk": assessment.duplicateRisk,
        "warnings": [
            {
                "code": warning.code,
                "severity": warning.severity,
                "node_name": warning.nodeName,
                "message": warning.message,
            }
            for warning in assessment.warnings
        ],
        "evidence": [
            {
                "kind": item.kind,
                "node_name": item.nodeName,
                "node_type": item.nodeType,
                "mutation": item.mutation,
                "run_status": item.runStatus,
                "output_item_count": item.outputItemCount,
            }
            for item in assessment.evidence
        ],
        "transport_status_code": assessment.transportStatusCode,
        "configured_mutation_nodes": assessment.configuredMutationNodes,
        "executed_mutation_nodes": assessment.executedMutationNodes,
        "successful_mutation_nodes": assessment.successfulMutationNodes,
        "zero_output_mutation_nodes": assessment.zeroOutputMutationNodes,
        "run_data_hints": [
            {
                "node_name": hint.nodeName,
                "node_type": hint.nodeType,
                "mutation": hint.mutation,
                "run_status": hint.runStatus,
                "branch_item_counts": hint.branchItemCounts,
                "output_item_count": hint.outputItemCount,
                "has_error": hint.hasError,
            }
            for hint in assessment.runDataHints
        ],
        "reasons": assessment.reasons,
    }


def _batch_row_payload(row: WorkflowBatchRowResultData) -> dict[str, Any]:
    return {
        "rowNumber": row.rowNumber,
        "status": row.status,
        "functional_status": row.functionalStatus,
        "assessment": _assessment_payload(row.assessment),
        "claimable_outcome": row.claimableOutcome,
        "execution_id": row.executionId,
        "summary": row.summary,
        "error": row.error,
        "outputs": row.outputs,
        "artifacts": [artifact.model_dump(exclude_none=True) for artifact in row.artifacts],
        "presentation": (
            row.presentation.model_dump(exclude_none=True) if row.presentation else None
        ),
    }


def _batch_result_payload(result: WorkflowBatchRunResultData) -> dict[str, Any]:
    return {
        "success": (
            result.failed == 0
            and result.skipped == 0
            and all(row.functionalStatus in {"verified", "no_action"} for row in result.results)
        ),
        "workflow_id": result.workflowId,
        "batchRunId": result.batchRunId,
        "status": result.status,
        "totalRows": result.totalRows,
        "succeeded": result.succeeded,
        "failed": result.failed,
        "skipped": result.skipped,
        "verified": result.verified,
        "no_action": result.noAction,
        "partial": result.partial,
        "needs_attention": result.needsAttention,
        "unknown": result.unknown,
        "results": [_batch_row_payload(row) for row in result.results],
    }


async def _persist_batch_row_artifacts(
    user_id: str,
    workflow_id: str,
    batch_run_id: str,
    row: WorkflowBatchRowResultData,
    *,
    instance_id: str,
) -> None:
    for artifact in row.artifacts:
        try:
            await store.save_artifact(
                user_id,
                artifact.model_dump(exclude_none=True),
                origin={
                    "kind": "workflow_batch_run",
                    "workflowId": workflow_id,
                    "batchRunId": batch_run_id,
                    "rowNumber": row.rowNumber,
                    "executionId": row.executionId,
                    "instanceId": instance_id,
                },
            )
        except Exception as exc:
            log.error(
                "workflow_batch_artifact_persist_error",
                workflow_id=workflow_id,
                batch_run_id=batch_run_id,
                row_number=row.rowNumber,
                error_type=type(exc).__name__,
                error=str(exc),
                exc_info=True,
            )


@router.get("/workflows")
async def list_workflows(request: Request):
    user_id = get_user_id(request)
    try:
        context, client = await _request_n8n(request, user_id)
    except N8nProviderError as exc:
        raise _provider_http_error(exc) from exc

    workflows = await client.list_workflows()
    metadata_by_id = await store.get_all_workflow_metadata(
        user_id,
        instance_id=context.target.instance_id,
    )
    if context.target.ownership == "shared_dev":
        workflows = [workflow for workflow in workflows if workflow.id in metadata_by_id]

    def _serialize(w: n8n_client.N8nWorkflow) -> dict:
        input_schema = _workflow_input_schema_from_metadata(metadata_by_id.get(w.id))
        return {
            "id": w.id,
            "name": w.name,
            "status": "active" if w.active else "inactive",
            "nodeCount": w.node_count,
            "createdAt": w.created_at,
            "updatedAt": w.updated_at,
            "executionCount": 0,
            "inputSchema": _input_schema_payload(input_schema),
            "managedByConduut": w.id in metadata_by_id,
            "readOnly": context.target.ownership == "customer_owned" and w.id not in metadata_by_id,
        }

    return {"workflows": [_serialize(w) for w in workflows]}


@router.post("/workflows/{workflow_id}/adopt")
async def adopt_workflow(
    workflow_id: str,
    request: Request,
    body: WorkflowAdoptRequest | None = None,
):
    user_id = get_user_id(request)
    try:
        context, client = await _request_n8n(request, user_id)
        workflow = await client.get_workflow(workflow_id)
    except N8nProviderError as exc:
        raise _provider_http_error(exc) from exc
    except n8n_client.N8nApiError as exc:
        raise HTTPException(status_code=exc.status_code, detail={"message": exc.message}) from exc
    existing = await _get_workflow_metadata(
        user_id,
        workflow_id,
        instance_id=context.target.instance_id,
    )
    resources = dict(existing.resources) if existing else {}
    resources["adopted_from_external"] = True
    resources["adopted_at"] = store._now_iso()
    resources["workflow_baseline"] = {
        "instance_id": context.target.instance_id,
        "workflow_fingerprint": workflow_fingerprint(workflow),
        "workflow_updated_at": str(workflow.get("updatedAt") or ""),
    }
    resources["external_workflow_baseline"] = dict(resources["workflow_baseline"])
    saved = await store.save_workflow_metadata(
        user_id,
        workflow_id,
        input_schema=(
            body.inputSchema if body is not None else (existing.input_schema if existing else [])
        ),
        resources=resources,
        instance_id=context.target.instance_id,
    )
    return {
        "workflow_id": workflow_id,
        "adopted": True,
        "instanceId": context.target.instance_id,
        "inputSchema": _input_schema_payload(saved.input_schema),
        "baseline": resources["workflow_baseline"],
    }


@router.patch("/workflows/{workflow_id}/activate")
async def activate_workflow(workflow_id: str, request: Request):
    user_id = get_user_id(request)
    try:
        context, client = await _request_n8n(request, user_id)
        await _ensure_workflow_mutation_allowed(
            user_id,
            workflow_id,
            instance_id=context.target.instance_id,
            ownership=context.target.ownership,
            action="activated",
        )
        workflow = await client.get_workflow(workflow_id)
        drift_reason = _workflow_drift_reason(
            await _get_workflow_metadata(
                user_id,
                workflow_id,
                instance_id=context.target.instance_id,
            ),
            workflow,
            instance_id=context.target.instance_id,
        )
        if drift_reason:
            raise _workflow_drift_error(drift_reason)
        readiness = await analyze_workflow_readiness_payload(workflow, user_id=user_id, n8n=client)
        if readiness["missing_credentials"]:
            raise HTTPException(
                status_code=409,
                detail={"message": "Workflow has missing credentials."},
            )
        if workflow_requires_preview(workflow):
            with sandbox_use_n8n_client(client):
                assurance = await preview_workflow_run(
                    workflow,
                    user_id=user_id,
                    input_payload=None,
                    execution_policy="safe",
                    issue_token=False,
                    instance_id=context.target.instance_id,
                )
            if not assurance.get("ready") or assurance.get("coverage") != "full":
                raise HTTPException(
                    status_code=409,
                    detail={
                        "code": "workflow_assurance_required",
                        "message": "The workflow safety check needs attention before activation.",
                        "assurance": assurance,
                    },
                )
        await client.activate_workflow(workflow_id)
        await _refresh_workflow_baseline(
            user_id,
            workflow_id,
            instance_id=context.target.instance_id,
            client=client,
        )
    except N8nProviderError as exc:
        raise _provider_http_error(exc) from exc
    except n8n_client.N8nApiError as e:
        raise HTTPException(status_code=e.status_code, detail={"message": e.message}) from e
    return {"success": True, "workflow_id": workflow_id}


@router.patch("/workflows/{workflow_id}/deactivate")
async def deactivate_workflow(workflow_id: str, request: Request):
    user_id = get_user_id(request)
    try:
        context, client = await _request_n8n(request, user_id)
        await _ensure_workflow_mutation_allowed(
            user_id,
            workflow_id,
            instance_id=context.target.instance_id,
            ownership=context.target.ownership,
            action="deactivated",
        )
        workflow = await client.get_workflow(workflow_id)
        drift_reason = _workflow_drift_reason(
            await _get_workflow_metadata(
                user_id,
                workflow_id,
                instance_id=context.target.instance_id,
            ),
            workflow,
            instance_id=context.target.instance_id,
        )
        if drift_reason:
            raise _workflow_drift_error(drift_reason)
        await client.deactivate_workflow(workflow_id)
        await _refresh_workflow_baseline(
            user_id,
            workflow_id,
            instance_id=context.target.instance_id,
            client=client,
        )
    except N8nProviderError as exc:
        raise _provider_http_error(exc) from exc
    except n8n_client.N8nApiError as e:
        raise HTTPException(status_code=e.status_code, detail={"message": e.message}) from e
    return {"success": True, "workflow_id": workflow_id}


@router.post("/workflows/{workflow_id}/run")
async def run_workflow(workflow_id: str, request: Request, body: WorkflowRunRequest | None = None):
    user_id = get_user_id(request)
    try:
        context, client = await _request_n8n(request, user_id)
        await _ensure_workflow_mutation_allowed(
            user_id,
            workflow_id,
            instance_id=context.target.instance_id,
            ownership=context.target.ownership,
            action="run",
        )
        workflow = await client.get_workflow(workflow_id)
        drift_reason = _workflow_drift_reason(
            await _get_workflow_metadata(
                user_id,
                workflow_id,
                instance_id=context.target.instance_id,
            ),
            workflow,
            instance_id=context.target.instance_id,
        )
        if drift_reason:
            raise _workflow_drift_error(drift_reason)
        readiness = await analyze_workflow_readiness_payload(workflow, user_id=user_id, n8n=client)
        if readiness["missing_credentials"]:
            raise HTTPException(
                status_code=409,
                detail={"message": "Workflow has missing credentials."},
            )
        input_payload = body.input if body else {}
        if not await consume_workflow_preview(
            workflow,
            user_id=user_id,
            input_payload=input_payload,
            preview_token=body.previewToken if body else None,
            execution_policy="safe",
            instance_id=context.target.instance_id,
        ):
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "workflow_preview_required",
                    "message": "Review and confirm the safe action preview before running.",
                },
            )
        result = await run_workflow_with_input(
            workflow,
            user_id=user_id,
            input_payload=input_payload,
            n8n=client,
        )
        await _refresh_workflow_baseline(
            user_id,
            workflow_id,
            instance_id=context.target.instance_id,
            client=client,
        )
        for artifact in result.artifacts:
            try:
                await store.save_artifact(
                    user_id,
                    artifact.model_dump(exclude_none=True),
                    origin={
                        "kind": "workflow_run",
                        "workflowId": workflow_id,
                        "executionId": result.executionId,
                        "instanceId": context.target.instance_id,
                    },
                )
            except Exception as exc:
                log.error(
                    "workflow_artifact_persist_error",
                    workflow_id=workflow_id,
                    error_type=type(exc).__name__,
                    error=str(exc),
                    exc_info=True,
                )
        return {
            "success": result.functionalStatus in {"verified", "no_action"},
            "workflow_id": workflow_id,
            "execution_id": result.executionId,
            "status": result.status,
            "functional_status": result.functionalStatus,
            "assessment": _assessment_payload(result.assessment),
            "claimable_outcome": result.claimableOutcome,
            "summary": result.summary,
            "failed_node": result.failedNode,
            "error": result.error,
            "outputs": result.outputs,
            "artifacts": [artifact.model_dump(exclude_none=True) for artifact in result.artifacts],
            "presentation": (
                result.presentation.model_dump(exclude_none=True) if result.presentation else None
            ),
        }
    except ValueError as e:
        raise HTTPException(status_code=422, detail={"message": str(e)}) from e
    except N8nProviderError as exc:
        raise _provider_http_error(exc) from exc
    except n8n_client.N8nApiError as e:
        raise HTTPException(status_code=e.status_code, detail={"message": e.message}) from e


@router.post("/workflows/{workflow_id}/preview-run")
async def preview_run_workflow(
    workflow_id: str, request: Request, body: WorkflowRunRequest | None = None
):
    """Resolve a side-effect-free preview and return a short-lived approval token."""

    user_id = get_user_id(request)
    try:
        context, client = await _request_n8n(request, user_id)
        await _ensure_workflow_mutation_allowed(
            user_id,
            workflow_id,
            instance_id=context.target.instance_id,
            ownership=context.target.ownership,
            action="previewed",
        )
        workflow = await client.get_workflow(workflow_id)
        drift_reason = _workflow_drift_reason(
            await _get_workflow_metadata(
                user_id,
                workflow_id,
                instance_id=context.target.instance_id,
            ),
            workflow,
            instance_id=context.target.instance_id,
        )
        if drift_reason:
            raise _workflow_drift_error(drift_reason)
    except N8nProviderError as exc:
        raise _provider_http_error(exc) from exc
    readiness = await analyze_workflow_readiness_payload(workflow, user_id=user_id, n8n=client)
    if readiness["missing_credentials"]:
        raise HTTPException(
            status_code=409,
            detail={"message": "Workflow has missing credentials."},
        )
    if not workflow_requires_preview(workflow):
        return {
            "workflow_id": workflow_id,
            "ready": True,
            "status": "not_required",
            "coverage": "full",
        }
    with sandbox_use_n8n_client(client):
        result = await preview_workflow_run(
            workflow,
            user_id=user_id,
            input_payload=body.input if body else {},
            execution_policy="safe",
            instance_id=context.target.instance_id,
        )
    if not result.get("ready"):
        raise HTTPException(status_code=409, detail=result)
    return result


@router.post("/workflows/{workflow_id}/batch-run")
async def batch_run_workflow(
    workflow_id: str,
    request: Request,
    body: WorkflowBatchRunRequest,
):
    """Run a workflow once per provided mapped input row and return row-level results."""

    user_id = get_user_id(request)
    try:
        context, client = await _request_n8n(request, user_id)
        await _ensure_workflow_mutation_allowed(
            user_id,
            workflow_id,
            instance_id=context.target.instance_id,
            ownership=context.target.ownership,
            action="run",
        )
        workflow = await client.get_workflow(workflow_id)
        drift_reason = _workflow_drift_reason(
            await _get_workflow_metadata(
                user_id,
                workflow_id,
                instance_id=context.target.instance_id,
            ),
            workflow,
            instance_id=context.target.instance_id,
        )
        if drift_reason:
            raise _workflow_drift_error(drift_reason)
        readiness = await analyze_workflow_readiness_payload(workflow, user_id=user_id, n8n=client)
        if readiness["missing_credentials"]:
            raise HTTPException(
                status_code=409,
                detail={"message": "Workflow has missing credentials."},
            )
        rows = [row.model_dump() for row in body.rows]
        if not await consume_workflow_preview(
            workflow,
            user_id=user_id,
            input_payload={"rows": rows},
            preview_token=body.previewToken,
            execution_policy="safe",
            instance_id=context.target.instance_id,
        ):
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "workflow_preview_required",
                    "message": "Review and confirm the safe batch preview before running.",
                },
            )
        result = await run_workflow_batch_with_input(
            workflow,
            user_id=user_id,
            rows=rows,
            n8n=client,
        )
        await _refresh_workflow_baseline(
            user_id,
            workflow_id,
            instance_id=context.target.instance_id,
            client=client,
        )
        for row in result.results:
            await _persist_batch_row_artifacts(
                user_id,
                workflow_id,
                result.batchRunId,
                row,
                instance_id=context.target.instance_id,
            )
        return _batch_result_payload(result)
    except ValueError as e:
        raise HTTPException(status_code=422, detail={"message": str(e)}) from e
    except N8nProviderError as exc:
        raise _provider_http_error(exc) from exc
    except n8n_client.N8nApiError as e:
        raise HTTPException(status_code=e.status_code, detail={"message": e.message}) from e


@router.post("/workflows/{workflow_id}/batch-preview")
async def preview_batch_run_workflow(
    workflow_id: str,
    request: Request,
    body: WorkflowBatchRunRequest,
):
    user_id = get_user_id(request)
    try:
        context, client = await _request_n8n(request, user_id)
        await _ensure_workflow_mutation_allowed(
            user_id,
            workflow_id,
            instance_id=context.target.instance_id,
            ownership=context.target.ownership,
            action="previewed",
        )
        workflow = await client.get_workflow(workflow_id)
        drift_reason = _workflow_drift_reason(
            await _get_workflow_metadata(
                user_id,
                workflow_id,
                instance_id=context.target.instance_id,
            ),
            workflow,
            instance_id=context.target.instance_id,
        )
        if drift_reason:
            raise _workflow_drift_error(drift_reason)
    except N8nProviderError as exc:
        raise _provider_http_error(exc) from exc
    readiness = await analyze_workflow_readiness_payload(workflow, user_id=user_id, n8n=client)
    if readiness["missing_credentials"]:
        raise HTTPException(
            status_code=409,
            detail={"message": "Workflow has missing credentials."},
        )
    if not workflow_requires_preview(workflow):
        return {
            "workflow_id": workflow_id,
            "ready": True,
            "status": "not_required",
            "coverage": "full",
        }
    rows = [row.model_dump() for row in body.rows]
    with sandbox_use_n8n_client(client):
        result = await preview_workflow_batch(
            workflow,
            user_id=user_id,
            rows=rows,
            execution_policy="safe",
            instance_id=context.target.instance_id,
        )
    if not result.get("ready"):
        raise HTTPException(status_code=409, detail=result)
    return result


@router.post("/workflows/{workflow_id}/batch-run/stream")
async def stream_batch_run_workflow(
    workflow_id: str,
    request: Request,
    body: WorkflowBatchRunRequest,
):
    """Stream row-level workflow batch progress as server-sent events."""

    user_id = get_user_id(request)
    try:
        context, client = await _request_n8n(request, user_id)
        await _ensure_workflow_mutation_allowed(
            user_id,
            workflow_id,
            instance_id=context.target.instance_id,
            ownership=context.target.ownership,
            action="run",
        )
        workflow = await client.get_workflow(workflow_id)
        drift_reason = _workflow_drift_reason(
            await _get_workflow_metadata(
                user_id,
                workflow_id,
                instance_id=context.target.instance_id,
            ),
            workflow,
            instance_id=context.target.instance_id,
        )
        if drift_reason:
            raise _workflow_drift_error(drift_reason)
        readiness = await analyze_workflow_readiness_payload(workflow, user_id=user_id, n8n=client)
        if readiness["missing_credentials"]:
            raise HTTPException(
                status_code=409,
                detail={"message": "Workflow has missing credentials."},
            )
        rows = [row.model_dump() for row in body.rows]
        if not await consume_workflow_preview(
            workflow,
            user_id=user_id,
            input_payload={"rows": rows},
            preview_token=body.previewToken,
            execution_policy="safe",
            instance_id=context.target.instance_id,
        ):
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "workflow_preview_required",
                    "message": "Review and confirm the safe batch preview before running.",
                },
            )
    except N8nProviderError as exc:
        raise _provider_http_error(exc) from exc
    except n8n_client.N8nApiError as e:
        raise HTTPException(status_code=e.status_code, detail={"message": e.message}) from e

    async def events():
        batch_run_id: str | None = None
        try:
            async for event, payload in iter_workflow_batch_with_input(
                workflow,
                user_id=user_id,
                rows=rows,
                n8n=client,
            ):
                if event == "started":
                    if isinstance(payload, dict):
                        batch_run_id = str(payload.get("batchRunId") or "")
                    yield _sse(event, payload if isinstance(payload, dict) else {})
                    continue

                if event == "row_started":
                    yield _sse(event, payload if isinstance(payload, dict) else {})
                    continue

                if event == "row_finished" and isinstance(payload, WorkflowBatchRowResultData):
                    if batch_run_id:
                        await _persist_batch_row_artifacts(
                            user_id,
                            workflow_id,
                            batch_run_id,
                            payload,
                            instance_id=context.target.instance_id,
                        )
                    yield _sse(event, _batch_row_payload(payload))
                    continue

                if event == "completed" and isinstance(payload, WorkflowBatchRunResultData):
                    await _refresh_workflow_baseline(
                        user_id,
                        workflow_id,
                        instance_id=context.target.instance_id,
                        client=client,
                    )
                    yield _sse(event, _batch_result_payload(payload))
        except ValueError as exc:
            yield _sse("error", {"message": str(exc)})
        except n8n_client.N8nApiError as exc:
            yield _sse("error", {"message": exc.message, "status": exc.status_code})
        except Exception as exc:
            log.error(
                "workflow_batch_stream_error",
                workflow_id=workflow_id,
                error_type=type(exc).__name__,
                error=str(exc),
                exc_info=True,
            )
            yield _sse("error", {"message": "Workflow batch run failed."})

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.delete("/workflows/{workflow_id}", status_code=204)
async def delete_workflow(workflow_id: str, request: Request):
    user_id = get_user_id(request)
    try:
        context, client = await _request_n8n(request, user_id)
        await _ensure_workflow_mutation_allowed(
            user_id,
            workflow_id,
            instance_id=context.target.instance_id,
            ownership=context.target.ownership,
            action="deleted",
        )
        workflow = await client.get_workflow(workflow_id)
        drift_reason = _workflow_drift_reason(
            await _get_workflow_metadata(
                user_id,
                workflow_id,
                instance_id=context.target.instance_id,
            ),
            workflow,
            instance_id=context.target.instance_id,
        )
        if drift_reason:
            raise _workflow_drift_error(drift_reason)
        await client.delete_workflow(workflow_id)
        await store.delete_workflow_metadata(user_id, workflow_id)
    except N8nProviderError as exc:
        raise _provider_http_error(exc) from exc
    except n8n_client.N8nApiError as e:
        raise HTTPException(status_code=e.status_code, detail={"message": e.message}) from e
