from datetime import datetime, timezone

import pytest

from src import store, usage


def _event(
    event_id: str,
    *,
    created_at: str,
    provider: str = "deepseek",
    model: str = "deepseek-v4-pro",
    tier: str = "medium",
    input_tokens: int = 100,
    output_tokens: int = 20,
) -> store.AgentUsageEvent:
    return store.AgentUsageEvent(
        id=event_id,
        run_id=event_id,
        conversation_id="conv_1",
        provider=provider,
        model=model,
        tier=tier,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cache_read_tokens=50,
        cache_write_tokens=5,
        model_requests=2,
        tool_calls=3,
        created_at=created_at,
    )


@pytest.mark.asyncio
async def test_usage_summary_aggregates_totals_days_and_models(monkeypatch):
    async def fake_list(_user_id: str, *, start_at: str):
        assert start_at == "2026-07-08T12:00:00+00:00"
        return [
            _event("run_1", created_at="2026-07-14T10:00:00+00:00"),
            _event(
                "run_2",
                created_at="2026-07-15T11:00:00+00:00",
                provider="openai",
                model="gpt-5-mini",
                tier="simple",
                input_tokens=40,
                output_tokens=10,
            ),
        ]

    monkeypatch.setattr(usage.store, "list_agent_usage_events", fake_list)

    summary = await usage.get_usage_summary(
        "user_1",
        days=7,
        now=datetime(2026, 7, 15, 12, tzinfo=timezone.utc),
    )

    assert summary.totals.model_dump() == {
        "agent_runs": 2,
        "input_tokens": 140,
        "output_tokens": 30,
        "total_tokens": 170,
        "cache_read_tokens": 100,
        "cache_write_tokens": 10,
        "model_requests": 4,
        "tool_calls": 6,
    }
    assert [(item.date, item.total_tokens) for item in summary.daily[-2:]] == [
        ("2026-07-14", 120),
        ("2026-07-15", 50),
    ]
    assert len(summary.daily) == 8  # rolling 7x24h spans two partial UTC boundary days
    assert [item.model for item in summary.by_model] == ["deepseek-v4-pro", "gpt-5-mini"]


@pytest.mark.asyncio
async def test_usage_summary_skips_malformed_and_out_of_range_events(monkeypatch):
    async def fake_list(_user_id: str, *, start_at: str):
        return [
            _event("bad", created_at="not-a-date"),
            _event("old", created_at="2026-07-01T00:00:00+00:00"),
        ]

    monkeypatch.setattr(usage.store, "list_agent_usage_events", fake_list)

    summary = await usage.get_usage_summary(
        "user_1",
        days=1,
        now=datetime(2026, 7, 15, 12, tzinfo=timezone.utc),
    )

    assert summary.totals.total_tokens == 0
    assert summary.by_model == []


@pytest.mark.asyncio
async def test_usage_summary_ignores_other_future_event_types(monkeypatch):
    async def fake_list(_user_id: str, *, start_at: str):
        event = _event("router_1", created_at="2026-07-15T11:00:00+00:00")
        return [store.AgentUsageEvent(**{**event.__dict__, "event_type": "router_run_completed"})]

    monkeypatch.setattr(usage.store, "list_agent_usage_events", fake_list)

    summary = await usage.get_usage_summary(
        "user_1",
        days=1,
        now=datetime(2026, 7, 15, 12, tzinfo=timezone.utc),
    )

    assert summary.totals.agent_runs == 0
    assert summary.totals.total_tokens == 0
