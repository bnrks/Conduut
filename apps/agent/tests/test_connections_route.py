from urllib.parse import parse_qs, urlparse

import pytest
from fastapi import HTTPException

from src import n8n_client, store
from src.config import settings
from src.oauth import google
from src.routes import connections as connections_route


def _oauth_state(*, used: bool = False, expires_at: str = "2999-01-01T00:00:00+00:00"):
    return store.OAuthState(
        id="state_1",
        user_id="user_1",
        provider="google",
        service="gmail",
        code_verifier="verifier_1",
        return_to="/dashboard/connections",
        expires_at=expires_at,
        used=used,
    )


def _app_connection(**overrides):
    data = {
        "id": "google_gmail",
        "provider": "google",
        "service": "gmail",
        "account_email": "user@example.com",
        "google_sub": "google_sub",
        "credential_type": "gmailOAuth2",
        "n8n_credential_id": "cred_1",
        "n8n_credential_name": "Google Gmail - user@example.com - Conduut",
        "status": "connected",
        "scopes": google.GMAIL_SEND_SCOPES,
        "created_at": "now",
        "updated_at": "now",
    }
    data.update(overrides)
    return store.AppConnection(**data)


def test_google_authorization_url_includes_pkce_offline_and_gmail_scope(monkeypatch):
    monkeypatch.setattr(settings, "google_oauth_client_id", "client_id")
    monkeypatch.setattr(settings, "google_oauth_client_secret", "client_secret")
    monkeypatch.setattr(settings, "public_web_url", "http://localhost:3000")

    url = google.authorization_url(state="state_1", code_verifier="verifier_1")
    query = parse_qs(urlparse(url).query)

    assert query["client_id"] == ["client_id"]
    assert query["redirect_uri"] == ["http://localhost:3000/api/oauth/google/callback"]
    assert query["access_type"] == ["offline"]
    assert query["prompt"] == ["consent"]
    assert query["state"] == ["state_1"]
    assert query["code_challenge_method"] == ["S256"]
    assert query["code_challenge"] == [google.code_challenge("verifier_1")]
    scopes = query["scope"][0].split()
    assert "openid" in scopes
    assert "email" in scopes
    assert "profile" in scopes
    assert "https://www.googleapis.com/auth/gmail.send" in scopes
    assert "https://www.googleapis.com/auth/gmail.readonly" in scopes


@pytest.mark.asyncio
async def test_authorize_google_gmail_saves_state_and_returns_url(monkeypatch):
    monkeypatch.setattr(connections_route, "get_user_id", lambda _request: "user_1")
    monkeypatch.setattr(connections_route.google, "ensure_google_oauth_configured", lambda: None)
    monkeypatch.setattr(connections_route.google, "generate_state", lambda: "state_1")
    monkeypatch.setattr(
        connections_route.google,
        "generate_code_verifier",
        lambda: "verifier_1",
    )
    monkeypatch.setattr(
        connections_route.google,
        "authorization_url",
        lambda *, state, code_verifier: (
            f"https://google.test?state={state}&verifier={code_verifier}"
        ),
    )
    monkeypatch.setattr(
        connections_route.google,
        "expires_at",
        lambda: "2999-01-01T00:00:00+00:00",
    )

    saved: dict[str, object] = {}

    async def fake_save_oauth_state(state_id: str, **kwargs):
        saved["state_id"] = state_id
        saved.update(kwargs)
        return _oauth_state()

    monkeypatch.setattr(connections_route.store, "save_oauth_state", fake_save_oauth_state)

    response = await connections_route.authorize_google_gmail(
        object(),
        connections_route.AuthorizeIn(return_to="/dashboard/connections"),
    )

    assert response == {"authorizationUrl": "https://google.test?state=state_1&verifier=verifier_1"}
    assert saved["state_id"] == "state_1"
    assert saved["user_id"] == "user_1"
    assert saved["provider"] == "google"
    assert saved["service"] == "gmail"
    assert saved["code_verifier"] == "verifier_1"
    assert saved["return_to"] == "/dashboard/connections"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("state", "expected_message"),
    [
        (None, "Invalid OAuth state."),
        (_oauth_state(used=True), "OAuth state has already been used."),
        (_oauth_state(expires_at="2000-01-01T00:00:00+00:00"), "OAuth state has expired."),
    ],
)
async def test_google_callback_rejects_invalid_used_or_expired_state(
    monkeypatch,
    state,
    expected_message,
):
    async def fake_get_oauth_state(_state_id: str):
        return state

    monkeypatch.setattr(connections_route.store, "get_oauth_state", fake_get_oauth_state)

    with pytest.raises(HTTPException) as exc:
        await connections_route.google_gmail_callback(
            connections_route.GoogleCallbackIn(code="code", state="state_1")
        )

    assert exc.value.status_code == 400
    assert exc.value.detail == {"message": expected_message}


