"""Readiness analysis and OAuth/credential auto-attach tests."""

import pytest
from n8n_registry.models import CredentialTypeInfo

from src import store
from src.agent.tools import analyze_workflow_readiness_payload
from src.agent.tools import readiness as readiness_module


@pytest.mark.asyncio
async def test_analyze_workflow_readiness_emits_credential_request(monkeypatch):
    monkeypatch.setattr(
        "src.agent.tools.registry.get_node_schema",
        lambda _node_type: {
            "credentials": ["demoApi"],
        },
    )

    async def fake_schema(_credential_type):
        return {
            "properties": {
                "apiKey": {
                    "type": "string",
                    "displayName": "API Key",
                }
            },
            "required": ["apiKey"],
        }

    monkeypatch.setattr("src.agent.tools.n8n_client.get_credential_schema", fake_schema)

    readiness = await analyze_workflow_readiness_payload(
        {
            "id": "wf_1",
            "name": "Demo",
            "nodes": [
                {
                    "name": "Demo Trigger",
                    "type": "n8n-nodes-base.demoTrigger",
                    "parameters": {},
                }
            ],
        }
    )

    assert readiness["ready"] is False
    assert readiness["testable"] is False
    attachment = readiness["missing_credentials"][0]
    assert attachment.type == "credential_request"
    assert attachment.data.workflowId == "wf_1"
    assert attachment.data.credentialType == "demoApi"
    assert attachment.data.fields[0].name == "apiKey"


@pytest.mark.asyncio
async def test_manual_trigger_workflow_is_testable_from_conduut(monkeypatch):
    monkeypatch.setattr("src.agent.tools.registry.get_node_schema", lambda _node_type: None)

    readiness = await analyze_workflow_readiness_payload(
        {
            "id": "wf_1",
            "nodes": [
                {
                    "name": "ManualTrigger",
                    "type": "n8n-nodes-base.manualTrigger",
                    "parameters": {},
                }
            ],
        }
    )

    assert readiness["ready"] is True
    assert readiness["testable"] is True
    assert readiness["manual_trigger_nodes"][0]["name"] == "ManualTrigger"


@pytest.mark.asyncio
async def test_webhook_default_none_auth_does_not_request_credentials(monkeypatch):
    monkeypatch.setattr(
        "src.agent.tools.registry.get_node_schema",
        lambda node_type: {
            "n8n-nodes-base.webhook": {
                "credentials": ["httpBasicAuth", "httpHeaderAuth", "jwtAuth"],
                "keyParameters": [
                    {
                        "name": "authentication",
                        "default": "none",
                    }
                ],
            },
            "n8n-nodes-base.respondToWebhook": {
                "credentials": ["jwtAuth"],
                "keyParameters": [],
            },
        }.get(node_type),
    )

    readiness = await analyze_workflow_readiness_payload(
        {
            "id": "wf_1",
            "name": "Webhook Workflow",
            "nodes": [
                {
                    "name": "Webhook",
                    "type": "n8n-nodes-base.webhook",
                    "parameters": {
                        "httpMethod": "POST",
                        "path": "test",
                    },
                },
                {
                    "name": "Respond to Webhook",
                    "type": "n8n-nodes-base.respondToWebhook",
                    "parameters": {},
                },
            ],
        }
    )

    assert readiness["ready"] is True
    assert readiness["testable"] is True
    assert readiness["missing_credentials"] == []


