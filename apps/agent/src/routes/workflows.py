"""Workflows router — n8n workflow'larını listeler ve yönetir."""

import asyncio
from typing import Any, Literal

import structlog
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from src import n8n_client, store
from src.agent.tools import (
    _input_schema_payload,
    _workflow_input_schema_from_metadata,
    analyze_workflow_readiness_payload,
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


@router.get("/workflows")
async def list_workflows(request: Request):
    # TODO: MVP'de tek paylaşık n8n instance kullanılıyor.
    # Per-user container izolasyonu gelince user_id ile filtreleme eklenecek.
    user_id = get_user_id(request)

    workflows = await n8n_client.list_workflows()

    # Her workflow için node sayısını paralel olarak çek
    async def _enrich(w: n8n_client.N8nWorkflow) -> dict:
        try:
            detail = await n8n_client.get_workflow(w.id)
            node_count = len(detail.get("nodes", []))
        except Exception:
            node_count = 0
        metadata = await store.get_workflow_metadata(user_id, w.id)
        input_schema = _workflow_input_schema_from_metadata(metadata)
        return {
            "id": w.id,
            "name": w.name,
            "status": "active" if w.active else "inactive",
            "nodeCount": node_count,
            "createdAt": w.created_at,
            "updatedAt": w.updated_at,
            "executionCount": 0,
            "inputSchema": _input_schema_payload(input_schema),
        }

    enriched = await asyncio.gather(*[_enrich(w) for w in workflows])
    return {"workflows": list(enriched)}


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
            for artifact in row.artifacts:
                try:
                    await store.save_artifact(
                        user_id,
                        artifact.model_dump(exclude_none=True),
                        origin={
                            "kind": "workflow_batch_run",
                            "workflowId": workflow_id,
                            "batchRunId": result.batchRunId,
                            "rowNumber": row.rowNumber,
                            "executionId": row.executionId,
                        },
                    )
                except Exception as exc:
                    log.error(
                        "workflow_batch_artifact_persist_error",
                        workflow_id=workflow_id,
                        batch_run_id=result.batchRunId,
                        row_number=row.rowNumber,
                        error_type=type(exc).__name__,
                        error=str(exc),
                        exc_info=True,
                    )
        return {
            "success": result.status != "failed",
            "workflow_id": workflow_id,
            "batchRunId": result.batchRunId,
            "status": result.status,
            "totalRows": result.totalRows,
            "succeeded": result.succeeded,
            "failed": result.failed,
            "skipped": result.skipped,
            "results": [
                {
                    "rowNumber": row.rowNumber,
                    "status": row.status,
                    "execution_id": row.executionId,
                    "summary": row.summary,
                    "error": row.error,
                    "artifacts": [
                        artifact.model_dump(exclude_none=True) for artifact in row.artifacts
                    ],
                }
                for row in result.results
            ],
        }
    except ValueError as e:
        raise HTTPException(status_code=422, detail={"message": str(e)}) from e
    except n8n_client.N8nApiError as e:
        raise HTTPException(status_code=e.status_code, detail={"message": e.message}) from e


@router.delete("/workflows/{workflow_id}", status_code=204)
async def delete_workflow(workflow_id: str, request: Request):
    user_id = get_user_id(request)
    try:
        await n8n_client.delete_workflow(workflow_id)
        await store.delete_workflow_metadata(user_id, workflow_id)
    except n8n_client.N8nApiError as e:
        raise HTTPException(status_code=e.status_code, detail={"message": e.message}) from e
