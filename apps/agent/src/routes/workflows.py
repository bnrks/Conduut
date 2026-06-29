"""Workflows router — n8n workflow'larını listeler ve yönetir."""

import json
from typing import Any, Literal

import structlog
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from src import n8n_client, store
from src.agent.schemas import WorkflowBatchRowResultData, WorkflowBatchRunResultData
from src.agent.tools import (
    _input_schema_payload,
    _workflow_input_schema_from_metadata,
    analyze_workflow_readiness_payload,
    iter_workflow_batch_with_input,
    run_workflow_batch_with_input,
    run_workflow_with_input,
)
from src.auth import get_user_id

router = APIRouter()
log = structlog.get_logger()


class WorkflowRunRequest(BaseModel):
    input: dict[str, Any] = Field(default_factory=dict)
    source: Literal["dashboard", "agent"] = "dashboard"


class WorkflowBatchRunRowRequest(BaseModel):
    rowNumber: int = Field(gt=0)
    input: dict[str, Any] = Field(default_factory=dict)


class WorkflowBatchRunOptions(BaseModel):
    continueOnError: bool = True


class WorkflowBatchRunRequest(BaseModel):
    rows: list[WorkflowBatchRunRowRequest] = Field(min_length=1, max_length=50)
    source: Literal["dashboard"] = "dashboard"
    options: WorkflowBatchRunOptions = Field(default_factory=WorkflowBatchRunOptions)