@pytest.mark.asyncio
async def test_webhook_basic_auth_requests_selected_credential(monkeypatch):
    monkeypatch.setattr(
        "src.agent.tools.registry.get_node_schema",
        lambda node_type: (
            {
                "credentials": ["httpBasicAuth", "httpHeaderAuth", "jwtAuth"],
                "keyParameters": [
                    {
                        "name": "authentication",
                        "default": "none",
                    }
                ],
            }
            if node_type == "n8n-nodes-base.webhook"
            else None
        ),
    )

    async def fake_schema(_credential_type):
        return {
            "properties": {
                "user": {"type": "string"},
                "password": {"type": "string"},
            },
            "required": ["user", "password"],
        }

    monkeypatch.setattr("src.agent.tools.n8n_client.get_credential_schema", fake_schema)

    readiness = await analyze_workflow_readiness_payload(
        {
            "id": "wf_1",
            "nodes": [
                {
                    "name": "Webhook",
                    "type": "n8n-nodes-base.webhook",
                    "parameters": {"authentication": "basicAuth"},
                }
            ],
        }
    )

    assert readiness["ready"] is False
    attachment = readiness["missing_credentials"][0]
    assert attachment.data.credentialType == "httpBasicAuth"


@pytest.mark.asyncio
async def test_gmail_send_readiness_auto_attaches_existing_connection(monkeypatch):
    monkeypatch.setattr(
        "src.agent.tools.registry.get_node_schema",
        lambda node_type: (
            {"credentials": ["gmailOAuth2"]} if node_type == "n8n-nodes-base.gmail" else None
        ),
    )

    async def fake_get_connection(user_id: str, connection_id: str):
        assert user_id == "user_1"
        assert connection_id == "google_gmail"
        return store.AppConnection(
            id="google_gmail",
            provider="google",
            service="gmail",
            account_email="user@example.com",
            google_sub="google_sub",
            credential_type="gmailOAuth2",
            n8n_credential_id="cred_1",
            n8n_credential_name="Google Gmail - user@example.com - Conduut",
            status="connected",
            scopes=["https://www.googleapis.com/auth/gmail.send"],
            created_at="now",
            updated_at="now",
        )

    attached: dict[str, str] = {}

    async def fake_attach(workflow_id, node_name, credential_type, credential_id, credential_name):
        attached.update(
            {
                "workflow_id": workflow_id,
                "node_name": node_name,
                "credential_type": credential_type,
                "credential_id": credential_id,
                "credential_name": credential_name,
            }
        )
        return {}

    monkeypatch.setattr("src.agent.tools.store.get_connection", fake_get_connection)
    monkeypatch.setattr(
        "src.agent.tools.n8n_client.attach_credential_to_workflow",
        fake_attach,
    )

    workflow = {
        "id": "wf_1",
        "name": "Send mail",
        "nodes": [
            {
                "name": "Gmail",
                "type": "n8n-nodes-base.gmail",
                "parameters": {"resource": "message", "operation": "send"},
            }
        ],
    }

    readiness = await analyze_workflow_readiness_payload(workflow, user_id="user_1")

    assert readiness["ready"] is True
    assert readiness["missing_credentials"] == []
    assert attached["workflow_id"] == "wf_1"
    assert attached["node_name"] == "Gmail"
    assert workflow["nodes"][0]["credentials"]["gmailOAuth2"]["id"] == "cred_1"


@pytest.mark.asyncio
async def test_gmail_send_readiness_replaces_stale_existing_credential(monkeypatch):
    monkeypatch.setattr(
        "src.agent.tools.registry.get_node_schema",
        lambda node_type: (
            {"credentials": ["gmailOAuth2"]} if node_type == "n8n-nodes-base.gmail" else None
        ),
    )

    async def fake_get_connection(_user_id: str, _connection_id: str):
        return store.AppConnection(
            id="google_gmail",
            provider="google",
            service="gmail",
            account_email="user@example.com",
            google_sub="google_sub",
            credential_type="gmailOAuth2",
            n8n_credential_id="fresh_cred",
            n8n_credential_name="Google Gmail - user@example.com - Conduut",
            status="connected",
            scopes=["https://www.googleapis.com/auth/gmail.send"],
            created_at="now",
            updated_at="now",
        )

    attached: dict[str, str] = {}

    async def fake_attach(workflow_id, node_name, credential_type, credential_id, credential_name):
        attached.update(
            {
                "workflow_id": workflow_id,
                "node_name": node_name,
                "credential_type": credential_type,
                "credential_id": credential_id,
                "credential_name": credential_name,
            }
        )
        return {}

    monkeypatch.setattr("src.agent.tools.store.get_connection", fake_get_connection)
    monkeypatch.setattr(
        "src.agent.tools.n8n_client.attach_credential_to_workflow",
        fake_attach,
    )

    workflow = {
        "id": "wf_1",
        "name": "Send mail",
        "nodes": [
            {
                "name": "Gmail",
                "type": "n8n-nodes-base.gmail",
                "parameters": {"resource": "message", "operation": "send"},
                "credentials": {
                    "gmailOAuth2": {
                        "id": "deleted_cred",
                        "name": "Deleted Gmail credential",
                    }
                },
            }
        ],
    }

    readiness = await analyze_workflow_readiness_payload(workflow, user_id="user_1")

    assert readiness["ready"] is True
    assert readiness["missing_credentials"] == []
    assert attached["credential_id"] == "fresh_cred"
    assert workflow["nodes"][0]["credentials"]["gmailOAuth2"]["id"] == "fresh_cred"


