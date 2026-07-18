"""Validation, repair, and runtime-input pipeline tests."""

import pytest
from pydantic_ai import ModelRetry

from src import n8n_client
from src.agent.schemas import (
    WorkflowInputField,
    WorkflowNode,
)
from src.agent.tools import (
    _apply_runtime_inputs_to_nodes,
    _infer_runtime_input_schema,
    _validated_runtime_workflow,
    _validated_workflow,
    _validated_workflow_input,
    _workflow_with_conduut_webhook_trigger,
    _workflow_with_post_webhook_trigger,
)
from src.agent.tools.factory import (
    _dedup_existing_workflow,
    _normalized_user_input_request,
    _validated_create_or_dedup_workflow,
)


def test_normalized_user_input_request_limits_missing_fields_to_current_step():
    question, fields, choices, reason, remaining = _normalized_user_input_request(
        "Bu otomasyon icin bilgileri paylasin",
        ["E-posta servisi", "Google Sheet ID", "Sheet adi"],
        ["Gmail", "SMTP"],
        "Servis secimi sonraki sorulari belirler.",
    )

    assert question == "Bu otomasyon icin bilgileri paylasin"
    assert fields == ["E-posta servisi"]
    assert [choice.label for choice in choices] == ["Gmail", "SMTP"]
    assert reason == "Servis secimi sonraki sorulari belirler."
    assert remaining == ["Google Sheet ID", "Sheet adi"]


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


def test_runtime_pipeline_repairs_compact_broken_ai_workflow(monkeypatch):
    """End-to-end proof of the create_workflow path: a compact payload carrying
    every raw-path bug GPT-5 makes (chat model in main, {{input.x}}, $json.body
    read in a non-trigger-fed node, a {{ }} field with no '=') is turned into a
    correct n8n workflow by normalize -> repair -> validate, with no ModelRetry."""

    schemas = {
        "n8n-nodes-base.webhook": {
            "type": "n8n-nodes-base.webhook",
            "typeVersion": 2,
            "isTrigger": True,
        },
        "@n8n/n8n-nodes-langchain.lmChatOpenAi": {
            "type": "@n8n/n8n-nodes-langchain.lmChatOpenAi",
            "typeVersion": 1,
            "isTrigger": False,
        },
        "@n8n/n8n-nodes-langchain.agent": {
            "type": "@n8n/n8n-nodes-langchain.agent",
            "typeVersion": 1.7,
            "isTrigger": False,
        },
        "n8n-nodes-base.gmail": {
            "type": "n8n-nodes-base.gmail",
            "typeVersion": 2.1,
            "isTrigger": False,
        },
    }
    monkeypatch.setattr(
        "src.agent.validation.default_registry.get_node_schema",
        lambda node_type: schemas.get(node_type) or schemas.get(node_type.split(".")[-1]),
    )

    # Compact nodes: no id/typeVersion/position. AI Agent uses the invalid
    # {{input.x}} form (bug 2).
    nodes = [
        WorkflowNode(name="Webhook", type="n8n-nodes-base.webhook", parameters={"path": "p"}),
        WorkflowNode(
            name="OpenAI Chat Model",
            type="@n8n/n8n-nodes-langchain.lmChatOpenAi",
            parameters={"model": "gpt-4o-mini"},
        ),
        WorkflowNode(
            name="AI Agent",
            type="@n8n/n8n-nodes-langchain.agent",
            parameters={"promptType": "define", "text": "Proposal for {{input.company}}"},
        ),
        WorkflowNode(
            name="Send Email",
            type="n8n-nodes-base.gmail",
            parameters={
                "resource": "message",
                "operation": "send",
                # bug 3: $json.body.* read in a node fed by the AI Agent, not the
                # webhook. bug 4: subject has {{ }} but no leading '='.
                "sendTo": "={{ $json.body.email }}",
                "subject": "Proposal for {{ $json.body.company }}",
                "message": "={{ $('AI Agent').first().json.output }}",
                "emailType": "text",
            },
        ),
    ]
    # Bug 1: chat model wired into the main flow instead of the ai_languageModel port.
    connections = {
        "Webhook": {"main": [[{"node": "AI Agent", "type": "main", "index": 0}]]},
        "OpenAI Chat Model": {"main": [[{"node": "AI Agent", "type": "main", "index": 0}]]},
        "AI Agent": {"main": [[{"node": "Send Email", "type": "main", "index": 0}]]},
    }
    input_schema = [
        WorkflowInputField(name="company", label="Company", type="string"),
        WorkflowInputField(name="email", label="Email", type="email"),
    ]

    # Must not raise ModelRetry — everything is deterministically repaired.
    validated_nodes, validated_connections, _schema = _validated_runtime_workflow(
        nodes, connections, input_schema
    )

    # Bug 1 fixed: chat model attached via the ai_languageModel port (with the
    # correct connection type), gone from the main flow.
    chat = validated_connections["OpenAI Chat Model"]
    assert "main" not in chat
    assert chat["ai_languageModel"][0][0]["node"] == "AI Agent"
    assert chat["ai_languageModel"][0][0]["type"] == "ai_languageModel"

    # Bug 2 fixed: {{input.company}} -> trigger body expression; and the AI Agent
    # (fed directly by the webhook) keeps $json.body but becomes an expression.
    agent = next(n for n in validated_nodes if n.name == "AI Agent")
    assert "input.company" not in agent.parameters["text"]
    assert "$('Webhook').first().json.body.company" in agent.parameters["text"]
    assert agent.parameters["text"].startswith("=")

    # Bugs 3 & 4 fixed: Gmail is fed by the AI Agent, so webhook inputs are
    # qualified to $('Webhook')...; the subject gains the leading '='.
    gmail = next(n for n in validated_nodes if n.name == "Send Email")
    assert gmail.parameters["sendTo"] == "={{ $('Webhook').first().json.body.email }}"
    assert gmail.parameters["subject"].startswith("=")
    assert "$('Webhook').first().json.body.company" in gmail.parameters["subject"]
    # The already-correct agent-output reference is left intact.
    assert gmail.parameters["message"] == "={{ $('AI Agent').first().json.output }}"

    # Boilerplate filled.
    for node in validated_nodes:
        assert node.typeVersion is not None
        assert node.position is not None


