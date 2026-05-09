"""n8n REST API client. Tek bir n8n instance'ıyla konuşur (MVP)."""

from dataclasses import dataclass
from typing import Any

import httpx
import structlog

from src.config import settings

log = structlog.get_logger()


class N8nApiError(RuntimeError):
    """Typed n8n API error that preserves the user-facing response body."""

    def __init__(self, status_code: int, message: str, *, method: str, path: str):
        super().__init__(message)
        self.status_code = status_code
        self.message = message
        self.method = method
        self.path = path


def _error_message(response: httpx.Response) -> str:
    content_type = response.headers.get("content-type", "")
    payload = response.json() if content_type.startswith("application/json") else None
    if isinstance(payload, dict):
        detail = payload.get("message") or payload.get("detail") or payload.get("error")
        if isinstance(detail, str):
            return detail
    text = response.text.strip()
    return text[:500] or f"n8n API returned {response.status_code}"


def _raise_for_status(response: httpx.Response) -> None:
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        request = exc.request
        raise N8nApiError(
            response.status_code,
            _error_message(response),
            method=request.method,
            path=request.url.path,
        ) from exc


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
        _raise_for_status(r)
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
        _raise_for_status(r)
        return r.json()


def _workflow_settings(settings: dict[str, Any] | None = None) -> dict[str, Any]:
    merged = dict(settings or {})
    merged.setdefault("executionOrder", "v1")
    return merged


async def create_workflow(
    name: str,
    nodes: list[dict],
    connections: dict,
    settings: dict[str, Any] | None = None,
) -> N8nWorkflow:
    payload = {
        "name": name,
        "nodes": nodes,
        "connections": connections,
        "settings": _workflow_settings(settings),
    }
    async with _client() as c:
        r = await c.post("/workflows", json=payload)
        _raise_for_status(r)
        w = r.json()
        log.info("n8n_workflow_created", workflow_id=w["id"], name=name)
        return N8nWorkflow(
            id=w["id"],
            name=w["name"],
            active=w.get("active", False),
            created_at=w.get("createdAt", ""),
            updated_at=w.get("updatedAt", ""),
        )


async def update_workflow(
    workflow_id: str,
    name: str,
    nodes: list[dict],
    connections: dict,
    settings: dict[str, Any] | None = None,
) -> N8nWorkflow:  # noqa: E501
    payload = {
        "name": name,
        "nodes": nodes,
        "connections": connections,
        "settings": _workflow_settings(settings),
    }
    async with _client() as c:
        r = await c.put(f"/workflows/{workflow_id}", json=payload)
        _raise_for_status(r)
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
        r = await c.post(f"/workflows/{workflow_id}/activate")
        _raise_for_status(r)
        log.info("n8n_workflow_activated", workflow_id=workflow_id)


async def deactivate_workflow(workflow_id: str) -> None:
    async with _client() as c:
        r = await c.post(f"/workflows/{workflow_id}/deactivate")
        _raise_for_status(r)
        log.info("n8n_workflow_deactivated", workflow_id=workflow_id)


async def delete_workflow(workflow_id: str) -> None:
    async with _client() as c:
        r = await c.delete(f"/workflows/{workflow_id}")
        _raise_for_status(r)
        log.info("n8n_workflow_deleted", workflow_id=workflow_id)


# ---------------------------------------------------------------------------
# Credentials
# ---------------------------------------------------------------------------


@dataclass
class N8nCredential:
    id: str
    name: str
    type: str


async def list_credentials() -> list[N8nCredential]:
    async with _client() as c:
        r = await c.get("/credentials")
        _raise_for_status(r)
        items = r.json().get("data", [])
        return [
            N8nCredential(
                id=str(item.get("id", "")),
                name=item.get("name", ""),
                type=item.get("type", ""),
            )
            for item in items
        ]


async def get_credential_schema(credential_type: str) -> dict[str, Any]:
    async with _client() as c:
        r = await c.get(f"/credentials/schema/{credential_type}")
        _raise_for_status(r)
        return r.json()