def _sse(event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


def _batch_row_payload(row: WorkflowBatchRowResultData) -> dict[str, Any]:
    return {
        "rowNumber": row.rowNumber,
        "status": row.status,
        "execution_id": row.executionId,
        "summary": row.summary,
        "error": row.error,
        "artifacts": [artifact.model_dump(exclude_none=True) for artifact in row.artifacts],
    }


def _batch_result_payload(result: WorkflowBatchRunResultData) -> dict[str, Any]:
    return {
        "success": result.status != "failed",
        "workflow_id": result.workflowId,
        "batchRunId": result.batchRunId,
        "status": result.status,
        "totalRows": result.totalRows,
        "succeeded": result.succeeded,
        "failed": result.failed,
        "skipped": result.skipped,
        "results": [_batch_row_payload(row) for row in result.results],
    }


async def _persist_batch_row_artifacts(
    user_id: str,
    workflow_id: str,
    batch_run_id: str,
    row: WorkflowBatchRowResultData,
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
    # TODO: MVP'de tek paylaşık n8n instance kullanılıyor.
    # Per-user container izolasyonu gelince user_id ile filtreleme eklenecek.
    user_id = get_user_id(request)

    # Düz 2 çağrı (workflow sayısından bağımsız): n8n list + tek Firestore
    # metadata sorgusu. nodeCount n8n list cevabından (N8nWorkflow.node_count)
    # gelir — listede ayrı get_workflow (N+1, ~1-2.4sn/çağrı) ATMAYIZ; metadata
    # da workflow-başına değil tek sorguda toplanır.
    workflows = await n8n_client.list_workflows()
    metadata_by_id = await store.get_all_workflow_metadata(user_id)

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
        }

    return {"workflows": [_serialize(w) for w in workflows]}


@router.patch("/workflows/{workflow_id}/activate")
async def activate_workflow(workflow_id: str, request: Request):
    user_id = get_user_id(request)
    try:
        workflow = await n8n_client.get_workflow(workflow_id)
        readiness = await analyze_workflow_readiness_payload(workflow, user_id=user_id)
        if readiness["missing_credentials"]:
            raise HTTPException(
                status_code=409,
                detail={"message": "Workflow has missing credentials."},
            )
        await n8n_client.activate_workflow(workflow_id)
    except n8n_client.N8nApiError as e:
        raise HTTPException(status_code=e.status_code, detail={"message": e.message}) from e
    return {"success": True, "workflow_id": workflow_id}


@router.patch("/workflows/{workflow_id}/deactivate")
async def deactivate_workflow(workflow_id: str, request: Request):
    get_user_id(request)
    try:
        await n8n_client.deactivate_workflow(workflow_id)
    except n8n_client.N8nApiError as e:
        raise HTTPException(status_code=e.status_code, detail={"message": e.message}) from e
    return {"success": True, "workflow_id": workflow_id}


@router.post("/workflows/{workflow_id}/run")
async def run_workflow(workflow_id: str, request: Request, body: WorkflowRunRequest | None = None):
    user_id = get_user_id(request)
    try:
        workflow = await n8n_client.get_workflow(workflow_id)
        readiness = await analyze_workflow_readiness_payload(workflow, user_id=user_id)
        if readiness["missing_credentials"]:
            raise HTTPException(
                status_code=409,
                detail={"message": "Workflow has missing credentials."},
            )
        result = await run_workflow_with_input(
            workflow,
            user_id=user_id,
            input_payload=(body.input if body else {}),
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
            "success": result.status not in {"error", "failed"},
            "workflow_id": workflow_id,
            "execution_id": result.executionId,
            "status": result.status,
            "summary": result.summary,
            "outputs": result.outputs,
            "artifacts": [artifact.model_dump(exclude_none=True) for artifact in result.artifacts],
            "presentation": (
                result.presentation.model_dump(exclude_none=True) if result.presentation else None
            ),
        }
    except ValueError as e:
        raise HTTPException(status_code=422, detail={"message": str(e)}) from e
    except n8n_client.N8nApiError as e:
        raise HTTPException(status_code=e.status_code, detail={"message": e.message}) from e


@router.post("/workflows/{workflow_id}/batch-run")
async def batch_run_workflow(
    workflow_id: str,
    request: Request,
    body: WorkflowBatchRunRequest,
):
    """Run a workflow once per provided mapped input row and return row-level results."""

    user_id = get_user_id(request)
    try:
        workflow = await n8n_client.get_workflow(workflow_id)
        readiness = await analyze_workflow_readiness_payload(workflow, user_id=user_id)
        if readiness["missing_credentials"]:
            raise HTTPException(
                status_code=409,
                detail={"message": "Workflow has missing credentials."},
            )
        result = await run_workflow_batch_with_input(
            workflow,
            user_id=user_id,
            rows=[row.model_dump() for row in body.rows],
        )
        for row in result.results:
            await _persist_batch_row_artifacts(user_id, workflow_id, result.batchRunId, row)
        return _batch_result_payload(result)
    except ValueError as e:
        raise HTTPException(status_code=422, detail={"message": str(e)}) from e
    except n8n_client.N8nApiError as e:
        raise HTTPException(status_code=e.status_code, detail={"message": e.message}) from e


@router.post("/workflows/{workflow_id}/batch-run/stream")
async def stream_batch_run_workflow(
    workflow_id: str,
    request: Request,
    body: WorkflowBatchRunRequest,
):
    """Stream row-level workflow batch progress as server-sent events."""

    user_id = get_user_id(request)
    try:
        workflow = await n8n_client.get_workflow(workflow_id)
        readiness = await analyze_workflow_readiness_payload(workflow, user_id=user_id)
        if readiness["missing_credentials"]:
            raise HTTPException(
                status_code=409,
                detail={"message": "Workflow has missing credentials."},
            )
    except n8n_client.N8nApiError as e:
        raise HTTPException(status_code=e.status_code, detail={"message": e.message}) from e

    async def events():
        batch_run_id: str | None = None
        try:
            async for event, payload in iter_workflow_batch_with_input(
                workflow,
                user_id=user_id,
                rows=[row.model_dump() for row in body.rows],
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
                        )
                    yield _sse(event, _batch_row_payload(payload))
                    continue

                if event == "completed" and isinstance(payload, WorkflowBatchRunResultData):
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
        await n8n_client.delete_workflow(workflow_id)
        await store.delete_workflow_metadata(user_id, workflow_id)
    except n8n_client.N8nApiError as e:
        raise HTTPException(status_code=e.status_code, detail={"message": e.message}) from e
