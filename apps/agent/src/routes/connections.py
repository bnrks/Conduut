"""App connection routes, including Conduut-managed Google OAuth."""

from typing import Any

import httpx
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from src import n8n_client, store
from src.auth import get_user_id
from src.oauth import google

router = APIRouter()

GOOGLE_GMAIL_CONNECTION_ID = "google_gmail"
GOOGLE_GMAIL_CREDENTIAL_TYPE = "gmailOAuth2"
GOOGLE_SHEETS_CONNECTION_ID = "google_sheets"
GOOGLE_SHEETS_CREDENTIAL_TYPE = "googleSheetsOAuth2Api"

GOOGLE_CONNECTIONS: dict[str, dict[str, Any]] = {
    "gmail": {
        "connection_id": GOOGLE_GMAIL_CONNECTION_ID,
        "credential_type": GOOGLE_GMAIL_CREDENTIAL_TYPE,
        "service": "gmail",
        "service_name": "Google Gmail",
        "credential_prefix": "Google Gmail",
        "scopes": google.GMAIL_CONNECTION_SCOPES,
        "credential_data": google.n8n_gmail_credential_data,
    },
    "sheets": {
        "connection_id": GOOGLE_SHEETS_CONNECTION_ID,
        "credential_type": GOOGLE_SHEETS_CREDENTIAL_TYPE,
        "service": "sheets",
        "service_name": "Google Sheets",
        "credential_prefix": "Google Sheets",
        "scopes": google.GOOGLE_SHEETS_CONNECTION_SCOPES,
        "credential_data": google.n8n_google_sheets_credential_data,
    },
}


class AuthorizeIn(BaseModel):
    return_to: str | None = None


class GoogleCallbackIn(BaseModel):
    code: str
    state: str


def _connection_payload(connection: store.AppConnection) -> dict[str, Any]:
    service_name = next(
        (
            config["service_name"]
            for config in GOOGLE_CONNECTIONS.values()
            if config["connection_id"] == connection.id
        ),
        connection.service,
    )
    return {
        "id": connection.id,
        "provider": connection.provider,
        "service": connection.service,
        "serviceName": service_name,
        "serviceIcon": connection.provider,
        "accountEmail": connection.account_email,
        "status": connection.status,
        "credentialType": connection.credential_type,
        "connectedAt": connection.created_at,
        "updatedAt": connection.updated_at,
        "scopes": connection.scopes,
    }


def _google_connection_config(service: str) -> dict[str, Any]:
    config = GOOGLE_CONNECTIONS.get(service)
    if not config:
        raise HTTPException(status_code=404, detail={"message": "Unsupported Google service."})
    return config


def _oauth_http_error(exc: httpx.HTTPStatusError, fallback: str) -> HTTPException:
    message = fallback
    try:
        payload = exc.response.json()
        if isinstance(payload, dict):
            message = str(
                payload.get("error_description")
                or payload.get("error")
                or payload.get("message")
                or fallback
            )
    except ValueError:
        message = exc.response.text[:300] or fallback
    return HTTPException(status_code=502, detail={"message": message})


@router.get("/connections")
async def list_connections(request: Request):
    user_id = get_user_id(request)
    connections = await store.list_connections(user_id)
    return {"connections": [_connection_payload(item) for item in connections]}


async def _authorize_google_service(request: Request, body: AuthorizeIn, service: str):
    user_id = get_user_id(request)
    config = _google_connection_config(service)
    try:
        google.ensure_google_oauth_configured()
        state = google.generate_state()
        code_verifier = google.generate_code_verifier()
        await store.save_oauth_state(
            state,
            user_id=user_id,
            provider="google",
            service=config["service"],
            code_verifier=code_verifier,
            return_to=google.safe_return_to(body.return_to),
            expires_at=google.expires_at(),
        )
        return {
            "authorizationUrl": google.authorization_url(
                state=state,
                code_verifier=code_verifier,
                service=config["service"],
            )
        }
    except google.GoogleOAuthConfigError as exc:
        raise HTTPException(status_code=503, detail={"message": str(exc)}) from exc


@router.post("/connections/google/gmail/authorize")
async def authorize_google_gmail(request: Request, body: AuthorizeIn):
    return await _authorize_google_service(request, body, "gmail")


