"""n8n REST API client. Tek bir n8n instance'ıyla konuşur (MVP)."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from copy import deepcopy
from dataclasses import dataclass
from time import perf_counter
from typing import Any
from weakref import WeakValueDictionary

import httpx
import structlog

from src.config import settings, shared_dev_n8n_api_key
from src.logging_config import redact_for_logging
from src.n8n_security import normalize_customer_owned_n8n_url, pin_customer_owned_n8n_url

log = structlog.get_logger()

_workflow_locks: WeakValueDictionary[str, asyncio.Lock] = WeakValueDictionary()


class N8nApiError(RuntimeError):
    """Typed n8n API error that preserves the user-facing response body."""

    def __init__(self, status_code: int, message: str, *, method: str, path: str):
        super().__init__(message)
        self.status_code = status_code
        self.message = message
        self.method = method
        self.path = path


@dataclass(frozen=True)
class N8nClient:
    base_url: str
    api_key: str
    webhook_base_url: str | None = None
    instance_id: str | None = None
    ownership: str | None = None

    @property
    def api_base_url(self) -> str:
        return f"{self.base_url.rstrip('/')}/api/v1"

    @property
    def resolved_webhook_base_url(self) -> str:
        return (self.webhook_base_url or self.base_url).rstrip("/")

    def _validate_runtime_urls(self) -> None:
        if self.ownership == "customer_owned":
            normalize_customer_owned_n8n_url(self.base_url)
            normalize_customer_owned_n8n_url(self.resolved_webhook_base_url)

    def _lock_key(self, workflow_id: str) -> str:
        prefix = self.instance_id or "shared"
        return f"{prefix}:{workflow_id}"

    def _api_client(self, *, timeout: float = 30.0) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=self.api_base_url,
            headers={"X-N8N-API-KEY": self.api_key},
            timeout=timeout,
            follow_redirects=False,
        )

    def _pinned_target(
        self,
        url: str,
        *,
        headers: dict[str, str] | None = None,
    ) -> tuple[str, dict[str, str], dict[str, Any]]:
        request_headers = dict(headers or {})
        if self.ownership != "customer_owned":
            return url, request_headers, {}
        pinned = pin_customer_owned_n8n_url(url)
        request_headers["Host"] = pinned.host_header
        return (
            pinned.pinned_url,
            request_headers,
            {"sni_hostname": pinned.sni_hostname},
        )

    def _transport_error_for_log(self, exc: Exception) -> str | None:
        if self.ownership == "customer_owned":
            return None
        return str(exc)

    async def request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        started_at = perf_counter()
        log.debug(
            "n8n_request_started",
            method=method.upper(),
            path=path,
            instance_id=self.instance_id,
            ownership=self.ownership,
            params=kwargs.get("params"),
            payload_summary=_request_payload_summary(kwargs.get("json")),
        )
        try:
            if self.ownership == "customer_owned":
                url = f"{self.api_base_url}/{path.lstrip('/')}"
                pinned_url, headers, extensions = self._pinned_target(
                    url,
                    headers={"X-N8N-API-KEY": self.api_key},
                )
                async with httpx.AsyncClient(timeout=30.0, follow_redirects=False) as c:
                    response = await c.request(
                        method,
                        pinned_url,
                        headers=headers,
                        extensions=extensions,
                        **kwargs,
                    )
            else:
                async with self._api_client() as c:
                    response = await c.request(method, path, **kwargs)
        except Exception as exc:
            duration_ms = round((perf_counter() - started_at) * 1000, 2)
            log.error(
                "n8n_request_transport_error",
                method=method.upper(),
                path=path,
                duration_ms=duration_ms,
                instance_id=self.instance_id,
                ownership=self.ownership,
                error_type=type(exc).__name__,
                error=self._transport_error_for_log(exc),
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
            instance_id=self.instance_id,
            ownership=self.ownership,
            response_preview=_response_preview(response) if response.status_code >= 400 else None,
        )
        return response

    async def get_rest_settings(self) -> dict[str, Any]:
        url = f"{self.base_url.rstrip('/')}/rest/settings"
        url, headers, extensions = self._pinned_target(
            url,
            headers={"X-N8N-API-KEY": self.api_key},
        )
        started_at = perf_counter()
        try:
            async with httpx.AsyncClient(timeout=10.0, follow_redirects=False) as c:
                response = await c.get(url, headers=headers, extensions=extensions)
        except Exception as exc:
            duration_ms = round((perf_counter() - started_at) * 1000, 2)
            log.error(
                "n8n_settings_transport_error",
                duration_ms=duration_ms,
                instance_id=self.instance_id,
                ownership=self.ownership,
                error_type=type(exc).__name__,
                error=self._transport_error_for_log(exc),
            )
            raise
        if response.status_code >= 400:
            raise N8nApiError(
                response.status_code,
                _error_message(response),
                method="GET",
                path="/rest/settings",
            )
        payload = response.json()
        if not isinstance(payload, dict):
            raise N8nApiError(
                502,
                "n8n /rest/settings returned an unexpected payload",
                method="GET",
                path="/rest/settings",
            )
        return payload

    async def health_check(self) -> bool:
        try:
            url, headers, extensions = self._pinned_target(f"{self.base_url.rstrip('/')}/healthz")
            async with httpx.AsyncClient(timeout=5.0, follow_redirects=False) as c:
                response = await c.get(url, headers=headers, extensions=extensions)
                return response.status_code == 200
        except Exception:
            return False

    async def fetch_public_asset(self, path: str) -> httpx.Response:
        """Fetch a public n8n asset through the target-aware SSRF boundary."""
        url = f"{self.base_url.rstrip('/')}/{path.lstrip('/')}"
        url, headers, extensions = self._pinned_target(url)
        async with httpx.AsyncClient(timeout=10.0, follow_redirects=False) as client:
            return await client.get(url, headers=headers, extensions=extensions)

    async def call_webhook(
        self, path: str, payload: dict[str, Any] | None = None
    ) -> httpx.Response:
        started_at = perf_counter()
        url = f"{self.resolved_webhook_base_url}/webhook/{path}"
        url, headers, extensions = self._pinned_target(url)
        log.debug(
            "n8n_webhook_request_started",
            path=path,
            instance_id=self.instance_id,
            ownership=self.ownership,
            payload_summary=_request_payload_summary(payload),
        )
        try:
            async with httpx.AsyncClient(timeout=_WEBHOOK_RUN_TIMEOUT, follow_redirects=False) as c:
                response = await c.post(
                    url,
                    json=payload or {},
                    headers=headers,
                    extensions=extensions,
                )
        except Exception as exc:
            duration_ms = round((perf_counter() - started_at) * 1000, 2)
            log.error(
                "n8n_webhook_transport_error",
                path=path,
                duration_ms=duration_ms,
                instance_id=self.instance_id,
                ownership=self.ownership,
                error_type=type(exc).__name__,
                error=self._transport_error_for_log(exc),
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
            instance_id=self.instance_id,
            ownership=self.ownership,
            response_preview=_response_preview(response) if response.status_code >= 400 else None,
        )
        return response

    async def list_workflows_raw(self) -> list[dict]:
        response = await self.request("GET", "/workflows")
        _raise_for_status(response)
        return list(response.json().get("data", []))

    async def list_workflows(self) -> list["N8nWorkflow"]:
        items = await self.list_workflows_raw()
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

    async def get_workflow(self, workflow_id: str) -> dict[str, Any]:
        response = await self.request("GET", f"/workflows/{workflow_id}")
        _raise_for_status(response)
        return response.json()

    async def _put_workflow_preserving_activation(
        self,
        workflow_id: str,
        payload: dict[str, Any],
        *,
        was_active: bool,
    ) -> dict[str, Any]:
        response = await self.request("PUT", f"/workflows/{workflow_id}", json=payload)
        _raise_for_status(response)
        updated = response.json()
        if was_active:
            latest = await self.get_workflow(workflow_id)
            if not latest.get("active", False):
                updated["active"] = False
                return updated
            await self.deactivate_workflow(workflow_id)
            await self.activate_workflow(workflow_id)
            updated["active"] = True
        return updated

    async def _mutate_workflow(
        self,
        workflow_id: str,
        mutate: "WorkflowMutator",
        *,
        verify: "WorkflowVerifier" | None = None,
    ) -> dict[str, Any]:
        async with _workflow_lock(self._lock_key(workflow_id)):
            current = await self.get_workflow(workflow_id)
            mutated, changed = mutate(deepcopy(current))
            if not changed:
                return current
            committed = await self._put_workflow_preserving_activation(
                workflow_id,
                _workflow_payload(mutated),
                was_active=bool(current.get("active", False)),
            )
            if verify and not verify(committed):
                raise N8nApiError(
                    409,
                    "Workflow mutation could not be verified against the committed result",
                    method="PUT",
                    path=f"/workflows/{workflow_id}",
                )
            return committed

    async def create_workflow(
        self,
        name: str,
        nodes: list[dict],
        connections: dict,
        settings_: dict[str, Any] | None = None,
    ) -> "N8nWorkflow":
        payload = {
            "name": name,
            "nodes": nodes,
            "connections": connections,
            "settings": _workflow_settings(settings_),
        }
        response = await self.request("POST", "/workflows", json=payload)
        _raise_for_status(response)
        workflow = response.json()
        return N8nWorkflow(
            id=workflow["id"],
            name=workflow["name"],
            active=workflow.get("active", False),
            created_at=workflow.get("createdAt", ""),
            updated_at=workflow.get("updatedAt", ""),
        )

    async def update_workflow(
        self,
        workflow_id: str,
        name: str,
        nodes: list[dict],
        connections: dict | None,
        settings_: dict[str, Any] | None = None,
    ) -> "N8nWorkflow":
        def mutate(current: dict[str, Any]) -> tuple[dict[str, Any], bool]:
            current_nodes = current.get("nodes") if isinstance(current.get("nodes"), list) else []
            current_connections = (
                current.get("connections") if isinstance(current.get("connections"), dict) else {}
            )
            current_settings = (
                current.get("settings") if isinstance(current.get("settings"), dict) else {}
            )
            current_name = str(current.get("name") or "Workflow")
            merged_nodes = _merge_retained_node_state(current_nodes, nodes)
            next_connections = (
                deepcopy(connections) if connections is not None else deepcopy(current_connections)
            )
            next_settings = _workflow_settings(
                settings_ if settings_ is not None else current_settings
            )
            changed = (
                current_name != name
                or current_nodes != merged_nodes
                or current_connections != next_connections
                or current_settings != next_settings
            )
            return (
                {
                    **current,
                    "name": name,
                    "nodes": merged_nodes,
                    "connections": next_connections,
                    "settings": next_settings,
                },
                changed,
            )

        workflow = await self._mutate_workflow(workflow_id, mutate)
        return N8nWorkflow(
            id=workflow["id"],
            name=workflow["name"],
            active=bool(workflow.get("active", False)),
            created_at=workflow.get("createdAt", ""),
            updated_at=workflow.get("updatedAt", ""),
        )

    async def activate_workflow(self, workflow_id: str) -> None:
        response = await self.request("POST", f"/workflows/{workflow_id}/activate")
        _raise_for_status(response)

    async def deactivate_workflow(self, workflow_id: str) -> None:
        response = await self.request("POST", f"/workflows/{workflow_id}/deactivate")
        _raise_for_status(response)

    async def delete_workflow(self, workflow_id: str) -> None:
        response = await self.request("DELETE", f"/workflows/{workflow_id}")
        _raise_for_status(response)

    async def list_credentials(self) -> list["N8nCredential"]:
        response = await self.request("GET", "/credentials")
        _raise_for_status(response)
        items = response.json().get("data", [])
        return [
            N8nCredential(
                id=str(item.get("id", "")),
                name=item.get("name", ""),
                type=item.get("type", ""),
            )
            for item in items
        ]

    async def get_credential_schema(self, credential_type: str) -> dict[str, Any]:
        response = await self.request("GET", f"/credentials/schema/{credential_type}")
        _raise_for_status(response)
        return response.json()

    async def create_credential(
        self, name: str, credential_type: str, data: dict[str, Any]
    ) -> "N8nCredential":
        response = await self.request(
            "POST",
            "/credentials",
            json={"name": name, "type": credential_type, "data": data},
        )
        _raise_for_status(response)
        item = response.json()
        return N8nCredential(
            id=str(item.get("id", "")),
            name=item.get("name", name),
            type=item.get("type", credential_type),
        )

    async def delete_credential(self, credential_id: str) -> None:
        response = await self.request("DELETE", f"/credentials/{credential_id}")
        _raise_for_status(response)

    async def attach_credential_to_workflow(
        self,
        workflow_id: str,
        node_name: str,
        credential_type: str,
        credential_id: str,
        credential_name: str,
        *,
        generic_auth_type: str | None = None,
    ) -> dict[str, Any]:
        def mutate(workflow: dict[str, Any]) -> tuple[dict[str, Any], bool]:
            nodes = workflow.get("nodes") if isinstance(workflow.get("nodes"), list) else []
            for node in nodes:
                if node.get("name") != node_name:
                    continue
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
                    return workflow, False
                if generic_auth_type:
                    params = node.setdefault("parameters", {})
                    params["authentication"] = "genericCredentialType"
                    params["genericAuthType"] = generic_auth_type
                credentials = node.setdefault("credentials", {})
                credentials[credential_type] = {"id": credential_id, "name": credential_name}
                return workflow, True
            raise N8nApiError(
                404,
                f"Node '{node_name}' was not found",
                method="PUT",
                path=f"/workflows/{workflow_id}",
            )

        def verify(committed: dict[str, Any]) -> bool:
            nodes = committed.get("nodes")
            if not isinstance(nodes, list):
                return False
            for node in nodes:
                if node.get("name") != node_name:
                    continue
                credentials = node.get("credentials")
                if not isinstance(credentials, dict):
                    return False
                attached = credentials.get(credential_type)
                credential_matches = (
                    isinstance(attached, dict)
                    and str(attached.get("id") or "") == credential_id
                    and str(attached.get("name") or "") == credential_name
                )
                if not credential_matches:
                    return False
                if not generic_auth_type:
                    return True
                parameters = node.get("parameters")
                return (
                    isinstance(parameters, dict)
                    and parameters.get("authentication") == "genericCredentialType"
                    and parameters.get("genericAuthType") == generic_auth_type
                )
            return False

        return await self._mutate_workflow(workflow_id, mutate, verify=verify)

    async def get_execution(self, execution_id: str) -> "N8nExecution":
        response = await self.request("GET", f"/executions/{execution_id}")
        _raise_for_status(response)
        return _execution_from_payload(response.json())

    async def list_executions_page(
        self,
        workflow_id: str | None = None,
        *,
        status: str | None = None,
        cursor: str | None = None,
        limit: int = 10,
    ) -> "N8nExecutionPage":
        params: dict[str, Any] = {"limit": limit}
        if workflow_id:
            params["workflowId"] = workflow_id
        if status:
            params["status"] = status
        if cursor:
            params["cursor"] = cursor
        response = await self.request("GET", "/executions", params=params)
        _raise_for_status(response)
        payload = response.json()
        items = payload.get("data", [])
        return N8nExecutionPage(
            executions=[_execution_from_payload(item) for item in items if isinstance(item, dict)],
            next_cursor=(str(payload["nextCursor"]) if payload.get("nextCursor") else None),
        )

    async def list_executions(
        self, workflow_id: str | None = None, limit: int = 10
    ) -> list["N8nExecution"]:
        page = await self.list_executions_page(workflow_id=workflow_id, limit=limit)
        return page.executions

    async def get_execution_detail(self, execution_id: str) -> dict[str, Any]:
        response = await self.request(
            "GET",
            f"/executions/{execution_id}",
            params={"includeData": "true"},
        )
        _raise_for_status(response)
        return response.json()

    async def execute_workflow(self, workflow_id: str) -> dict[str, Any]:
        workflow = await self.get_workflow(workflow_id)
        nodes = workflow.get("nodes", [])
        await self.activate_workflow(workflow_id)
        for node in nodes:
            node_type = node.get("type", "")
            if node_type == "n8n-nodes-base.webhook":
                path = node.get("parameters", {}).get("path", "")
                if path:
                    webhook_base = self.resolved_webhook_base_url
                    return {
                        "workflow_id": workflow_id,
                        "status": "activated",
                        "trigger": "webhook",
                        "webhook_url": f"{webhook_base}/webhook/{path}",
                        "note": (
                            "Workflow activated. Call POST "
                            f"{webhook_base}/webhook/{path} to trigger it."
                        ),
                    }
        trigger_types = [n.get("type", "") for n in nodes if "trigger" in n.get("type", "").lower()]
        trigger = trigger_types[0] if trigger_types else "unknown"
        return {
            "workflow_id": workflow_id,
            "status": "activated",
            "trigger": trigger,
            "note": "Workflow activated and will run automatically on its trigger.",
        }


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
        headers={"X-N8N-API-KEY": shared_dev_n8n_api_key()},
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


def _workflow_lock(workflow_id: str) -> asyncio.Lock:
    lock = _workflow_locks.get(workflow_id)
    if lock is None:
        lock = asyncio.Lock()
        _workflow_locks[workflow_id] = lock
    return lock


def _workflow_payload(workflow: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": str(workflow.get("name") or "Workflow"),
        "nodes": deepcopy(workflow.get("nodes") or []),
        "connections": deepcopy(workflow.get("connections") or {}),
        "settings": _workflow_settings(workflow.get("settings")),
    }


def _find_retained_node(
    proposed_node: dict[str, Any],
    current_by_name: dict[str, dict[str, Any]],
    current_by_id: dict[str, dict[str, Any]],
) -> dict[str, Any] | None:
    node_name = proposed_node.get("name")
    node_type = proposed_node.get("type")
    if isinstance(node_name, str):
        current = current_by_name.get(node_name)
        if current and current.get("type") == node_type:
            return current

    node_id = proposed_node.get("id")
    if isinstance(node_id, str):
        current = current_by_id.get(node_id)
        if current and current.get("type") == node_type:
            return current
    return None


def _merge_retained_node_state(
    current_nodes: list[dict[str, Any]],
    proposed_nodes: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    current_by_name = {
        node["name"]: node
        for node in current_nodes
        if isinstance(node, dict) and isinstance(node.get("name"), str)
    }
    current_by_id = {
        node["id"]: node
        for node in current_nodes
        if isinstance(node, dict) and isinstance(node.get("id"), str)
    }
    merged_nodes: list[dict[str, Any]] = []
    for raw_node in proposed_nodes:
        node = deepcopy(raw_node)
        node.pop("credentials", None)
        current = _find_retained_node(node, current_by_name, current_by_id)
        if not current:
            merged_nodes.append(node)
            continue

        current_id = current.get("id")
        if isinstance(current_id, str) and current_id:
            node["id"] = current_id

        if "credentials" in current:
            node["credentials"] = deepcopy(current["credentials"])

        merged_nodes.append(node)
    return merged_nodes


WorkflowMutator = Callable[[dict[str, Any]], tuple[dict[str, Any], bool]]
WorkflowVerifier = Callable[[dict[str, Any]], bool]


async def _mutate_workflow(
    workflow_id: str,
    mutate: WorkflowMutator,
    *,
    verify: WorkflowVerifier | None = None,
) -> dict[str, Any]:
    async with _workflow_lock(workflow_id):
        current = await get_workflow(workflow_id)
        mutated, changed = mutate(deepcopy(current))
        if not changed:
            return current
        committed = await _put_workflow_preserving_activation(
            workflow_id,
            _workflow_payload(mutated),
            was_active=bool(current.get("active", False)),
        )
        if verify and not verify(committed):
            raise N8nApiError(
                409,
                "Workflow mutation could not be verified against the committed result",
                method="PUT",
                path=f"/workflows/{workflow_id}",
            )
        return committed


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
    connections: dict | None,
    settings: dict[str, Any] | None = None,
) -> N8nWorkflow:  # noqa: E501
    def mutate(current: dict[str, Any]) -> tuple[dict[str, Any], bool]:
        current_nodes = current.get("nodes") if isinstance(current.get("nodes"), list) else []
        current_connections = (
            current.get("connections") if isinstance(current.get("connections"), dict) else {}
        )
        current_settings = (
            current.get("settings") if isinstance(current.get("settings"), dict) else {}
        )
        current_name = str(current.get("name") or "Workflow")
        merged_nodes = _merge_retained_node_state(current_nodes, nodes)
        next_connections = (
            deepcopy(connections) if connections is not None else deepcopy(current_connections)
        )
        next_settings = _workflow_settings(settings if settings is not None else current_settings)
        changed = (
            current_name != name
            or current_nodes != merged_nodes
            or current_connections != next_connections
            or current_settings != next_settings
        )
        return (
            {
                **current,
                "name": name,
                "nodes": merged_nodes,
                "connections": next_connections,
                "settings": next_settings,
            },
            changed,
        )

    w = await _mutate_workflow(workflow_id, mutate)
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

    def mutate(workflow: dict[str, Any]) -> tuple[dict[str, Any], bool]:
        nodes = workflow.get("nodes") if isinstance(workflow.get("nodes"), list) else []
        for node in nodes:
            if node.get("name") != node_name:
                continue
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
                return workflow, False
            if generic_auth_type:
                params = node.setdefault("parameters", {})
                params["authentication"] = "genericCredentialType"
                params["genericAuthType"] = generic_auth_type
            credentials = node.setdefault("credentials", {})
            credentials[credential_type] = {"id": credential_id, "name": credential_name}
            return workflow, True
        raise N8nApiError(
            404,
            f"Node '{node_name}' was not found",
            method="PUT",
            path=f"/workflows/{workflow_id}",
        )

    def verify(committed: dict[str, Any]) -> bool:
        nodes = committed.get("nodes")
        if not isinstance(nodes, list):
            return False
        for node in nodes:
            if node.get("name") != node_name:
                continue
            credentials = node.get("credentials")
            if not isinstance(credentials, dict):
                return False
            attached = credentials.get(credential_type)
            credential_matches = (
                isinstance(attached, dict)
                and str(attached.get("id") or "") == credential_id
                and str(attached.get("name") or "") == credential_name
            )
            if not credential_matches:
                return False
            if not generic_auth_type:
                return True
            parameters = node.get("parameters")
            return (
                isinstance(parameters, dict)
                and parameters.get("authentication") == "genericCredentialType"
                and parameters.get("genericAuthType") == generic_auth_type
            )
        return False

    return await _mutate_workflow(workflow_id, mutate, verify=verify)


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


def extract_n8n_version(payload: dict[str, Any]) -> str:
    # n8n's REST response middleware wraps controller payloads in ``data``.
    # Keep accepting the unwrapped shape for older/custom deployments and
    # tests, but prefer the canonical CLI version in either shape.
    candidates = [payload]
    wrapped = payload.get("data")
    if isinstance(wrapped, dict):
        candidates.append(wrapped)

    for candidate in candidates:
        for key in ("versionCli", "version", "n8nVersion"):
            value = candidate.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return ""


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


async def fetch_public_asset(path: str) -> httpx.Response:
    async with httpx.AsyncClient(timeout=10.0, follow_redirects=False) as client:
        return await client.get(f"{settings.n8n_url.rstrip('/')}/{path.lstrip('/')}")


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
