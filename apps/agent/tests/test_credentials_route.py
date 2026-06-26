"""Tests for the custom credential library routes."""

import pytest
from fastapi import HTTPException
from n8n_registry.models import CredentialTypeInfo

from src import n8n_client, store
from src.routes import credentials as credentials_route
from src.routes.credentials import CredentialSubmitIn


def _custom_credential(**overrides):
    data = {
        "id": "cred_1",
        "label": "Stripe API",
        "credential_type": "httpHeaderAuth",
        "host": "api.stripe.com",
        "n8n_credential_id": "n8n_1",
        "n8n_credential_name": "Stripe API",
        "created_at": "now",
        "updated_at": "now",
    }
    data.update(overrides)
    return store.CustomCredential(**data)


def _patch_user(monkeypatch):
    monkeypatch.setattr(credentials_route, "get_user_id", lambda _request: "u1")


async def test_submit_http_credential_creates_and_attaches(monkeypatch):
    _patch_user(monkeypatch)
    calls: dict = {}

    async def fake_create(name, credential_type, data):
        calls["create"] = (name, credential_type, data)
        return n8n_client.N8nCredential(id="n8n_1", name=name, type=credential_type)

    async def fake_save(user_id, **kwargs):
        calls["save"] = kwargs
        return _custom_credential(host=kwargs["host"], label=kwargs["label"])

    async def fake_attach(*args, **kwargs):
        calls["attach"] = {"args": args, "kwargs": kwargs}
        return {}

    monkeypatch.setattr(credentials_route.n8n_client, "create_credential", fake_create)
    monkeypatch.setattr(credentials_route.store, "save_custom_credential", fake_save)
    monkeypatch.setattr(credentials_route.n8n_client, "attach_credential_to_workflow", fake_attach)

    body = CredentialSubmitIn(
        credential_type="httpHeaderAuth",
        data={"name": "Authorization", "value": "Bearer x"},
        label="Stripe API",
        host="https://api.stripe.com/v1",
        workflow_id="wf1",
        node_name="HTTP Request",
    )
    result = await credentials_route.submit_credential(object(), body)

    assert calls["create"][1] == "httpHeaderAuth"
    assert calls["save"]["host"] == "api.stripe.com"  # normalized
    assert calls["attach"]["kwargs"]["generic_auth_type"] == "httpHeaderAuth"
    assert result["credential"]["host"] == "api.stripe.com"
    assert result["workflow_id"] == "wf1"


async def test_submit_requires_host_for_http_type(monkeypatch):
    _patch_user(monkeypatch)

    async def fail_create(*a, **k):  # pragma: no cover - must not be called
        raise AssertionError("create should not be called without host")

    monkeypatch.setattr(credentials_route.n8n_client, "create_credential", fail_create)

    body = CredentialSubmitIn(
        credential_type="httpBasicAuth",
        data={"user": "u", "password": "p"},
    )
    with pytest.raises(HTTPException) as exc:
        await credentials_route.submit_credential(object(), body)
    assert exc.value.status_code == 422


async def test_submit_library_only_without_workflow(monkeypatch):
    _patch_user(monkeypatch)
    calls: dict = {"attach": False}

    async def fake_create(name, credential_type, data):
        return n8n_client.N8nCredential(id="n8n_1", name=name, type=credential_type)

    async def fake_save(user_id, **kwargs):
        calls["save"] = kwargs
        return _custom_credential(host=kwargs["host"], label=kwargs["label"])

    async def fake_attach(*a, **k):
        calls["attach"] = True
        return {}

    monkeypatch.setattr(credentials_route.n8n_client, "create_credential", fake_create)
    monkeypatch.setattr(credentials_route.store, "save_custom_credential", fake_save)
    monkeypatch.setattr(credentials_route.n8n_client, "attach_credential_to_workflow", fake_attach)

    body = CredentialSubmitIn(
        credential_type="httpHeaderAuth",
        data={"name": "X-API-Key", "value": "k"},
        host="api.test.com",
    )
    await credentials_route.submit_credential(object(), body)
    assert calls["attach"] is False
    assert calls["save"]["host"] == "api.test.com"


