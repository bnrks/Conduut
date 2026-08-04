from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

import src.store as _pkg_store

MigrationItemStatus = Literal[
    "legacy_shared",
    "migration_required",
    "customer_owned",
    "archived",
]
MigrationItemKind = Literal["workflow", "execution_archive", "credential", "connection"]


@dataclass
class N8nMigrationItem:
    item_id: str
    kind: MigrationItemKind
    legacy_id: str
    display_name: str
    status: MigrationItemStatus
    target_id: str = ""
    note: str = ""
    reconnect_required: bool = False
    cursor: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class N8nMigrationRecord:
    id: str
    user_id: str
    source_instance_id: str
    target_instance_id: str
    status: str
    created_at: str
    updated_at: str
    confirmed_at: str
    workflow_id_map: dict[str, str] = field(default_factory=dict)
    archived_execution_count: int = 0
    items: list[N8nMigrationItem] = field(default_factory=list)


@dataclass
class N8nMigrationExecutionSummary:
    summary_id: str
    workflow_legacy_id: str
    execution_id: str
    status: str
    started_at: str
    finished_at: str
    duration_ms: int | None = None
    mode: str | None = None
    error_message: str = ""


def _migrations_collection(user_id: str):
    return _pkg_store._user_ref(user_id).collection("n8n_migrations")


def _migration_ref(user_id: str, migration_id: str):
    return _migrations_collection(user_id).document(migration_id)


def _execution_archives_collection(user_id: str, migration_id: str):
    return _migration_ref(user_id, migration_id).collection("execution_archives")


def _item_from_data(data: dict[str, Any]) -> N8nMigrationItem:
    return N8nMigrationItem(
        item_id=str(data.get("item_id") or ""),
        kind=str(data.get("kind") or "workflow"),  # type: ignore[arg-type]
        legacy_id=str(data.get("legacy_id") or ""),
        display_name=str(data.get("display_name") or ""),
        status=str(data.get("status") or "legacy_shared"),  # type: ignore[arg-type]
        target_id=str(data.get("target_id") or ""),
        note=str(data.get("note") or ""),
        reconnect_required=bool(data.get("reconnect_required", False)),
        cursor=str(data.get("cursor") or ""),
        metadata=dict(data.get("metadata") or {}),
    )


def _item_to_data(item: N8nMigrationItem) -> dict[str, Any]:
    return {
        "item_id": item.item_id,
        "kind": item.kind,
        "legacy_id": item.legacy_id,
        "display_name": item.display_name,
        "status": item.status,
        "target_id": item.target_id,
        "note": item.note,
        "reconnect_required": item.reconnect_required,
        "cursor": item.cursor,
        "metadata": dict(item.metadata),
    }


def _record_from_data(migration_id: str, user_id: str, data: dict[str, Any]) -> N8nMigrationRecord:
    return N8nMigrationRecord(
        id=migration_id,
        user_id=user_id,
        source_instance_id=str(data.get("source_instance_id") or "shared_dev"),
        target_instance_id=str(data.get("target_instance_id") or ""),
        status=str(data.get("status") or "pending"),
        created_at=str(data.get("created_at") or ""),
        updated_at=str(data.get("updated_at") or ""),
        confirmed_at=str(data.get("confirmed_at") or ""),
        workflow_id_map={
            str(key): str(value)
            for key, value in dict(data.get("workflow_id_map") or {}).items()
            if value is not None
        },
        archived_execution_count=int(data.get("archived_execution_count") or 0),
        items=[_item_from_data(item) for item in list(data.get("items") or [])],
    )


def _record_to_data(record: N8nMigrationRecord) -> dict[str, Any]:
    return {
        "source_instance_id": record.source_instance_id,
        "target_instance_id": record.target_instance_id,
        "status": record.status,
        "created_at": record.created_at,
        "updated_at": record.updated_at,
        "confirmed_at": record.confirmed_at,
        "workflow_id_map": dict(record.workflow_id_map),
        "archived_execution_count": record.archived_execution_count,
        "items": [_item_to_data(item) for item in record.items],
    }


def _summary_to_data(summary: N8nMigrationExecutionSummary) -> dict[str, Any]:
    return {
        "workflow_legacy_id": summary.workflow_legacy_id,
        "execution_id": summary.execution_id,
        "status": summary.status,
        "started_at": summary.started_at,
        "finished_at": summary.finished_at,
        "duration_ms": summary.duration_ms,
        "mode": summary.mode,
        "error_message": summary.error_message,
    }


def _summary_from_data(summary_id: str, data: dict[str, Any]) -> N8nMigrationExecutionSummary:
    duration_raw = data.get("duration_ms")
    duration_ms = int(duration_raw) if isinstance(duration_raw, int | float) else None
    return N8nMigrationExecutionSummary(
        summary_id=summary_id,
        workflow_legacy_id=str(data.get("workflow_legacy_id") or ""),
        execution_id=str(data.get("execution_id") or ""),
        status=str(data.get("status") or ""),
        started_at=str(data.get("started_at") or ""),
        finished_at=str(data.get("finished_at") or ""),
        duration_ms=duration_ms,
        mode=str(data["mode"]) if data.get("mode") is not None else None,
        error_message=str(data.get("error_message") or ""),
    )


async def get_n8n_migration(user_id: str, migration_id: str) -> N8nMigrationRecord | None:
    doc = await _pkg_store._run(lambda: _migration_ref(user_id, migration_id).get())
    if not doc.exists:
        return None
    return _record_from_data(doc.id, user_id, doc.to_dict() or {})


async def save_n8n_migration(record: N8nMigrationRecord) -> N8nMigrationRecord:
    existing = await get_n8n_migration(record.user_id, record.id)
    now = _pkg_store._now_iso()
    payload = _record_to_data(
        N8nMigrationRecord(
            id=record.id,
            user_id=record.user_id,
            source_instance_id=record.source_instance_id,
            target_instance_id=record.target_instance_id,
            status=record.status,
            created_at=existing.created_at if existing else (record.created_at or now),
            updated_at=now,
            confirmed_at=record.confirmed_at,
            workflow_id_map=dict(record.workflow_id_map),
            archived_execution_count=record.archived_execution_count,
            items=list(record.items),
        )
    )
    await _pkg_store._run(lambda: _migration_ref(record.user_id, record.id).set(payload))
    return _record_from_data(record.id, record.user_id, payload)


async def upsert_n8n_migration_execution_summaries(
    user_id: str,
    migration_id: str,
    summaries: list[N8nMigrationExecutionSummary],
) -> None:
    for summary in summaries:
        payload = _summary_to_data(summary)
        await _pkg_store._run(
            lambda payload=payload, summary_id=summary.summary_id: (
                _execution_archives_collection(user_id, migration_id)
                .document(summary_id)
                .set(payload)
            )
        )


async def list_n8n_migration_execution_summaries(
    user_id: str,
    migration_id: str,
) -> list[N8nMigrationExecutionSummary]:
    docs = await _pkg_store._run(
        lambda: list(_execution_archives_collection(user_id, migration_id).stream())
    )
    return [_summary_from_data(doc.id, doc.to_dict() or {}) for doc in docs]
