import asyncio
from types import SimpleNamespace

import pytest

from src import store
from src.agent.schemas import (
    AgentDeps,
    PlatformActionPlan,
    WorkflowActionSpec,
    WorkflowPlan,
    WorkflowTriggerSpec,
)
from src.agent.tools.spec_compiler import create_workflow_from_plan_payload
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


@pytest.mark.asyncio
async def test_workflow_plan_provisions_spreadsheet_when_title_is_given(monkeypatch):
    schemas = {
        "n8n-nodes-base.webhook": {"type": "n8n-nodes-base.webhook", "typeVersion": 2.1},
        "n8n-nodes-base.gmail": {
            "type": "n8n-nodes-base.gmail",
            "typeVersion": 2.1,
        },
        "n8n-nodes-base.googleSheets": {
            "type": "n8n-nodes-base.googleSheets",
            "typeVersion": 4.7,
        },
        "n8n-nodes-base.set": {"type": "n8n-nodes-base.set", "typeVersion": 3.4},
    }
    created: dict = {}
    saved: dict = {}

    monkeypatch.setattr(
        "src.agent.tools.registry.get_node_schema",
        lambda node_type: schemas.get(node_type),
    )

    async def fake_provision(_deps, *, title: str, sheet_name: str | None, action_id: str):
        return {
            "action_id": action_id,
            "spreadsheet_id": "created_sheet",
            "spreadsheet_url": "https://sheet.test",
            "title": title,
            "sheet_name": sheet_name,
        }

    async def fake_create_workflow(name: str, nodes: list[dict], connections: dict):
        created["name"] = name
        created["nodes"] = nodes
        created["connections"] = connections
        return SimpleNamespace(id="wf_1", name=name, active=False)

    async def fake_get_workflow(_workflow_id: str):
        return {
            "id": "wf_1",
            "name": created["name"],
            "nodes": created["nodes"],
            "connections": created["connections"],
        }

    async def fake_save_workflow_metadata(
        user_id: str,
        workflow_id: str,
        input_schema: list[dict],
        resources: dict | None = None,
    ):
        saved["user_id"] = user_id
        saved["workflow_id"] = workflow_id
        saved["input_schema"] = input_schema
        saved["resources"] = resources

    async def fake_get_connection(_user_id: str, _connection_id: str):
        return None

    monkeypatch.setattr(
        "src.agent.tools.spec_compiler.provision_spreadsheet_for_workflow",
        fake_provision,
    )
    monkeypatch.setattr("src.agent.tools.n8n_client.create_workflow", fake_create_workflow)
    monkeypatch.setattr("src.agent.tools.n8n_client.get_workflow", fake_get_workflow)
    monkeypatch.setattr("src.agent.tools.store.save_workflow_metadata", fake_save_workflow_metadata)
    monkeypatch.setattr("src.agent.tools.store.get_connection", fake_get_connection)

    deps = AgentDeps("user_1", "conv_1", asyncio.Queue())
    result = await create_workflow_from_plan_payload(
        deps,
        "Send and log",
        WorkflowPlan(
            trigger=WorkflowTriggerSpec(kind="on_demand"),
            actions=[
                WorkflowActionSpec(
                    id="send",
                    action="gmail.send",
                    params={
                        "to": {"ref": "input.to"},
                        "subject": {"ref": "input.subject"},
                        "message": {"ref": "input.message"},
                    },
                ),
                WorkflowActionSpec(
                    id="log",
                    action="sheets.row.append",
                    after="send",
                    params={
                        "spreadsheet_title": "Sent Mail Log",
                        "sheet_name": "Log",
                        "columns": {
                            "To": {"ref": "input.to"},
                            "Subject": {"ref": "input.subject"},
                        },
                    },
                ),
            ],
        ),
    )

    append = next(node for node in created["nodes"] if node["name"] == "Google Sheets Append")
    assert result["id"] == "wf_1"
    assert append["parameters"]["documentId"]["value"] == "created_sheet"
    assert saved["resources"]["log.spreadsheet"]["spreadsheet_id"] == "created_sheet"
