import asyncio
from types import SimpleNamespace

import httpx
import pytest
from pydantic_ai import ModelRetry

from src import store
from src.agent.schemas import (
    AgentDeps,
    WorkflowNode,
    WorkflowSpec,
    WorkflowStepSpec,
    WorkflowTriggerSpec,
)
from src.agent.tools import (
    _apply_runtime_inputs_to_nodes,
    _infer_runtime_input_schema,
    _summarize_execution,
    _validated_runtime_workflow,
    _validated_workflow,
    _validated_workflow_input,
    _workflow_with_conduut_webhook_trigger,
    _workflow_with_post_webhook_trigger,
    analyze_workflow_readiness_payload,
    compile_workflow_spec,
    create_workflow_from_spec_payload,
    run_workflow_with_input,
)
from src.agent.tools.spec_compiler import WorkflowSpecCompileError


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


def test_compile_workflow_spec_creates_gmail_on_demand_workflow(monkeypatch):
    schemas = {
        "n8n-nodes-base.webhook": {
            "type": "n8n-nodes-base.webhook",
            "typeVersion": 2.1,
        },
        "n8n-nodes-base.gmail": {
            "type": "n8n-nodes-base.gmail",
            "typeVersion": 2.1,
        },
    }
    monkeypatch.setattr(
        "src.agent.tools.registry.get_node_schema",
        lambda node_type: schemas.get(node_type),
    )

    compiled = compile_workflow_spec(
        "Send Gmail",
        WorkflowSpec(
            trigger=WorkflowTriggerSpec(kind="on_demand"),
            steps=[WorkflowStepSpec(capability="send_email", service="gmail")],
        ),
    )

    assert [node.type for node in compiled.nodes] == [
        "n8n-nodes-base.webhook",
        "n8n-nodes-base.gmail",
    ]
    assert compiled.nodes[0].parameters["httpMethod"] == "POST"
    assert compiled.nodes[0].parameters["path"].startswith("conduut-spec-send-gmail-")
    assert compiled.nodes[1].parameters == {
        "resource": "message",
        "operation": "send",
        "sendTo": "={{$json.body.to}}",
        "subject": "={{$json.body.subject}}",
        "message": "={{$json.body.message}}",
        "emailType": "text",
    }
    assert compiled.connections == {
        "Webhook": {"main": [[{"node": "Gmail", "type": "main", "index": 0}]]}
    }
    assert [field.name for field in compiled.input_schema] == ["to", "subject", "message"]


def test_compile_workflow_spec_requires_registry_schemas(monkeypatch):
    monkeypatch.setattr("src.agent.tools.registry.get_node_schema", lambda _node_type: None)

    with pytest.raises(WorkflowSpecCompileError):
        compile_workflow_spec(
            "Send Gmail",
            WorkflowSpec(
                trigger=WorkflowTriggerSpec(kind="on_demand"),
                steps=[WorkflowStepSpec(capability="send_email", service="gmail")],
            ),
        )


def test_compile_workflow_spec_rejects_unsupported_step(monkeypatch):
    monkeypatch.setattr(
        "src.agent.tools.registry.get_node_schema",
        lambda _node_type: {"typeVersion": 1},
    )
    unsupported_step = WorkflowStepSpec.model_construct(
        id="sheet",
        capability="read_sheet",
        service="google_sheets",
        inputs={},
    )
    unsupported_spec = WorkflowSpec.model_construct(
        trigger=WorkflowTriggerSpec(kind="on_demand"),
        steps=[unsupported_step],
    )

    with pytest.raises(WorkflowSpecCompileError):
        compile_workflow_spec("Unsupported", unsupported_spec)


