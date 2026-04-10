"""Workflows router — n8n workflow'larını listeler ve yönetir."""

import asyncio

from fastapi import APIRouter, HTTPException, Request

from src import n8n_client
from src.auth import get_user_id

router = APIRouter()


@router.get("/workflows")
async def list_workflows(request: Request):
    # TODO: MVP'de tek paylaşık n8n instance kullanılıyor.
    # Per-user container izolasyonu gelince user_id ile filtreleme eklenecek.
    get_user_id(request)  # auth kontrolü

    workflows = await n8n_client.list_workflows()

    # Her workflow için node sayısını paralel olarak çek
    async def _enrich(w: n8n_client.N8nWorkflow) -> dict:
        try:
            detail = await n8n_client.get_workflow(w.id)
            node_count = len(detail.get("nodes", []))
        except Exception:
            node_count = 0
        return {
            "id": w.id,
            "name": w.name,
            "status": "active" if w.active else "inactive",
            "nodeCount": node_count,
            "createdAt": w.created_at,
            "updatedAt": w.updated_at,
            "executionCount": 0,
        }

    enriched = await asyncio.gather(*[_enrich(w) for w in workflows])
    return {"workflows": list(enriched)}


@router.patch("/workflows/{workflow_id}/activate")
async def activate_workflow(workflow_id: str, request: Request):
    get_user_id(request)
    try:
        await n8n_client.activate_workflow(workflow_id)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"success": True, "workflow_id": workflow_id}


@router.patch("/workflows/{workflow_id}/deactivate")
async def deactivate_workflow(workflow_id: str, request: Request):
    get_user_id(request)
    try:
        await n8n_client.deactivate_workflow(workflow_id)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"success": True, "workflow_id": workflow_id}


@router.delete("/workflows/{workflow_id}", status_code=204)
async def delete_workflow(workflow_id: str, request: Request):
    get_user_id(request)
    try:
        await n8n_client.delete_workflow(workflow_id)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
