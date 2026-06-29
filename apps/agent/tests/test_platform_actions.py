import asyncio

import pytest

from src import store
from src.agent.schemas import (
    AgentDeps,
    PlatformActionPlan,
)
from src.config import settings
from src.platforms.actions import run_platform_action_payload
from src.platforms.capabilities import (
    capabilities_for_scopes,
    resolve_permission_request,
)
from src.platforms.crypto import decrypt_connection_secret, encrypt_connection_secret


def _connection(**overrides):
    data = {
        "id": "google_sheets",
        "provider": "google",
        "service": "sheets",
        "account_email": "user@example.com",
        "google_sub": "google_sub",
        "credential_type": "googleSheetsOAuth2Api",
        "n8n_credential_id": "cred_1",
        "n8n_credential_name": "Google Sheets - user@example.com - Conduut",
        "status": "connected",
        "scopes": [
            "https://www.googleapis.com/auth/drive.file",
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive.metadata",
        ],
        "created_at": "now",
        "updated_at": "now",
        "capabilities": [
            "sheets.spreadsheet.create",
            "sheets.sheet.manage",
            "sheets.range.read",
            "sheets.range.update",
            "sheets.range.clear",
            "sheets.row.append",
        ],
        "permission_packs": ["sheets.app_files"],
        "direct_api_enabled": True,
        "encrypted_refresh_token": "",
    }
    data.update(overrides)
    return store.AppConnection(**data)


def test_permission_pack_mapping_for_sheets_app_files():
    scopes, capabilities, pack = resolve_permission_request(
        "sheets",
        permission_pack="sheets.app_files",
    )

    assert pack == "sheets.app_files"
    assert "https://www.googleapis.com/auth/drive.file" in scopes
    assert "https://www.googleapis.com/auth/spreadsheets" in scopes
    assert "sheets.spreadsheet.create" in capabilities
    assert "sheets.row.append" in capabilities
    assert "sheets.row.append" in capabilities_for_scopes(scopes)


def test_connection_secret_encryption_roundtrip(monkeypatch):
    monkeypatch.setattr(settings, "connection_encryption_key", "dev-secret-key")

    encrypted = encrypt_connection_secret("refresh_token")

    assert encrypted != "refresh_token"
    assert decrypt_connection_secret(encrypted) == "refresh_token"


@pytest.mark.asyncio
async def test_platform_action_emits_oauth_prompt_when_permission_missing(monkeypatch):
    async def fake_get_connection(_user_id: str, _connection_id: str):
        return None

    async def fake_audit(*_args, **_kwargs):
        return None

    monkeypatch.setattr("src.platforms.google_clients.store.get_connection", fake_get_connection)
    monkeypatch.setattr("src.platforms.actions.store.save_platform_action_audit", fake_audit)
    deps = AgentDeps("user_1", "conv_1", asyncio.Queue())

    result = await run_platform_action_payload(
        deps,
        PlatformActionPlan(
            action="sheets.spreadsheet.create",
            params={"title": "Leads"},
        ),
    )

    assert result.success is False
    assert result.status == "authorization_required"
    assert deps.awaiting_user_input is True
    assert deps.attachments[0]["type"] == "oauth_prompt"
    assert deps.attachments[0]["data"]["requiredCapabilities"] == ["sheets.spreadsheet.create"]


@pytest.mark.asyncio
async def test_platform_action_emits_oauth_prompt_when_reconnect_required(monkeypatch):
    async def fake_get_connection(_user_id: str, _connection_id: str):
        return _connection(direct_api_enabled=False, encrypted_refresh_token="")

    async def fake_audit(*_args, **_kwargs):
        return None

    monkeypatch.setattr("src.platforms.google_clients.store.get_connection", fake_get_connection)
    monkeypatch.setattr("src.platforms.actions.store.save_platform_action_audit", fake_audit)
    deps = AgentDeps("user_1", "conv_1", asyncio.Queue())

    result = await run_platform_action_payload(
        deps,
        PlatformActionPlan(
            action="sheets.spreadsheet.create",
            params={"title": "Leads"},
        ),
    )

    assert result.success is False
    assert result.status == "reconnect_required"
    assert result.permissionPack == "sheets.app_files"
    assert deps.awaiting_user_input is True
    assert deps.attachments[0]["type"] == "oauth_prompt"
    assert deps.attachments[0]["data"]["requiredCapabilities"] == ["sheets.spreadsheet.create"]