def test_compile_workflow_spec_creates_sheet_filter_gmail_workflow(monkeypatch):
    schemas = {
        "n8n-nodes-base.webhook": {"type": "n8n-nodes-base.webhook", "typeVersion": 2.1},
        "n8n-nodes-base.googleSheets": {
            "type": "n8n-nodes-base.googleSheets",
            "typeVersion": 4.7,
        },
        "n8n-nodes-base.filter": {"type": "n8n-nodes-base.filter", "typeVersion": 2.2},
        "n8n-nodes-base.gmail": {"type": "n8n-nodes-base.gmail", "typeVersion": 2.1},
    }
    monkeypatch.setattr(
        "src.agent.tools.registry.get_node_schema",
        lambda node_type: schemas.get(node_type),
    )

    compiled = compile_workflow_spec(
        "Hot leads",
        WorkflowSpec(
            trigger=WorkflowTriggerSpec(kind="on_demand"),
            steps=[
                WorkflowStepSpec(
                    id="read_leads",
                    capability="read_sheet_rows",
                    service="google_sheets",
                    inputs={"document_id": "sheet_123", "sheet_name": "Leads"},
                ),
                WorkflowStepSpec(
                    id="filter_hot",
                    capability="filter_items",
                    service="core",
                    inputs={"field": "score", "operator": ">=", "value": 80},
                ),
                WorkflowStepSpec(
                    id="email_hot",
                    capability="send_email",
                    service="gmail",
                    inputs={
                        "to_field": "email",
                        "subject": "Follow up",
                        "message": 'Hi {{$json["name"]}}, thanks for your interest.',
                    },
                ),
            ],
        ),
    )

    assert [node.name for node in compiled.nodes] == [
        "Webhook",
        "Google Sheets",
        "Filter",
        "Gmail",
    ]
    sheets = compiled.nodes[1].model_dump()
    assert sheets["parameters"]["operation"] == "read"
    assert sheets["parameters"]["documentId"] == {
        "__rl": True,
        "mode": "id",
        "value": "sheet_123",
    }
    assert sheets["parameters"]["sheetName"] == {
        "__rl": True,
        "mode": "name",
        "value": "Leads",
    }
    filter_node = compiled.nodes[2].model_dump()
    condition = filter_node["parameters"]["conditions"]["conditions"][0]
    assert condition["leftValue"] == '={{$json["score"]}}'
    assert condition["operator"] == {"type": "number", "operation": "gte"}
    assert condition["rightValue"] == 80
    gmail = compiled.nodes[3].model_dump()
    assert gmail["parameters"]["sendTo"] == '={{$json["email"]}}'
    assert gmail["parameters"]["subject"] == "Follow up"
    assert gmail["parameters"]["message"] == '=Hi {{$json["name"]}}, thanks for your interest.'
    assert compiled.input_schema == []
    assert compiled.connections == {
        "Webhook": {"main": [[{"node": "Google Sheets", "type": "main", "index": 0}]]},
        "Google Sheets": {"main": [[{"node": "Filter", "type": "main", "index": 0}]]},
        "Filter": {"main": [[{"node": "Gmail", "type": "main", "index": 0}]]},
    }


