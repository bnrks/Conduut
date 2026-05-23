"""Direct Google API clients for platform actions."""

from __future__ import annotations

import base64
from email.message import EmailMessage
from typing import Any
from urllib.parse import quote

import httpx
import structlog

from src import store
from src.config import settings
from src.oauth import google
from src.platforms.capabilities import (
    capability_requires_confirmation,
    capability_risk,
    connection_has_capability,
    permission_pack_for_capability,
)
from src.platforms.crypto import ConnectionSecretError, decrypt_connection_secret

log = structlog.get_logger()


class PlatformActionError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        status: str = "error",
        capability: str | None = None,
        permission_pack: str | None = None,
        risk: str | None = None,
    ):
        super().__init__(message)
        self.message = message
        self.status = status
        self.capability = capability
        self.permission_pack = permission_pack
        self.risk = risk


class MissingPlatformPermission(PlatformActionError):
    def __init__(self, capability: str):
        super().__init__(
            f"Missing required platform permission: {capability}",
            status="authorization_required",
            capability=capability,
            permission_pack=permission_pack_for_capability(capability),
            risk=capability_risk(capability),
        )


class PlatformConfirmationRequired(PlatformActionError):
    def __init__(self, capability: str):
        super().__init__(
            f"Explicit confirmation is required for {capability}.",
            status="confirmation_required",
            capability=capability,
            permission_pack=permission_pack_for_capability(capability),
            risk=capability_risk(capability),
        )


async def _refresh_access_token(refresh_token: str) -> str:
    data = {
        "client_id": settings.google_oauth_client_id,
        "client_secret": settings.google_oauth_client_secret,
        "refresh_token": refresh_token,
        "grant_type": "refresh_token",
    }
    async with httpx.AsyncClient(timeout=20.0) as client:
        response = await client.post(google.GOOGLE_TOKEN_URL, data=data)
    response.raise_for_status()
    payload = response.json()
    access_token = str(payload.get("access_token") or "")
    if not access_token:
        raise PlatformActionError("Google did not return an access token.")
    return access_token


async def _access_token_for_capability(
    user_id: str,
    connection_id: str,
    capability: str,
) -> tuple[str, store.AppConnection]:
    connection = await store.get_connection(user_id, connection_id)
    if not connection or connection.status != "connected":
        raise MissingPlatformPermission(capability)
    if not connection_has_capability(connection.capabilities, capability):
        raise MissingPlatformPermission(capability)
    if not connection.encrypted_refresh_token or not connection.direct_api_enabled:
        raise PlatformActionError(
            "This connection needs to be reconnected before direct platform actions can run.",
            status="reconnect_required",
            capability=capability,
            permission_pack=permission_pack_for_capability(capability),
            risk=capability_risk(capability),
        )
    try:
        refresh_token = decrypt_connection_secret(connection.encrypted_refresh_token)
    except ConnectionSecretError as exc:
        raise PlatformActionError(
            "This connection secret could not be used. Reconnect the account.",
            status="reconnect_required",
            capability=capability,
            permission_pack=permission_pack_for_capability(capability),
            risk=capability_risk(capability),
        ) from exc
    return await _refresh_access_token(refresh_token), connection