@pytest.mark.asyncio
async def test_managed_connection_same_credential_is_noop(monkeypatch):
    monkeypatch.setattr(
        "src.agent.tools.registry.get_node_schema",
        lambda node_type: (
            {"credentials": ["gmailOAuth2"]} if node_type == "n8n-nodes-base.gmail" else None
        ),
    )

    async def fake_get_connection(_user_id: str, _connection_id: str):
        return store.AppConnection(
            id="google_gmail",
            provider="google",
            service="gmail",
            account_email="user@example.com",
            google_sub="google_sub",
            credential_type="gmailOAuth2",
            n8n_credential_id="cred_1",
            n8n_credential_name="Google Gmail - user@example.com - Conduut",
            status="connected",
            scopes=["https://www.googleapis.com/auth/gmail.send"],
            created_at="now",
            updated_at="now",
        )

    async def fail_attach(*_args, **_kwargs):
        raise AssertionError("the same managed credential must not be attached again")

    mutations: list[str] = []
    monkeypatch.setattr("src.agent.tools.store.get_connection", fake_get_connection)
    monkeypatch.setattr(
        "src.agent.tools.n8n_client.attach_credential_to_workflow",
        fail_attach,
    )
    workflow = {
        "id": "wf_1",
        "name": "Send mail",
        "nodes": [
            {
                "name": "Gmail",
                "type": "n8n-nodes-base.gmail",
                "parameters": {"resource": "message", "operation": "send"},
                "credentials": {"gmailOAuth2": {"id": "cred_1", "name": "An older display name"}},
            }
        ],
    }

    readiness = await analyze_workflow_readiness_payload(
        workflow,
        user_id="user_1",
        before_mutation=lambda: mutations.append("mutation"),
    )

    assert readiness["ready"] is True
    assert readiness["missing_credentials"] == []
    assert mutations == []


@pytest.mark.asyncio
async def test_managed_connection_different_credential_marks_mutation_before_attach(monkeypatch):
    node = {
        "name": "Gmail",
        "type": "n8n-nodes-base.gmail",
        "parameters": {"resource": "message", "operation": "send"},
        "credentials": {"gmailOAuth2": {"id": "stale_cred", "name": "Stale"}},
    }

    async def fake_get_connection(_user_id: str, _connection_id: str):
        return store.AppConnection(
            id="google_gmail",
            provider="google",
            service="gmail",
            account_email="user@example.com",
            google_sub="google_sub",
            credential_type="gmailOAuth2",
            n8n_credential_id="fresh_cred",
            n8n_credential_name="Fresh",
            status="connected",
            scopes=["https://www.googleapis.com/auth/gmail.send"],
            created_at="now",
            updated_at="now",
        )

    calls: list[str] = []

    async def fake_attach(*_args, **_kwargs):
        calls.append("attach")
        return {}

    monkeypatch.setattr("src.agent.tools.store.get_connection", fake_get_connection)
    monkeypatch.setattr(
        "src.agent.tools.n8n_client.attach_credential_to_workflow",
        fake_attach,
    )

    attached = await readiness_module._attach_managed_connection_if_available(
        "user_1",
        "wf_1",
        node,
        "gmailOAuth2",
        lambda: calls.append("before_mutation"),
    )

    assert attached is True
    assert calls == ["before_mutation", "attach"]
    assert node["credentials"]["gmailOAuth2"]["id"] == "fresh_cred"


