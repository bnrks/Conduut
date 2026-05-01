import pytest
from pydantic_ai import ModelRetry

from src.agent.schemas import WorkflowNode
from src.agent.tools import (
    _summarize_execution,
    _validated_workflow,
    analyze_workflow_readiness_payload,
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
