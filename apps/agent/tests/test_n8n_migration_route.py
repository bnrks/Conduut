from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.routes import n8n_migration as migration_route
from src.store.n8n_migrations import N8nMigrationRecord


class _FakeService:
    def __init__(self):
        self.started_with = None
        self.advanced_with = None

    async def get_manifest(self, _user_id: str):
        return None

    async def preview(self, _user_id: str):
        return None, []

    async def start(self, _user_id: str, *, confirm: bool):
        self.started_with = confirm
        return N8nMigrationRecord(
            id="shared_to_inst_1",
            user_id="u1",
            source_instance_id="shared_dev",
            target_instance_id="inst_1",
            status="in_progress",
            created_at="2026-08-03T10:00:00+00:00",
            updated_at="2026-08-03T10:00:00+00:00",
            confirmed_at="2026-08-03T10:00:00+00:00",
        )

    async def advance(self, _user_id: str, *, batch_size: int):
        self.advanced_with = batch_size
        return N8nMigrationRecord(
            id="shared_to_inst_1",
            user_id="u1",
            source_instance_id="shared_dev",
            target_instance_id="inst_1",
            status="completed",
            created_at="2026-08-03T10:00:00+00:00",
            updated_at="2026-08-03T10:05:00+00:00",
            confirmed_at="2026-08-03T10:00:00+00:00",
        )


def _app():
    app = FastAPI()
    app.include_router(migration_route.router, prefix="/api")
    return TestClient(app)


def test_start_route_requires_explicit_confirm_flag(monkeypatch):
    fake_service = _FakeService()
    monkeypatch.setattr(migration_route, "service", fake_service)
    monkeypatch.setattr(migration_route, "get_user_id", lambda _request: "u1")

    response = _app().post("/api/n8n/migration/start", json={"confirm": True})

    assert response.status_code == 200
    assert fake_service.started_with is True
    assert response.json()["canStart"] is False


def test_advance_route_forwards_batch_size(monkeypatch):
    fake_service = _FakeService()
    monkeypatch.setattr(migration_route, "service", fake_service)
    monkeypatch.setattr(migration_route, "get_user_id", lambda _request: "u1")

    response = _app().post("/api/n8n/migration/advance", json={"batch_size": 7})

    assert response.status_code == 200
    assert fake_service.advanced_with == 7
    assert response.json()["status"] == "completed"


def test_get_route_returns_idle_dto(monkeypatch):
    fake_service = _FakeService()
    monkeypatch.setattr(migration_route, "service", fake_service)
    monkeypatch.setattr(migration_route, "get_user_id", lambda _request: "u1")

    response = _app().get("/api/n8n/migration")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "idle"
    assert body["canStart"] is False
    assert body["nextAction"] == "connect_n8n"