@pytest.mark.asyncio
async def test_gmail_create_operation_auto_attaches_existing_connection(monkeypatch):
    monkeypatch.setattr(
        "src.agent.tools.registry.get_node_schema",
        lambda node_type: (
            {"credentials": ["gmailOAuth2"]} if node_type == "n8n-nodes-base.gmail" else None
        ),
    )

    async def fake_get_connection(_user_id: str, _connection_id: str):
        return store.AppConnection(
            id="google_gmail",
            provider="google",
            service="gmail",
            account_email="user@example.com",
            google_sub="google_sub",
            credential_type="gmailOAuth2",
            n8n_credential_id="cred_1",
            n8n_credential_name="Google Gmail - user@example.com - Conduut",
            status="connected",
            scopes=["https://www.googleapis.com/auth/gmail.send"],
            created_at="now",
            updated_at="now",
        )

    attached: dict[str, str] = {}

    async def fake_attach(workflow_id, node_name, credential_type, credential_id, credential_name):
        attached["credential_id"] = credential_id
        return {}

    monkeypatch.setattr("src.agent.tools.store.get_connection", fake_get_connection)
    monkeypatch.setattr(
        "src.agent.tools.n8n_client.attach_credential_to_workflow",
        fake_attach,
    )

    readiness = await analyze_workflow_readiness_payload(
        {
            "id": "wf_1",
            "name": "Send mail",
            "nodes": [
                {
                    "name": "Gmail",
                    "type": "n8n-nodes-base.gmail",
                    "parameters": {"resource": "message", "operation": "create"},
                }
            ],
        },
        user_id="user_1",
    )

    assert readiness["ready"] is True
    assert readiness["missing_credentials"] == []
    assert attached["credential_id"] == "cred_1"


@pytest.mark.asyncio
async def test_gmail_send_readiness_emits_oauth_prompt_without_connection(monkeypatch):
    monkeypatch.setattr(
        "src.agent.tools.registry.get_node_schema",
        lambda node_type: (
            {"credentials": ["gmailOAuth2"]} if node_type == "n8n-nodes-base.gmail" else None
        ),
    )

    async def fake_get_connection(_user_id: str, _connection_id: str):
        return None

    async def fail_attach(*_args, **_kwargs):
        raise AssertionError("attach should not run without a connection")

    monkeypatch.setattr("src.agent.tools.store.get_connection", fake_get_connection)
    monkeypatch.setattr(
        "src.agent.tools.n8n_client.attach_credential_to_workflow",
        fail_attach,
    )

    readiness = await analyze_workflow_readiness_payload(
        {
            "id": "wf_1",
            "name": "Send mail",
            "nodes": [
                {
                    "name": "Gmail",
                    "type": "n8n-nodes-base.gmail",
                    "parameters": {"resource": "message", "operation": "send"},
                }
            ],
        },
        user_id="user_1",
    )

    assert readiness["ready"] is False
    attachment = readiness["missing_credentials"][0]
    assert attachment.type == "oauth_prompt"
    assert attachment.data.service == "Google Gmail"
    assert attachment.data.authorizePath == "/api/oauth/google/authorize?service=gmail"


