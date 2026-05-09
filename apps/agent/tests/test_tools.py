import httpx
import pytest
from pydantic_ai import ModelRetry

from src import store
from src.agent.schemas import WorkflowNode
from src.agent.tools import (
    _apply_runtime_inputs_to_nodes,
    _infer_runtime_input_schema,
    _summarize_execution,
    _validated_runtime_workflow,
    _validated_workflow,
    _validated_workflow_input,
    _workflow_with_conduut_webhook_trigger,
    analyze_workflow_readiness_payload,
    run_workflow_with_input,
)


def test_validated_workflow_canonicalizes_nodes_and_connections(monkeypatch):
    schemas = {
        "manualTrigger": {
            "type": "n8n-nodes-base.manualTrigger",
            "typeVersion": 1,
            "isTrigger": True,
        },
        "set": {
            "type": "n8n-nodes-base.set",
            "typeVersion": 3.4,
            "isTrigger": False,
        },
    }

    monkeypatch.setattr(
        "src.agent.validation.default_registry.get_node_schema",
        lambda node_type: schemas.get(node_type) or schemas.get(node_type.split(".")[-1]),
    )

    nodes = [
        WorkflowNode(
            id="trigger",
            name="Manual Trigger",
            type="manualTrigger",
            typeVersion=1,
            position=[250, 300],
            parameters={},
        ),
        WorkflowNode(
            id="set",
            name="Set",
            type="set",
            typeVersion=1,
            position=[500, 300],
            parameters={
                "mode": "manual",
                "assignments": {
                    "assignments": [
                        {
                            "id": "message",
                            "name": "message",
                            "type": "string",
                            "value": "hello from Conduut",
                        }
                    ]
                },
                "options": {},
            },
        ),
    ]

    validated_nodes, validated_connections = _validated_workflow(
        nodes,
        {"node1": {"main": [[{"node": "node2", "type": "main", "index": 0}]]}},
    )

    assert validated_nodes[0].type == "n8n-nodes-base.manualTrigger"
    assert validated_nodes[1].type == "n8n-nodes-base.set"
    assert validated_nodes[1].typeVersion == 3.4
    assert validated_connections == {
        "Manual Trigger": {"main": [[{"node": "Set", "type": "main", "index": 0}]]}
    }


def test_validated_workflow_raises_model_retry_on_invalid_payload():
    with pytest.raises(ModelRetry):
        _validated_workflow([], {})


def test_validated_workflow_adds_webhook_id_and_response_node_mode(monkeypatch):
    schemas = {
        "n8n-nodes-base.webhook": {
            "type": "n8n-nodes-base.webhook",
            "typeVersion": 2.1,
            "isTrigger": True,
        },
        "n8n-nodes-base.respondToWebhook": {
            "type": "n8n-nodes-base.respondToWebhook",
            "typeVersion": 1.5,
            "isTrigger": False,
        },
    }

    monkeypatch.setattr(
        "src.agent.validation.default_registry.get_node_schema",
        lambda node_type: schemas.get(node_type),
    )

    nodes = [
        WorkflowNode(
            id="webhook",
            name="Webhook",
            type="n8n-nodes-base.webhook",
            typeVersion=2.1,
            position=[250, 300],
            parameters={
                "httpMethod": "POST",
                "path": "test",
                "responseMode": "lastNode",
            },
        ),
        WorkflowNode(
            id="respond",
            name="Respond to Webhook",
            type="n8n-nodes-base.respondToWebhook",
            typeVersion=1.5,
            position=[500, 300],
            parameters={},
        ),
    ]

    validated_nodes, _connections = _validated_workflow(
        nodes,
        {"Webhook": {"main": [[{"node": "Respond to Webhook", "type": "main", "index": 0}]]}},
    )

    webhook = validated_nodes[0].model_dump()
    assert webhook["webhookId"]
    assert webhook["parameters"]["responseMode"] == "responseNode"