@router.post("/connections/google/sheets/authorize")
async def authorize_google_sheets(request: Request, body: AuthorizeIn):
    return await _authorize_google_service(request, body, "sheets")


async def _google_callback(body: GoogleCallbackIn, *, expected_service: str | None = None):
    state = await store.get_oauth_state(body.state)
    if state is None or state.provider != "google":
        raise HTTPException(status_code=400, detail={"message": "Invalid OAuth state."})
    if expected_service and state.service != expected_service:
        raise HTTPException(status_code=400, detail={"message": "Invalid OAuth state."})
    if state.used:
        raise HTTPException(
            status_code=400, detail={"message": "OAuth state has already been used."}
        )
    if google.is_expired(state.expires_at):
        raise HTTPException(status_code=400, detail={"message": "OAuth state has expired."})

    config = _google_connection_config(state.service)
    await store.mark_oauth_state_used(state.id)

    try:
        token_response = await google.exchange_code(
            code=body.code,
            code_verifier=state.code_verifier,
        )
    except httpx.HTTPStatusError as exc:
        raise _oauth_http_error(exc, "Google token exchange failed.") from exc
    except google.GoogleOAuthConfigError as exc:
        raise HTTPException(status_code=503, detail={"message": str(exc)}) from exc

    access_token = str(token_response.get("access_token") or "")
    refresh_token = str(token_response.get("refresh_token") or "")
    if not access_token or not refresh_token:
        raise HTTPException(
            status_code=400,
            detail={"message": "Google did not return an offline refresh token. Please reconnect."},
        )

    try:
        userinfo = await google.fetch_userinfo(access_token)
    except httpx.HTTPStatusError as exc:
        raise _oauth_http_error(exc, "Could not read Google account profile.") from exc

    account_email = str(userinfo.get("email") or "")
    google_sub = str(userinfo.get("sub") or "")
    if not account_email or not google_sub:
        raise HTTPException(
            status_code=400,
            detail={"message": "Google account profile did not include email/sub."},
        )

    connection_id = config["connection_id"]
    credential_type = config["credential_type"]
    credential_name = f"{config['credential_prefix']} - {account_email} - Conduut"
    credential_data = config["credential_data"](token_response)
    existing = await store.get_connection(state.user_id, connection_id)

    try:
        credential = await n8n_client.create_credential(
            credential_name,
            credential_type,
            credential_data,
        )
        connection = await store.save_connection(
            state.user_id,
            connection_id,
            provider="google",
            service=config["service"],
            account_email=account_email,
            google_sub=google_sub,
            credential_type=credential_type,
            n8n_credential_id=credential.id,
            n8n_credential_name=credential.name,
            scopes=config["scopes"],
        )
    except n8n_client.N8nApiError as exc:
        raise HTTPException(status_code=exc.status_code, detail={"message": exc.message}) from exc
    except Exception as exc:
        if "credential" in locals():
            try:
                await n8n_client.delete_credential(credential.id)
            except Exception:
                pass
        raise HTTPException(status_code=400, detail={"message": str(exc)}) from exc

    if existing and existing.n8n_credential_id != connection.n8n_credential_id:
        try:
            await n8n_client.delete_credential(existing.n8n_credential_id)
        except Exception:
            pass

    return {
        "connection": _connection_payload(connection),
        "returnTo": state.return_to,
    }


@router.post("/connections/google/callback")
async def google_callback(body: GoogleCallbackIn):
    return await _google_callback(body)


@router.post("/connections/google/gmail/callback")
async def google_gmail_callback(body: GoogleCallbackIn):
    return await _google_callback(body, expected_service="gmail")


@router.post("/connections/google/sheets/callback")
async def google_sheets_callback(body: GoogleCallbackIn):
    return await _google_callback(body, expected_service="sheets")


@router.delete("/connections/{connection_id}")
async def delete_connection(connection_id: str, request: Request):
    user_id = get_user_id(request)
    connection = await store.delete_connection(user_id, connection_id)
    if connection is None:
        raise HTTPException(status_code=404, detail={"message": "Connection not found."})

    try:
        await n8n_client.delete_credential(connection.n8n_credential_id)
    except Exception:
        pass

    return {"success": True, "connectionId": connection_id}
