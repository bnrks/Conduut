import pytest
from fastapi import HTTPException

from src import store
from src.routes import settings as settings_route


@pytest.mark.asyncio
async def test_verify_provider_success(monkeypatch):
    monkeypatch.setattr(settings_route, "get_user_id", lambda _request: "user_1")

    async def fake_get_provider(_user_id: str, provider: str):
        return store.ProviderConnection(provider=provider, api_key="key")

    monkeypatch.setattr(settings_route.store, "get_provider", fake_get_provider)

    async def fake_verify(_provider: str, _api_key: str) -> None:
        return None

    monkeypatch.setattr(settings_route, "verify_provider_connection", fake_verify)

    result = await settings_route.verify_provider("openai", request=object())

    assert result == {"valid": True, "provider": "openai"}


@pytest.mark.asyncio
async def test_verify_provider_failure(monkeypatch):
    monkeypatch.setattr(settings_route, "get_user_id", lambda _request: "user_1")

    async def fake_get_provider(_user_id: str, provider: str):
        return store.ProviderConnection(provider=provider, api_key="bad")

    monkeypatch.setattr(settings_route.store, "get_provider", fake_get_provider)

    async def fake_verify(_provider: str, _api_key: str) -> None:
        raise RuntimeError("Invalid API key")

    monkeypatch.setattr(settings_route, "verify_provider_connection", fake_verify)

    result = await settings_route.verify_provider("openai", request=object())

    assert result == {"valid": False, "provider": "openai", "error": "Invalid API key"}


@pytest.mark.asyncio
async def test_verify_provider_rejects_unsupported_provider(monkeypatch):
    monkeypatch.setattr(settings_route, "get_user_id", lambda _request: "user_1")

    with pytest.raises(HTTPException) as exc:
        await settings_route.verify_provider("custom", request=object())

    assert exc.value.status_code == 422


def test_model_option_includes_reasoning_efforts_for_supported_openai_model():
    assert settings_route._model_option("openai", "gpt-5") == {
        "id": "gpt-5",
        "name": "gpt-5",
        "supports_reasoning": True,
        "reasoning_efforts": ["minimal", "low", "medium", "high"],
    }


@pytest.mark.asyncio
async def test_openai_models_use_static_catalog_without_remote_fetch(monkeypatch):
    monkeypatch.setattr(settings_route, "get_user_id", lambda _request: "user_1")

    async def fake_get_provider(_user_id: str, provider: str):
        return store.ProviderConnection(provider=provider, api_key="key")

    monkeypatch.setattr(settings_route.store, "get_provider", fake_get_provider)

    def fail_if_called(*_args, **_kwargs):
        raise AssertionError("OpenAI model picker should not call the remote models API")

    monkeypatch.setattr(settings_route.httpx, "AsyncClient", fail_if_called)

    result = await settings_route.get_provider_models("openai", request=object())

    model_ids = {item["id"] for item in result["models"]}
    assert "gpt-5.2" in model_ids
    assert "gpt-4o-mini" in model_ids
    assert all("supports_reasoning" in item for item in result["models"])