def test_workflow_with_conduut_webhook_trigger_converts_manual_trigger(monkeypatch):
    monkeypatch.setattr(
        "src.agent.tools.registry.get_node_schema",
        lambda node_type: {"typeVersion": 2.1} if node_type == "n8n-nodes-base.webhook" else None,
    )

    converted = _workflow_with_conduut_webhook_trigger(
        {
            "id": "wf_123",
            "name": "Manual workflow",
            "nodes": [
                {
                    "id": "trigger",
                    "name": "ManualTrigger",
                    "type": "n8n-nodes-base.manualTrigger",
                    "typeVersion": 1,
                    "position": [250, 250],
                    "parameters": {},
                },
                {
                    "id": "gmail",
                    "name": "Gmail",
                    "type": "n8n-nodes-base.gmail",
                    "typeVersion": 2.1,
                    "position": [500, 250],
                    "parameters": {},
                },
            ],
            "connections": {
                "ManualTrigger": {"main": [[{"node": "Gmail", "type": "main", "index": 0}]]}
            },
        }
    )

    assert converted is not None
    trigger = converted["nodes"][0]
    assert trigger["type"] == "n8n-nodes-base.webhook"
    assert trigger["typeVersion"] == 2.1
    assert trigger["parameters"]["httpMethod"] == "POST"
    assert trigger["parameters"]["responseMode"] == "lastNode"
    assert trigger["parameters"]["path"].startswith("conduut-run-wf-123-trigger")
    assert trigger["webhookId"]
    assert converted["connections"]["ManualTrigger"]["main"][0][0]["node"] == "Gmail"


def test_gmail_send_runtime_schema_sets_webhook_expressions():
    nodes = [
        {
            "name": "Gmail",
            "type": "n8n-nodes-base.gmail",
            "parameters": {
                "resource": "message",
                "operation": "send",
                "sendTo": "old@example.com",
                "subject": "Old subject",
                "message": "Old body",
            },
        }
    ]

    input_schema = _infer_runtime_input_schema(nodes)
    _apply_runtime_inputs_to_nodes(nodes, input_schema)

    assert [field.name for field in input_schema] == ["to", "subject", "message"]
    assert nodes[0]["parameters"]["sendTo"] == "={{$json.to}}"
    assert nodes[0]["parameters"]["subject"] == "={{$json.subject}}"
    assert nodes[0]["parameters"]["message"] == "={{$json.message}}"
    assert nodes[0]["parameters"]["emailType"] == "text"


def test_validated_runtime_workflow_applies_gmail_inputs_before_validation(monkeypatch):
    schemas = {
        "n8n-nodes-base.webhook": {
            "type": "n8n-nodes-base.webhook",
            "typeVersion": 2.1,
            "isTrigger": True,
        },
        "n8n-nodes-base.gmail": {
            "type": "n8n-nodes-base.gmail",
            "typeVersion": 2.1,
            "isTrigger": False,
        },
    }

    monkeypatch.setattr(
        "src.agent.validation.default_registry.get_node_schema",
        lambda node_type: schemas.get(node_type),
    )

    nodes = [
        WorkflowNode(
            id="webhook",
            name="Webhook",
            type="n8n-nodes-base.webhook",
            typeVersion=2.1,
            position=[250, 300],
            parameters={
                "httpMethod": "POST",
                "path": "send-mail",
                "responseMode": "lastNode",
            },
        ),
        WorkflowNode(
            id="gmail",
            name="Gmail",
            type="n8n-nodes-base.gmail",
            typeVersion=2.1,
            position=[500, 300],
            parameters={
                "resource": "message",
                "operation": "send",
                "sendTo": "receiver@email.com",
                "subject": "Example subject",
                "message": "Example message",
            },
        ),
    ]

    validated_nodes, _connections, runtime_schema = _validated_runtime_workflow(
        nodes,
        {"Webhook": {"main": [[{"node": "Gmail", "type": "main", "index": 0}]]}},
    )

    gmail = validated_nodes[1].model_dump()
    assert [field.name for field in runtime_schema] == ["to", "subject", "message"]
    assert gmail["parameters"]["sendTo"] == "={{$json.to}}"
    assert gmail["parameters"]["subject"] == "={{$json.subject}}"
    assert gmail["parameters"]["message"] == "={{$json.message}}"


def test_validated_workflow_input_reports_missing_required_fields():
    input_schema = _infer_runtime_input_schema(
        [
            {
                "name": "Gmail",
                "type": "n8n-nodes-base.gmail",
                "parameters": {"resource": "message", "operation": "send"},
            }
        ]
    )

    payload, missing = _validated_workflow_input(
        input_schema,
        {"to": "person@example.com", "subject": "Hi"},
    )

    assert payload == {"to": "person@example.com", "subject": "Hi"}
    assert missing == ["message"]