def test_compile_workflow_spec_creates_daily_sheet_filter_gmail_workflow(monkeypatch):
    schemas = {
        "n8n-nodes-base.scheduleTrigger": {
            "type": "n8n-nodes-base.scheduleTrigger",
            "typeVersion": 1.3,
        },
        "n8n-nodes-base.googleSheets": {
            "type": "n8n-nodes-base.googleSheets",
            "typeVersion": 4.7,
        },
        "n8n-nodes-base.filter": {"type": "n8n-nodes-base.filter", "typeVersion": 2.2},
        "n8n-nodes-base.gmail": {"type": "n8n-nodes-base.gmail", "typeVersion": 2.1},
    }
    monkeypatch.setattr(
        "src.agent.tools.registry.get_node_schema",
        lambda node_type: schemas.get(node_type),
    )

    compiled = compile_workflow_spec(
        "Daily hot leads",
        WorkflowSpec(
            trigger=WorkflowTriggerSpec(kind="schedule", time="08:30"),
            steps=[
                WorkflowStepSpec(
                    capability="read_sheet_rows",
                    service="google_sheets",
                    inputs={"document_id": "sheet_123", "sheet_id": "gid=0"},
                ),
                WorkflowStepSpec(
                    capability="filter_items",
                    service="core",
                    inputs={"field": "status", "operator": "equals", "value": "Ready"},
                ),
                WorkflowStepSpec(
                    capability="send_email",
                    service="gmail",
                    inputs={"to_field": "email", "subject": "Ready", "message_field": "message"},
                ),
            ],
        ),
    )

    assert [node.id for node in compiled.nodes] == [
        "trigger",
        "read_sheet_rows",
        "filter_items",
        "send_email",
    ]
    schedule = compiled.nodes[0].model_dump()
    assert schedule["type"] == "n8n-nodes-base.scheduleTrigger"
    assert schedule["parameters"]["rule"]["interval"][0] == {
        "field": "days",
        "daysInterval": 1,
        "triggerAtHour": 8,
        "triggerAtMinute": 30,
    }
    assert compiled.nodes[1].parameters["sheetName"] == {
        "__rl": True,
        "mode": "id",
        "value": "gid=0",
    }
    assert compiled.nodes[3].parameters["message"] == '={{$json["message"]}}'
    assert compiled.connections["Schedule"]["main"][0][0]["node"] == "Google Sheets"


def test_compile_workflow_spec_requires_sheet_email_message(monkeypatch):
    monkeypatch.setattr(
        "src.agent.tools.registry.get_node_schema",
        lambda _node_type: {"typeVersion": 1},
    )

    with pytest.raises(WorkflowSpecCompileError, match="message"):
        compile_workflow_spec(
            "Missing message",
            WorkflowSpec(
                trigger=WorkflowTriggerSpec(kind="on_demand"),
                steps=[
                    WorkflowStepSpec(
                        capability="read_sheet_rows",
                        service="google_sheets",
                        inputs={"document_id": "sheet_123", "sheet_name": "Leads"},
                    ),
                    WorkflowStepSpec(
                        capability="filter_items",
                        service="core",
                        inputs={"field": "score", "operator": ">", "value": 80},
                    ),
                    WorkflowStepSpec(
                        capability="send_email",
                        service="gmail",
                        inputs={"to_field": "email", "subject": "Follow up"},
                    ),
                ],
            ),
        )


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