@pytest.mark.asyncio
async def test_sheets_create_direct_action_uses_encrypted_refresh_token(monkeypatch):
    monkeypatch.setattr(settings, "connection_encryption_key", "dev-secret-key")
    encrypted = encrypt_connection_secret("refresh_token")

    async def fake_get_connection(_user_id: str, _connection_id: str):
        return _connection(encrypted_refresh_token=encrypted)

    async def fake_refresh(refresh_token: str):
        assert refresh_token == "refresh_token"
        return "access_token"

    captured: dict = {}

    async def fake_google_request(method: str, url: str, **kwargs):
        captured["method"] = method
        captured["url"] = url
        captured["kwargs"] = kwargs
        return {"spreadsheetId": "sheet_123", "spreadsheetUrl": "https://sheet.test"}

    async def fake_audit(*_args, **kwargs):
        captured["audit"] = kwargs

    monkeypatch.setattr("src.platforms.google_clients.store.get_connection", fake_get_connection)
    monkeypatch.setattr("src.platforms.google_clients._refresh_access_token", fake_refresh)
    monkeypatch.setattr("src.platforms.google_clients._google_request", fake_google_request)
    monkeypatch.setattr("src.platforms.actions.store.save_platform_action_audit", fake_audit)
    deps = AgentDeps("user_1", "conv_1", asyncio.Queue())

    result = await run_platform_action_payload(
        deps,
        PlatformActionPlan(
            action="sheets.spreadsheet.create",
            params={"title": "Leads", "sheet_name": "Incoming"},
        ),
    )

    assert result.success is True
    assert result.targetResource == "sheet_123"
    assert captured["method"] == "POST"
    assert captured["kwargs"]["access_token"] == "access_token"
    assert captured["audit"]["target_resource"] == "sheet_123"


@pytest.mark.asyncio
async def test_sheets_write_uses_spreadsheet_created_earlier_in_same_agent_turn(monkeypatch):
    async def fake_create_spreadsheet(_self, *, title: str, sheet_title: str | None = None):
        assert title == "Conduut Artifacts V1 Test"
        assert sheet_title == "Leads"
        return {
            "spreadsheetId": "sheet_123",
            "spreadsheetUrl": "https://sheet.test",
            "properties": {"title": title},
        }

    ensured: dict = {}

    async def fake_ensure_sheet(_self, *, spreadsheet_id: str, title: str):
        ensured["spreadsheet_id"] = spreadsheet_id
        ensured["title"] = title
        return {"spreadsheetId": spreadsheet_id, "alreadyExists": True}

    async def fake_update_range(_self, *, spreadsheet_id: str, range: str, values: list):
        assert spreadsheet_id == "sheet_123"
        assert range == "Leads!A1"
        return {
            "spreadsheetId": spreadsheet_id,
            "updatedRange": "Leads!A1:D4",
            "updatedRows": 4,
        }

    async def fake_audit(*_args, **_kwargs):
        return None

    monkeypatch.setattr(
        "src.platforms.actions.SheetsClient.create_spreadsheet",
        fake_create_spreadsheet,
    )
    monkeypatch.setattr("src.platforms.actions.SheetsClient.ensure_sheet", fake_ensure_sheet)
    monkeypatch.setattr("src.platforms.actions.SheetsClient.update_range", fake_update_range)
    monkeypatch.setattr("src.platforms.actions.store.save_platform_action_audit", fake_audit)
    deps = AgentDeps("user_1", "conv_1", asyncio.Queue())

    create_result = await run_platform_action_payload(
        deps,
        PlatformActionPlan(
            action="sheets.spreadsheet.create",
            params={"title": "Conduut Artifacts V1 Test", "sheet_name": "Leads"},
        ),
    )
    update_result = await run_platform_action_payload(
        deps,
        PlatformActionPlan(
            action="sheets.range.update",
            params={
                "values": [
                    ["Ad Soyad", "Email", "Kaynak", "Durum"],
                    ["Ayse Yilmaz", "ayse@example.com", "Gmail", "Yeni"],
                ],
            },
        ),
    )

    assert create_result.success is True
    assert update_result.success is True
    assert ensured == {"spreadsheet_id": "sheet_123", "title": "Leads"}
    assert deps.platform_resources["google_sheets"]["spreadsheet_id"] == "sheet_123"


