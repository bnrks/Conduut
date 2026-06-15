import asyncio
from types import SimpleNamespace

import httpx
import pytest
from pydantic_ai import ModelRetry

from src import store
from src.agent.schemas import (
    AgentDeps,
    WorkflowActionSpec,
    WorkflowInputField,
    WorkflowNode,
    WorkflowPlan,
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
    compile_workflow_plan,
    compile_workflow_spec,
    create_workflow_from_plan_payload,
    create_workflow_from_spec_payload,
    iter_workflow_batch_with_input,
    run_workflow_batch_with_input,
    run_workflow_with_input,
)
from src.agent.tools.factory import _normalized_user_input_request
from src.agent.tools.spec_compiler import WorkflowPlanCompileError, WorkflowSpecCompileError


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


def test_compile_workflow_plan_creates_gmail_on_demand_workflow(monkeypatch):
    schemas = {
        "n8n-nodes-base.webhook": {"type": "n8n-nodes-base.webhook", "typeVersion": 2.1},
        "n8n-nodes-base.gmail": {"type": "n8n-nodes-base.gmail", "typeVersion": 2.1},
    }
    monkeypatch.setattr(
        "src.agent.tools.registry.get_node_schema",
        lambda node_type: schemas.get(node_type),
    )

    compiled = compile_workflow_plan(
        "Send Gmail",
        WorkflowPlan(
            trigger=WorkflowTriggerSpec(kind="on_demand"),
            actions=[
                WorkflowActionSpec(
                    id="send_email",
                    action="gmail.send",
                    params={
                        "to": {"ref": "input.to"},
                        "subject": {"ref": "input.subject"},
                        "message": {"ref": "input.message"},
                    },
                )
            ],
        ),
    )

    assert [node.type for node in compiled.nodes] == [
        "n8n-nodes-base.webhook",
        "n8n-nodes-base.gmail",
    ]
    gmail = compiled.nodes[1].model_dump()
    assert gmail["parameters"] == {
        "resource": "message",
        "operation": "send",
        "sendTo": '={{$(\'Webhook\').first().json["body"]["to"]}}',
        "subject": '={{$(\'Webhook\').first().json["body"]["subject"]}}',
        "message": '={{$(\'Webhook\').first().json["body"]["message"]}}',
        "emailType": "text",
    }
    assert compiled.connections == {
        "Webhook": {"main": [[{"node": "Gmail", "type": "main", "index": 0}]]}
    }
    assert [field.name for field in compiled.input_schema] == ["to", "subject", "message"]