async def test_list_credentials(monkeypatch):
    _patch_user(monkeypatch)

    async def fake_list(user_id):
        return [_custom_credential()]

    monkeypatch.setattr(credentials_route.store, "list_custom_credentials", fake_list)
    result = await credentials_route.list_credentials(object())
    assert result["credentials"][0]["label"] == "Stripe API"
    assert "n8n_credential_id" not in result["credentials"][0]


async def test_credential_types(monkeypatch):
    _patch_user(monkeypatch)
    result = await credentials_route.credential_types(object())
    assert {t["type"] for t in result["types"]} == {
        "httpHeaderAuth",
        "httpBasicAuth",
        "httpQueryAuth",
        "httpCustomAuth",
    }


async def test_delete_credential(monkeypatch):
    _patch_user(monkeypatch)
    deleted: dict = {}

    async def fake_get(user_id, credential_id):
        return _custom_credential(id=credential_id)

    async def fake_n8n_delete(n8n_id):
        deleted["n8n"] = n8n_id

    async def fake_store_delete(user_id, credential_id):
        deleted["store"] = credential_id

    monkeypatch.setattr(credentials_route.store, "get_custom_credential", fake_get)
    monkeypatch.setattr(credentials_route.n8n_client, "delete_credential", fake_n8n_delete)
    monkeypatch.setattr(credentials_route.store, "delete_custom_credential", fake_store_delete)

    result = await credentials_route.delete_credential(object(), "cred_9")
    assert result["deleted"] is True
    assert deleted["n8n"] == "n8n_1"
    assert deleted["store"] == "cred_9"


async def test_delete_credential_not_found(monkeypatch):
    _patch_user(monkeypatch)

    async def fake_get(user_id, credential_id):
        return None

    monkeypatch.setattr(credentials_route.store, "get_custom_credential", fake_get)
    with pytest.raises(HTTPException) as exc:
        await credentials_route.delete_credential(object(), "missing")
    assert exc.value.status_code == 404


async def test_credential_catalog_excludes_oauth(monkeypatch):
    _patch_user(monkeypatch)
    monkeypatch.setattr(
        credentials_route.registry,
        "list_credential_catalog",
        lambda q=None: [{"type": "openAiApi", "label": "OpenAI", "icon_url": ""}],
    )
    result = await credentials_route.credential_catalog_list(object(), q=None)
    assert [c["type"] for c in result["catalog"]] == ["openAiApi"]


async def test_credential_catalog_schema_returns_fields(monkeypatch):
    _patch_user(monkeypatch)

    async def fake_schema(credential_type):
        assert credential_type == "openAiApi"
        return {
            "properties": {"apiKey": {"type": "string", "displayName": "API Key"}},
            "required": ["apiKey"],
        }

    monkeypatch.setattr(credentials_route.n8n_client, "get_credential_schema", fake_schema)
    result = await credentials_route.credential_catalog_schema(object(), "openAiApi")
    assert result["credentialType"] == "openAiApi"
    assert result["fields"][0]["name"] == "apiKey"
    assert result["fields"][0]["type"] == "password"


async def test_credential_catalog_schema_rejects_oauth_by_name(monkeypatch):
    _patch_user(monkeypatch)
    with pytest.raises(HTTPException) as exc:
        await credentials_route.credential_catalog_schema(object(), "slackOAuth2Api")
    assert exc.value.status_code == 422


async def test_submit_type_matched_credential_no_host(monkeypatch):
    _patch_user(monkeypatch)
    calls: dict = {"attach": False}

    async def fake_create(name, credential_type, data):
        return n8n_client.N8nCredential(id="n8n_9", name=name, type=credential_type)

    async def fake_save(user_id, **kwargs):
        calls["save"] = kwargs
        return _custom_credential(
            id="cred_t", label=kwargs["label"], credential_type="openAiApi", host=""
        )

    async def fake_attach(*args, **kwargs):
        calls["attach"] = kwargs
        return {}

    monkeypatch.setattr(credentials_route.n8n_client, "create_credential", fake_create)
    monkeypatch.setattr(credentials_route.store, "save_custom_credential", fake_save)
    monkeypatch.setattr(credentials_route.n8n_client, "attach_credential_to_workflow", fake_attach)

    body = CredentialSubmitIn(
        credential_type="openAiApi",
        data={"apiKey": "sk-x"},
        label="OpenAI",
        match_kind="type",
        workflow_id="wf1",
        node_name="OpenAI Chat Model",
    )
    result = await credentials_route.submit_credential(object(), body)
    assert calls["save"]["match_kind"] == "type"
    assert calls["save"]["host"] == ""
    # Predefined type-matched: do NOT wire generic HTTP auth.
    assert calls["attach"]["generic_auth_type"] is None
    assert result["credential"]["credential_type"] == "openAiApi"


