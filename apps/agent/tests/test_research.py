"""Tests for the API auth research engine (cache + scheme mapping)."""

from src.agent import research


def test_credential_type_for_scheme():
    assert research.credential_type_for_scheme("header") == "httpHeaderAuth"
    assert research.credential_type_for_scheme("query") == "httpQueryAuth"
    assert research.credential_type_for_scheme("basic") == "httpBasicAuth"
    assert research.credential_type_for_scheme("custom") == "httpCustomAuth"
    assert research.credential_type_for_scheme("none") is None
    assert research.credential_type_for_scheme("unknown") is None


def _cache(**overrides):
    from src import store

    data = {
        "host": "api.api-ninjas.com",
        "scheme": "header",
        "credential_type": "httpHeaderAuth",
        "field_name": "X-Api-Key",
        "value_prefix": "",
        "secret_fields": ["key"],
        "summary": "X-Api-Key header",
        "source_url": "https://api-ninjas.com",
        "confidence": "high",
        "researched_at": "2026-06-21T00:00:00+00:00",
        "model": "gemini-2.5-flash",
    }
    data.update(overrides)
    return store.ApiAuthCache(**data)


async def test_research_cache_hit_skips_grounding(monkeypatch):
    calls = {"grounding": 0}

    async def fake_get(_host):
        return _cache()

    async def fake_run(_q):  # pragma: no cover - must not be called on cache hit
        calls["grounding"] += 1
        return research.AuthResearchResult(scheme="basic")

    monkeypatch.setattr(research.store, "get_api_auth_cache", fake_get)
    monkeypatch.setattr(research, "_run_grounding_research", fake_run)
    monkeypatch.setattr(research, "_is_stale", lambda _ts, _ttl: False)

    result = await research.research_api_auth("https://api.api-ninjas.com/v1/quotes")
    assert calls["grounding"] == 0
    assert result.scheme == "header"
    assert result.field_name == "X-Api-Key"


async def test_research_cache_miss_then_saves(monkeypatch):
    saved: dict = {}

    async def fake_get(_host):
        return None

    async def fake_save(host, **kwargs):
        saved["host"] = host
        saved.update(kwargs)

    async def fake_run(_q):
        return research.AuthResearchResult(
            scheme="header",
            field_name="X-Api-Key",
            secret_fields=["key"],
            confidence="high",
            source_url="https://api-ninjas.com",
        )

    monkeypatch.setattr(research.store, "get_api_auth_cache", fake_get)
    monkeypatch.setattr(research.store, "save_api_auth_cache", fake_save)
    monkeypatch.setattr(research, "_run_grounding_research", fake_run)

    result = await research.research_api_auth("https://api.api-ninjas.com/v1/quotes")
    assert result.field_name == "X-Api-Key"
    assert saved["host"] == "api.api-ninjas.com"
    assert saved["credential_type"] == "httpHeaderAuth"
    assert saved["confidence"] == "high"


async def test_research_low_confidence_not_cached(monkeypatch):
    saved = {"called": False}

    async def fake_get(_host):
        return None

    async def fake_save(*_a, **_k):  # pragma: no cover - must not be called
        saved["called"] = True

    async def fake_run(_q):
        return research.AuthResearchResult(scheme="header", confidence="low")

    monkeypatch.setattr(research.store, "get_api_auth_cache", fake_get)
    monkeypatch.setattr(research.store, "save_api_auth_cache", fake_save)
    monkeypatch.setattr(research, "_run_grounding_research", fake_run)

    result = await research.research_api_auth("https://api.weird.test/x")
    assert result.confidence == "low"
    assert saved["called"] is False
