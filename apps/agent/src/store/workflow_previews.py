"""Short-lived, one-use approvals for side-effect workflow runs."""

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

import src.store as _pkg_store


@dataclass(frozen=True)
class WorkflowRunPreview:
    token: str
    workflow_id: str
    workflow_fingerprint: str
    input_hash: str
    expires_at: str
    payload: dict[str, Any]


def workflow_input_hash(payload: dict[str, Any] | None) -> str:
    encoded = json.dumps(payload or {}, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


async def save_workflow_run_preview(
    user_id: str,
    workflow_id: str,
    *,
    workflow_fingerprint: str,
    input_payload: dict[str, Any] | None,
    payload: dict[str, Any],
    ttl_seconds: int = 600,
) -> WorkflowRunPreview:
    token = uuid4().hex
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(seconds=max(60, ttl_seconds))
    input_hash = workflow_input_hash(input_payload)
    data = {
        "workflow_id": workflow_id,
        "workflow_fingerprint": workflow_fingerprint,
        "input_hash": input_hash,
        "created_at": now.isoformat(),
        "expires_at": expires_at.isoformat(),
        "payload": dict(payload),
    }
    ref = _pkg_store._user_ref(user_id).collection("workflow_run_previews").document(token)
    await _pkg_store._run(lambda: ref.set(data))
    return WorkflowRunPreview(
        token=token,
        workflow_id=workflow_id,
        workflow_fingerprint=workflow_fingerprint,
        input_hash=input_hash,
        expires_at=data["expires_at"],
        payload=dict(payload),
    )


async def consume_workflow_run_preview(
    user_id: str,
    token: str,
    *,
    workflow_id: str,
    workflow_fingerprint: str,
    input_payload: dict[str, Any] | None,
) -> WorkflowRunPreview | None:
    ref = _pkg_store._user_ref(user_id).collection("workflow_run_previews").document(token)
    expected_input_hash = workflow_input_hash(input_payload)
    now = datetime.now(timezone.utc)

    def _consume():
        # Firestore transactions make the approval one-use even when two run
        # requests race. Import lazily so unit tests can patch the store without
        # initializing the Google client.
        from google.cloud import firestore

        transaction = _pkg_store.db.transaction()

        @firestore.transactional
        def _read_delete(txn):
            snapshot = ref.get(transaction=txn)
            if not snapshot.exists:
                return None
            data = snapshot.to_dict() or {}
            try:
                expires_at = datetime.fromisoformat(str(data.get("expires_at") or ""))
            except ValueError:
                return None
            if expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=timezone.utc)
            if expires_at <= now:
                txn.delete(ref)
                return None
            if (
                data.get("workflow_id") != workflow_id
                or data.get("workflow_fingerprint") != workflow_fingerprint
                or data.get("input_hash") != expected_input_hash
            ):
                return None
            txn.delete(ref)
            return data

        return _read_delete(transaction)

    data = await _pkg_store._run(_consume)
    if not isinstance(data, dict):
        return None
    try:
        expires_at = datetime.fromisoformat(str(data.get("expires_at") or ""))
    except ValueError:
        return None
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if (
        data.get("workflow_id") != workflow_id
        or data.get("workflow_fingerprint") != workflow_fingerprint
        or data.get("input_hash") != expected_input_hash
    ):
        return None
    return WorkflowRunPreview(
        token=token,
        workflow_id=workflow_id,
        workflow_fingerprint=workflow_fingerprint,
        input_hash=expected_input_hash,
        expires_at=expires_at.isoformat(),
        payload=dict(data.get("payload") or {}),
    )
