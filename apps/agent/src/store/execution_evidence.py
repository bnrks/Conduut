"""Append-only sanitized execution evidence envelopes."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from google.api_core.exceptions import AlreadyExists

import src.store as _pkg_store
from src.agent.schemas import ExecutionEvidenceEnvelope


def _execution_evidence_ref(user_id: str, evidence_id: str):
    return _pkg_store._user_ref(user_id).collection("execution_evidence").document(evidence_id)


def _evidence_hash(model: ExecutionEvidenceEnvelope) -> str:
    payload = model.model_dump(exclude={"createdAt", "evidenceHash"}, exclude_none=True)
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _document_id(model: ExecutionEvidenceEnvelope, evidence_hash: str) -> str:
    execution_id = re.sub(r"[^A-Za-z0-9_-]+", "_", model.executionId or "unknown")
    return f"{execution_id}--{evidence_hash}"


async def _existing_envelope(ref) -> ExecutionEvidenceEnvelope | None:
    snapshot = await _pkg_store._run(ref.get)
    if not getattr(snapshot, "exists", False):
        return None
    payload = snapshot.to_dict()
    if not isinstance(payload, dict):
        return None
    return ExecutionEvidenceEnvelope.model_validate(payload)


async def save_execution_evidence(
    user_id: str,
    envelope: ExecutionEvidenceEnvelope | dict[str, Any],
) -> ExecutionEvidenceEnvelope:
    model = (
        envelope
        if isinstance(envelope, ExecutionEvidenceEnvelope)
        else ExecutionEvidenceEnvelope.model_validate(envelope)
    )
    evidence_hash = model.evidenceHash or _evidence_hash(model)
    evidence_id = _document_id(model, evidence_hash)
    ref = _execution_evidence_ref(user_id, evidence_id)
    existing = await _existing_envelope(ref)
    if existing is not None:
        return existing

    created_at = model.createdAt or _pkg_store._now_iso()
    stored = model.model_copy(
        update={
            "createdAt": created_at,
            "evidenceHash": evidence_hash,
        }
    )
    try:
        await _pkg_store._run(lambda: ref.create(stored.model_dump(exclude_none=True)))
    except AlreadyExists:
        existing = await _existing_envelope(ref)
        if existing is not None:
            return existing
        raise
    return stored
