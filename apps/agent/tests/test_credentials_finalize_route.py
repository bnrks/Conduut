"""Tests for the draft credential finalize route."""

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from src import n8n_client, store
from src.routes import credentials as credentials_route
from src.routes.credentials import CredentialFinalizeIn


@pytest.fixture(autouse=True)
def _request_scoped_shared_n8n(monkeypatch):
    context = SimpleNamespace(
        target=SimpleNamespace(instance_id="shared_dev", ownership="shared_dev")
    )

    async def fake_request_n8n(_request, _user_id):
        return context, credentials_route.n8n_client

    async def fake_active_instance(_user_id):
        return None

    monkeypatch.setattr(credentials_route, "_request_n8n", fake_request_n8n)
    monkeypatch.setattr(credentials_route.store, "get_active_n8n_instance", fake_active_instance)


def _draft(**overrides):
    data = {
        "id": "draft1",
        "label": "API Ninjas",
        "credential_type": "httpHeaderAuth",
        "host": "api.api-ninjas.com",
        "n8n_credential_id": "",
        "n8n_credential_name": "",
        "created_at": "now",
        "updated_at": "now",
        "status": "draft",
        "auth_config": {"field_name": "X-Api-Key", "value_prefix": ""},
        "secret_fields": ["key"],
        "source_url": "https://api-ninjas.com",
        "confidence": "high",
        "pending_workflow_id": "wf1",
        "pending_node_name": "HTTP",
    }
    data.update(overrides)
    return store.CustomCredential(**data)


def _patch_user(monkeypatch):
    monkeypatch.setattr(credentials_route, "get_user_id", lambda _request: "u1")


async def test_finalize_creates_and_attaches(monkeypatch):
    _patch_user(monkeypatch)
    calls: dict = {}

    async def fake_get(_uid, _cid, **_kwargs):
        return _draft()

    async def fake_create(name, credential_type, data):
        calls["create"] = (name, credential_type, data)
        return n8n_client.N8nCredential(id="n8n_9", name=name, type=credential_type)

    async def fake_finalize(_uid, _cid, *, n8n_credential_id, n8n_credential_name, **_kwargs):
        calls["finalize"] = (n8n_credential_id, n8n_credential_name)
        return _draft(status="ready", n8n_credential_id=n8n_credential_id)

    async def fake_attach(*args, **kwargs):
        calls["attach"] = {"args": args, "kwargs": kwargs}
        return {}

    monkeypatch.setattr(credentials_route.store, "get_custom_credential", fake_get)
    monkeypatch.setattr(credentials_route.n8n_client, "create_credential", fake_create)
    monkeypatch.setattr(credentials_route.store, "finalize_draft_credential", fake_finalize)
    monkeypatch.setattr(credentials_route.n8n_client, "attach_credential_to_workflow", fake_attach)

    body = CredentialFinalizeIn(data={"key": "secret-123"})
    result = await credentials_route.finalize_credential(object(), "draft1", body)

    # header auth: value = value_prefix + key
    assert calls["create"][1] == "httpHeaderAuth"
    assert calls["create"][2] == {"name": "X-Api-Key", "value": "secret-123"}
    assert calls["finalize"] == ("n8n_9", "API Ninjas")
    assert calls["attach"]["kwargs"]["generic_auth_type"] == "httpHeaderAuth"
    assert result["workflow_id"] == "wf1"


async def test_customer_owned_finalize_cannot_mutate_external_workflow(monkeypatch):
    _patch_user(monkeypatch)
    context = SimpleNamespace(
        target=SimpleNamespace(instance_id="inst_1", ownership="customer_owned")
    )
    created = False

    class _Client:
        async def create_credential(self, *_args, **_kwargs):
            nonlocal created
            created = True

    async def fake_request_n8n(_request, _user_id):
        return context, _Client()

    async def fake_get(_uid, _cid, **_kwargs):
        return _draft(instance_id="inst_1")

    async def fake_metadata(_user_id, _workflow_id, **_kwargs):
        return None

    monkeypatch.setattr(credentials_route, "_request_n8n", fake_request_n8n)
    monkeypatch.setattr(credentials_route.store, "get_custom_credential", fake_get)
    monkeypatch.setattr(credentials_route.store, "get_workflow_metadata", fake_metadata)

    with pytest.raises(HTTPException) as exc:
        await credentials_route.finalize_credential(
            object(), "draft1", CredentialFinalizeIn(data={"key": "secret"})
        )

    assert exc.value.status_code == 409
    assert exc.value.detail["code"] == "workflow_adoption_required"
    assert created is False


async def test_finalize_basic_auth_builds_user_password(monkeypatch):
    _patch_user(monkeypatch)
    calls: dict = {}

    async def fake_get(_uid, _cid, **_kwargs):
        return _draft(
            credential_type="httpBasicAuth",
            auth_config={"field_name": "", "value_prefix": ""},
            secret_fields=["user", "password"],
            pending_workflow_id="",
            pending_node_name="",
        )

    async def fake_create(name, credential_type, data):
        calls["data"] = data
        return n8n_client.N8nCredential(id="n8n_9", name=name, type=credential_type)

    async def fake_finalize(_uid, _cid, **_k):
        return _draft(status="ready", n8n_credential_id="n8n_9")

    monkeypatch.setattr(credentials_route.store, "get_custom_credential", fake_get)
    monkeypatch.setattr(credentials_route.n8n_client, "create_credential", fake_create)
    monkeypatch.setattr(credentials_route.store, "finalize_draft_credential", fake_finalize)

    body = CredentialFinalizeIn(data={"user": "bob", "password": "p4ss"})
    await credentials_route.finalize_credential(object(), "draft1", body)
    assert calls["data"] == {"user": "bob", "password": "p4ss"}


async def test_finalize_unknown_draft_404(monkeypatch):
    _patch_user(monkeypatch)

    async def fake_get(_uid, _cid, **_kwargs):
        return None

    monkeypatch.setattr(credentials_route.store, "get_custom_credential", fake_get)
    with pytest.raises(HTTPException) as exc:
        await credentials_route.finalize_credential(object(), "nope", CredentialFinalizeIn(data={}))
    assert exc.value.status_code == 404


async def test_finalize_already_ready_409(monkeypatch):
    _patch_user(monkeypatch)

    async def fake_get(_uid, _cid, **_kwargs):
        return _draft(status="ready", n8n_credential_id="n8n_old")

    monkeypatch.setattr(credentials_route.store, "get_custom_credential", fake_get)
    with pytest.raises(HTTPException) as exc:
        await credentials_route.finalize_credential(
            object(), "draft1", CredentialFinalizeIn(data={"key": "x"})
        )
    assert exc.value.status_code == 409


async def test_list_includes_status(monkeypatch):
    _patch_user(monkeypatch)

    async def fake_list(_uid, **_kwargs):
        return [_draft(status="draft")]

    monkeypatch.setattr(credentials_route.store, "list_custom_credentials", fake_list)
    result = await credentials_route.list_credentials(object())
    assert result["credentials"][0]["status"] == "draft"
