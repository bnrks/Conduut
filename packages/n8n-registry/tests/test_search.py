from n8n_registry.models import NodeInfo
from n8n_registry.registry import NodeRegistry
from n8n_registry.search import build_schema_response


def _node(index: int) -> NodeInfo:
    return NodeInfo(
        type_name=f"n8n-nodes-base.email{index}",
        display_name=f"Email {index}",
        description="Send email",
        type_version=1,
        credentials=[],
        category="Communication",
        is_trigger=False,
    )


def test_registry_search_nodes_defaults_to_twenty_and_clamps_limit():
    registry = NodeRegistry()
    registry._nodes = [_node(index) for index in range(25)]

    assert len(registry.search_nodes("email")) == 20
    assert len(registry.search_nodes("email", limit=0)) == 1
    assert len(registry.search_nodes("email", limit=60)) == 25


def test_set_node_schema_uses_assignments_example():
    schema = build_schema_response(
        NodeInfo(
            type_name="n8n-nodes-base.set",
            display_name="Edit Fields (Set)",
            description="Modify, add, or remove item fields",
            type_version=3.4,
            credentials=[],
            category="Core Nodes",
            is_trigger=False,
            key_properties=[
                {
                    "name": "mode",
                    "displayName": "Mode",
                    "type": "options",
                    "required": False,
                    "default": "manual",
                },
                {
                    "name": "options",
                    "displayName": "Options",
                    "type": "collection",
                    "required": False,
                    "default": {},
                },
            ],
        )
    )

    assignments = schema["exampleNode"]["parameters"]["assignments"]["assignments"]

    assert schema["exampleNode"]["type"] == "n8n-nodes-base.set"
    assert schema["exampleNode"]["typeVersion"] == 3.4
    assert assignments == [
        {
            "id": "message",
            "name": "message",
            "type": "string",
            "value": "hello from Conduut",
        }
    ]
    assert schema["usageHints"]
