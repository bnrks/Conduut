"""n8n REST API client. Tek bir n8n instance'ıyla konuşur (MVP)."""
from dataclasses import dataclass

import httpx
import structlog

from src.config import settings

log = structlog.get_logger()


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        base_url=f"{settings.n8n_url}/api/v1",
        headers={"X-N8N-API-KEY": settings.n8n_api_key},
        timeout=30.0,
    )


# ---------------------------------------------------------------------------
# Dataclass'lar
# ---------------------------------------------------------------------------

@dataclass
class N8nWorkflow:
    id: str
    name: str
    active: bool
    created_at: str
    updated_at: str


@dataclass
class N8nExecution:
    id: str
    workflow_id: str
    status: str  # "running" | "success" | "error" | "waiting"
    started_at: str
    finished_at: str | None = None
    data: dict | None = None


# ---------------------------------------------------------------------------
# Workflow işlemleri
# ---------------------------------------------------------------------------

async def list_workflows() -> list[N8nWorkflow]:
    async with _client() as c:
        r = await c.get("/workflows")
        r.raise_for_status()
        items = r.json().get("data", [])
        return [
            N8nWorkflow(
                id=w["id"],
                name=w["name"],
                active=w.get("active", False),
                created_at=w.get("createdAt", ""),
                updated_at=w.get("updatedAt", ""),
            )
            for w in items
        ]


async def get_workflow(workflow_id: str) -> dict:
    async with _client() as c:
        r = await c.get(f"/workflows/{workflow_id}")
        r.raise_for_status()
        return r.json()


async def create_workflow(name: str, nodes: list[dict], connections: dict) -> N8nWorkflow:
    payload = {
        "name": name,
        "nodes": nodes,
        "connections": connections,
        "settings": {"executionOrder": "v1"},
    }
    async with _client() as c:
        r = await c.post("/workflows", json=payload)
        r.raise_for_status()
        w = r.json()
        log.info("n8n_workflow_created", workflow_id=w["id"], name=name)
        return N8nWorkflow(
            id=w["id"],
            name=w["name"],
            active=w.get("active", False),
            created_at=w.get("createdAt", ""),
            updated_at=w.get("updatedAt", ""),
        )


async def update_workflow(workflow_id: str, name: str, nodes: list[dict], connections: dict) -> N8nWorkflow:
    payload = {
        "name": name,
        "nodes": nodes,
        "connections": connections,
        "settings": {"executionOrder": "v1"},
    }
    async with _client() as c:
        r = await c.put(f"/workflows/{workflow_id}", json=payload)
        r.raise_for_status()
        w = r.json()
        return N8nWorkflow(
            id=w["id"],
            name=w["name"],
            active=w.get("active", False),
            created_at=w.get("createdAt", ""),
            updated_at=w.get("updatedAt", ""),
        )


async def activate_workflow(workflow_id: str) -> None:
    async with _client() as c:
        r = await c.patch(f"/workflows/{workflow_id}", json={"active": True})
        r.raise_for_status()
        log.info("n8n_workflow_activated", workflow_id=workflow_id)


async def deactivate_workflow(workflow_id: str) -> None:
    async with _client() as c:
        r = await c.patch(f"/workflows/{workflow_id}", json={"active": False})
        r.raise_for_status()


async def delete_workflow(workflow_id: str) -> None:
    async with _client() as c:
        r = await c.delete(f"/workflows/{workflow_id}")
        r.raise_for_status()
        log.info("n8n_workflow_deleted", workflow_id=workflow_id)


# ---------------------------------------------------------------------------
# Execution
# ---------------------------------------------------------------------------

async def execute_workflow(workflow_id: str, data: dict | None = None) -> N8nExecution:
    payload = {"workflowData": {"id": workflow_id}}
    if data:
        payload["runData"] = data
    async with _client() as c:
        r = await c.post(f"/workflows/{workflow_id}/run", json=payload)
        r.raise_for_status()
        e = r.json().get("data", {})
        log.info("n8n_workflow_executed", workflow_id=workflow_id)
        return N8nExecution(
            id=e.get("executionId", ""),
            workflow_id=workflow_id,
            status="running",
            started_at=e.get("startedAt", ""),
        )


async def get_execution(execution_id: str) -> N8nExecution:
    async with _client() as c:
        r = await c.get(f"/executions/{execution_id}")
        r.raise_for_status()
        e = r.json()
        return N8nExecution(
            id=e["id"],
            workflow_id=e.get("workflowId", ""),
            status=e.get("status", "unknown"),
            started_at=e.get("startedAt", ""),
            finished_at=e.get("finishedAt"),
        )


async def list_executions(workflow_id: str | None = None, limit: int = 10) -> list[N8nExecution]:
    params: dict = {"limit": limit}
    if workflow_id:
        params["workflowId"] = workflow_id
    async with _client() as c:
        r = await c.get("/executions", params=params)
        r.raise_for_status()
        items = r.json().get("data", [])
        return [
            N8nExecution(
                id=e["id"],
                workflow_id=e.get("workflowId", ""),
                status=e.get("status", "unknown"),
                started_at=e.get("startedAt", ""),
                finished_at=e.get("finishedAt"),
            )
            for e in items
        ]


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------

async def health_check() -> bool:
    try:
        async with httpx.AsyncClient(timeout=5.0) as c:
            r = await c.get(f"{settings.n8n_url}/healthz")
            return r.status_code == 200
    except Exception:
        return False