@pytest.mark.asyncio
async def test_gmail_trigger_readiness_auto_attaches_connected_read_connection(monkeypatch):
    monkeypatch.setattr(
        "src.agent.tools.registry.get_node_schema",
        lambda node_type: (
            {"credentials": ["gmailOAuth2"]} if node_type == "n8n-nodes-base.gmailTrigger" else None
        ),
    )

    async def fake_get_connection(user_id: str, connection_id: str):
        assert user_id == "user_1"
        assert connection_id == "google_gmail"
        return store.AppConnection(
            id="google_gmail",
            provider="google",
            service="gmail",
            account_email="user@example.com",
            google_sub="google_sub",
            credential_type="gmailOAuth2",
            n8n_credential_id="gmail_read_cred",
            n8n_credential_name="Google Gmail - user@example.com - Conduut",
            status="connected",
            scopes=["https://www.googleapis.com/auth/gmail.readonly"],
            created_at="now",
            updated_at="now",
        )

    attached: dict[str, str] = {}

    async def fake_attach(workflow_id, node_name, credential_type, credential_id, credential_name):
        attached.update(
            {
                "workflow_id": workflow_id,
                "node_name": node_name,
                "credential_type": credential_type,
                "credential_id": credential_id,
                "credential_name": credential_name,
            }
        )
        return {}

    monkeypatch.setattr("src.agent.tools.store.get_connection", fake_get_connection)
    monkeypatch.setattr(
        "src.agent.tools.n8n_client.attach_credential_to_workflow",
        fake_attach,
    )

    workflow = {
        "id": "wf_trigger",
        "name": "Log incoming mail",
        "nodes": [
            {
                "name": "Gmail Trigger",
                "type": "n8n-nodes-base.gmailTrigger",
                "parameters": {"pollTimes": {"item": [{"mode": "everyMinute"}]}},
            }
        ],
    }

    readiness = await analyze_workflow_readiness_payload(workflow, user_id="user_1")

    assert readiness["ready"] is True
    assert readiness["missing_credentials"] == []
    assert attached["credential_id"] == "gmail_read_cred"
    assert workflow["nodes"][0]["credentials"]["gmailOAuth2"]["id"] == "gmail_read_cred"


@pytest.mark.asyncio
async def test_gmail_trigger_readiness_emits_oauth_prompt_without_connection(monkeypatch):
    monkeypatch.setattr(
        "src.agent.tools.registry.get_node_schema",
        lambda node_type: (
            {"credentials": ["gmailOAuth2"]} if node_type == "n8n-nodes-base.gmailTrigger" else None
        ),
    )

    async def fake_get_connection(_user_id: str, _connection_id: str):
        return None

    async def fail_schema(*_args, **_kwargs):
        raise AssertionError("managed Gmail OAuth must not load a generic credential form")

    monkeypatch.setattr("src.agent.tools.store.get_connection", fake_get_connection)
    monkeypatch.setattr("src.agent.tools.n8n_client.get_credential_schema", fail_schema)

    readiness = await analyze_workflow_readiness_payload(
        {
            "id": "wf_trigger",
            "name": "Log incoming mail",
            "nodes": [
                {
                    "name": "Gmail Trigger",
                    "type": "n8n-nodes-base.gmailTrigger",
                    "parameters": {},
                }
            ],
        },
        user_id="user_1",
    )

    assert readiness["ready"] is False
    attachment = readiness["missing_credentials"][0]
    assert attachment.type == "oauth_prompt"
    assert attachment.data.service == "Google Gmail"
    assert attachment.data.authorizePath == "/api/oauth/google/authorize?service=gmail"


@pytest.mark.asyncio
async def test_unknown_oauth_never_emits_generic_credential_fields(monkeypatch):
    monkeypatch.setattr(
        "src.agent.tools.registry.get_node_schema",
        lambda _node_type: {"credentials": ["slackOAuth2Api"]},
    )
    monkeypatch.setattr(
        "src.agent.tools.registry.get_credential_definition",
        lambda _credential_type: CredentialTypeInfo(
            name="slackOAuth2Api",
            display_name="Slack OAuth2",
            is_oauth=True,
        ),
    )

    async def fail_schema(*_args, **_kwargs):
        raise AssertionError("OAuth credentials must not expose serverUrl or client secrets")

    async def no_workflows():
        return []

    monkeypatch.setattr("src.agent.tools.n8n_client.get_credential_schema", fail_schema)
    monkeypatch.setattr("src.agent.tools.n8n_client.list_workflows_raw", no_workflows)

    readiness = await analyze_workflow_readiness_payload(
        {
            "id": "wf_oauth",
            "name": "Slack workflow",
            "nodes": [
                {
                    "name": "Slack",
                    "type": "n8n-nodes-base.slack",
                    "parameters": {"authentication": "oAuth2"},
                }
            ],
        }
    )

    assert readiness["ready"] is False
    attachment = readiness["missing_credentials"][0]
    assert attachment.type == "user_input_request"
    assert attachment.data.missingFields == []
    assert "Connections" in attachment.data.question
    assert "serverUrl" not in attachment.data.question


