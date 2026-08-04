from __future__ import annotations

from dataclasses import asdict, dataclass, field
from uuid import uuid4

import src.store as _pkg_store


@dataclass
class N8nInstanceRecord:
    id: str
    display_name: str
    ownership: str
    provider: str
    base_url: str
    webhook_base_url: str
    api_key_secret_ref: str
    n8n_version: str
    compatibility_status: str
    connection_status: str
    capabilities: list[str] = field(default_factory=list)
    verified_at: str = ""
    last_health_at: str = ""
    last_error_code: str | None = None
    created_at: str = ""
    updated_at: str = ""
    is_active: bool = True


def _n8n_instances_collection(user_id: str):
    return _pkg_store._user_ref(user_id).collection("n8n_instances")


async def _set_active_instance_id(user_id: str, instance_id: str | None) -> None:
    await _pkg_store._run(
        lambda: _pkg_store._user_ref(user_id).set(
            {"active_n8n_instance_id": instance_id},
            merge=True,
        )
    )


def _record_from_data(doc_id: str, data: dict) -> N8nInstanceRecord:
    return N8nInstanceRecord(
        id=doc_id,
        display_name=str(data.get("display_name") or ""),
        ownership=str(data.get("ownership") or ""),
        provider=str(data.get("provider") or "manual"),
        base_url=str(data.get("base_url") or ""),
        webhook_base_url=str(data.get("webhook_base_url") or ""),
        api_key_secret_ref=str(data.get("api_key_secret_ref") or ""),
        n8n_version=str(data.get("n8n_version") or ""),
        compatibility_status=str(data.get("compatibility_status") or "unknown"),
        connection_status=str(data.get("connection_status") or "pending"),
        capabilities=[str(item) for item in data.get("capabilities") or []],
        verified_at=str(data.get("verified_at") or ""),
        last_health_at=str(data.get("last_health_at") or ""),
        last_error_code=(
            str(data["last_error_code"]) if data.get("last_error_code") is not None else None
        ),
        created_at=str(data.get("created_at") or ""),
        updated_at=str(data.get("updated_at") or ""),
        is_active=bool(data.get("is_active", False)),
    )


async def save_n8n_instance(
    user_id: str,
    *,
    instance_id: str | None = None,
    display_name: str,
    ownership: str,
    provider: str,
    base_url: str,
    webhook_base_url: str,
    api_key_secret_ref: str,
    n8n_version: str,
    compatibility_status: str,
    connection_status: str,
    capabilities: list[str] | None = None,
    verified_at: str = "",
    last_health_at: str = "",
    last_error_code: str | None = None,
    is_active: bool = True,
) -> N8nInstanceRecord:
    doc_id = instance_id or uuid4().hex
    existing = await get_n8n_instance(user_id, doc_id)
    now = _pkg_store._now_iso()
    payload = {
        "display_name": display_name,
        "ownership": ownership,
        "provider": provider,
        "base_url": base_url,
        "webhook_base_url": webhook_base_url,
        "api_key_secret_ref": api_key_secret_ref,
        "n8n_version": n8n_version,
        "compatibility_status": compatibility_status,
        "connection_status": connection_status,
        "capabilities": list(capabilities or []),
        "verified_at": verified_at,
        "last_health_at": last_health_at,
        "last_error_code": last_error_code,
        "created_at": existing.created_at if existing else now,
        "updated_at": now,
        "is_active": is_active,
    }
    if is_active:
        await deactivate_other_n8n_instances(user_id, except_instance_id=doc_id)
    await _pkg_store._run(lambda: _n8n_instances_collection(user_id).document(doc_id).set(payload))
    if is_active:
        await _set_active_instance_id(user_id, doc_id)
    else:
        active = await get_active_n8n_instance(user_id)
        if active is None:
            await _set_active_instance_id(user_id, None)
    return _record_from_data(doc_id, payload)


async def get_n8n_instance(user_id: str, instance_id: str) -> N8nInstanceRecord | None:
    doc = await _pkg_store._run(
        lambda: _n8n_instances_collection(user_id).document(instance_id).get()
    )
    if not doc.exists:
        return None
    return _record_from_data(doc.id, doc.to_dict() or {})


async def list_n8n_instances(user_id: str) -> list[N8nInstanceRecord]:
    docs = await _pkg_store._run(lambda: list(_n8n_instances_collection(user_id).stream()))
    records = [_record_from_data(doc.id, doc.to_dict() or {}) for doc in docs]
    return sorted(records, key=lambda item: item.created_at)


async def get_active_n8n_instance(user_id: str) -> N8nInstanceRecord | None:
    user_doc = await _pkg_store._run(lambda: _pkg_store._user_ref(user_id).get())
    if getattr(user_doc, "exists", False):
        data = user_doc.to_dict() or {}
        active_id = str(data.get("active_n8n_instance_id") or "")
        if active_id:
            active = await get_n8n_instance(user_id, active_id)
            if active is not None and active.is_active:
                return active
    for record in reversed(await list_n8n_instances(user_id)):
        if record.is_active:
            return record
    return None


async def get_latest_n8n_instance(user_id: str) -> N8nInstanceRecord | None:
    records = await list_n8n_instances(user_id)
    if not records:
        return None
    return records[-1]


async def deactivate_other_n8n_instances(user_id: str, *, except_instance_id: str) -> None:
    records = await list_n8n_instances(user_id)
    for record in records:
        if record.id == except_instance_id or not record.is_active:
            continue
        payload = asdict(record)
        payload.pop("id", None)
        payload["is_active"] = False
        payload["updated_at"] = _pkg_store._now_iso()
        await _pkg_store._run(
            lambda payload=payload, record_id=record.id: (
                _n8n_instances_collection(user_id).document(record_id).set(payload)
            )
        )


async def delete_n8n_instance(user_id: str, instance_id: str) -> None:
    await _pkg_store._run(lambda: _n8n_instances_collection(user_id).document(instance_id).delete())
    active = await get_active_n8n_instance(user_id)
    await _set_active_instance_id(user_id, active.id if active else None)