async def test_list_credentials_includes_match_kind(monkeypatch):
    _patch_user(monkeypatch)

    async def fake_list(user_id):
        return [_custom_credential(credential_type="openAiApi", host="", match_kind="type")]

    monkeypatch.setattr(credentials_route.store, "list_custom_credentials", fake_list)
    result = await credentials_route.list_credentials(object())
    assert result["credentials"][0]["match_kind"] == "type"


async def test_credential_catalog_schema_rejects_oauth_by_signature(monkeypatch):
    _patch_user(monkeypatch)

    async def fake_schema(credential_type):
        return {"properties": {"clientId": {}, "oauthTokenData": {}}}

    monkeypatch.setattr(credentials_route.n8n_client, "get_credential_schema", fake_schema)
    with pytest.raises(HTTPException) as exc:
        await credentials_route.credential_catalog_schema(object(), "weirdApi")
    assert exc.value.status_code == 422


async def test_catalog_list_from_registry(monkeypatch):
    _patch_user(monkeypatch)
    monkeypatch.setattr(
        credentials_route.registry,
        "list_credential_catalog",
        lambda q=None: [{"type": "anthropicApi", "label": "Anthropic", "icon_url": "icons/a.svg"}],
    )
    result = await credentials_route.credential_catalog_list(object(), q=None)
    assert result["catalog"][0]["icon_url"] == "icons/a.svg"


async def test_catalog_schema_from_definition(monkeypatch):
    _patch_user(monkeypatch)
    definition = CredentialTypeInfo(
        name="anthropicApi",
        display_name="Anthropic",
        icon_url="icons/a.svg",
        properties=[
            {
                "displayName": "API Key",
                "name": "apiKey",
                "type": "string",
                "typeOptions": {"password": True},
                "required": True,
            }
        ],
    )
    monkeypatch.setattr(
        credentials_route.registry,
        "get_credential_definition",
        lambda t: definition if t == "anthropicApi" else None,
    )
    result = await credentials_route.credential_catalog_schema(object(), "anthropicApi")
    assert result["label"] == "Anthropic"
    assert result["iconUrl"] == "icons/a.svg"
    assert result["fields"][0]["name"] == "apiKey"
    assert result["fields"][0]["type"] == "password"


async def test_catalog_schema_oauth_definition_rejected(monkeypatch):
    _patch_user(monkeypatch)
    definition = CredentialTypeInfo(name="slackOAuth2Api", display_name="Slack", is_oauth=True)
    monkeypatch.setattr(
        credentials_route.registry, "get_credential_definition", lambda t: definition
    )
    with pytest.raises(HTTPException) as exc:
        await credentials_route.credential_catalog_schema(object(), "slackOAuth2Api")
    assert exc.value.status_code == 422


async def test_credential_icon_rejects_non_icon_path():
    with pytest.raises(HTTPException) as exc:
        await credentials_route.credential_icon(path="../../etc/passwd")
    assert exc.value.status_code == 400


async def test_credential_icon_streams_svg(monkeypatch):
    class _Resp:
        status_code = 200
        content = b"<svg/>"
        headers = {"content-type": "image/svg+xml"}

    class _Client:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, url):
            assert url.endswith("/icons/slack.svg")
            return _Resp()

    monkeypatch.setattr(credentials_route.httpx, "AsyncClient", _Client)
    result = await credentials_route.credential_icon(path="icons/slack.svg")
    assert result.media_type == "image/svg+xml"
    assert result.body == b"<svg/>"