@pytest.mark.asyncio
async def test_sheets_action_rejects_missing_spreadsheet_id_before_google_request(monkeypatch):
    async def fail_if_called(*_args, **_kwargs):
        raise AssertionError("Google Sheets client should not be called without spreadsheet_id")

    async def fake_audit(*_args, **_kwargs):
        return None

    monkeypatch.setattr("src.platforms.actions.SheetsClient.read_range", fail_if_called)
    monkeypatch.setattr("src.platforms.actions.store.save_platform_action_audit", fake_audit)
    deps = AgentDeps("user_1", "conv_1", asyncio.Queue())

    result = await run_platform_action_payload(
        deps,
        PlatformActionPlan(action="sheets.range.read", params={"range": "Leads!A1:D4"}),
    )

    assert result.success is False
    assert result.status == "missing_input"
    assert "spreadsheet_id" in (result.error or "")


@pytest.mark.asyncio
async def test_sheets_append_direct_action_emits_artifact_preview(monkeypatch):
    ensured: dict = {}

    async def fake_ensure_sheet(_self, *, spreadsheet_id: str, title: str):
        ensured["spreadsheet_id"] = spreadsheet_id
        ensured["title"] = title
        return {"spreadsheetId": spreadsheet_id, "alreadyExists": True}

    async def fake_append_row(_self, *, spreadsheet_id: str, range: str, values: list):
        assert range == "Log!A1"
        return {
            "spreadsheetId": spreadsheet_id,
            "updates": {"updatedRange": f"{range}!A2:B2", "updatedRows": 1},
        }

    async def fake_audit(*_args, **_kwargs):
        return None

    monkeypatch.setattr("src.platforms.actions.SheetsClient.ensure_sheet", fake_ensure_sheet)
    monkeypatch.setattr("src.platforms.actions.SheetsClient.append_row", fake_append_row)
    monkeypatch.setattr("src.platforms.actions.store.save_platform_action_audit", fake_audit)
    deps = AgentDeps("user_1", "conv_1", asyncio.Queue())

    result = await run_platform_action_payload(
        deps,
        PlatformActionPlan(
            action="sheets.row.append",
            params={
                "spreadsheet_id": "sheet_123",
                "sheet_name": "Log",
                "row": {"Email": "person@example.com", "Status": "Sent"},
            },
        ),
    )

    assert result.success is True
    assert result.artifacts[0].title == "Google Sheets row added"
    assert result.artifacts[0].url == "https://docs.google.com/spreadsheets/d/sheet_123/edit"
    assert result.artifacts[0].table is not None
    assert result.artifacts[0].table.columns == ["Email", "Status"]
    assert result.artifacts[0].table.rows == [{"Email": "person@example.com", "Status": "Sent"}]
    assert deps.attachments[0]["type"] == "artifact_preview"
    assert ensured == {"spreadsheet_id": "sheet_123", "title": "Log"}


