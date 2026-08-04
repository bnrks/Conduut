"""Artifacts collection — Sheets/Gmail result previews."""

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any

import src.store as _pkg_store


@dataclass
class ArtifactRecord:
    id: str
    service: str
    type: str
    title: str
    created_at: str
    origin: dict[str, Any] = field(default_factory=dict)
    description: str | None = None
    url: str | None = None
    source: dict[str, Any] = field(default_factory=dict)
    table: dict[str, Any] | None = None
    message: dict[str, Any] | None = None


def _artifact_ref(user_id: str, artifact_id: str):
    return _pkg_store._user_ref(user_id).collection("artifacts").document(artifact_id)


def _normalize_artifact_origin(origin: dict[str, Any]) -> dict[str, Any]:
    normalized: dict[str, Any] = {"kind": str(origin.get("kind") or "chat")}
    for source_key, target_key in (
        ("conversation_id", "conversationId"),
        ("conversationId", "conversationId"),
        ("workflow_id", "workflowId"),
        ("workflowId", "workflowId"),
        ("execution_id", "executionId"),
        ("executionId", "executionId"),
        ("instance_id", "instanceId"),
        ("instanceId", "instanceId"),
    ):
        value = origin.get(source_key)
        if value:
            normalized[target_key] = str(value)
    return normalized


def _artifact_preview_type(artifact: dict[str, Any]) -> str:
    service = str(artifact.get("service") or "")
    if service == "gmail":
        return "message_preview"
    return "table_preview"


def _artifact_document_id(artifact: dict[str, Any], origin: dict[str, Any]) -> str:
    source = artifact.get("source") if isinstance(artifact.get("source"), dict) else {}
    identity = [
        artifact.get("service"),
        artifact.get("title"),
        artifact.get("url"),
        source.get("spreadsheetId"),
        source.get("range"),
        source.get("messageId"),
        source.get("threadId"),
        source.get("query"),
        source.get("action"),
        origin.get("kind"),
        origin.get("conversationId"),
        origin.get("workflowId"),
        origin.get("executionId"),
        origin.get("instanceId"),
    ]
    encoded = json.dumps(identity, sort_keys=True, separators=(",", ":"), default=str)
    return "art_" + hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:32]


def _artifact_from_doc(doc) -> ArtifactRecord:
    data = doc.to_dict() or {}
    source = data.get("source") if isinstance(data.get("source"), dict) else {}
    origin = data.get("origin") if isinstance(data.get("origin"), dict) else {}
    table = data.get("table") if isinstance(data.get("table"), dict) else None
    message = data.get("message") if isinstance(data.get("message"), dict) else None
    return ArtifactRecord(
        id=doc.id,
        service=str(data.get("service") or ""),
        type=str(data.get("type") or "table_preview"),
        title=str(data.get("title") or "Artifact"),
        description=data.get("description"),
        url=data.get("url"),
        source=source,
        table=table,
        message=message,
        origin=origin,
        created_at=str(data.get("created_at") or ""),
    )


async def save_artifact(
    user_id: str,
    artifact: dict[str, Any],
    *,
    origin: dict[str, Any],
) -> ArtifactRecord:
    origin_data = _normalize_artifact_origin(origin)
    artifact_id = _artifact_document_id(artifact, origin_data)
    source = artifact.get("source") if isinstance(artifact.get("source"), dict) else {}
    table = artifact.get("table") if isinstance(artifact.get("table"), dict) else None
    message = artifact.get("message") if isinstance(artifact.get("message"), dict) else None
    now = _pkg_store._now_iso()
    data: dict[str, Any] = {
        "service": str(artifact.get("service") or ""),
        "type": _artifact_preview_type(artifact),
        "title": str(artifact.get("title") or "Artifact"),
        "source": source,
        "origin": origin_data,
        "created_at": now,
    }
    if artifact.get("description"):
        data["description"] = str(artifact["description"])
    if artifact.get("url"):
        data["url"] = str(artifact["url"])
    if table is not None:
        data["table"] = table
    if message is not None:
        data["message"] = message

    await _pkg_store._run(lambda: _artifact_ref(user_id, artifact_id).set(data))
    return ArtifactRecord(id=artifact_id, **data)


async def list_artifacts(
    user_id: str,
    *,
    limit: int = 50,
    service: str | None = None,
) -> list[ArtifactRecord]:
    normalized_limit = max(1, min(limit, 100))
    fetch_limit = normalized_limit if service is None else min(max(normalized_limit * 4, 50), 200)
    docs = await _pkg_store._run(
        lambda: list(
            _pkg_store._user_ref(user_id)
            .collection("artifacts")
            .order_by("created_at", direction="DESCENDING")
            .limit(fetch_limit)
            .stream()
        )
    )
    artifacts = [_artifact_from_doc(doc) for doc in docs]
    if service:
        artifacts = [artifact for artifact in artifacts if artifact.service == service]
    return artifacts[:normalized_limit]


async def delete_artifact(user_id: str, artifact_id: str) -> bool:
    ref = _artifact_ref(user_id, artifact_id)
    doc = await _pkg_store._run(lambda: ref.get())
    if not doc.exists:
        return False
    await _pkg_store._run(lambda: ref.delete())
    return True