@pytest.mark.asyncio
async def test_gmail_read_readiness_requires_read_capability(monkeypatch):
    monkeypatch.setattr(
        "src.agent.tools.registry.get_node_schema",
        lambda node_type: (
            {"credentials": ["gmailOAuth2"]} if node_type == "n8n-nodes-base.gmail" else None
        ),
    )

    async def fake_get_connection(_user_id: str, _connection_id: str):
        return store.AppConnection(
            id="google_gmail",
            provider="google",
            service="gmail",
            account_email="user@example.com",
            google_sub="google_sub",
            credential_type="gmailOAuth2",
            n8n_credential_id="cred_1",
            n8n_credential_name="Google Gmail - user@example.com - Conduut",
            status="connected",
            scopes=["https://www.googleapis.com/auth/gmail.send"],
            capabilities=["google.gmail.send"],
            created_at="now",
            updated_at="now",
        )

    async def fail_attach(*_args, **_kwargs):
        raise AssertionError("read capability is required before attach")

    monkeypatch.setattr("src.agent.tools.store.get_connection", fake_get_connection)
    monkeypatch.setattr(
        "src.agent.tools.n8n_client.attach_credential_to_workflow",
        fail_attach,
    )

    readiness = await analyze_workflow_readiness_payload(
        {
            "id": "wf_1",
            "name": "Read mail",
            "nodes": [
                {
                    "name": "Gmail",
                    "type": "n8n-nodes-base.gmail",
                    "parameters": {"resource": "message", "operation": "get"},
                }
            ],
        },
        user_id="user_1",
    )

    assert readiness["ready"] is False
    attachment = readiness["missing_credentials"][0]
    assert attachment.type == "oauth_prompt"
    assert attachment.data.authorizePath == "/api/oauth/google/authorize?service=gmail"


@pytest.mark.asyncio
async def test_google_sheets_readiness_auto_attaches_existing_connection(monkeypatch):
    monkeypatch.setattr(
        "src.agent.tools.registry.get_node_schema",
        lambda node_type: (
            {"credentials": ["googleSheetsOAuth2Api"]}
            if node_type == "n8n-nodes-base.googleSheets"
            else None
        ),
    )

    async def fake_get_connection(user_id: str, connection_id: str):
        assert user_id == "user_1"
        assert connection_id == "google_sheets"
        return store.AppConnection(
            id="google_sheets",
            provider="google",
            service="sheets",
            account_email="user@example.com",
            google_sub="google_sub",
            credential_type="googleSheetsOAuth2Api",
            n8n_credential_id="cred_sheets",
            n8n_credential_name="Google Sheets - user@example.com - Conduut",
            status="connected",
            scopes=["https://www.googleapis.com/auth/spreadsheets"],
            created_at="now",
            updated_at="now",
        )

    attached: dict[str, str] = {}

    async def fake_attach(workflow_id, node_name, credential_type, credential_id, credential_name):
        attached.update(
            {
                "workflow_id": workflow_id,
                "node_name": node_name,
                "credential_type": credential_type,
                "credential_id": credential_id,
                "credential_name": credential_name,
            }
        )
        return {}

    monkeypatch.setattr("src.agent.tools.store.get_connection", fake_get_connection)
    monkeypatch.setattr(
        "src.agent.tools.n8n_client.attach_credential_to_workflow",
        fake_attach,
    )

    workflow = {
        "id": "wf_1",
        "name": "Read leads",
        "nodes": [
            {
                "name": "Google Sheets",
                "type": "n8n-nodes-base.googleSheets",
                "parameters": {"authentication": "oAuth2", "operation": "read"},
            }
        ],
    }

    readiness = await analyze_workflow_readiness_payload(workflow, user_id="user_1")

    assert readiness["ready"] is True
    assert readiness["missing_credentials"] == []
    assert attached["workflow_id"] == "wf_1"
    assert attached["node_name"] == "Google Sheets"
    assert attached["credential_type"] == "googleSheetsOAuth2Api"
    assert workflow["nodes"][0]["credentials"]["googleSheetsOAuth2Api"]["id"] == "cred_sheets"