@pytest.mark.asyncio
async def test_gmail_send_direct_action_emits_message_artifact_preview(monkeypatch):
    async def fake_send(_self, *, to: str, subject: str, message: str):
        assert to == "person@example.com"
        assert subject == "Hello"
        assert message == "Mail body"
        return {"id": "msg_123", "threadId": "thread_123", "labelIds": ["SENT"]}

    async def fake_audit(*_args, **_kwargs):
        return None

    monkeypatch.setattr("src.platforms.actions.GmailClient.send", fake_send)
    monkeypatch.setattr("src.platforms.actions.store.save_platform_action_audit", fake_audit)
    deps = AgentDeps("user_1", "conv_1", asyncio.Queue())

    result = await run_platform_action_payload(
        deps,
        PlatformActionPlan(
            action="gmail.message.send",
            params={
                "to": "person@example.com",
                "subject": "Hello",
                "message": "Mail body",
            },
        ),
    )

    assert result.success is True
    assert result.artifacts[0].service == "gmail"
    assert result.artifacts[0].title == "Gmail message sent"
    assert result.artifacts[0].url == "https://mail.google.com/mail/u/0/#all/msg_123"
    assert result.artifacts[0].message is not None
    assert result.artifacts[0].message.messageId == "msg_123"
    assert result.artifacts[0].message.to == ["person@example.com"]
    assert result.artifacts[0].message.subject == "Hello"
    assert result.artifacts[0].message.bodyPreview == "Mail body"
    assert deps.attachments[0]["type"] == "artifact_preview"
    assert deps.attachments[0]["data"]["service"] == "gmail"


@pytest.mark.asyncio
async def test_gmail_get_uses_latest_search_message_context(monkeypatch):
    async def fake_search(_self, *, query: str = "", limit: int = 10):
        assert query == "in:inbox"
        return {
            "messages": [{"id": "msg_latest", "threadId": "thread_latest"}],
            "resultSizeEstimate": 201,
        }

    async def fake_get(_self, *, message_id: str, format: str = "metadata"):
        assert message_id == "msg_latest"
        assert format == "metadata"
        return {
            "id": message_id,
            "threadId": "thread_latest",
            "snippet": "Latest mail snippet",
            "payload": {
                "headers": [
                    {"name": "From", "value": "sender@example.com"},
                    {"name": "Subject", "value": "Latest subject"},
                ]
            },
        }

    async def fake_audit(*_args, **_kwargs):
        return None

    monkeypatch.setattr("src.platforms.actions.GmailClient.search", fake_search)
    monkeypatch.setattr("src.platforms.actions.GmailClient.get", fake_get)
    monkeypatch.setattr("src.platforms.actions.store.save_platform_action_audit", fake_audit)
    deps = AgentDeps("user_1", "conv_1", asyncio.Queue())

    search_result = await run_platform_action_payload(
        deps,
        PlatformActionPlan(
            action="gmail.message.search",
            params={"query": "in:inbox", "limit": 1},
        ),
    )
    get_result = await run_platform_action_payload(
        deps,
        PlatformActionPlan(action="gmail.message.get", params={}),
    )

    assert search_result.success is True
    assert deps.platform_resources["gmail"]["message_id"] == "msg_latest"
    assert get_result.success is True
    assert get_result.targetResource == "msg_latest"
    assert get_result.artifacts[0].message is not None
    assert get_result.artifacts[0].message.subject == "Latest subject"
    assert get_result.artifacts[0].message.snippet == "Latest mail snippet"


@pytest.mark.asyncio
async def test_gmail_get_without_message_context_returns_missing_input(monkeypatch):
    async def fail_if_called(*_args, **_kwargs):
        raise AssertionError("Gmail get should not be called without a message_id.")

    async def fake_audit(*_args, **_kwargs):
        return None

    monkeypatch.setattr("src.platforms.actions.GmailClient.get", fail_if_called)
    monkeypatch.setattr("src.platforms.actions.store.save_platform_action_audit", fake_audit)
    deps = AgentDeps("user_1", "conv_1", asyncio.Queue())

    result = await run_platform_action_payload(
        deps,
        PlatformActionPlan(action="gmail.message.get", params={}),
    )

    assert result.success is False
    assert result.status == "missing_input"
    assert "message_id" in (result.error or "")


