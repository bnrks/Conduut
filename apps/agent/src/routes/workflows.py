"""Workflows router — n8n workflow'larını listeler ve yönetir."""

import asyncio
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from src import n8n_client, store
from src.agent.tools import (
    _input_schema_payload,
    _workflow_input_schema_from_metadata,
    analyze_workflow_readiness_payload,
    run_workflow_with_input,
)
from src.auth import get_user_id

router = APIRouter()


class WorkflowRunRequest(BaseModel):
    input: dict[str, Any] = Field(default_factory=dict)
    source: Literal["dashboard", "agent"] = "dashboard"


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


@router.delete("/workflows/{workflow_id}", status_code=204)
async def delete_workflow(workflow_id: str, request: Request):
    user_id = get_user_id(request)
    try:
        await n8n_client.delete_workflow(workflow_id)
        await store.delete_workflow_metadata(user_id, workflow_id)
    except n8n_client.N8nApiError as e:
        raise HTTPException(status_code=e.status_code, detail={"message": e.message}) from e
