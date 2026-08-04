from __future__ import annotations

import json
import re
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from typing import Any, Protocol

from src import store
from src.config import settings, shared_dev_n8n_api_key
from src.n8n_client import N8nApiError, N8nClient
from src.n8n_provider import N8nClientFactory
from src.n8n_target import N8nTarget
from src.secret_store import SecretStore, get_secret_store
from src.store.n8n_migrations import (
    N8nMigrationExecutionSummary,
    N8nMigrationItem,
    N8nMigrationRecord,
)

_MAX_ARCHIVED_EXECUTIONS = 10_000
_ARCHIVE_WINDOW_DAYS = 30
_EXECUTION_PAGE_SIZE = 100
_EXECUTION_PAGES_PER_ADVANCE = 2


class MigrationError(RuntimeError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        status_code: int,
        retryable: bool = False,
        action: str = "retry",
    ):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.retryable = retryable
        self.action = action


class MigrationConfirmationRequiredError(MigrationError):
    def __init__(self):
        super().__init__(
            "n8n_migration_confirmation_required",
            "Legacy migration requires explicit confirmation.",
            status_code=409,
            action="confirm_start",
        )


class MigrationConnectionRequiredError(MigrationError):
    def __init__(self):
        super().__init__(
            "n8n_connection_required",
            "Connect a customer-owned n8n instance before starting migration.",
            status_code=404,
            action="connect_n8n",
        )


class MigrationSourceUnavailableError(MigrationError):
    def __init__(self):
        super().__init__(
            "n8n_migration_source_unavailable",
            "Shared legacy n8n source is not configured for migration.",
            status_code=503,
            retryable=True,
            action="retry_later",
        )


class MigrationReadbackError(MigrationError):
    def __init__(self, workflow_id: str):
        super().__init__(
            "n8n_migration_readback_failed",
            f"Migrated workflow '{workflow_id}' failed read-back verification.",
            status_code=502,
            retryable=True,
            action="retry_advance",
        )


class MigrationStoreProtocol(Protocol):
    async def get_n8n_migration(
        self,
        user_id: str,
        migration_id: str,
    ) -> N8nMigrationRecord | None: ...

    async def save_n8n_migration(self, record: N8nMigrationRecord) -> N8nMigrationRecord: ...

    async def upsert_n8n_migration_execution_summaries(
        self,
        user_id: str,
        migration_id: str,
        summaries: list[N8nMigrationExecutionSummary],
    ) -> None: ...


class LegacyStoreProtocol(Protocol):
    async def get_active_n8n_instance(self, user_id: str) -> store.N8nInstanceRecord | None: ...

    async def get_all_workflow_metadata(
        self,
        user_id: str,
    ) -> dict[str, store.WorkflowMetadata]: ...

    async def list_custom_credentials(self, user_id: str) -> list[store.CustomCredential]: ...

    async def list_connections(self, user_id: str) -> list[store.AppConnection]: ...

    async def save_workflow_metadata(
        self,
        user_id: str,
        workflow_id: str,
        *,
        input_schema: list[dict],
        resources: dict | None = None,
        instance_id: str | None = None,
    ) -> store.WorkflowMetadata: ...


class N8nWorkflowTransport(Protocol):
    async def list_workflows(self) -> list[dict[str, Any]]: ...

    async def get_workflow(self, workflow_id: str) -> dict[str, Any]: ...

    async def create_workflow(self, payload: dict[str, Any]) -> dict[str, Any]: ...

    async def list_executions_page(
        self,
        workflow_id: str,
        *,
        cursor: str | None,
        limit: int,
    ) -> dict[str, Any]: ...

    async def get_execution_detail(self, execution_id: str) -> dict[str, Any]: ...