@pytest.mark.asyncio
async def test_google_sheets_readiness_emits_oauth_prompt_without_connection(monkeypatch):
    monkeypatch.setattr(
        "src.agent.tools.registry.get_node_schema",
        lambda node_type: (
            {"credentials": ["googleSheetsOAuth2Api"]}
            if node_type == "n8n-nodes-base.googleSheets"
            else None
        ),
    )

    async def fake_get_connection(_user_id: str, _connection_id: str):
        return None

    async def fail_attach(*_args, **_kwargs):
        raise AssertionError("attach should not run without a connection")

    monkeypatch.setattr("src.agent.tools.store.get_connection", fake_get_connection)
    monkeypatch.setattr(
        "src.agent.tools.n8n_client.attach_credential_to_workflow",
        fail_attach,
    )

    readiness = await analyze_workflow_readiness_payload(
        {
            "id": "wf_1",
            "name": "Read leads",
            "nodes": [
                {
                    "name": "Google Sheets",
                    "type": "n8n-nodes-base.googleSheets",
                    "parameters": {"authentication": "oAuth2", "operation": "read"},
                }
            ],
        },
        user_id="user_1",
    )

    assert readiness["ready"] is False
    attachment = readiness["missing_credentials"][0]
    assert attachment.type == "oauth_prompt"
    assert attachment.data.service == "Google Sheets"
    assert attachment.data.authorizePath == "/api/oauth/google/authorize?service=sheets"


@pytest.mark.asyncio
async def test_google_sheets_write_readiness_requires_write_capability(monkeypatch):
    monkeypatch.setattr(
        "src.agent.tools.registry.get_node_schema",
        lambda node_type: (
            {"credentials": ["googleSheetsOAuth2Api"]}
            if node_type == "n8n-nodes-base.googleSheets"
            else None
        ),
    )

    async def fake_get_connection(_user_id: str, _connection_id: str):
        return store.AppConnection(
            id="google_sheets",
            provider="google",
            service="sheets",
            account_email="user@example.com",
            google_sub="google_sub",
            credential_type="googleSheetsOAuth2Api",
            n8n_credential_id="cred_sheets",
            n8n_credential_name="Google Sheets - user@example.com - Conduut",
            status="connected",
            scopes=["https://www.googleapis.com/auth/spreadsheets"],
            capabilities=["google.sheets.read"],
            created_at="now",
            updated_at="now",
        )

    async def fail_attach(*_args, **_kwargs):
        raise AssertionError("write capability is required before attach")

    monkeypatch.setattr("src.agent.tools.store.get_connection", fake_get_connection)
    monkeypatch.setattr(
        "src.agent.tools.n8n_client.attach_credential_to_workflow",
        fail_attach,
    )

    readiness = await analyze_workflow_readiness_payload(
        {
            "id": "wf_1",
            "name": "Append row",
            "nodes": [
                {
                    "name": "Google Sheets",
                    "type": "n8n-nodes-base.googleSheets",
                    "parameters": {"authentication": "oAuth2", "operation": "append"},
                }
            ],
        },
        user_id="user_1",
    )

    assert readiness["ready"] is False
    attachment = readiness["missing_credentials"][0]
    assert attachment.type == "oauth_prompt"
    assert attachment.data.authorizePath == "/api/oauth/google/authorize?service=sheets"