@pytest.mark.asyncio
async def test_run_workflow_with_input_sends_payload_to_webhook(monkeypatch):
    sent: dict = {}

    async def fake_get_workflow_metadata(_user_id: str, workflow_id: str):
        return store.WorkflowMetadata(
            workflow_id=workflow_id,
            input_schema=[
                {
                    "name": "to",
                    "label": "Recipient email",
                    "type": "email",
                    "required": True,
                }
            ],
            created_at="now",
            updated_at="now",
        )

    async def fake_activate(_workflow_id: str):
        sent["activated"] = True

    async def fake_call_webhook(path: str, payload: dict):
        sent["path"] = path
        sent["payload"] = payload
        return httpx.Response(200, json={"ok": True})

    async def fake_list_executions(*_args, **_kwargs):
        return []

    monkeypatch.setattr("src.agent.tools.store.get_workflow_metadata", fake_get_workflow_metadata)
    monkeypatch.setattr("src.agent.tools.n8n_client.activate_workflow", fake_activate)
    monkeypatch.setattr("src.agent.tools.n8n_client.call_webhook", fake_call_webhook)
    monkeypatch.setattr("src.agent.tools.n8n_client.list_executions", fake_list_executions)
    monkeypatch.setattr("src.agent.tools.registry.get_node_schema", lambda _node_type: None)

    result = await run_workflow_with_input(
        {
            "id": "wf_1",
            "name": "Runtime workflow",
            "active": False,
            "nodes": [
                {
                    "name": "Webhook",
                    "type": "n8n-nodes-base.webhook",
                    "parameters": {"path": "runtime-test"},
                }
            ],
        },
        user_id="user_1",
        input_payload={"to": "person@example.com"},
    )

    assert sent["activated"] is True
    assert sent["path"] == "runtime-test"
    assert sent["payload"] == {"to": "person@example.com"}
    assert result.status == "triggered"


def test_summarize_execution_includes_node_output_preview():
    result = _summarize_execution(
        {
            "id": "42",
            "workflowId": "wf_1",
            "status": "success",
            "data": {
                "resultData": {
                    "runData": {
                        "Set": [
                            {
                                "data": {
                                    "main": [
                                        [
                                            {"json": {"message": "hello from Conduut"}},
                                            {"json": {"message": "second item"}},
                                        ]
                                    ]
                                }
                            }
                        ]
                    }
                }
            },
        },
        response={"statusCode": 200, "body": {"ok": True}},
    )

    assert result.summary == "Workflow run completed with 2 output item(s)."
    assert result.outputs[0]["nodeName"] == "Set"
    assert result.outputs[0]["itemCount"] == 2
    assert result.outputs[0]["items"][0]["message"] == "hello from Conduut"
    assert result.response is None


def test_summarize_execution_hides_webhook_transport_metadata():
    result = _summarize_execution(
        {
            "id": "42",
            "workflowId": "wf_1",
            "status": "success",
            "data": {
                "resultData": {
                    "runData": {
                        "Webhook": [
                            {
                                "data": {
                                    "main": [
                                        [
                                            {
                                                "json": {
                                                    "headers": {"host": "n8n:5678"},
                                                    "params": {},
                                                    "query": {},
                                                    "body": {"source": "conduut_test"},
                                                    "webhookUrl": "http://localhost:5678/webhook/test",
                                                    "executionMode": "production",
                                                }
                                            }
                                        ]
                                    ]
                                }
                            }
                        ],
                        "Respond to Webhook": [
                            {
                                "data": {
                                    "main": [
                                        [
                                            {
                                                "json": {
                                                    "headers": {"host": "n8n:5678"},
                                                    "body": {"source": "conduut_test"},
                                                }
                                            }
                                        ]
                                    ]
                                }
                            }
                        ],
                    }
                }
            },
        },
        response={"statusCode": 200, "body": {"source": "conduut_test"}},
        workflow={
            "nodes": [
                {"name": "Webhook", "type": "n8n-nodes-base.webhook"},
                {"name": "Respond to Webhook", "type": "n8n-nodes-base.respondToWebhook"},
            ]
        },
    )

    assert result.summary == "Workflow run completed."
    assert result.outputs == []
    assert result.response is None


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
    assert attachment.data.authorizePath == "/api/connections/google/gmail/authorize"


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

    monkeypatch.setattr("src.agent.tools.store.get_connection", fail_get_connection)
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
    assert attachment.type == "credential_request"
    assert attachment.data.credentialType == "gmailOAuth2"
