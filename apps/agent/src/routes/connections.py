"""App connection routes, including Conduut-managed Google OAuth."""

from typing import Any

import httpx
import structlog
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from src import n8n_client, store
from src.auth import get_user_id
from src.n8n_provider import N8nClientFactory, N8nInstanceResolver, N8nProviderError, error_detail
from src.oauth import google
from src.platforms import capabilities as platform_capabilities
from src.platforms.crypto import can_encrypt_connection_secrets, encrypt_connection_secret

router = APIRouter()
log = structlog.get_logger()
resolver = N8nInstanceResolver()
client_factory = N8nClientFactory()

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
    requested_capabilities: list[str] | None = None
    permission_pack: str | None = None


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
        "capabilities": connection.capabilities
        or google.capabilities_for_scopes(connection.scopes),
        "permissionPacks": connection.permission_packs
        or platform_capabilities.permission_packs_for_scopes(connection.scopes),
        "directApiEnabled": connection.direct_api_enabled,
        "missingRecommendedCapabilities": [
            capability
            for capability in google.service_capabilities(connection.service)
            if not platform_capabilities.connection_has_capability(
                connection.capabilities or google.capabilities_for_scopes(connection.scopes),
                capability,
            )
        ],
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


def _provider_http_error(exc: N8nProviderError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=error_detail(exc))


async def _request_n8n(request: Request, user_id: str):
    request_state = getattr(request, "state", None)
    request_headers = getattr(request, "headers", {})
    request_id = getattr(request_state, "request_id", None) or request_headers.get("x-request-id")
    context = await resolver.resolve(user_id, request_id=request_id)
    client = await client_factory.for_request_context(context)
    return context, client


@router.get("/connections")
async def list_connections(request: Request):
    user_id = get_user_id(request)
    instance = await store.get_active_n8n_instance(user_id)
    connections = (
        await store.list_connections(user_id, instance_id=instance.id)
        if instance is not None
        else await store.list_connections(user_id)
    )
    return {"connections": [_connection_payload(item) for item in connections]}


async def _authorize_google_service(request: Request, body: AuthorizeIn, service: str):
    user_id = get_user_id(request)
    try:
        context, _client = await _request_n8n(request, user_id)
    except N8nProviderError as exc:
        raise _provider_http_error(exc) from exc
    config = _google_connection_config(service)
    log.info(
        "oauth_authorize_started",
        user_id=user_id,
        provider="google",
        service=config["service"],
        return_to=body.return_to,
        permission_pack=body.permission_pack,
        requested_capabilities=body.requested_capabilities,
    )
    try:
        google.ensure_google_oauth_configured()
        scopes, requested_capabilities, permission_pack = (
            platform_capabilities.resolve_permission_request(
                config["service"],
                permission_pack=body.permission_pack,
                requested_capabilities=body.requested_capabilities,
            )
        )
        if not scopes:
            raise HTTPException(
                status_code=400,
                detail={"message": "Unsupported Google permission request."},
            )
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
            requested_capabilities=requested_capabilities,
            permission_pack=permission_pack,
            instance_id=context.target.instance_id,
            ownership=context.target.ownership,
        )
        log.info(
            "oauth_authorize_created",
            user_id=user_id,
            provider="google",
            service=config["service"],
        )
        return {
            "authorizationUrl": google.authorization_url(
                state=state,
                code_verifier=code_verifier,
                service=config["service"],
                scopes=scopes,
            )
        }
    except google.GoogleOAuthConfigError as exc:
        log.error(
            "oauth_authorize_config_error",
            user_id=user_id,
            provider="google",
            service=config["service"],
            error=str(exc),
        )
        raise HTTPException(status_code=503, detail={"message": str(exc)}) from exc


@router.post("/connections/google/gmail/authorize")
async def authorize_google_gmail(request: Request, body: AuthorizeIn):
    return await _authorize_google_service(request, body, "gmail")