class N8nWorkflowTransportAdapter:
    def __init__(self, client: N8nClient):
        self._client = client

    async def list_workflows(self) -> list[dict[str, Any]]:
        response = await self._client.request("GET", "/workflows")
        _raise_for_status(response)
        payload = response.json()
        return list(payload.get("data") or [])

    async def get_workflow(self, workflow_id: str) -> dict[str, Any]:
        response = await self._client.request("GET", f"/workflows/{workflow_id}")
        _raise_for_status(response)
        payload = response.json()
        if not isinstance(payload, dict):
            raise N8nApiError(502, "n8n workflow payload was not an object", method="GET", path="")
        return payload

    async def create_workflow(self, payload: dict[str, Any]) -> dict[str, Any]:
        response = await self._client.request("POST", "/workflows", json=payload)
        _raise_for_status(response)
        created = response.json()
        if not isinstance(created, dict):
            raise N8nApiError(502, "n8n workflow payload was not an object", method="POST", path="")
        return created

    async def list_executions_page(
        self,
        workflow_id: str,
        *,
        cursor: str | None,
        limit: int,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"workflowId": workflow_id, "limit": limit}
        if cursor:
            params["cursor"] = cursor
        response = await self._client.request("GET", "/executions", params=params)
        _raise_for_status(response)
        payload = response.json()
        if not isinstance(payload, dict):
            raise N8nApiError(
                502,
                "n8n executions payload was not an object",
                method="GET",
                path="",
            )
        return payload

    async def get_execution_detail(self, execution_id: str) -> dict[str, Any]:
        response = await self._client.request(
            "GET",
            f"/executions/{execution_id}",
            params={"includeData": "true"},
        )
        _raise_for_status(response)
        payload = response.json()
        if not isinstance(payload, dict):
            raise N8nApiError(502, "n8n execution payload was not an object", method="GET", path="")
        return payload


def _raise_for_status(response: Any) -> None:
    if getattr(response, "status_code", 200) < 400:
        return
    message = ""
    try:
        payload = response.json()
    except Exception:
        payload = None
    if isinstance(payload, dict):
        detail = payload.get("message") or payload.get("detail") or payload.get("error")
        if isinstance(detail, str):
            message = detail
    if not message:
        message = str(getattr(response, "text", "") or f"n8n API returned {response.status_code}")
    request = getattr(response, "request", None)
    method = getattr(request, "method", "GET")
    url = getattr(request, "url", "")
    raise N8nApiError(response.status_code, message, method=method, path=str(url))


def migration_id_for_target(target_instance_id: str) -> str:
    return f"shared_to_{target_instance_id}"


def migration_error_detail(exc: MigrationError) -> dict[str, str | bool]:
    return {
        "code": exc.code,
        "message": exc.message,
        "retryable": exc.retryable,
        "action": exc.action,
    }


def _workflow_item_id(workflow_id: str) -> str:
    return f"workflow:{workflow_id}"


def _execution_archive_item_id(workflow_id: str) -> str:
    return f"execution_archive:{workflow_id}"


def _credential_item_id(credential_id: str) -> str:
    return f"credential:{credential_id}"


def _connection_item_id(connection_id: str) -> str:
    return f"connection:{connection_id}"


def _workflow_payload_for_migration(source_workflow: dict[str, Any]) -> dict[str, Any]:
    nodes: list[dict[str, Any]] = []
    for raw_node in list(source_workflow.get("nodes") or []):
        if not isinstance(raw_node, dict):
            continue
        node = json.loads(json.dumps(raw_node))
        node.pop("credentials", None)
        nodes.append(node)
    return {
        "name": str(source_workflow.get("name") or "Workflow"),
        "nodes": nodes,
        "connections": json.loads(json.dumps(source_workflow.get("connections") or {})),
        "settings": json.loads(json.dumps(source_workflow.get("settings") or {})),
    }