def test_compile_workflow_plan_creates_gmail_then_sheets_append_workflow(monkeypatch):
    schemas = {
        "n8n-nodes-base.webhook": {"type": "n8n-nodes-base.webhook", "typeVersion": 2.1},
        "n8n-nodes-base.gmail": {"type": "n8n-nodes-base.gmail", "typeVersion": 2.1},
        "n8n-nodes-base.googleSheets": {
            "type": "n8n-nodes-base.googleSheets",
            "typeVersion": 4.7,
        },
        "n8n-nodes-base.set": {"type": "n8n-nodes-base.set", "typeVersion": 3.4},
    }
    monkeypatch.setattr(
        "src.agent.tools.registry.get_node_schema",
        lambda node_type: schemas.get(node_type),
    )

    compiled = compile_workflow_plan(
        "Send and log Gmail",
        WorkflowPlan(
            trigger=WorkflowTriggerSpec(kind="on_demand"),
            actions=[
                WorkflowActionSpec(
                    id="send_email",
                    action="gmail.send",
                    params={
                        "to": {"ref": "input.to"},
                        "subject": {"ref": "input.subject"},
                        "message": {"ref": "input.message"},
                    },
                ),
                WorkflowActionSpec(
                    id="log_email",
                    action="sheets.row.append",
                    after="send_email",
                    params={
                        "spreadsheet_id": "sheet_123",
                        "sheet_name": "Logs",
                        "columns": {
                            "run_time": "NOW()",
                            "created_at": "=NOW()",
                            "To": {"ref": "input.to"},
                            "Subject": {"ref": "input.subject"},
                            "Message": {"ref": "input.message"},
                        },
                    },
                ),
            ],
        ),
    )

    assert [node.name for node in compiled.nodes] == [
        "Webhook",
        "Gmail",
        "Prepare Sheets Row",
        "Google Sheets Append",
    ]
    prepare = compiled.nodes[2].model_dump()
    assert prepare["type"] == "n8n-nodes-base.set"
    assert prepare["parameters"] == {
        "mode": "manual",
        "assignments": {
            "assignments": [
                {
                    "id": "run_time",
                    "name": "run_time",
                    "type": "string",
                    "value": "={{$now.toISO()}}",
                },
                {
                    "id": "created_at",
                    "name": "created_at",
                    "type": "string",
                    "value": "={{$now.toISO()}}",
                },
                {
                    "id": "To",
                    "name": "To",
                    "type": "string",
                    "value": '={{$(\'Webhook\').first().json["body"]["to"]}}',
                },
                {
                    "id": "Subject",
                    "name": "Subject",
                    "type": "string",
                    "value": '={{$(\'Webhook\').first().json["body"]["subject"]}}',
                },
                {
                    "id": "Message",
                    "name": "Message",
                    "type": "string",
                    "value": '={{$(\'Webhook\').first().json["body"]["message"]}}',
                },
            ]
        },
        "includeOtherFields": False,
        "options": {},
    }
    sheets = compiled.nodes[3].model_dump()
    assert sheets["parameters"]["operation"] == "append"
    assert sheets["parameters"]["documentId"] == {
        "__rl": True,
        "mode": "id",
        "value": "sheet_123",
    }
    assert sheets["parameters"]["sheetName"] == {
        "__rl": True,
        "mode": "name",
        "value": "Logs",
    }
    assert sheets["parameters"]["columns"] == {
        "mappingMode": "autoMapInputData",
        "value": {},
    }
    assert sheets["parameters"]["options"] == {"handlingExtraData": "insertInNewColumn"}
    assert compiled.connections == {
        "Webhook": {"main": [[{"node": "Gmail", "type": "main", "index": 0}]]},
        "Gmail": {"main": [[{"node": "Prepare Sheets Row", "type": "main", "index": 0}]]},
        "Prepare Sheets Row": {
            "main": [[{"node": "Google Sheets Append", "type": "main", "index": 0}]]
        },
    }


