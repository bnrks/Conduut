import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src import usage
from src.routes import usage as usage_route


@pytest.mark.parametrize("days", [1, 7, 30, 90])
def test_usage_route_parses_authenticated_user_and_days(monkeypatch, days):
    monkeypatch.setattr(usage_route, "get_user_id", lambda _request: "user_1")
    calls = []

    async def fake_summary(user_id: str, *, days: int):
        calls.append((user_id, days))
        return usage.UsageSummary(
            days=days,
            starts_at="2026-07-08T12:00:00+00:00",
            ends_at="2026-07-15T12:00:00+00:00",
            totals=usage.UsageTotals(total_tokens=42),
        )

    monkeypatch.setattr(usage_route.usage, "get_usage_summary", fake_summary)

    app = FastAPI()
    app.include_router(usage_route.router, prefix="/api")
    response = TestClient(app).get(f"/api/usage?days={days}")

    assert calls == [("user_1", days)]
    assert response.status_code == 200
    assert response.json()["totals"]["total_tokens"] == 42
    assert response.json()["scope"] == "completed_agent_runs"


def test_usage_route_rejects_unsupported_days(monkeypatch):
    monkeypatch.setattr(usage_route, "get_user_id", lambda _request: "user_1")

    app = FastAPI()
    app.include_router(usage_route.router, prefix="/api")
    response = TestClient(app).get("/api/usage?days=14")

    assert response.status_code == 422
    assert response.json() == {"detail": "days must be one of 1, 7, 30, or 90"}
