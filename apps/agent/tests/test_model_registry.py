"""Tests for the Conduut-managed model registry + profiles."""

from src.agent.model_registry import (
    PROFILES,
    Tier,
    active_profile,
    resolve,
    router_choice,
)
from src.agent.provider_factory import SUPPORTED_PROVIDERS
from src.config import settings


def test_default_profile_tier_primaries(monkeypatch):
    monkeypatch.setattr(settings, "model_profile", "default")
    assert resolve(Tier.SIMPLE).provider == "anthropic"
    assert resolve(Tier.SIMPLE).model == "claude-haiku-4-5-20251001"
    assert resolve(Tier.MEDIUM).model == "claude-sonnet-4-6"
    assert resolve(Tier.HARD).provider == "google"
    assert resolve(Tier.HARD).model == "gemini-3.1-pro-preview"
    assert router_choice().model == "gpt-5-mini"


def test_default_medium_uses_adaptive_thinking(monkeypatch):
    monkeypatch.setattr(settings, "model_profile", "default")
    spec = resolve(Tier.MEDIUM).thinking
    assert spec.enabled is True
    assert spec.effort == "medium"


def test_default_secondaries_are_gpt(monkeypatch):
    monkeypatch.setattr(settings, "model_profile", "default")
    for tier in Tier:
        assert resolve(tier, secondary=True).provider == "openai"


def test_gpt_profile_all_primaries_openai(monkeypatch):
    monkeypatch.setattr(settings, "model_profile", "gpt")
    for tier in Tier:
        assert resolve(tier).provider == "openai"
    assert router_choice().provider == "openai"


def test_unknown_profile_falls_back_to_default(monkeypatch):
    monkeypatch.setattr(settings, "model_profile", "nope")
    assert active_profile().name == "default"


def test_every_choice_uses_supported_provider():
    for profile in PROFILES.values():
        choices = [profile.router]
        for tier_config in profile.tiers.values():
            choices += [tier_config.primary, tier_config.secondary]
        for choice in choices:
            assert choice.provider in SUPPORTED_PROVIDERS


def test_every_tier_has_primary_and_secondary():
    for profile in PROFILES.values():
        for tier in Tier:
            tier_config = profile.tiers[tier]
            assert tier_config.primary is not None
            assert tier_config.secondary is not None
