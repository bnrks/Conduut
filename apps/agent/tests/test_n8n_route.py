from fastapi import FastAPI
from fastapi.testclient import TestClient

from src import store
from src.routes import n8n as n8n_route


def _record(**overrides):
    data = {
        "id": "inst_1",
        "display_name": "Primary",
        "ownership": "customer_owned",
        "provider": "manual",
        "base_url": "https://automation.example.com",
        "webhook_base_url": "https://automation.example.com",
        "api_key_secret_ref": "secret-ref",
        "n8n_version": "1.121.3",
        "compatibility_status": "supported",
        "connection_status": "connected",
        "capabilities": ["workflows", "executions", "credentials"],
        "verified_at": "2026-08-03T10:00:00+00:00",
        "last_health_at": "2026-08-03T10:00:00+00:00",
        "last_error_code": None,
        "created_at": "2026-08-03T10:00:00+00:00",
        "updated_at": "2026-08-03T10:00:00+00:00",
        "is_active": True,
    }
    data.update(overrides)
    return store.N8nInstanceRecord(**data)


def _app():
    app = FastAPI()
    app.include_router(n8n_route.router, prefix="/api")
    return TestClient(app)


def test_get_n8n_route_returns_active_instance(monkeypatch):
    monkeypatch.setattr(n8n_route, "get_user_id", lambda _request: "u1")

    async def fake_get(_user_id):
        return _record()

    monkeypatch.setattr(n8n_route.store, "get_active_n8n_instance", fake_get)
    monkeypatch.setattr(n8n_route.store, "get_latest_n8n_instance", fake_get)

    response = _app().get("/api/n8n/instance")

    assert response.status_code == 200
    assert response.json()["instance"]["status"] == "connected"
    assert response.json()["instance"]["displayName"] == "Primary"


def test_connect_n8n_route_redacts_secret_from_response(monkeypatch):
    monkeypatch.setattr(n8n_route, "get_user_id", lambda _request: "u1")

    async def fake_connect(user_id, *, base_url, api_key, display_name, webhook_base_url=None):
        assert user_id == "u1"
        assert api_key == "secret"
        return _record(
            display_name=display_name,
            base_url=base_url,
            webhook_base_url=webhook_base_url or base_url,
        )

    monkeypatch.setattr(n8n_route.resolver, "connect", fake_connect)

    response = _app().post(
        "/api/n8n/instance",
        json={
            "baseUrl": "https://automation.example.com",
            "apiKey": "secret",
            "displayName": "Prod",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert "api_key" not in str(body).lower()
    assert "https://" not in str(body).lower()
    assert "baseUrl" not in str(body)
    assert body["instance"]["displayName"] == "Prod"
