"""Agent token-usage aggregation for the authenticated dashboard."""

from collections import defaultdict
from datetime import datetime, timedelta, timezone

from pydantic import BaseModel, Field

from src import store


class UsageTotals(BaseModel):
    agent_runs: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    model_requests: int = 0
    tool_calls: int = 0


class DailyUsage(BaseModel):
    date: str
    agent_runs: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0


class ModelUsage(UsageTotals):
    provider: str
    model: str
    tier: str


class UsageSummary(BaseModel):
    days: int
    starts_at: str
    ends_at: str
    totals: UsageTotals
    daily: list[DailyUsage] = Field(default_factory=list)
    by_model: list[ModelUsage] = Field(default_factory=list)
    scope: str = "completed_agent_runs"


def _utc_datetime(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _add_event(target: dict[str, int], event: store.AgentUsageEvent) -> None:
    target["agent_runs"] += 1
    target["input_tokens"] += event.input_tokens
    target["output_tokens"] += event.output_tokens
    target["total_tokens"] += event.total_tokens
    target["cache_read_tokens"] += event.cache_read_tokens
    target["cache_write_tokens"] += event.cache_write_tokens
    target["model_requests"] += event.model_requests
    target["tool_calls"] += event.tool_calls


def _empty_counters() -> dict[str, int]:
    return {
        "agent_runs": 0,
        "input_tokens": 0,
        "output_tokens": 0,
        "total_tokens": 0,
        "cache_read_tokens": 0,
        "cache_write_tokens": 0,
        "model_requests": 0,
        "tool_calls": 0,
    }


async def get_usage_summary(
    user_id: str,
    *,
    days: int,
    now: datetime | None = None,
) -> UsageSummary:
    end = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    start = end - timedelta(days=days)
    events = await store.list_agent_usage_events(user_id, start_at=start.isoformat())

    totals = _empty_counters()
    by_day: dict[str, dict[str, int]] = defaultdict(_empty_counters)
    by_model: dict[tuple[str, str, str], dict[str, int]] = defaultdict(_empty_counters)

    for event in events:
        if event.event_type != "agent_run_completed":
            continue
        created_at = _utc_datetime(event.created_at)
        if created_at is None or created_at < start or created_at > end:
            continue
        _add_event(totals, event)
        _add_event(by_day[created_at.date().isoformat()], event)
        _add_event(by_model[(event.provider, event.model, event.tier)], event)

    daily: list[DailyUsage] = []
    cursor = start.date()
    while cursor <= end.date():
        date = cursor.isoformat()
        daily.append(DailyUsage(date=date, **by_day[date]))
        cursor += timedelta(days=1)

    models = [
        ModelUsage(provider=provider, model=model, tier=tier, **counters)
        for (provider, model, tier), counters in by_model.items()
    ]
    models.sort(key=lambda item: (-item.total_tokens, item.provider, item.model, item.tier))

    return UsageSummary(
        days=days,
        starts_at=start.isoformat(),
        ends_at=end.isoformat(),
        totals=UsageTotals(**totals),
        daily=daily,
        by_model=models,
    )
