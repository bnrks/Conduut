"""n8n REST API client. Tek bir n8n instance'ıyla konuşur (MVP)."""

from dataclasses import dataclass
from time import perf_counter
from typing import Any

import httpx
import structlog

from src.config import settings
from src.logging_config import redact_for_logging

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


def _response_preview(response: httpx.Response) -> Any:
    content_type = response.headers.get("content-type", "")
    if content_type.startswith("application/json"):
        try:
            return redact_for_logging(response.json())
        except ValueError:
            return _error_message(response)
    return redact_for_logging(response.text.strip())


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


def _request_payload_summary(payload: Any) -> dict[str, Any] | None:
    """Return technical shape/count metadata without workflow or user values."""

    if payload is None:
        return None
    if not isinstance(payload, dict):
        return {"type": type(payload).__name__}
    summary: dict[str, Any] = {
        "keys": sorted(str(key) for key in payload)[:20],
    }
    nodes = payload.get("nodes")
    if isinstance(nodes, list):
        summary["node_count"] = len(nodes)
        summary["node_types"] = sorted(
            {str(node.get("type")) for node in nodes if isinstance(node, dict) and node.get("type")}
        )[:20]
    connections = payload.get("connections")
    if isinstance(connections, dict):
        summary["connection_source_count"] = len(connections)
    rows = payload.get("rows")
    if isinstance(rows, list):
        summary["row_count"] = len(rows)
    return summary


async def _request(method: str, path: str, **kwargs: Any) -> httpx.Response:
    started_at = perf_counter()
    log.debug(
        "n8n_request_started",
        method=method.upper(),
        path=path,
        params=kwargs.get("params"),
        payload_summary=_request_payload_summary(kwargs.get("json")),
    )
    try:
        async with _client() as c:
            response = await c.request(method, path, **kwargs)
    except Exception as exc:
        duration_ms = round((perf_counter() - started_at) * 1000, 2)
        log.error(
            "n8n_request_transport_error",
            method=method.upper(),
            path=path,
            duration_ms=duration_ms,
            error_type=type(exc).__name__,
            error=str(exc),
        )
        raise

    duration_ms = round((perf_counter() - started_at) * 1000, 2)
    event = "n8n_request_error" if response.status_code >= 400 else "n8n_request_finished"
    log_method = log.warning if response.status_code >= 400 else log.info
    log_method(
        event,
        method=method.upper(),
        path=path,
        status_code=response.status_code,
        duration_ms=duration_ms,
        response_preview=_response_preview(response) if response.status_code >= 400 else None,
    )
    return response


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
    # n8n list cevabı her workflow'un node'larını da döndürür; node sayısını
    # buradan türetip listede her workflow için ayrı get_workflow (N+1) atmaktan
    # kaçınırız. create/update yollarında set edilmez (0).
    node_count: int = 0


@dataclass
class N8nExecution:
    id: str
    workflow_id: str
    status: str  # "running" | "success" | "error" | "waiting"
    started_at: str
    finished_at: str | None = None
    mode: str | None = None
    data: dict | None = None


@dataclass
class N8nExecutionPage:
    """One cursor-paginated page from n8n's executions API."""

    executions: list[N8nExecution]
    next_cursor: str | None = None


# ---------------------------------------------------------------------------
# Workflow işlemleri
# ---------------------------------------------------------------------------


async def list_workflows_raw() -> list[dict]:
    """Ham n8n list cevabı (her workflow'un `nodes`'u dahil). Credential reuse
    taraması gibi node detayı gereken yerler per-workflow get_workflow (N+1)
    yerine bunu kullanır."""
    r = await _request("GET", "/workflows")
    _raise_for_status(r)
    return list(r.json().get("data", []))


async def list_workflows() -> list[N8nWorkflow]:
    items = await list_workflows_raw()
    return [
        N8nWorkflow(
            id=w["id"],
            name=w["name"],
            active=w.get("active", False),
            created_at=w.get("createdAt", ""),
            updated_at=w.get("updatedAt", ""),
            node_count=len(w.get("nodes") or []),
        )
        for w in items
    ]