def test_validated_runtime_workflow_preserves_fallback_connections_for_update():
    nodes = [
        WorkflowNode(
            name="Webhook",
            type="n8n-nodes-base.webhook",
            typeVersion=2,
            parameters={"httpMethod": "POST", "path": "existing"},
        ),
        WorkflowNode(
            name="Code",
            type="n8n-nodes-base.code",
            typeVersion=2,
            parameters={"jsCode": "return items;"},
        ),
    ]
    existing_connections = {"Webhook": {"main": [[{"node": "Code", "type": "main", "index": 0}]]}}

    _, validated_connections, _ = _validated_runtime_workflow(
        nodes,
        None,
        fallback_connections=existing_connections,
        infer_missing_connections=False,
    )

    assert validated_connections == existing_connections


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


def test_workflow_with_post_webhook_trigger_sets_missing_http_method():
    converted = _workflow_with_post_webhook_trigger(
        {
            "id": "wf_123",
            "name": "Webhook workflow",
            "nodes": [
                {
                    "id": "webhook",
                    "name": "Webhook",
                    "type": "n8n-nodes-base.webhook",
                    "parameters": {
                        "multipleMethods": False,
                        "path": "send-email-gmail",
                        "authentication": "none",
                        "options": {},
                    },
                },
                {
                    "id": "gmail",
                    "name": "Gmail",
                    "type": "n8n-nodes-base.gmail",
                    "parameters": {},
                },
            ],
            "connections": {"Webhook": {"main": [[{"node": "Gmail", "type": "main", "index": 0}]]}},
        }
    )

    assert converted is not None
    trigger = converted["nodes"][0]
    assert trigger["parameters"]["httpMethod"] == "POST"
    assert trigger["parameters"]["multipleMethods"] is False


