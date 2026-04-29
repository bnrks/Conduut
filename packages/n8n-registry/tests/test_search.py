from n8n_registry.models import NodeInfo
from n8n_registry.search import build_schema_response


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