def test_compile_workflow_plan_rejects_missing_semantic_params(monkeypatch):
    monkeypatch.setattr(
        "src.agent.tools.registry.get_node_schema",
        lambda _node_type: {"typeVersion": 1},
    )

    with pytest.raises(WorkflowPlanCompileError, match="columns"):
        compile_workflow_plan(
            "Missing columns",
            WorkflowPlan(
                trigger=WorkflowTriggerSpec(kind="on_demand"),
                actions=[
                    WorkflowActionSpec(
                        id="log_email",
                        action="sheets.row.append",
                        params={"spreadsheet_id": "sheet_123", "sheet_name": "Logs"},
                    )
                ],
            ),
        )


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
async def test_create_workflow_from_plan_payload_creates_workflow_and_emits_oauth_prompts(
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
        "n8n-nodes-base.googleSheets": {
            "type": "n8n-nodes-base.googleSheets",
            "typeVersion": 4.7,
            "credentials": ["googleSheetsOAuth2Api"],
        },
        "n8n-nodes-base.set": {
            "type": "n8n-nodes-base.set",
            "typeVersion": 3.4,
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
        return SimpleNamespace(id="wf_plan", name=name, active=False)

    async def fake_get_workflow(_workflow_id: str):
        return {
            "id": "wf_plan",
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

    result = await create_workflow_from_plan_payload(
        deps,
        "Plan Gmail Log",
        WorkflowPlan(
            trigger=WorkflowTriggerSpec(kind="on_demand"),
            actions=[
                WorkflowActionSpec(
                    id="send_email",
                    action="gmail.send",
                    params={
                        "to": {"ref": "input.to"},
                        "subject": {"ref": "input.subject"},
                        "message": {"ref": "input.message"},
                    },
                ),
                WorkflowActionSpec(
                    id="log_email",
                    action="sheets.row.append",
                    after="send_email",
                    params={
                        "spreadsheet_id": "sheet_123",
                        "sheet_name": "Logs",
                        "columns": {
                            "To": {"ref": "input.to"},
                            "Subject": {"ref": "input.subject"},
                            "Message": {"ref": "input.message"},
                        },
                    },
                ),
            ],
        ),
    )

    assert result == {
        "id": "wf_plan",
        "name": "Plan Gmail Log",
        "active": False,
        "ready": False,
        "missing_credentials": 2,
        "instruction": (
            "Stop now. A credential or app connection request was shown to the user. "
            "Tell the user the workflow was created but needs that connection before it "
            "can run. Do not activate or execute the workflow until the user connects it."
        ),
    }
    assert [node["name"] for node in created["nodes"]] == [
        "Webhook",
        "Gmail",
        "Prepare Sheets Row",
        "Google Sheets Append",
    ]
    assert created["nodes"][2]["type"] == "n8n-nodes-base.set"
    assert created["nodes"][2]["parameters"]["includeOtherFields"] is False
    assert created["nodes"][3]["parameters"]["operation"] == "append"
    assert [field["name"] for field in saved["input_schema"]] == ["to", "subject", "message"]
    assert [attachment["type"] for attachment in deps.attachments] == [
        "workflow_preview",
        "oauth_prompt",
        "oauth_prompt",
    ]
    assert deps.awaiting_user_input is True


@pytest.mark.asyncio
async def test_create_workflow_from_plan_payload_returns_error_before_side_effects(
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

    result = await create_workflow_from_plan_payload(
        deps,
        "Plan Gmail",
        WorkflowPlan(
            trigger=WorkflowTriggerSpec(kind="on_demand"),
            actions=[
                WorkflowActionSpec(
                    id="send_email",
                    action="gmail.send",
                    params={
                        "to": {"ref": "input.to"},
                        "subject": {"ref": "input.subject"},
                        "message": {"ref": "input.message"},
                    },
                )
            ],
        ),
    )

    assert "registry schema" in result["error"]
    assert deps.attachments == []


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


@pytest.mark.asyncio
async def test_run_workflow_with_input_summarizes_execution_after_webhook_error(monkeypatch):
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

    async def fake_readiness(_workflow: dict, *, user_id: str):
        assert user_id == "user_1"
        return {"webhook_nodes": [{"parameters": {"path": "runtime-test", "httpMethod": "POST"}}]}

    async def fake_call_webhook(_path: str, _payload: dict):
        return httpx.Response(500, json={"message": "Error in workflow"})

    async def fake_list_executions(*_args, **_kwargs):
        return [SimpleNamespace(id="exec_1")]

    async def fake_get_execution_detail(_execution_id: str):
        return {
            "id": "exec_1",
            "workflowId": "wf_1",
            "status": "error",
            "data": {
                "resultData": {
                    "lastNodeExecuted": "Gmail",
                    "error": {
                        "node": {"name": "Gmail"},
                        "message": "Gmail credential token is invalid or expired.",
                    },
                    "runData": {},
                }
            },
        }

    monkeypatch.setattr("src.agent.tools.store.get_workflow_metadata", fake_get_workflow_metadata)
    monkeypatch.setattr(
        "src.agent.tools.workflow_runner.analyze_workflow_readiness_payload",
        fake_readiness,
    )
    monkeypatch.setattr("src.agent.tools.n8n_client.call_webhook", fake_call_webhook)
    monkeypatch.setattr("src.agent.tools.n8n_client.list_executions", fake_list_executions)
    monkeypatch.setattr(
        "src.agent.tools.n8n_client.get_execution_detail", fake_get_execution_detail
    )

    result = await run_workflow_with_input(
        {
            "id": "wf_1",
            "name": "Runtime workflow",
            "active": True,
            "nodes": [
                {
                    "name": "Webhook",
                    "type": "n8n-nodes-base.webhook",
                    "parameters": {"path": "runtime-test", "httpMethod": "POST"},
                },
                {
                    "name": "Gmail",
                    "type": "n8n-nodes-base.gmail",
                    "parameters": {"resource": "message", "operation": "send"},
                },
            ],
        },
        user_id="user_1",
        input_payload={"to": "person@example.com"},
    )

    assert result.status == "error"
    assert result.executionId == "exec_1"
    assert result.failedNode == "Gmail"
    assert result.error == "Gmail credential token is invalid or expired."
    assert "Gmail credential token" in result.summary


@pytest.mark.asyncio
async def test_run_workflow_batch_with_input_continues_after_row_errors(monkeypatch):
    sent_payloads: list[dict] = []

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

    async def fake_readiness(_workflow: dict, *, user_id: str):
        assert user_id == "user_1"
        return {"webhook_nodes": [{"parameters": {"path": "runtime-test", "httpMethod": "POST"}}]}

    async def fake_call_webhook(_path: str, payload: dict):
        sent_payloads.append(payload)
        if payload["to"] == "broken@example.com":
            raise RuntimeError("transport failed")
        return httpx.Response(200, json={"ok": True})

    async def fake_list_executions(*_args, **_kwargs):
        return []

    monkeypatch.setattr("src.agent.tools.store.get_workflow_metadata", fake_get_workflow_metadata)
    monkeypatch.setattr(
        "src.agent.tools.workflow_runner.analyze_workflow_readiness_payload",
        fake_readiness,
    )
    monkeypatch.setattr("src.agent.tools.n8n_client.call_webhook", fake_call_webhook)
    monkeypatch.setattr("src.agent.tools.n8n_client.list_executions", fake_list_executions)

    result = await run_workflow_batch_with_input(
        {
            "id": "wf_1",
            "name": "Runtime workflow",
            "active": True,
            "nodes": [
                {
                    "name": "Webhook",
                    "type": "n8n-nodes-base.webhook",
                    "parameters": {"path": "runtime-test", "httpMethod": "POST"},
                }
            ],
        },
        user_id="user_1",
        rows=[
            {"rowNumber": 2, "input": {"to": "person@example.com"}},
            {"rowNumber": 3, "input": {"to": ""}},
            {"rowNumber": 4, "input": {"to": "broken@example.com"}},
        ],
    )

    assert result.status == "completed_with_errors"
    assert result.succeeded == 1
    assert result.skipped == 1
    assert result.failed == 1
    assert [row.status for row in result.results] == ["success", "skipped", "failed"]
    assert sent_payloads == [{"to": "person@example.com"}, {"to": "broken@example.com"}]


@pytest.mark.asyncio
async def test_iter_workflow_batch_with_input_streams_row_progress(monkeypatch):
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

    async def fake_readiness(_workflow: dict, *, user_id: str):
        assert user_id == "user_1"
        return {"webhook_nodes": [{"parameters": {"path": "runtime-test", "httpMethod": "POST"}}]}

    async def fake_call_webhook(_path: str, _payload: dict):
        return httpx.Response(200, json={"ok": True})

    async def fake_list_executions(*_args, **_kwargs):
        return []

    monkeypatch.setattr("src.agent.tools.store.get_workflow_metadata", fake_get_workflow_metadata)
    monkeypatch.setattr(
        "src.agent.tools.workflow_runner.analyze_workflow_readiness_payload",
        fake_readiness,
    )
    monkeypatch.setattr("src.agent.tools.n8n_client.call_webhook", fake_call_webhook)
    monkeypatch.setattr("src.agent.tools.n8n_client.list_executions", fake_list_executions)

    events = [
        (event, payload)
        async for event, payload in iter_workflow_batch_with_input(
            {
                "id": "wf_1",
                "name": "Runtime workflow",
                "active": True,
                "nodes": [
                    {
                        "name": "Webhook",
                        "type": "n8n-nodes-base.webhook",
                        "parameters": {"path": "runtime-test", "httpMethod": "POST"},
                    }
                ],
            },
            user_id="user_1",
            rows=[
                {"rowNumber": 2, "input": {"to": "person@example.com"}},
                {"rowNumber": 3, "input": {"to": ""}},
            ],
        )
    ]

    assert [event for event, _payload in events] == [
        "started",
        "row_started",
        "row_finished",
        "row_started",
        "row_finished",
        "completed",
    ]
    assert events[0][1]["totalRows"] == 2
    assert events[1][1] == {"rowNumber": 2, "index": 1, "totalRows": 2}
    assert events[2][1].status == "success"
    assert events[4][1].status == "skipped"
    assert events[5][1].skipped == 1


@pytest.mark.asyncio
async def test_run_workflow_with_input_returns_sheets_artifact(monkeypatch):
    async def fake_get_workflow_metadata(_user_id: str, workflow_id: str):
        return store.WorkflowMetadata(
            workflow_id=workflow_id,
            input_schema=[],
            resources={
                "log.spreadsheet": {
                    "spreadsheet_id": "sheet_123",
                    "spreadsheet_url": "https://sheet.test",
                    "sheet_name": "Log",
                }
            },
            created_at="now",
            updated_at="now",
        )

    async def fake_call_webhook(_path: str, _payload: dict):
        return httpx.Response(200, json={"ok": True})

    async def fake_list_executions(*_args, **_kwargs):
        return [SimpleNamespace(id="exec_1")]

    async def fake_get_execution_detail(_execution_id: str):
        return {
            "id": "exec_1",
            "workflowId": "wf_1",
            "status": "success",
            "data": {
                "resultData": {
                    "runData": {
                        "Prepare Sheets Row": [
                            {
                                "data": {
                                    "main": [
                                        [
                                            {
                                                "json": {
                                                    "Email": "person@example.com",
                                                    "Status": "Sent",
                                                }
                                            }
                                        ]
                                    ]
                                }
                            }
                        ]
                    }
                }
            },
        }

    monkeypatch.setattr("src.agent.tools.store.get_workflow_metadata", fake_get_workflow_metadata)
    monkeypatch.setattr("src.agent.tools.n8n_client.call_webhook", fake_call_webhook)
    monkeypatch.setattr("src.agent.tools.n8n_client.list_executions", fake_list_executions)
    monkeypatch.setattr(
        "src.agent.tools.n8n_client.get_execution_detail",
        fake_get_execution_detail,
    )
    monkeypatch.setattr("src.agent.tools.registry.get_node_schema", lambda _node_type: None)

    result = await run_workflow_with_input(
        {
            "id": "wf_1",
            "name": "Runtime workflow",
            "active": True,
            "nodes": [
                {
                    "name": "Webhook",
                    "type": "n8n-nodes-base.webhook",
                    "parameters": {"path": "runtime-test", "httpMethod": "POST"},
                }
            ],
        },
        user_id="user_1",
        input_payload={},
    )

    assert result.status == "success"
    assert result.artifacts[0].title == "Google Sheets row added"
    assert result.artifacts[0].url == "https://sheet.test"
    assert result.artifacts[0].table is not None
    assert result.artifacts[0].table.rows == [{"Email": "person@example.com", "Status": "Sent"}]


@pytest.mark.asyncio
async def test_run_workflow_with_input_returns_gmail_artifact(monkeypatch):
    async def fake_get_workflow_metadata(_user_id: str, workflow_id: str):
        return store.WorkflowMetadata(
            workflow_id=workflow_id,
            input_schema=[],
            resources={},
            created_at="now",
            updated_at="now",
        )

    async def fake_call_webhook(_path: str, _payload: dict):
        return httpx.Response(200, json={"ok": True})

    async def fake_list_executions(*_args, **_kwargs):
        return [SimpleNamespace(id="exec_1")]

    async def fake_get_execution_detail(_execution_id: str):
        return {
            "id": "exec_1",
            "workflowId": "wf_1",
            "status": "success",
            "data": {
                "resultData": {
                    "runData": {
                        "Gmail": [
                            {
                                "data": {
                                    "main": [
                                        [
                                            {
                                                "json": {
                                                    "id": "msg_123",
                                                    "threadId": "thread_123",
                                                    "labelIds": ["SENT"],
                                                }
                                            }
                                        ]
                                    ]
                                }
                            }
                        ]
                    }
                }
            },
        }

    monkeypatch.setattr("src.agent.tools.store.get_workflow_metadata", fake_get_workflow_metadata)
    monkeypatch.setattr("src.agent.tools.n8n_client.call_webhook", fake_call_webhook)
    monkeypatch.setattr("src.agent.tools.n8n_client.list_executions", fake_list_executions)
    monkeypatch.setattr(
        "src.agent.tools.n8n_client.get_execution_detail",
        fake_get_execution_detail,
    )
    monkeypatch.setattr("src.agent.tools.registry.get_node_schema", lambda _node_type: None)

    result = await run_workflow_with_input(
        {
            "id": "wf_1",
            "name": "Runtime workflow",
            "active": True,
            "nodes": [
                {
                    "name": "Webhook",
                    "type": "n8n-nodes-base.webhook",
                    "parameters": {"path": "runtime-test", "httpMethod": "POST"},
                }
            ],
        },
        user_id="user_1",
        input_payload={},
    )

    assert result.status == "success"
    assert result.artifacts[0].service == "gmail"
    assert result.artifacts[0].title == "Gmail message sent"
    assert result.artifacts[0].url == "https://mail.google.com/mail/u/0/#all/msg_123"
    assert result.artifacts[0].message is not None
    assert result.artifacts[0].message.messageId == "msg_123"


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