async def get_workflow(workflow_id: str) -> dict:
    r = await _request("GET", f"/workflows/{workflow_id}")
    _raise_for_status(r)
    return r.json()


def _workflow_settings(workflow_settings: dict[str, Any] | None = None) -> dict[str, Any]:
    merged = dict(workflow_settings or {})
    merged.setdefault("executionOrder", "v1")
    merged.setdefault("timezone", settings.workflow_timezone)
    return merged


async def _put_workflow_preserving_activation(
    workflow_id: str,
    payload: dict[str, Any],
    *,
    was_active: bool,
) -> dict[str, Any]:
    """Update a workflow and restore n8n's trigger registration when active."""

    r = await _request("PUT", f"/workflows/{workflow_id}", json=payload)
    _raise_for_status(r)
    updated = r.json()
    if was_active:
        # Re-read after the PUT: a user may have explicitly deactivated the
        # workflow after our initial snapshot. Do not overwrite that newer
        # intent merely to repair trigger registration.
        latest = await get_workflow(workflow_id)
        if not latest.get("active", False):
            updated["active"] = False
            return updated
        await deactivate_workflow(workflow_id)
        await activate_workflow(workflow_id)
        updated["active"] = True
    return updated


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
    r = await _request("POST", "/workflows", json=payload)
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
    current = await get_workflow(workflow_id)
    was_active = bool(current.get("active", False))
    payload = {
        "name": name,
        "nodes": nodes,
        "connections": connections,
        "settings": _workflow_settings(settings),
    }
    w = await _put_workflow_preserving_activation(
        workflow_id,
        payload,
        was_active=was_active,
    )
    return N8nWorkflow(
        id=w["id"],
        name=w["name"],
        active=bool(w.get("active", False)),
        created_at=w.get("createdAt", ""),
        updated_at=w.get("updatedAt", ""),
    )


async def activate_workflow(workflow_id: str) -> None:
    r = await _request("POST", f"/workflows/{workflow_id}/activate")
    _raise_for_status(r)
    log.info("n8n_workflow_activated", workflow_id=workflow_id)


async def deactivate_workflow(workflow_id: str) -> None:
    r = await _request("POST", f"/workflows/{workflow_id}/deactivate")
    _raise_for_status(r)
    log.info("n8n_workflow_deactivated", workflow_id=workflow_id)


async def delete_workflow(workflow_id: str) -> None:
    r = await _request("DELETE", f"/workflows/{workflow_id}")
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
    r = await _request("GET", "/credentials")
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
    r = await _request("GET", f"/credentials/schema/{credential_type}")
    _raise_for_status(r)
    return r.json()


async def create_credential(name: str, credential_type: str, data: dict[str, Any]) -> N8nCredential:
    payload = {"name": name, "type": credential_type, "data": data}
    r = await _request("POST", "/credentials", json=payload)
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
    r = await _request("DELETE", f"/credentials/{credential_id}")
    _raise_for_status(r)
    log.info("n8n_credential_deleted", credential_id=credential_id)


async def attach_credential_to_workflow(
    workflow_id: str,
    node_name: str,
    credential_type: str,
    credential_id: str,
    credential_name: str,
    *,
    generic_auth_type: str | None = None,
) -> dict:
    """Attach a credential to a workflow node.

    When ``generic_auth_type`` is given (HTTP Request generic auth), the node's
    parameters are also set to ``authentication=genericCredentialType`` and
    ``genericAuthType=<generic_auth_type>`` so n8n actually uses the credential.
    Default None preserves the existing behaviour (Gmail/Sheets OAuth).
    """

    workflow = await get_workflow(workflow_id)
    nodes = workflow.get("nodes", [])
    matched = False
    for node in nodes:
        if node.get("name") == node_name:
            existing_credential = node.get("credentials", {}).get(credential_type, {})
            same_credential = (
                isinstance(existing_credential, dict)
                and str(existing_credential.get("id") or "") == credential_id
            )
            parameters = node.get("parameters", {})
            generic_auth_configured = not generic_auth_type or (
                isinstance(parameters, dict)
                and parameters.get("authentication") == "genericCredentialType"
                and parameters.get("genericAuthType") == generic_auth_type
            )
            if same_credential and generic_auth_configured:
                return workflow
            if generic_auth_type:
                params = node.setdefault("parameters", {})
                params["authentication"] = "genericCredentialType"
                params["genericAuthType"] = generic_auth_type
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
        "settings": _workflow_settings(workflow.get("settings")),
    }
    return await _put_workflow_preserving_activation(
        workflow_id,
        payload,
        was_active=bool(workflow.get("active", False)),
    )


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
    r = await _request("GET", f"/executions/{execution_id}")
    _raise_for_status(r)
    return _execution_from_payload(r.json())