@pytest.mark.asyncio
async def test_create_workflow_from_spec_payload_creates_workflow_and_emits_oauth_prompt(
    monkeypatch,
):
    schemas = {
        "n8n-nodes-base.webhook": {
            "type": "n8n-nodes-base.webhook",
            "typeVersion": 2.1,
        },
        "n8n-nodes-base.gmail": {
            "type": "n8n-nodes-base.gmail",
            "typeVersion": 2.1,
            "credentials": ["gmailOAuth2"],
        },
    }
    created: dict = {}
    saved: dict = {}

    monkeypatch.setattr(
        "src.agent.tools.registry.get_node_schema",
        lambda node_type: schemas.get(node_type),
    )

    async def fake_create_workflow(name: str, nodes: list[dict], connections: dict):
        created["name"] = name
        created["nodes"] = nodes
        created["connections"] = connections
        return SimpleNamespace(id="wf_spec", name=name, active=False)

    async def fake_get_workflow(_workflow_id: str):
        return {
            "id": "wf_spec",
            "name": created["name"],
            "nodes": created["nodes"],
            "connections": created["connections"],
        }

    async def fake_save_workflow_metadata(user_id: str, workflow_id: str, input_schema: list[dict]):
        saved["user_id"] = user_id
        saved["workflow_id"] = workflow_id
        saved["input_schema"] = input_schema

    async def fake_get_connection(_user_id: str, _connection_id: str):
        return None

    monkeypatch.setattr("src.agent.tools.n8n_client.create_workflow", fake_create_workflow)
    monkeypatch.setattr("src.agent.tools.n8n_client.get_workflow", fake_get_workflow)
    monkeypatch.setattr("src.agent.tools.store.save_workflow_metadata", fake_save_workflow_metadata)
    monkeypatch.setattr("src.agent.tools.store.get_connection", fake_get_connection)

    deps = AgentDeps(
        user_id="user_1",
        conversation_id="conv_1",
        event_queue=asyncio.Queue(),
    )

    result = await create_workflow_from_spec_payload(
        deps,
        "Spec Gmail",
        WorkflowSpec(
            trigger=WorkflowTriggerSpec(kind="on_demand"),
            steps=[WorkflowStepSpec(capability="send_email", service="gmail")],
        ),
    )

    assert result == {
        "id": "wf_spec",
        "name": "Spec Gmail",
        "active": False,
        "ready": False,
        "missing_credentials": 1,
        "instruction": (
            "Stop now. A credential or app connection request was shown to the user. "
            "Tell the user the workflow was created but needs that connection before it "
            "can run. Do not activate or execute the workflow until the user connects it."
        ),
    }
    assert created["nodes"][0]["type"] == "n8n-nodes-base.webhook"
    assert created["nodes"][1]["parameters"]["sendTo"] == "={{$json.body.to}}"
    assert saved == {
        "user_id": "user_1",
        "workflow_id": "wf_spec",
        "input_schema": [
            {
                "name": "to",
                "label": "Recipient email",
                "type": "email",
                "required": True,
                "placeholder": "name@example.com",
            },
            {
                "name": "subject",
                "label": "Subject",
                "type": "string",
                "required": True,
                "placeholder": "Email subject",
            },
            {
                "name": "message",
                "label": "Message",
                "type": "textarea",
                "required": True,
                "placeholder": "Email body",
            },
        ],
    }
    assert [attachment["type"] for attachment in deps.attachments] == [
        "workflow_preview",
        "oauth_prompt",
    ]
    assert deps.awaiting_user_input is True


@pytest.mark.asyncio
async def test_create_workflow_from_spec_payload_creates_sheet_filter_gmail_workflow(
    monkeypatch,
):
    schemas = {
        "n8n-nodes-base.webhook": {
            "type": "n8n-nodes-base.webhook",
            "typeVersion": 2.1,
        },
        "n8n-nodes-base.googleSheets": {
            "type": "n8n-nodes-base.googleSheets",
            "typeVersion": 4.7,
        },
        "n8n-nodes-base.filter": {
            "type": "n8n-nodes-base.filter",
            "typeVersion": 2.2,
        },
        "n8n-nodes-base.gmail": {
            "type": "n8n-nodes-base.gmail",
            "typeVersion": 2.1,
        },
    }
    created: dict = {}
    saved: dict = {}

    monkeypatch.setattr(
        "src.agent.tools.registry.get_node_schema",
        lambda node_type: schemas.get(node_type),
    )

    async def fake_create_workflow(name: str, nodes: list[dict], connections: dict):
        created["name"] = name
        created["nodes"] = nodes
        created["connections"] = connections
        return SimpleNamespace(id="wf_sheet_spec", name=name, active=False)

    async def fake_get_workflow(_workflow_id: str):
        return {
            "id": "wf_sheet_spec",
            "name": created["name"],
            "nodes": created["nodes"],
            "connections": created["connections"],
        }

    async def fake_save_workflow_metadata(user_id: str, workflow_id: str, input_schema: list[dict]):
        saved["user_id"] = user_id
        saved["workflow_id"] = workflow_id
        saved["input_schema"] = input_schema

    monkeypatch.setattr("src.agent.tools.n8n_client.create_workflow", fake_create_workflow)
    monkeypatch.setattr("src.agent.tools.n8n_client.get_workflow", fake_get_workflow)
    monkeypatch.setattr("src.agent.tools.store.save_workflow_metadata", fake_save_workflow_metadata)

    deps = AgentDeps(
        user_id="user_1",
        conversation_id="conv_1",
        event_queue=asyncio.Queue(),
    )

    result = await create_workflow_from_spec_payload(
        deps,
        "Hot leads",
        WorkflowSpec(
            trigger=WorkflowTriggerSpec(kind="on_demand"),
            steps=[
                WorkflowStepSpec(
                    capability="read_sheet_rows",
                    service="google_sheets",
                    inputs={"document_id": "sheet_123", "sheet_name": "Leads"},
                ),
                WorkflowStepSpec(
                    capability="filter_items",
                    service="core",
                    inputs={"field": "score", "operator": ">=", "value": 80},
                ),
                WorkflowStepSpec(
                    capability="send_email",
                    service="gmail",
                    inputs={"to_field": "email", "subject": "Follow up", "message_field": "body"},
                ),
            ],
        ),
    )

    assert result == {"id": "wf_sheet_spec", "name": "Hot leads", "active": False}
    assert [node["id"] for node in created["nodes"]] == [
        "trigger",
        "read_sheet_rows",
        "filter_items",
        "send_email",
    ]
    assert created["nodes"][3]["parameters"]["sendTo"] == '={{$json["email"]}}'
    assert created["nodes"][3]["parameters"]["message"] == '={{$json["body"]}}'
    assert saved == {
        "user_id": "user_1",
        "workflow_id": "wf_sheet_spec",
        "input_schema": [],
    }
    assert [attachment["type"] for attachment in deps.attachments] == ["workflow_preview"]


