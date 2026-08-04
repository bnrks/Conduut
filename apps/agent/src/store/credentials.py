"""Custom (HTTP) credential library — per-user, host-matched."""

from dataclasses import dataclass, field
from uuid import uuid4

import src.store as _pkg_store


@dataclass
class CustomCredential:
    """Reusable custom (HTTP) credential the user manages through Conduut.

    The secret lives only in n8n; this record is the non-secret pointer +
    host hint used for agent host-matching and dashboard listing.
    """

    id: str
    label: str
    credential_type: str
    host: str
    n8n_credential_id: str
    n8n_credential_name: str
    created_at: str
    updated_at: str
    instance_id: str = ""
    # Draft support: an agent-prepared credential whose secret the user fills
    # later. status="draft" -> no n8n credential yet; "ready" -> finalized.
    status: str = "ready"
    auth_config: dict = field(default_factory=dict)
    secret_fields: list[str] = field(default_factory=list)
    source_url: str = ""
    confidence: str = ""
    # "host" -> matched to HTTP Request nodes by URL host (generic HTTP auth);
    # "type" -> matched to any node by n8n credential type (e.g. openAiApi).
    match_kind: str = "host"
    pending_workflow_id: str = ""
    pending_node_name: str = ""


def _custom_credentials_ref(user_id: str):
    return _pkg_store._user_ref(user_id).collection("credentials")


def _custom_credential_from_data(credential_id: str, data: dict) -> CustomCredential:
    return CustomCredential(
        id=credential_id,
        label=data.get("label", ""),
        credential_type=data.get("credential_type", ""),
        host=data.get("host", ""),
        n8n_credential_id=data.get("n8n_credential_id", ""),
        n8n_credential_name=data.get("n8n_credential_name", ""),
        created_at=data.get("created_at", ""),
        updated_at=data.get("updated_at", ""),
        instance_id=str(data.get("instance_id") or ""),
        status=data.get("status", "ready"),
        auth_config=dict(data.get("auth_config") or {}),
        secret_fields=list(data.get("secret_fields") or []),
        source_url=data.get("source_url", ""),
        confidence=data.get("confidence", ""),
        match_kind=data.get("match_kind", "host"),
        pending_workflow_id=data.get("pending_workflow_id", ""),
        pending_node_name=data.get("pending_node_name", ""),
    )


def _custom_credential_from_doc(doc) -> CustomCredential:
    return _custom_credential_from_data(doc.id, doc.to_dict() or {})


async def save_custom_credential(
    user_id: str,
    *,
    label: str,
    credential_type: str,
    host: str,
    n8n_credential_id: str,
    n8n_credential_name: str,
    match_kind: str = "host",
    instance_id: str = "",
) -> CustomCredential:
    credential_id = str(uuid4())
    now = _pkg_store._now_iso()
    data = {
        "label": label,
        "credential_type": credential_type,
        "host": host,
        "n8n_credential_id": n8n_credential_id,
        "n8n_credential_name": n8n_credential_name,
        "instance_id": instance_id,
        "status": "ready",
        "match_kind": match_kind,
        "created_at": now,
        "updated_at": now,
    }
    await _pkg_store._run(
        lambda: _custom_credentials_ref(user_id).document(credential_id).set(data)
    )
    return _custom_credential_from_data(credential_id, data)


async def save_draft_credential(
    user_id: str,
    *,
    label: str,
    credential_type: str,
    host: str,
    auth_config: dict,
    secret_fields: list[str],
    source_url: str,
    confidence: str,
    pending_workflow_id: str = "",
    pending_node_name: str = "",
    instance_id: str = "",
) -> CustomCredential:
    credential_id = str(uuid4())
    now = _pkg_store._now_iso()
    data = {
        "label": label,
        "credential_type": credential_type,
        "host": host,
        "n8n_credential_id": "",
        "n8n_credential_name": "",
        "instance_id": instance_id,
        "status": "draft",
        "auth_config": dict(auth_config),
        "secret_fields": list(secret_fields),
        "source_url": source_url,
        "confidence": confidence,
        "pending_workflow_id": pending_workflow_id,
        "pending_node_name": pending_node_name,
        "created_at": now,
        "updated_at": now,
    }
    await _pkg_store._run(
        lambda: _custom_credentials_ref(user_id).document(credential_id).set(data)
    )
    return _custom_credential_from_data(credential_id, data)


async def finalize_draft_credential(
    user_id: str,
    credential_id: str,
    *,
    n8n_credential_id: str,
    n8n_credential_name: str,
    instance_id: str | None = None,
) -> CustomCredential | None:
    ref = _custom_credentials_ref(user_id).document(credential_id)
    doc = await _pkg_store._run(lambda: ref.get())
    if not doc.exists:
        return None
    data = doc.to_dict() or {}
    if data.get("status") != "draft":
        return None
    stored_instance_id = str(data.get("instance_id") or "")
    if (
        instance_id is not None
        and stored_instance_id != instance_id
        and not (instance_id == "shared_dev" and not stored_instance_id)
    ):
        return None
    if instance_id is not None:
        data["instance_id"] = instance_id
    data["status"] = "ready"
    data["n8n_credential_id"] = n8n_credential_id
    data["n8n_credential_name"] = n8n_credential_name
    data["updated_at"] = _pkg_store._now_iso()
    await _pkg_store._run(lambda: ref.set(data))
    return _custom_credential_from_data(credential_id, data)


async def list_custom_credentials(
    user_id: str,
    *,
    instance_id: str | None = None,
) -> list[CustomCredential]:
    docs = await _pkg_store._run(lambda: list(_custom_credentials_ref(user_id).stream()))
    credentials = [_custom_credential_from_doc(doc) for doc in docs]
    if instance_id is not None:
        credentials = [
            item
            for item in credentials
            if item.instance_id == instance_id
            or (instance_id == "shared_dev" and not item.instance_id)
        ]
    return credentials


async def get_custom_credential(
    user_id: str,
    credential_id: str,
    *,
    instance_id: str | None = None,
) -> CustomCredential | None:
    doc = await _pkg_store._run(
        lambda: _custom_credentials_ref(user_id).document(credential_id).get()
    )
    if not doc.exists:
        return None
    credential = _custom_credential_from_doc(doc)
    if (
        instance_id is not None
        and credential.instance_id != instance_id
        and not (instance_id == "shared_dev" and not credential.instance_id)
    ):
        return None
    return credential


async def delete_custom_credential(
    user_id: str,
    credential_id: str,
    *,
    instance_id: str | None = None,
) -> None:
    if instance_id is not None:
        existing = await get_custom_credential(user_id, credential_id, instance_id=instance_id)
        if existing is None:
            return
    await _pkg_store._run(lambda: _custom_credentials_ref(user_id).document(credential_id).delete())