@pytest.mark.asyncio
async def test_google_callback_creates_n8n_credential_and_connection(monkeypatch):
    monkeypatch.setattr(settings, "google_oauth_client_id", "client_id")
    monkeypatch.setattr(settings, "google_oauth_client_secret", "client_secret")

    async def fake_get_oauth_state(_state_id: str):
        return _oauth_state()

    marked: list[str] = []

    async def fake_mark_used(state_id: str):
        marked.append(state_id)

    token_response = {
        "access_token": "access_token",
        "refresh_token": "refresh_token",
        "token_type": "Bearer",
        "expires_in": 3600,
        "scope": (
            "openid email profile https://www.googleapis.com/auth/gmail.send "
            "https://www.googleapis.com/auth/gmail.readonly"
        ),
    }

    async def fake_exchange_code(*, code: str, code_verifier: str):
        assert code == "code"
        assert code_verifier == "verifier_1"
        return token_response

    async def fake_fetch_userinfo(access_token: str):
        assert access_token == "access_token"
        return {"email": "user@example.com", "sub": "google_sub"}

    async def fake_get_connection(_user_id: str, _connection_id: str):
        return None

    created: dict[str, object] = {}

    async def fake_create_credential(name: str, credential_type: str, data: dict):
        created["name"] = name
        created["credential_type"] = credential_type
        created["data"] = data
        return n8n_client.N8nCredential(id="cred_1", name=name, type=credential_type)

    saved_connection: dict[str, object] = {}

    async def fake_save_connection(user_id: str, connection_id: str, **kwargs):
        saved_connection["user_id"] = user_id
        saved_connection["connection_id"] = connection_id
        saved_connection.update(kwargs)
        return _app_connection(**kwargs)

    monkeypatch.setattr(connections_route.store, "get_oauth_state", fake_get_oauth_state)
    monkeypatch.setattr(connections_route.store, "mark_oauth_state_used", fake_mark_used)
    monkeypatch.setattr(connections_route.google, "exchange_code", fake_exchange_code)
    monkeypatch.setattr(connections_route.google, "fetch_userinfo", fake_fetch_userinfo)
    monkeypatch.setattr(connections_route.store, "get_connection", fake_get_connection)
    monkeypatch.setattr(connections_route.n8n_client, "create_credential", fake_create_credential)
    monkeypatch.setattr(connections_route.store, "save_connection", fake_save_connection)

    response = await connections_route.google_gmail_callback(
        connections_route.GoogleCallbackIn(code="code", state="state_1")
    )

    assert marked == ["state_1"]
    assert created["credential_type"] == "gmailOAuth2"
    credential_data = created["data"]
    assert credential_data["serverUrl"] == "https://accounts.google.com"
    assert credential_data["clientId"] == "client_id"
    assert credential_data["clientSecret"] == "client_secret"
    assert credential_data["sendAdditionalBodyProperties"] is False
    assert credential_data["additionalBodyProperties"] == {}
    assert credential_data["oauthTokenData"]["access_token"] == "access_token"
    assert credential_data["oauthTokenData"]["refresh_token"] == "refresh_token"
    assert saved_connection["user_id"] == "user_1"
    assert saved_connection["connection_id"] == "google_gmail"
    assert response["connection"]["id"] == "google_gmail"
    assert response["connection"]["accountEmail"] == "user@example.com"
    assert response["returnTo"] == "/dashboard/connections"


@pytest.mark.asyncio
async def test_google_callback_cleans_up_n8n_credential_after_store_failure(monkeypatch):
    monkeypatch.setattr(settings, "google_oauth_client_id", "client_id")
    monkeypatch.setattr(settings, "google_oauth_client_secret", "client_secret")

    async def fake_get_oauth_state(_state_id: str):
        return _oauth_state()

    async def fake_noop(*_args, **_kwargs):
        return None

    async def fake_exchange_code(*_args, **_kwargs):
        return {
            "access_token": "access_token",
            "refresh_token": "refresh_token",
            "token_type": "Bearer",
        }

    async def fake_fetch_userinfo(_access_token: str):
        return {"email": "user@example.com", "sub": "google_sub"}

    async def fake_get_connection(_user_id: str, _connection_id: str):
        return None

    async def fake_create_credential(name: str, credential_type: str, _data: dict):
        return n8n_client.N8nCredential(id="cred_1", name=name, type=credential_type)

    async def fail_save_connection(*_args, **_kwargs):
        raise RuntimeError("firestore down")

    deleted: list[str] = []

    async def fake_delete_credential(credential_id: str):
        deleted.append(credential_id)

    monkeypatch.setattr(connections_route.store, "get_oauth_state", fake_get_oauth_state)
    monkeypatch.setattr(connections_route.store, "mark_oauth_state_used", fake_noop)
    monkeypatch.setattr(connections_route.google, "exchange_code", fake_exchange_code)
    monkeypatch.setattr(connections_route.google, "fetch_userinfo", fake_fetch_userinfo)
    monkeypatch.setattr(connections_route.store, "get_connection", fake_get_connection)
    monkeypatch.setattr(connections_route.n8n_client, "create_credential", fake_create_credential)
    monkeypatch.setattr(connections_route.store, "save_connection", fail_save_connection)
    monkeypatch.setattr(connections_route.n8n_client, "delete_credential", fake_delete_credential)

    with pytest.raises(HTTPException) as exc:
        await connections_route.google_gmail_callback(
            connections_route.GoogleCallbackIn(code="code", state="state_1")
        )

    assert exc.value.status_code == 400
    assert deleted == ["cred_1"]