async def create_credential(name: str, credential_type: str, data: dict[str, Any]) -> N8nCredential:
    payload = {"name": name, "type": credential_type, "data": data}
    async with _client() as c:
        r = await c.post("/credentials", json=payload)
        _raise_for_status(r)
        item = r.json()
        credential = N8nCredential(
            id=str(item.get("id", "")),
            name=item.get("name", name),
            type=item.get("type", credential_type),
        )
        log.info("n8n_credential_created", credential_id=credential.id, type=credential.type)
        return credential


async def delete_credential(credential_id: str) -> None:
    async with _client() as c:
        r = await c.delete(f"/credentials/{credential_id}")
        _raise_for_status(r)
        log.info("n8n_credential_deleted", credential_id=credential_id)


async def attach_credential_to_workflow(
    workflow_id: str,
    node_name: str,
    credential_type: str,
    credential_id: str,
    credential_name: str,
) -> dict:
    workflow = await get_workflow(workflow_id)
    nodes = workflow.get("nodes", [])
    matched = False
    for node in nodes:
        if node.get("name") == node_name:
            credentials = node.setdefault("credentials", {})
            credentials[credential_type] = {"id": credential_id, "name": credential_name}
            matched = True
            break
    if not matched:
        raise N8nApiError(404, f"Node '{node_name}' was not found", method="PUT", path="/workflows")

    payload = {
        "name": workflow.get("name", "Workflow"),
        "nodes": nodes,
        "connections": workflow.get("connections", {}),
        "settings": workflow.get("settings") or {"executionOrder": "v1"},
    }
    async with _client() as c:
        r = await c.put(f"/workflows/{workflow_id}", json=payload)
        _raise_for_status(r)
        return r.json()


# ---------------------------------------------------------------------------
# Execution
# ---------------------------------------------------------------------------


async def execute_workflow(workflow_id: str) -> dict:
    """Workflow'u aktive eder ve trigger bilgisini döner.

    n8n public REST API v1'de manuel çalıştırma endpoint'i yoktur.
    Workflow'u aktive etmek, trigger'ına (schedule, webhook, vb.) göre
    otomatik olarak çalışmasını sağlar.
    Webhook trigger'ı varsa test için çağrılabilecek URL'i de döner.
    """
    # Önce workflow node'larını al (trigger tipini öğrenmek için)
    wf = await get_workflow(workflow_id)
    nodes = wf.get("nodes", [])

    # Workflow'u aktive et
    await activate_workflow(workflow_id)
    log.info("n8n_workflow_executed", workflow_id=workflow_id)

    # Webhook trigger varsa URL'ini döndür
    for node in nodes:
        node_type = node.get("type", "")
        if node_type == "n8n-nodes-base.webhook":
            path = node.get("parameters", {}).get("path", "")
            if path:
                n8n_base = settings.n8n_url.rstrip("/")
                return {
                    "workflow_id": workflow_id,
                    "status": "activated",
                    "trigger": "webhook",
                    "webhook_url": f"{n8n_base}/webhook/{path}",
                    "note": (
                        f"Workflow activated. Call POST {n8n_base}/webhook/{path} to trigger it."
                    ),
                }

    # Schedule veya diğer trigger
    trigger_types = [n.get("type", "") for n in nodes if "trigger" in n.get("type", "").lower()]
    trigger = trigger_types[0] if trigger_types else "unknown"
    return {
        "workflow_id": workflow_id,
        "status": "activated",
        "trigger": trigger,
        "note": "Workflow activated and will run automatically on its trigger.",
    }


async def get_execution(execution_id: str) -> N8nExecution:
    async with _client() as c:
        r = await c.get(f"/executions/{execution_id}")
        _raise_for_status(r)
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
        _raise_for_status(r)
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


async def get_execution_detail(execution_id: str) -> dict[str, Any]:
    async with _client() as c:
        r = await c.get(f"/executions/{execution_id}", params={"includeData": "true"})
        _raise_for_status(r)
        return r.json()


async def call_webhook(path: str, payload: dict[str, Any] | None = None) -> httpx.Response:
    async with httpx.AsyncClient(timeout=30.0) as c:
        return await c.post(f"{settings.n8n_url.rstrip('/')}/webhook/{path}", json=payload or {})
