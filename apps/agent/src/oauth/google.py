"""Google OAuth broker helpers for Conduut-managed n8n credentials."""

import base64
import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlencode

import httpx

from src.config import settings

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://openidconnect.googleapis.com/v1/userinfo"
GMAIL_CONNECTION_SCOPES = [
    "openid",
    "email",
    "profile",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.readonly",
]

GMAIL_SEND_SCOPES = GMAIL_CONNECTION_SCOPES


class GoogleOAuthConfigError(RuntimeError):
    """Raised when Google OAuth cannot run with the current environment."""


def ensure_google_oauth_configured() -> None:
    if not settings.google_oauth_client_id or not settings.google_oauth_client_secret:
        raise GoogleOAuthConfigError("Google OAuth is not configured.")


def redirect_uri() -> str:
    return f"{settings.public_web_url.rstrip('/')}/api/oauth/google/callback"


def generate_state() -> str:
    return secrets.token_urlsafe(32)


def generate_code_verifier() -> str:
    return secrets.token_urlsafe(64)


def code_challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


def expires_at() -> str:
    ttl = max(settings.oauth_state_ttl_seconds, 60)
    return (datetime.now(timezone.utc) + timedelta(seconds=ttl)).isoformat()


def is_expired(value: str) -> bool:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return True
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed <= datetime.now(timezone.utc)


def safe_return_to(value: str | None) -> str:
    if not value or not value.startswith("/") or value.startswith("//"):
        return "/dashboard/connections"
    return value


def authorization_url(*, state: str, code_verifier: str) -> str:
    ensure_google_oauth_configured()
    params = {
        "client_id": settings.google_oauth_client_id,
        "redirect_uri": redirect_uri(),
        "response_type": "code",
        "scope": " ".join(GMAIL_CONNECTION_SCOPES),
        "access_type": "offline",
        "prompt": "consent",
        "include_granted_scopes": "true",
        "state": state,
        "code_challenge": code_challenge(code_verifier),
        "code_challenge_method": "S256",
    }
    return f"{GOOGLE_AUTH_URL}?{urlencode(params)}"


async def exchange_code(*, code: str, code_verifier: str) -> dict[str, Any]:
    ensure_google_oauth_configured()
    data = {
        "client_id": settings.google_oauth_client_id,
        "client_secret": settings.google_oauth_client_secret,
        "code": code,
        "code_verifier": code_verifier,
        "grant_type": "authorization_code",
        "redirect_uri": redirect_uri(),
    }
    async with httpx.AsyncClient(timeout=20.0) as client:
        response = await client.post(GOOGLE_TOKEN_URL, data=data)
    response.raise_for_status()
    return response.json()


async def fetch_userinfo(access_token: str) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=20.0) as client:
        response = await client.get(
            GOOGLE_USERINFO_URL,
            headers={"Authorization": f"Bearer {access_token}"},
        )
    response.raise_for_status()
    return response.json()


def n8n_oauth_token_data(token_response: dict[str, Any]) -> dict[str, Any]:
    access_token = str(token_response.get("access_token") or "")
    refresh_token = str(token_response.get("refresh_token") or "")
    token_type = str(token_response.get("token_type") or "Bearer")
    scope = str(token_response.get("scope") or " ".join(GMAIL_CONNECTION_SCOPES))
    expires_in = token_response.get("expires_in")

    data: dict[str, Any] = {
        "access_token": access_token,
        "accessToken": access_token,
        "refresh_token": refresh_token,
        "refreshToken": refresh_token,
        "token_type": token_type,
        "tokenType": token_type,
        "scope": scope,
    }
    if expires_in is not None:
        data["expires_in"] = expires_in
    return data


def n8n_gmail_credential_data(token_response: dict[str, Any]) -> dict[str, Any]:
    return {
        "serverUrl": "https://accounts.google.com",
        "clientId": settings.google_oauth_client_id,
        "clientSecret": settings.google_oauth_client_secret,
        "sendAdditionalBodyProperties": False,
        "additionalBodyProperties": {},
        "oauthTokenData": n8n_oauth_token_data(token_response),
    }