@router.post("/connections/google/sheets/authorize")
async def authorize_google_sheets(request: Request, body: AuthorizeIn):
    return await _authorize_google_service(request, body, "sheets")


async def _google_callback(body: GoogleCallbackIn, *, expected_service: str | None = None):
    log.info(
        "oauth_callback_started",
        provider="google",
        expected_service=expected_service,
    )
    state = await store.get_oauth_state(body.state)
    if state is None or state.provider != "google":
        log.warning(
            "oauth_callback_rejected",
            provider="google",
            reason="invalid_state",
            expected_service=expected_service,
        )
        raise HTTPException(status_code=400, detail={"message": "Invalid OAuth state."})
    if expected_service and state.service != expected_service:
        log.warning(
            "oauth_callback_rejected",
            provider="google",
            service=state.service,
            expected_service=expected_service,
            reason="service_mismatch",
        )
        raise HTTPException(status_code=400, detail={"message": "Invalid OAuth state."})
    if state.used:
        log.warning(
            "oauth_callback_rejected",
            provider="google",
            service=state.service,
            reason="state_used",
        )
        raise HTTPException(
            status_code=400, detail={"message": "OAuth state has already been used."}
        )
    if google.is_expired(state.expires_at):
        log.warning(
            "oauth_callback_rejected",
            provider="google",
            service=state.service,
            reason="state_expired",
        )
        raise HTTPException(status_code=400, detail={"message": "OAuth state has expired."})

    config = _google_connection_config(state.service)
    expected_instance_id = state.instance_id
    expected_ownership = state.ownership
    try:
        current_context = await resolver.resolve(state.user_id, request_id=f"oauth:{state.id}")
        current_client = await client_factory.for_request_context(current_context)
    except N8nProviderError as exc:
        raise _provider_http_error(exc) from exc
    if (
        (current_context.target.ownership == "customer_owned" and not expected_instance_id)
        or (expected_instance_id and current_context.target.instance_id != expected_instance_id)
        or (expected_ownership and current_context.target.ownership != expected_ownership)
    ):
        log.warning(
            "oauth_callback_rejected",
            provider="google",
            service=config["service"],
            reason="instance_changed",
            expected_instance_id=expected_instance_id,
            current_instance_id=current_context.target.instance_id,
        )
        raise HTTPException(
            status_code=409,
            detail={
                "code": "n8n_instance_changed",
                "message": "The active n8n instance changed during OAuth. Reconnect and try again.",
            },
        )
    await store.mark_oauth_state_used(state.id)

    try:
        token_response = await google.exchange_code(
            code=body.code,
            code_verifier=state.code_verifier,
        )
        log.info(
            "oauth_token_exchange_succeeded",
            provider="google",
            service=config["service"],
        )
    except httpx.HTTPStatusError as exc:
        log.warning(
            "oauth_token_exchange_failed",
            provider="google",
            service=config["service"],
            status_code=exc.response.status_code,
            error_type=type(exc).__name__,
        )
        raise _oauth_http_error(exc, "Google token exchange failed.") from exc
    except google.GoogleOAuthConfigError as exc:
        log.error(
            "oauth_token_exchange_config_error",
            provider="google",
            service=config["service"],
            error=str(exc),
        )
        raise HTTPException(status_code=503, detail={"message": str(exc)}) from exc

    access_token = str(token_response.get("access_token") or "")
    refresh_token = str(token_response.get("refresh_token") or "")
    if not access_token or not refresh_token:
        log.warning(
            "oauth_callback_missing_offline_token",
            provider="google",
            service=config["service"],
        )
        raise HTTPException(
            status_code=400,
            detail={"message": "Google did not return an offline refresh token. Please reconnect."},
        )

    try:
        userinfo = await google.fetch_userinfo(access_token)
        log.info(
            "oauth_userinfo_loaded",
            provider="google",
            service=config["service"],
        )
    except httpx.HTTPStatusError as exc:
        log.warning(
            "oauth_userinfo_failed",
            provider="google",
            service=config["service"],
            status_code=exc.response.status_code,
            error_type=type(exc).__name__,
        )
        raise _oauth_http_error(exc, "Could not read Google account profile.") from exc

    account_email = str(userinfo.get("email") or "")
    google_sub = str(userinfo.get("sub") or "")
    if not account_email or not google_sub:
        log.warning(
            "oauth_userinfo_missing_identity",
            provider="google",
            service=config["service"],
        )
        raise HTTPException(
            status_code=400,
            detail={"message": "Google account profile did not include email/sub."},
        )

    connection_id = config["connection_id"]
    credential_type = config["credential_type"]
    credential_name = f"{config['credential_prefix']} - {account_email} - Conduut"
    granted_scopes = google.scopes_from_token_response(
        token_response,
        default_scopes=config["scopes"],
    )
    capabilities = google.capabilities_for_scopes(granted_scopes)
    existing = await store.get_connection(
        state.user_id,
        connection_id,
        instance_id=current_context.target.instance_id,
    )
    permission_packs = platform_capabilities.permission_packs_for_scopes(granted_scopes)
    if state.permission_pack and state.permission_pack not in permission_packs:
        permission_packs.append(state.permission_pack)
    if existing:
        for pack in existing.permission_packs:
            if pack not in permission_packs:
                permission_packs.append(pack)
    credential_data = config["credential_data"](token_response)
    encrypted_refresh_token = ""
    direct_api_enabled = False
    if can_encrypt_connection_secrets():
        encrypted_refresh_token = encrypt_connection_secret(refresh_token)
        direct_api_enabled = True

    try:
        credential = await current_client.create_credential(
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
            scopes=granted_scopes,
            capabilities=capabilities,
            permission_packs=permission_packs,
            direct_api_enabled=direct_api_enabled,
            encrypted_refresh_token=encrypted_refresh_token,
            instance_id=current_context.target.instance_id,
        )
        log.info(
            "oauth_connection_saved",
            user_id=state.user_id,
            provider="google",
            service=config["service"],
            connection_id=connection_id,
            credential_type=credential_type,
            capability_count=len(capabilities),
        )
    except n8n_client.N8nApiError as exc:
        log.warning(
            "oauth_n8n_credential_failed",
            user_id=state.user_id,
            provider="google",
            service=config["service"],
            credential_type=credential_type,
            status_code=exc.status_code,
            error=exc.message,
        )
        raise HTTPException(status_code=exc.status_code, detail={"message": exc.message}) from exc
    except Exception as exc:
        if "credential" in locals():
            try:
                await current_client.delete_credential(credential.id)
                log.info(
                    "oauth_orphan_credential_deleted",
                    user_id=state.user_id,
                    provider="google",
                    service=config["service"],
                    credential_id=credential.id,
                )
            except Exception:
                pass
        log.error(
            "oauth_connection_save_failed",
            user_id=state.user_id,
            provider="google",
            service=config["service"],
            error_type=type(exc).__name__,
            error=str(exc),
            exc_info=True,
        )
        raise HTTPException(status_code=400, detail={"message": str(exc)}) from exc

    if existing and existing.n8n_credential_id != connection.n8n_credential_id:
        try:
            await current_client.delete_credential(existing.n8n_credential_id)
            log.info(
                "oauth_replaced_old_credential_deleted",
                user_id=state.user_id,
                provider="google",
                service=config["service"],
                connection_id=connection_id,
            )
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
    try:
        context, client = await _request_n8n(request, user_id)
    except N8nProviderError as exc:
        raise _provider_http_error(exc) from exc
    connection = await store.delete_connection(
        user_id,
        connection_id,
        instance_id=context.target.instance_id,
    )
    if connection is None:
        raise HTTPException(status_code=404, detail={"message": "Connection not found."})

    try:
        await client.delete_credential(connection.n8n_credential_id)
    except Exception:
        pass

    return {"success": True, "connectionId": connection_id}