def _execution_from_payload(payload: dict[str, Any]) -> N8nExecution:
    return N8nExecution(
        id=str(payload.get("id", "")),
        workflow_id=str(payload.get("workflowId", "")),
        status=str(payload.get("status", "unknown")),
        started_at=str(payload.get("startedAt", "")),
        # Current n8n responses use stoppedAt. Keep finishedAt as a fallback
        # for older payloads and fixtures already used by Conduut.
        finished_at=payload.get("stoppedAt") or payload.get("finishedAt"),
        mode=str(payload["mode"]) if payload.get("mode") else None,
    )


async def list_executions_page(
    workflow_id: str | None = None,
    *,
    status: str | None = None,
    cursor: str | None = None,
    limit: int = 10,
) -> N8nExecutionPage:
    """Return one execution page while preserving n8n's opaque cursor."""

    params: dict = {"limit": limit}
    if workflow_id:
        params["workflowId"] = workflow_id
    if status:
        params["status"] = status
    if cursor:
        params["cursor"] = cursor
    r = await _request("GET", "/executions", params=params)
    _raise_for_status(r)
    payload = r.json()
    items = payload.get("data", [])
    return N8nExecutionPage(
        executions=[_execution_from_payload(item) for item in items if isinstance(item, dict)],
        next_cursor=(str(payload["nextCursor"]) if payload.get("nextCursor") else None),
    )


async def list_executions(workflow_id: str | None = None, limit: int = 10) -> list[N8nExecution]:
    """Backward-compatible unpaged execution list for existing agent paths."""

    page = await list_executions_page(workflow_id=workflow_id, limit=limit)
    return page.executions


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
    r = await _request("GET", f"/executions/{execution_id}", params={"includeData": "true"})
    _raise_for_status(r)
    return r.json()


# A synchronous webhook run (responseMode=lastNode) blocks until the WHOLE
# workflow finishes. AI/LLM workflows routinely take 30-120s, so this must be far
# longer than the 30s used for quick CRUD API calls — otherwise the run times out
# even though n8n completes the execution successfully.
_WEBHOOK_RUN_TIMEOUT = 120.0


async def call_webhook(path: str, payload: dict[str, Any] | None = None) -> httpx.Response:
    started_at = perf_counter()
    url = f"{settings.n8n_url.rstrip('/')}/webhook/{path}"
    log.debug(
        "n8n_webhook_request_started",
        path=path,
        payload_summary=_request_payload_summary(payload),
    )
    try:
        async with httpx.AsyncClient(timeout=_WEBHOOK_RUN_TIMEOUT) as c:
            response = await c.post(url, json=payload or {})
    except Exception as exc:
        duration_ms = round((perf_counter() - started_at) * 1000, 2)
        log.error(
            "n8n_webhook_transport_error",
            path=path,
            duration_ms=duration_ms,
            error_type=type(exc).__name__,
            error=str(exc),
        )
        raise
    duration_ms = round((perf_counter() - started_at) * 1000, 2)
    event = "n8n_webhook_error" if response.status_code >= 400 else "n8n_webhook_finished"
    log_method = log.warning if response.status_code >= 400 else log.info
    log_method(
        event,
        path=path,
        status_code=response.status_code,
        duration_ms=duration_ms,
        response_preview=_response_preview(response) if response.status_code >= 400 else None,
    )
    return response