def test_gmail_send_runtime_schema_fills_empty_fields():
    # A bare Gmail send (no recipient/subject/message) becomes a parametric form.
    nodes = [
        {
            "name": "Gmail",
            "type": "n8n-nodes-base.gmail",
            "parameters": {
                "resource": "message",
                "operation": "send",
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


def test_gmail_send_preserves_fixed_recipient_and_upstream_message():
    # Fixed recipient + content from an upstream node must NOT be turned into
    # runtime inputs (otherwise the workflow can never run without manual input).
    nodes = [
        {"name": "Webhook", "type": "n8n-nodes-base.webhook", "parameters": {}},
        {
            "name": "Get Quote",
            "type": "n8n-nodes-base.httpRequest",
            "parameters": {"url": "https://api.api-ninjas.com/v1/quotes"},
        },
        {
            "name": "Send Email",
            "type": "n8n-nodes-base.gmail",
            "parameters": {
                "resource": "message",
                "operation": "send",
                "sendTo": "burakturan113@gmail.com",
                "subject": "Günün Sözü",
                "message": "={{ $('Get Quote').first().json[0].quote }}",
            },
        },
    ]

    input_schema = _infer_runtime_input_schema(nodes)
    _apply_runtime_inputs_to_nodes(nodes, input_schema)

    assert input_schema == []
    gmail = nodes[2]["parameters"]
    assert gmail["sendTo"] == "burakturan113@gmail.com"
    assert gmail["subject"] == "Günün Sözü"
    assert gmail["message"] == "={{ $('Get Quote').first().json[0].quote }}"


def test_gmail_send_fills_only_empty_fields():
    # Concrete recipient kept; empty subject/message become runtime inputs.
    nodes = [
        {"name": "Webhook", "type": "n8n-nodes-base.webhook", "parameters": {}},
        {
            "name": "Send Email",
            "type": "n8n-nodes-base.gmail",
            "parameters": {
                "resource": "message",
                "operation": "send",
                "sendTo": "burakturan113@gmail.com",
            },
        },
    ]

    input_schema = _infer_runtime_input_schema(nodes)
    _apply_runtime_inputs_to_nodes(nodes, input_schema)

    assert [field.name for field in input_schema] == ["subject", "message"]
    gmail = nodes[1]["parameters"]
    assert gmail["sendTo"] == "burakturan113@gmail.com"
    assert gmail["subject"] == "={{$json.body.subject}}"
    assert gmail["message"] == "={{$json.body.message}}"


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
            },
        ),
    ]

    validated_nodes, _connections, runtime_schema = _validated_runtime_workflow(
        nodes,
        {"Webhook": {"main": [[{"node": "Gmail", "type": "main", "index": 0}]]}},
    )

    gmail = validated_nodes[1].model_dump()
    assert [field.name for field in runtime_schema] == ["to", "subject", "message"]
    assert gmail["parameters"]["sendTo"] == "={{$json.body.to}}"
    assert gmail["parameters"]["subject"] == "={{$json.body.subject}}"
    assert gmail["parameters"]["message"] == "={{$json.body.message}}"


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


# --------------------------------------------------------------------------
# create_workflow dedup: tolerate a deleted (stale) remembered workflow id
# --------------------------------------------------------------------------


async def test_dedup_existing_workflow_none_id_returns_none():
    assert await _dedup_existing_workflow(None) is None


async def test_dedup_existing_workflow_returns_workflow_when_present(monkeypatch):
    async def fake_get(wid):
        return {"id": wid, "settings": {"executionOrder": "v1"}}

    monkeypatch.setattr(n8n_client, "get_workflow", fake_get)
    result = await _dedup_existing_workflow("wf-1")
    assert result["id"] == "wf-1"


async def test_dedup_existing_workflow_returns_none_on_404(monkeypatch):
    # The user deleted the workflow and asked to rebuild in the same chat -> the
    # remembered dedup id is gone. create_workflow must recreate, not die on 404.
    async def fake_get(wid):
        raise n8n_client.N8nApiError(404, "Not Found", method="GET", path=f"/workflows/{wid}")

    monkeypatch.setattr(n8n_client, "get_workflow", fake_get)
    assert await _dedup_existing_workflow("gone-id") is None


async def test_dedup_existing_workflow_reraises_non_404(monkeypatch):
    async def fake_get(wid):
        raise n8n_client.N8nApiError(500, "Server Error", method="GET", path=f"/workflows/{wid}")

    monkeypatch.setattr(n8n_client, "get_workflow", fake_get)
    with pytest.raises(n8n_client.N8nApiError):
        await _dedup_existing_workflow("boom-id")


def test_deduped_create_preserves_existing_topology_when_connections_are_omitted(monkeypatch):
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
        WorkflowNode(name="Trigger", type="manualTrigger", parameters={}),
        WorkflowNode(
            name="Branch A",
            type="set",
            parameters={
                "mode": "manual",
                "assignments": {
                    "assignments": [{"id": "a", "name": "branch", "type": "string", "value": "a"}]
                },
                "options": {},
            },
        ),
        WorkflowNode(
            name="Branch B",
            type="set",
            parameters={
                "mode": "manual",
                "assignments": {
                    "assignments": [{"id": "b", "name": "branch", "type": "string", "value": "b"}]
                },
                "options": {},
            },
        ),
    ]
    existing_connections = {
        "Trigger": {
            "main": [
                [
                    {"node": "Branch A", "type": "main", "index": 0},
                    {"node": "Branch B", "type": "main", "index": 0},
                ]
            ]
        }
    }

    _, validated_connections, _, requested_connections = _validated_create_or_dedup_workflow(
        nodes,
        None,
        None,
        {"id": "wf-1", "connections": existing_connections},
    )

    assert requested_connections is None
    assert validated_connections == existing_connections
