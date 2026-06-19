"""Tests for the tier router/classifier."""

import asyncio

from src.agent import router
from src.agent.model_registry import Tier
from src.agent.router import TierDecision
from src.config import settings


class _FakeResult:
    def __init__(self, output):
        self.output = output


class _FakeAgent:
    def __init__(self, *, output=None, raise_exc=None):
        self.output = output
        self.raise_exc = raise_exc
        self.run_kwargs = None

    async def run(self, prompt, **kwargs):
        self.run_kwargs = kwargs
        if self.raise_exc is not None:
            raise self.raise_exc
        return _FakeResult(self.output)


def test_classify_maps_decision_to_tier(monkeypatch):
    fake = _FakeAgent(output=TierDecision(tier="hard", reason="complex branching"))
    monkeypatch.setattr(router, "_build_router_agent", lambda: fake)
    assert asyncio.run(router.classify_tier("build something complex")) == Tier.HARD


def test_classify_falls_back_to_medium_on_error(monkeypatch):
    fake = _FakeAgent(raise_exc=RuntimeError("router down"))
    monkeypatch.setattr(router, "_build_router_agent", lambda: fake)
    assert asyncio.run(router.classify_tier("anything")) == Tier.MEDIUM


def test_classify_uses_thinking_off_and_single_request(monkeypatch):
    monkeypatch.setattr(settings, "model_profile", "default")
    fake = _FakeAgent(output=TierDecision(tier="simple", reason="greeting"))
    monkeypatch.setattr(router, "_build_router_agent", lambda: fake)

    asyncio.run(router.classify_tier("hi there"))

    # default router = openai gpt-5-mini, reasoning minimal (thinking OFF).
    assert fake.run_kwargs["model_settings"] == {"openai_reasoning_effort": "minimal"}
    assert fake.run_kwargs["usage_limits"].request_limit == 1
