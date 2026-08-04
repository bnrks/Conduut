from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from src.auth import get_user_id
from src.n8n_migration import N8nMigrationService, migration_error_detail
from src.store.n8n_migrations import N8nMigrationItem, N8nMigrationRecord

router = APIRouter()
service = N8nMigrationService()


class N8nMigrationStartIn(BaseModel):
    confirm: bool = False


class N8nMigrationAdvanceIn(BaseModel):
    batch_size: int = Field(default=10, ge=1, le=100)


def _http_error(exc: Exception) -> HTTPException:
    status_code = getattr(exc, "status_code", 500)
    detail = (
        migration_error_detail(exc)  # type: ignore[arg-type]
        if hasattr(exc, "code") and hasattr(exc, "message")
        else {
            "code": "internal_error",
            "message": str(exc),
            "retryable": False,
            "action": "retry",
        }
    )
    return HTTPException(status_code=status_code, detail=detail)


def _serialize_item(item: N8nMigrationItem) -> dict:
    return {
        "itemId": item.item_id,
        "kind": item.kind,
        "legacyId": item.legacy_id,
        "displayName": item.display_name,
        "status": item.status,
        "targetId": item.target_id or None,
        "note": item.note or None,
        "reconnectRequired": item.reconnect_required,
        "cursor": item.cursor or None,
        "metadata": item.metadata,
    }


def _summary_items(items: list[N8nMigrationItem], *, limit: int = 25) -> list[dict]:
    ranked = sorted(
        items,
        key=lambda item: (
            item.status == "customer_owned",
            item.status == "archived",
            item.kind,
            item.legacy_id,
        ),
    )
    return [_serialize_item(item) for item in ranked[:limit]]


def _serialize_status(
    *,
    manifest: N8nMigrationRecord | None,
    preview_items: list[N8nMigrationItem],
    target_connected: bool,
    updated_at: str,
) -> dict:
    items = manifest.items if manifest is not None else preview_items
    status_counts: dict[str, int] = {}
    for item in items:
        status_counts[item.status] = status_counts.get(item.status, 0) + 1

    workflow_items = [item for item in items if item.kind == "workflow"]
    migrated_workflows = sum(1 for item in workflow_items if item.status == "customer_owned")
    remaining_workflows = sum(1 for item in workflow_items if item.status == "legacy_shared")
    reconnect_required_count = sum(1 for item in items if item.reconnect_required)

    can_start = target_connected and manifest is None
    can_advance = manifest is not None and any(item.status == "legacy_shared" for item in items)
    next_action = "noop"
    if not target_connected:
        next_action = "connect_n8n"
    elif can_start:
        next_action = "confirm_start"
    elif can_advance:
        next_action = "advance"
    elif reconnect_required_count > 0:
        next_action = "reconnect_credentials"

    return {
        "id": manifest.id if manifest is not None else None,
        "sourceInstanceId": manifest.source_instance_id if manifest is not None else "shared_dev",
        "targetInstanceId": manifest.target_instance_id if manifest is not None else None,
        "status": manifest.status if manifest is not None else "idle",
        "createdAt": manifest.created_at if manifest is not None else None,
        "updatedAt": updated_at or None,
        "confirmedAt": manifest.confirmed_at if manifest is not None else None,
        "workflowIdMap": dict(manifest.workflow_id_map) if manifest is not None else {},
        "archivedRunCount": manifest.archived_execution_count if manifest is not None else 0,
        "statusCounts": status_counts,
        "totalWorkflows": len(workflow_items),
        "migratedWorkflows": migrated_workflows,
        "remainingWorkflows": remaining_workflows,
        "reconnectRequiredCount": reconnect_required_count,
        "canStart": can_start,
        "canAdvance": can_advance,
        "nextAction": next_action,
        "items": _summary_items(items),
    }


@router.get("/n8n/migration")
async def get_n8n_migration(request: Request):
    user_id = get_user_id(request)
    try:
        manifest = await service.get_manifest(user_id)
        if manifest is None:
            target, preview_items = await service.preview(user_id)
            return _serialize_status(
                manifest=None,
                preview_items=preview_items,
                target_connected=target is not None and target.connection_status == "connected",
                updated_at=target.updated_at if target is not None else "",
            )
    except Exception as exc:  # pragma: no cover - defensive
        raise _http_error(exc) from exc
    return _serialize_status(
        manifest=manifest,
        preview_items=[],
        target_connected=True,
        updated_at=manifest.updated_at,
    )


@router.post("/n8n/migration/start")
async def start_n8n_migration(request: Request, body: N8nMigrationStartIn):
    user_id = get_user_id(request)
    try:
        manifest = await service.start(user_id, confirm=body.confirm)
    except Exception as exc:
        raise _http_error(exc) from exc
    return _serialize_status(
        manifest=manifest,
        preview_items=[],
        target_connected=True,
        updated_at=manifest.updated_at,
    )


@router.post("/n8n/migration/advance")
async def advance_n8n_migration(request: Request, body: N8nMigrationAdvanceIn):
    user_id = get_user_id(request)
    try:
        manifest = await service.advance(user_id, batch_size=body.batch_size)
    except Exception as exc:
        raise _http_error(exc) from exc
    return _serialize_status(
        manifest=manifest,
        preview_items=[],
        target_connected=True,
        updated_at=manifest.updated_at,
    )
