import pytest
from pydantic_ai import ModelRetry

from src.agent.schemas import WorkflowNode
from src.agent.tools import _validated_workflow


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
