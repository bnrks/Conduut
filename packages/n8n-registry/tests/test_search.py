from n8n_registry.models import NodeInfo
from n8n_registry.registry import NodeRegistry
from n8n_registry.search import build_schema_response, collect_credential_types


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


def _cred_node(type_name, display_name, creds):
    return NodeInfo(
        type_name=type_name,
        display_name=display_name,
        description="",
        type_version=1,
        credentials=creds,
        category="",
        is_trigger=False,
    )


def test_collect_credential_types_aggregates_nodes():
    nodes = [
        _cred_node("n8n-nodes-base.openAi", "OpenAI", ["openAiApi"]),
        _cred_node("@n8n/n8n-nodes-langchain.lmChatOpenAi", "OpenAI Chat Model", ["openAiApi"]),
        _cred_node("n8n-nodes-base.slack", "Slack", ["slackApi", "slackOAuth2Api"]),
        _cred_node("n8n-nodes-base.noAuth", "No Auth", []),
    ]
    result = collect_credential_types(nodes)
    by_type = {entry["type"]: entry["nodes"] for entry in result}
    assert set(by_type) == {"openAiApi", "slackApi", "slackOAuth2Api"}
    assert by_type["openAiApi"] == ["OpenAI", "OpenAI Chat Model"]
    assert [entry["type"] for entry in result] == sorted(by_type)


def test_registry_list_credential_types():
    registry = NodeRegistry()
    registry._nodes = [_cred_node("n8n-nodes-base.openAi", "OpenAI", ["openAiApi"])]
    assert registry.list_credential_types() == [{"type": "openAiApi", "nodes": ["OpenAI"]}]