def _workflow_fingerprint(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return sha256(encoded.encode("utf-8")).hexdigest()


def _workflow_baseline_payload(
    *,
    instance_id: str,
    fingerprint: str,
    workflow_updated_at: str,
) -> dict[str, str]:
    return {
        "instance_id": instance_id,
        "workflow_fingerprint": fingerprint,
        "workflow_updated_at": workflow_updated_at,
    }


def _parse_iso(value: str) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    normalized = text.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(normalized)
    except ValueError:
        return None


def _duration_ms(started_at: str, finished_at: str) -> int | None:
    started = _parse_iso(started_at)
    finished = _parse_iso(finished_at)
    if started is None or finished is None:
        return None
    return max(0, int((finished - started).total_seconds() * 1000))


def _truncate(value: str, *, limit: int = 300) -> str:
    text = str(value or "").strip()
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."


def _redact_secret_text(value: str) -> str:
    text = str(value or "")
    replacements = [
        (r"(?i)(authorization\s*[:=]\s*bearer\s+)[^\s,;]+", r"\1[redacted]"),
        (r"(?i)(bearer\s+)[^\s,;]+", r"\1[redacted]"),
        (r"(?i)(api[_ -]?key\s*[:=]\s*)[^\s,;]+", r"\1[redacted]"),
        (r"(?i)(token\s*[:=]\s*)[^\s,;]+", r"\1[redacted]"),
    ]
    for pattern, replacement in replacements:
        text = re.sub(pattern, replacement, text)
    return text


def _execution_error_message(payload: dict[str, Any]) -> str:
    result_data = payload.get("data", {}).get("resultData", {})
    if isinstance(result_data, dict):
        error = result_data.get("error")
        if isinstance(error, dict):
            for key in ("message", "description"):
                if isinstance(error.get(key), str) and error.get(key):
                    return _truncate(_redact_secret_text(error[key]))
        if (
            isinstance(result_data.get("lastNodeExecuted"), str)
            and payload.get("status") == "error"
        ):
            return _truncate(f"Failed at {result_data['lastNodeExecuted']}")
    if isinstance(payload.get("error"), str):
        return _truncate(_redact_secret_text(str(payload["error"])))
    return ""


class N8nMigrationService:
    def __init__(
        self,
        *,
        legacy_store: LegacyStoreProtocol = store,
        migration_store: MigrationStoreProtocol = store,
        secret_store: SecretStore | None = None,
        client_factory: N8nClientFactory | None = None,
        source_transport: N8nWorkflowTransport | None = None,
    ):
        self._legacy_store = legacy_store
        self._migration_store = migration_store
        self._secret_store = secret_store or get_secret_store()
        self._client_factory = client_factory or N8nClientFactory(secret_store=self._secret_store)
        self._source_transport = source_transport

    async def preview(
        self,
        user_id: str,
    ) -> tuple[store.N8nInstanceRecord | None, list[N8nMigrationItem]]:
        target = await self._legacy_store.get_active_n8n_instance(user_id)
        if target is None:
            return None, []
        return target, await self._build_inventory_items(user_id, target)

    async def get_manifest(self, user_id: str) -> N8nMigrationRecord | None:
        target = await self._legacy_store.get_active_n8n_instance(user_id)
        if target is None:
            return None
        return await self._migration_store.get_n8n_migration(
            user_id,
            migration_id_for_target(target.id),
        )

    async def start(self, user_id: str, *, confirm: bool) -> N8nMigrationRecord:
        target = await self._require_target_instance(user_id)
        migration_id = migration_id_for_target(target.id)
        existing = await self._migration_store.get_n8n_migration(user_id, migration_id)
        if existing is not None:
            return existing
        if not confirm:
            raise MigrationConfirmationRequiredError()

        items = await self._build_inventory_items(user_id, target)
        now = store._now_iso()
        record = N8nMigrationRecord(
            id=migration_id,
            user_id=user_id,
            source_instance_id="shared_dev",
            target_instance_id=target.id,
            status="pending",
            created_at=now,
            updated_at=now,
            confirmed_at=now,
            items=items,
        )
        return await self._migration_store.save_n8n_migration(record)

    async def advance(self, user_id: str, *, batch_size: int = 10) -> N8nMigrationRecord:
        target = await self._require_target_instance(user_id)
        migration_id = migration_id_for_target(target.id)
        manifest = await self._migration_store.get_n8n_migration(user_id, migration_id)
        if manifest is None:
            raise MigrationConfirmationRequiredError()

        target_transport = await self._target_transport(target)
        source_transport = self._source_transport or self._build_source_transport()
        processed = 0
        items = list(manifest.items)
        for index, item in enumerate(items):
            if processed >= max(1, batch_size):
                break
            updated = await self._advance_item(
                manifest=manifest,
                item=item,
                source_transport=source_transport,
                target_transport=target_transport,
            )
            if updated is item:
                continue
            items[index] = updated
            manifest = replace(manifest, items=items)
            processed += 1

        if processed > 0:
            status = (
                "completed"
                if all(item.status != "legacy_shared" for item in manifest.items)
                else "in_progress"
            )
            manifest = replace(manifest, status=status)
        return await self._migration_store.save_n8n_migration(manifest)

    async def _build_inventory_items(
        self,
        user_id: str,
        target: store.N8nInstanceRecord,
    ) -> list[N8nMigrationItem]:
        metadata_by_id = await self._legacy_store.get_all_workflow_metadata(user_id)
        credentials = await self._legacy_store.list_custom_credentials(user_id)
        connections = await self._legacy_store.list_connections(user_id)

        items: list[N8nMigrationItem] = []
        for workflow_id in sorted(metadata_by_id):
            metadata = metadata_by_id[workflow_id]
            instance_id = str(metadata.resources.get("instance_id") or "")
            status = (
                "customer_owned" if instance_id and instance_id == target.id else "legacy_shared"
            )
            items.append(
                N8nMigrationItem(
                    item_id=_workflow_item_id(workflow_id),
                    kind="workflow",
                    legacy_id=workflow_id,
                    display_name=workflow_id,
                    status=status,
                    metadata={"source_instance_id": instance_id or "shared_dev"},
                )
            )
            if status != "customer_owned":
                items.append(
                    N8nMigrationItem(
                        item_id=_execution_archive_item_id(workflow_id),
                        kind="execution_archive",
                        legacy_id=workflow_id,
                        display_name=f"{workflow_id} executions",
                        status="legacy_shared",
                    )
                )

        for credential in sorted(credentials, key=lambda item: item.id):
            if credential.instance_id and credential.instance_id == target.id:
                status = "customer_owned"
            else:
                status = "legacy_shared" if credential.n8n_credential_id else "migration_required"
            items.append(
                N8nMigrationItem(
                    item_id=_credential_item_id(credential.id),
                    kind="credential",
                    legacy_id=credential.id,
                    display_name=credential.label or credential.id,
                    status=status,
                    reconnect_required=(status == "migration_required"),
                    metadata={
                        "credential_type": credential.credential_type,
                        "pending_workflow_id": credential.pending_workflow_id,
                        "pending_node_name": credential.pending_node_name,
                        "draft_status": credential.status,
                        "source_instance_id": credential.instance_id or "shared_dev",
                    },
                )
            )

        for connection in sorted(connections, key=lambda item: item.id):
            if connection.instance_id and connection.instance_id == target.id:
                status = "customer_owned"
            else:
                status = "legacy_shared" if connection.n8n_credential_id else "migration_required"
            items.append(
                N8nMigrationItem(
                    item_id=_connection_item_id(connection.id),
                    kind="connection",
                    legacy_id=connection.id,
                    display_name=connection.service or connection.id,
                    status=status,
                    reconnect_required=status == "migration_required",
                    metadata={
                        "provider": connection.provider,
                        "service": connection.service,
                        "credential_type": connection.credential_type,
                        "source_instance_id": connection.instance_id or "shared_dev",
                    },
                )
            )
        return items

    async def _advance_item(
        self,
        *,
        manifest: N8nMigrationRecord,
        item: N8nMigrationItem,
        source_transport: N8nWorkflowTransport,
        target_transport: N8nWorkflowTransport,
    ) -> N8nMigrationItem:
        if item.kind == "workflow" and item.status == "legacy_shared":
            return await self._migrate_workflow(manifest, item, source_transport, target_transport)
        if item.kind == "execution_archive" and item.status == "legacy_shared":
            return await self._archive_execution_summaries(manifest, item, source_transport)
        if item.kind == "credential" and item.status == "legacy_shared":
            return self._mark_credential_reconnect_required(manifest, item)
        if item.kind == "connection" and item.status == "legacy_shared":
            return self._mark_connection_reconnect_required(item)
        return item

    async def _migrate_workflow(
        self,
        manifest: N8nMigrationRecord,
        item: N8nMigrationItem,
        source_transport: N8nWorkflowTransport,
        target_transport: N8nWorkflowTransport,
    ) -> N8nMigrationItem:
        source_workflow = await source_transport.get_workflow(item.legacy_id)
        payload = _workflow_payload_for_migration(source_workflow)
        fingerprint = _workflow_fingerprint(payload)

        target_id = item.target_id or manifest.workflow_id_map.get(item.legacy_id, "")
        readback: dict[str, Any] | None = None
        if target_id:
            try:
                readback = await target_transport.get_workflow(target_id)
            except N8nApiError:
                target_id = ""
                readback = None
        if readback is None:
            target_id = await self._find_existing_target_workflow_id(
                target_transport,
                payload,
                fingerprint,
            )
            if target_id:
                readback = await target_transport.get_workflow(target_id)
        if readback is None:
            created = await target_transport.create_workflow(payload)
            target_id = str(created.get("id") or "")
            readback = await target_transport.get_workflow(target_id)

        migrated = _workflow_payload_for_migration(readback)
        if readback.get("active") or _workflow_fingerprint(migrated) != fingerprint:
            raise MigrationReadbackError(item.legacy_id)

        await self._save_migrated_workflow_metadata(
            manifest=manifest,
            legacy_workflow_id=item.legacy_id,
            target_workflow_id=target_id,
            fingerprint=fingerprint,
            target_updated_at=str(readback.get("updatedAt") or ""),
        )
        manifest.workflow_id_map[item.legacy_id] = target_id
        return replace(
            item,
            status="customer_owned",
            target_id=target_id,
            note=(
                "Migrated to the customer-owned instance with all node "
                "credential references stripped."
            ),
            metadata={**item.metadata, "fingerprint": fingerprint},
        )

    async def _save_migrated_workflow_metadata(
        self,
        *,
        manifest: N8nMigrationRecord,
        legacy_workflow_id: str,
        target_workflow_id: str,
        fingerprint: str,
        target_updated_at: str,
    ) -> None:
        metadata_by_id = await self._legacy_store.get_all_workflow_metadata(manifest.user_id)
        legacy_metadata = metadata_by_id.get(legacy_workflow_id)
        if legacy_metadata is None:
            return

        resources = dict(legacy_metadata.resources)
        resources["instance_id"] = manifest.target_instance_id
        resources["workflow_baseline"] = _workflow_baseline_payload(
            instance_id=manifest.target_instance_id,
            fingerprint=fingerprint,
            workflow_updated_at=target_updated_at,
        )
        resources["migration_provenance"] = {
            "migration_id": manifest.id,
            "source_instance_id": manifest.source_instance_id,
            "target_instance_id": manifest.target_instance_id,
            "source_workflow_id": legacy_workflow_id,
            "migrated_at": store._now_iso(),
        }

        save_kwargs = {
            "input_schema": list(legacy_metadata.input_schema),
            "resources": resources,
            "instance_id": manifest.target_instance_id,
        }
        try:
            await self._legacy_store.save_workflow_metadata(
                manifest.user_id,
                target_workflow_id,
                **save_kwargs,
            )
        except TypeError:
            save_kwargs.pop("instance_id", None)
            await self._legacy_store.save_workflow_metadata(
                manifest.user_id,
                target_workflow_id,
                **save_kwargs,
            )

    async def _find_existing_target_workflow_id(
        self,
        target_transport: N8nWorkflowTransport,
        payload: dict[str, Any],
        fingerprint: str,
    ) -> str:
        name = str(payload.get("name") or "")
        candidates = []
        for workflow in await target_transport.list_workflows():
            if str(workflow.get("name") or "") != name:
                continue
            if _workflow_fingerprint(_workflow_payload_for_migration(workflow)) == fingerprint:
                candidates.append(str(workflow.get("id") or ""))
        if len(candidates) == 1:
            return candidates[0]
        return ""

    async def _archive_execution_summaries(
        self,
        manifest: N8nMigrationRecord,
        item: N8nMigrationItem,
        source_transport: N8nWorkflowTransport,
    ) -> N8nMigrationItem:
        if manifest.archived_execution_count >= _MAX_ARCHIVED_EXECUTIONS:
            return replace(
                item,
                status="archived",
                note="Archive limit reached; no additional legacy execution summaries were copied.",
            )

        cursor = item.cursor or None
        cutoff = datetime.now(tz=UTC) - timedelta(days=_ARCHIVE_WINDOW_DAYS)
        pages_processed = 0
        summaries: list[N8nMigrationExecutionSummary] = []
        done = False
        next_cursor = cursor or ""
        while pages_processed < _EXECUTION_PAGES_PER_ADVANCE and not done:
            page = await source_transport.list_executions_page(
                item.legacy_id,
                cursor=next_cursor or None,
                limit=_EXECUTION_PAGE_SIZE,
            )
            executions = list(page.get("data") or [])
            next_cursor = str(page.get("nextCursor") or "")
            if not executions:
                done = True
                break
            for execution in executions:
                if manifest.archived_execution_count + len(summaries) >= _MAX_ARCHIVED_EXECUTIONS:
                    done = True
                    break
                started_at = str(execution.get("startedAt") or "")
                started = _parse_iso(started_at)
                if started is not None and started < cutoff:
                    done = True
                    break
                execution_id = str(execution.get("id") or "")
                detail = await source_transport.get_execution_detail(execution_id)
                finished_at = str(detail.get("stoppedAt") or detail.get("finishedAt") or "")
                summaries.append(
                    N8nMigrationExecutionSummary(
                        summary_id=f"{item.legacy_id}:{execution_id}",
                        workflow_legacy_id=item.legacy_id,
                        execution_id=execution_id,
                        status=str(detail.get("status") or execution.get("status") or ""),
                        started_at=started_at,
                        finished_at=finished_at,
                        duration_ms=_duration_ms(started_at, finished_at),
                        mode=str(detail["mode"]) if detail.get("mode") is not None else None,
                        error_message=_execution_error_message(detail),
                    )
                )
            pages_processed += 1
            if not next_cursor:
                done = True

        if summaries:
            await self._migration_store.upsert_n8n_migration_execution_summaries(
                manifest.user_id,
                manifest.id,
                summaries,
            )
            manifest.archived_execution_count += len(summaries)

        if done:
            return replace(
                item,
                status="archived",
                cursor="",
                note="Stored sanitized legacy execution summaries for up to 30 days of history.",
            )
        return replace(item, cursor=next_cursor)

    def _mark_credential_reconnect_required(
        self,
        manifest: N8nMigrationRecord,
        item: N8nMigrationItem,
    ) -> N8nMigrationItem:
        pending_workflow_id = str(item.metadata.get("pending_workflow_id") or "")
        target_pending_workflow_id = manifest.workflow_id_map.get(pending_workflow_id, "")
        note = "Reconnect required; legacy credential ids and secrets were not copied."
        metadata = dict(item.metadata)
        if target_pending_workflow_id:
            metadata["pending_target_workflow_id"] = target_pending_workflow_id
            note = (
                "Reconnect required; legacy credential ids and secrets were not copied. "
                "Pending workflow metadata was remapped to the migrated workflow."
            )
        if metadata.get("draft_status") == "draft":
            note = (
                "Draft credential metadata was retained. Finalize it again on the "
                "customer-owned instance."
            )
        return replace(
            item,
            status="migration_required",
            reconnect_required=True,
            note=note,
            metadata=metadata,
        )

    def _mark_connection_reconnect_required(self, item: N8nMigrationItem) -> N8nMigrationItem:
        return replace(
            item,
            status="migration_required",
            reconnect_required=True,
            note=(
                "Reconnect required; OAuth and other connection secrets were not "
                "copied from shared n8n."
            ),
        )

    async def _require_target_instance(self, user_id: str) -> store.N8nInstanceRecord:
        target = await self._legacy_store.get_active_n8n_instance(user_id)
        if target is None or target.connection_status != "connected":
            raise MigrationConnectionRequiredError()
        return target

    def _build_source_transport(self) -> N8nWorkflowTransport:
        api_key = shared_dev_n8n_api_key()
        if not str(settings.n8n_url or "").strip() or not api_key:
            raise MigrationSourceUnavailableError()
        client = N8nClient(
            base_url=str(settings.n8n_url).rstrip("/"),
            api_key=api_key,
            webhook_base_url=str(settings.n8n_url).rstrip("/"),
            instance_id="shared_dev",
            ownership="shared_dev",
        )
        return N8nWorkflowTransportAdapter(client)

    async def _target_transport(self, target: store.N8nInstanceRecord) -> N8nWorkflowTransport:
        client = await self._client_factory.for_target(
            N8nTarget(
                tenant_id="migration",
                instance_id=target.id,
                ownership="customer_owned",
                base_url=target.base_url,
                webhook_base_url=target.webhook_base_url,
                api_key_secret_ref=target.api_key_secret_ref,
                n8n_version=target.n8n_version,
            )
        )
        return N8nWorkflowTransportAdapter(client)