async def _google_request(
    method: str,
    url: str,
    *,
    access_token: str,
    json: dict[str, Any] | None = None,
    params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.request(
            method,
            url,
            headers={"Authorization": f"Bearer {access_token}"},
            json=json,
            params=params,
        )
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        log.warning(
            "google_platform_request_failed",
            method=method,
            url=url,
            status_code=exc.response.status_code,
        )
        raise PlatformActionError(f"Google API returned {exc.response.status_code}.") from exc
    if response.content:
        return response.json()
    return {}


def _encoded_message(to: str, subject: str, message: str) -> str:
    email = EmailMessage()
    email["To"] = to
    email["Subject"] = subject
    email.set_content(message)
    return base64.urlsafe_b64encode(email.as_bytes()).decode("ascii").rstrip("=")


def _sheets_values_url(spreadsheet_id: str, range: str, *, suffix: str = "") -> str:
    return (
        "https://sheets.googleapis.com/v4/spreadsheets/"
        f"{quote(spreadsheet_id)}/values/{quote(range, safe='!:$')}{suffix}"
    )


class GmailClient:
    connection_id = "google_gmail"

    def __init__(self, user_id: str):
        self.user_id = user_id

    async def _token(self, capability: str, *, confirmed: bool = False) -> str:
        if capability_requires_confirmation(capability) and not confirmed:
            raise PlatformConfirmationRequired(capability)
        token, _connection = await _access_token_for_capability(
            self.user_id,
            self.connection_id,
            capability,
        )
        return token

    async def send(self, *, to: str, subject: str, message: str) -> dict[str, Any]:
        token = await self._token("gmail.message.send")
        return await _google_request(
            "POST",
            "https://gmail.googleapis.com/gmail/v1/users/me/messages/send",
            access_token=token,
            json={"raw": _encoded_message(to, subject, message)},
        )

    async def search(self, *, query: str = "", limit: int = 10) -> dict[str, Any]:
        token = await self._token("gmail.message.read")
        return await _google_request(
            "GET",
            "https://gmail.googleapis.com/gmail/v1/users/me/messages",
            access_token=token,
            params={"q": query, "maxResults": max(1, min(limit, 25))},
        )

    async def get(self, *, message_id: str, format: str = "metadata") -> dict[str, Any]:
        token = await self._token("gmail.message.read")
        return await _google_request(
            "GET",
            f"https://gmail.googleapis.com/gmail/v1/users/me/messages/{quote(message_id)}",
            access_token=token,
            params={"format": format},
        )

    async def modify(
        self,
        *,
        message_id: str,
        add_labels: list[str] | None = None,
        remove_labels: list[str] | None = None,
    ) -> dict[str, Any]:
        token = await self._token("gmail.message.modify")
        return await _google_request(
            "POST",
            f"https://gmail.googleapis.com/gmail/v1/users/me/messages/{quote(message_id)}/modify",
            access_token=token,
            json={
                "addLabelIds": add_labels or [],
                "removeLabelIds": remove_labels or [],
            },
        )

    async def trash(self, *, message_id: str, confirmed: bool = False) -> dict[str, Any]:
        token = await self._token("gmail.message.trash", confirmed=confirmed)
        return await _google_request(
            "POST",
            f"https://gmail.googleapis.com/gmail/v1/users/me/messages/{quote(message_id)}/trash",
            access_token=token,
        )


class SheetsClient:
    connection_id = "google_sheets"

    def __init__(self, user_id: str):
        self.user_id = user_id

    async def _token(self, capability: str, *, confirmed: bool = False) -> str:
        if capability_requires_confirmation(capability) and not confirmed:
            raise PlatformConfirmationRequired(capability)
        token, _connection = await _access_token_for_capability(
            self.user_id,
            self.connection_id,
            capability,
        )
        return token

    async def create_spreadsheet(
        self,
        *,
        title: str,
        sheet_title: str | None = None,
    ) -> dict[str, Any]:
        token = await self._token("sheets.spreadsheet.create")
        body: dict[str, Any] = {"properties": {"title": title}}
        if sheet_title:
            body["sheets"] = [{"properties": {"title": sheet_title}}]
        return await _google_request(
            "POST",
            "https://sheets.googleapis.com/v4/spreadsheets",
            access_token=token,
            json=body,
        )

    async def add_sheet(
        self,
        *,
        spreadsheet_id: str,
        title: str,
    ) -> dict[str, Any]:
        token = await self._token("sheets.sheet.manage")
        return await _google_request(
            "POST",
            f"https://sheets.googleapis.com/v4/spreadsheets/{quote(spreadsheet_id)}:batchUpdate",
            access_token=token,
            json={"requests": [{"addSheet": {"properties": {"title": title}}}]},
        )

    async def delete_sheet(
        self,
        *,
        spreadsheet_id: str,
        sheet_id: int,
        confirmed: bool = False,
    ) -> dict[str, Any]:
        token = await self._token("sheets.range.clear", confirmed=confirmed)
        return await _google_request(
            "POST",
            f"https://sheets.googleapis.com/v4/spreadsheets/{quote(spreadsheet_id)}:batchUpdate",
            access_token=token,
            json={"requests": [{"deleteSheet": {"sheetId": sheet_id}}]},
        )

    async def read_range(self, *, spreadsheet_id: str, range: str) -> dict[str, Any]:
        token = await self._token("sheets.range.read")
        return await _google_request(
            "GET",
            _sheets_values_url(spreadsheet_id, range),
            access_token=token,
        )

    async def update_range(
        self,
        *,
        spreadsheet_id: str,
        range: str,
        values: list[list[Any]],
    ) -> dict[str, Any]:
        token = await self._token("sheets.range.update")
        return await _google_request(
            "PUT",
            _sheets_values_url(spreadsheet_id, range),
            access_token=token,
            params={"valueInputOption": "USER_ENTERED"},
            json={"values": values},
        )

    async def clear_range(
        self,
        *,
        spreadsheet_id: str,
        range: str,
        confirmed: bool = False,
    ) -> dict[str, Any]:
        token = await self._token("sheets.range.clear", confirmed=confirmed)
        return await _google_request(
            "POST",
            _sheets_values_url(spreadsheet_id, range, suffix=":clear"),
            access_token=token,
            json={},
        )

    async def append_row(
        self,
        *,
        spreadsheet_id: str,
        range: str,
        values: list[Any],
    ) -> dict[str, Any]:
        token = await self._token("sheets.row.append")
        return await _google_request(
            "POST",
            _sheets_values_url(spreadsheet_id, range, suffix=":append"),
            access_token=token,
            params={"valueInputOption": "USER_ENTERED", "insertDataOption": "INSERT_ROWS"},
            json={"values": [values]},
        )
