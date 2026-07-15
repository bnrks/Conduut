"""Immutable per-user agent usage events."""

import hashlib
from dataclasses import dataclass

from google.api_core.exceptions import Conflict
from google.cloud.firestore_v1 import FieldFilter

import src.store as _pkg_store


@dataclass(frozen=True)
class AgentUsageEvent:
    id: str
    run_id: str
    conversation_id: str
    provider: str
    model: str
    tier: str
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    cache_write_tokens: int
    model_requests: int
    tool_calls: int
    created_at: str
    event_type: str = "agent_run_completed"
    schema_version: int = 1

    @property
    def total_tokens(self) -> int:
        """Provider-neutral total; cache counters are details, not extra tokens."""

        return self.input_tokens + self.output_tokens


def _usage_event_document_id(run_id: str) -> str:
    digest = hashlib.sha256(f"agent_run:{run_id}".encode("utf-8")).hexdigest()[:32]
    return f"usage_{digest}"


def _usage_event_ref(user_id: str, event_id: str):
    return _pkg_store._user_ref(user_id).collection("usage_events").document(event_id)


def _non_negative_int(value: object) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _usage_event_from_doc(doc) -> AgentUsageEvent:
    data = doc.to_dict() or {}
    return AgentUsageEvent(
        id=doc.id,
        run_id=str(data.get("run_id") or ""),
        conversation_id=str(data.get("conversation_id") or ""),
        provider=str(data.get("provider") or "unknown"),
        model=str(data.get("model") or "unknown"),
        tier=str(data.get("tier") or "unknown"),
        input_tokens=_non_negative_int(data.get("input_tokens")),
        output_tokens=_non_negative_int(data.get("output_tokens")),
        cache_read_tokens=_non_negative_int(data.get("cache_read_tokens")),
        cache_write_tokens=_non_negative_int(data.get("cache_write_tokens")),
        model_requests=_non_negative_int(data.get("model_requests")),
        tool_calls=_non_negative_int(data.get("tool_calls")),
        created_at=str(data.get("created_at") or ""),
        event_type=str(data.get("event_type") or "agent_run_completed"),
        schema_version=_non_negative_int(data.get("schema_version")) or 1,
    )


async def save_agent_usage_event(
    user_id: str,
    *,
    run_id: str,
    conversation_id: str,
    provider: str,
    model: str,
    tier: str,
    input_tokens: int,
    output_tokens: int,
    cache_read_tokens: int = 0,
    cache_write_tokens: int = 0,
    model_requests: int = 0,
    tool_calls: int = 0,
) -> AgentUsageEvent:
    """Create one append-only event; repeated run ids are idempotent."""

    event_id = _usage_event_document_id(run_id)
    ref = _usage_event_ref(user_id, event_id)
    data = {
        "schema_version": 1,
        "event_type": "agent_run_completed",
        "run_id": run_id,
        "conversation_id": conversation_id,
        "provider": provider,
        "model": model,
        "tier": tier,
        "input_tokens": _non_negative_int(input_tokens),
        "output_tokens": _non_negative_int(output_tokens),
        "cache_read_tokens": _non_negative_int(cache_read_tokens),
        "cache_write_tokens": _non_negative_int(cache_write_tokens),
        "model_requests": _non_negative_int(model_requests),
        "tool_calls": _non_negative_int(tool_calls),
        "created_at": _pkg_store._now_iso(),
    }

    try:
        await _pkg_store._run(lambda: ref.create(data))
        return AgentUsageEvent(id=event_id, **data)
    except Conflict:
        existing = await _pkg_store._run(lambda: ref.get())
        return _usage_event_from_doc(existing)


async def list_agent_usage_events(
    user_id: str,
    *,
    start_at: str,
) -> list[AgentUsageEvent]:
    docs = await _pkg_store._run(
        lambda: list(
            _pkg_store._user_ref(user_id)
            .collection("usage_events")
            .where(filter=FieldFilter("created_at", ">=", start_at))
            .order_by("created_at", direction="ASCENDING")
            .stream()
        )
    )
    return [_usage_event_from_doc(doc) for doc in docs]