@pytest.mark.asyncio
async def test_create_workflow_from_spec_payload_returns_error_before_side_effects(
    monkeypatch,
):
    monkeypatch.setattr("src.agent.tools.registry.get_node_schema", lambda _node_type: None)

    async def fail_create_workflow(*_args, **_kwargs):
        raise AssertionError("n8n create should not run when compile fails")

    monkeypatch.setattr("src.agent.tools.n8n_client.create_workflow", fail_create_workflow)
    deps = AgentDeps(
        user_id="user_1",
        conversation_id="conv_1",
        event_queue=asyncio.Queue(),
    )

    result = await create_workflow_from_spec_payload(
        deps,
        "Spec Gmail",
        WorkflowSpec(
            trigger=WorkflowTriggerSpec(kind="on_demand"),
            steps=[WorkflowStepSpec(capability="send_email", service="gmail")],
        ),
    )

    assert "registry schema" in result["error"]
    assert deps.attachments == []


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

    async def fake_update_workflow(**kwargs):
        sent["updated_nodes"] = kwargs["nodes"]
        return SimpleNamespace(id=kwargs["workflow_id"])

    async def fake_get_workflow(_workflow_id: str):
        return {
            "id": "wf_1",
            "name": "Runtime workflow",
            "active": False,
            "nodes": sent["updated_nodes"],
        }

    async def fake_call_webhook(path: str, payload: dict):
        sent["path"] = path
        sent["payload"] = payload
        return httpx.Response(200, json={"ok": True})

    async def fake_list_executions(*_args, **_kwargs):
        return []

    monkeypatch.setattr("src.agent.tools.store.get_workflow_metadata", fake_get_workflow_metadata)
    monkeypatch.setattr("src.agent.tools.n8n_client.activate_workflow", fake_activate)
    monkeypatch.setattr("src.agent.tools.n8n_client.update_workflow", fake_update_workflow)
    monkeypatch.setattr("src.agent.tools.n8n_client.get_workflow", fake_get_workflow)
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
    assert sent["updated_nodes"][0]["parameters"]["httpMethod"] == "POST"
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
    assert attachment.data.authorizePath == "/api/oauth/google/authorize?service=gmail"


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