@pytest.mark.asyncio
async def test_gmail_read_operation_auto_attaches_existing_connection(monkeypatch):
    monkeypatch.setattr(
        "src.agent.tools.registry.get_node_schema",
        lambda node_type: (
            {"credentials": ["gmailOAuth2"]} if node_type == "n8n-nodes-base.gmail" else None
        ),
    )

    async def fake_get_connection(_user_id: str, _connection_id: str):
        return store.AppConnection(
            id="google_gmail",
            provider="google",
            service="gmail",
            account_email="user@example.com",
            google_sub="google_sub",
            credential_type="gmailOAuth2",
            n8n_credential_id="cred_1",
            n8n_credential_name="Google Gmail - user@example.com - Conduut",
            status="connected",
            scopes=["https://www.googleapis.com/auth/gmail.readonly"],
            created_at="now",
            updated_at="now",
        )

    attached: dict[str, str] = {}

    async def fake_attach(workflow_id, node_name, credential_type, credential_id, credential_name):
        attached.update(
            {
                "workflow_id": workflow_id,
                "node_name": node_name,
                "credential_type": credential_type,
                "credential_id": credential_id,
                "credential_name": credential_name,
            }
        )
        return {}

    monkeypatch.setattr("src.agent.tools.store.get_connection", fake_get_connection)
    monkeypatch.setattr(
        "src.agent.tools.n8n_client.attach_credential_to_workflow",
        fake_attach,
    )

    readiness = await analyze_workflow_readiness_payload(
        {
            "id": "wf_1",
            "name": "Read mail",
            "nodes": [
                {
                    "name": "Gmail",
                    "type": "n8n-nodes-base.gmail",
                    "parameters": {"resource": "message", "operation": "get"},
                }
            ],
        },
        user_id="user_1",
    )

    assert readiness["ready"] is True
    assert readiness["missing_credentials"] == []
    assert attached["credential_id"] == "cred_1"


@pytest.mark.asyncio
async def test_gmail_modify_operation_does_not_auto_attach_read_send_connection(monkeypatch):
    monkeypatch.setattr(
        "src.agent.tools.registry.get_node_schema",
        lambda node_type: (
            {"credentials": ["gmailOAuth2"]} if node_type == "n8n-nodes-base.gmail" else None
        ),
    )

    async def fail_get_connection(*_args, **_kwargs):
        raise AssertionError("gmail modify should not use managed read/send connection")

    async def fail_attach(*_args, **_kwargs):
        raise AssertionError("gmail modify should not attach managed read/send connection")

    async def fake_schema(_credential_type: str):
        return {
            "properties": {"clientId": {"type": "string", "displayName": "Client ID"}},
            "required": ["clientId"],
        }

    async def fake_list_custom_credentials(_user_id: str):
        return []

    monkeypatch.setattr("src.agent.tools.store.get_connection", fail_get_connection)
    monkeypatch.setattr(
        "src.agent.tools.store.list_custom_credentials",
        fake_list_custom_credentials,
    )
    monkeypatch.setattr(
        "src.agent.tools.n8n_client.attach_credential_to_workflow",
        fail_attach,
    )
    monkeypatch.setattr("src.agent.tools.n8n_client.get_credential_schema", fake_schema)

    readiness = await analyze_workflow_readiness_payload(
        {
            "id": "wf_1",
            "name": "Read mail",
            "nodes": [
                {
                    "name": "Gmail",
                    "type": "n8n-nodes-base.gmail",
                    "parameters": {"resource": "message", "operation": "markAsRead"},
                }
            ],
        },
        user_id="user_1",
    )

    assert readiness["ready"] is False
    attachment = readiness["missing_credentials"][0]
    assert attachment.type == "user_input_request"
    assert "gmailOAuth2" in (attachment.data.reason or "")