@pytest.mark.asyncio
async def test_sheets_sheet_create_direct_action_is_idempotent(monkeypatch):
    async def fake_ensure_sheet(_self, *, spreadsheet_id: str, title: str):
        assert spreadsheet_id == "sheet_123"
        assert title == "Leads"
        return {
            "spreadsheetId": spreadsheet_id,
            "alreadyExists": True,
            "sheet": {"properties": {"sheetId": 7, "title": title}},
        }

    async def fake_audit(*_args, **_kwargs):
        return None

    monkeypatch.setattr("src.platforms.actions.SheetsClient.ensure_sheet", fake_ensure_sheet)
    monkeypatch.setattr("src.platforms.actions.store.save_platform_action_audit", fake_audit)
    deps = AgentDeps("user_1", "conv_1", asyncio.Queue())

    result = await run_platform_action_payload(
        deps,
        PlatformActionPlan(
            action="sheets.sheet.create",
            params={"spreadsheet_id": "sheet_123", "sheet_name": "Leads"},
        ),
    )

    assert result.success is True
    assert result.data is not None
    assert result.data["alreadyExists"] is True
    assert result.artifacts[0].title == "Google Sheets tab created"


@pytest.mark.asyncio
async def test_sheets_range_update_ensures_named_sheet_and_uses_header_artifact(monkeypatch):
    ensured: dict = {}

    async def fake_ensure_sheet(_self, *, spreadsheet_id: str, title: str):
        ensured["spreadsheet_id"] = spreadsheet_id
        ensured["title"] = title
        return {"spreadsheetId": spreadsheet_id, "alreadyExists": True}

    async def fake_update_range(_self, *, spreadsheet_id: str, range: str, values: list):
        assert spreadsheet_id == "sheet_123"
        assert range == "Leads!A1"
        return {
            "spreadsheetId": spreadsheet_id,
            "updatedRange": "Leads!A1:D4",
            "updatedRows": 4,
        }

    async def fake_audit(*_args, **_kwargs):
        return None

    monkeypatch.setattr("src.platforms.actions.SheetsClient.ensure_sheet", fake_ensure_sheet)
    monkeypatch.setattr("src.platforms.actions.SheetsClient.update_range", fake_update_range)
    monkeypatch.setattr("src.platforms.actions.store.save_platform_action_audit", fake_audit)
    deps = AgentDeps("user_1", "conv_1", asyncio.Queue())

    result = await run_platform_action_payload(
        deps,
        PlatformActionPlan(
            action="sheets.range.update",
            params={
                "spreadsheet_id": "sheet_123",
                "sheet_name": "Leads",
                "values": [
                    ["Ad Soyad", "Email", "Kaynak", "Durum"],
                    ["Ayse Yilmaz", "ayse@example.com", "Gmail", "Yeni"],
                ],
            },
        ),
    )

    assert result.success is True
    assert ensured == {"spreadsheet_id": "sheet_123", "title": "Leads"}
    assert result.artifacts[0].table is not None
    assert result.artifacts[0].table.columns == ["Ad Soyad", "Email", "Kaynak", "Durum"]
    assert result.artifacts[0].table.rows == [
        {
            "Ad Soyad": "Ayse Yilmaz",
            "Email": "ayse@example.com",
            "Kaynak": "Gmail",
            "Durum": "Yeni",
        }
    ]


@pytest.mark.asyncio
async def test_sheets_read_direct_action_returns_table_artifact(monkeypatch):
    async def fake_read_range(_self, *, spreadsheet_id: str, range: str):
        assert spreadsheet_id == "sheet_123"
        assert range == "Log!A1:B3"
        return {
            "range": range,
            "values": [["Email", "Status"], ["person@example.com", "Sent"]],
        }

    async def fake_audit(*_args, **_kwargs):
        return None

    monkeypatch.setattr("src.platforms.actions.SheetsClient.read_range", fake_read_range)
    monkeypatch.setattr("src.platforms.actions.store.save_platform_action_audit", fake_audit)
    deps = AgentDeps("user_1", "conv_1", asyncio.Queue())

    result = await run_platform_action_payload(
        deps,
        PlatformActionPlan(
            action="sheets.range.read",
            params={"spreadsheet_id": "sheet_123", "range": "Log!A1:B3"},
        ),
    )

    assert result.success is True
    assert result.artifacts[0].title == "Google Sheets range read"
    assert result.artifacts[0].table is not None
    assert result.artifacts[0].table.columns == ["Email", "Status"]
    assert result.artifacts[0].table.rows == [{"Email": "person@example.com", "Status": "Sent"}]
