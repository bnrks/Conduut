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
