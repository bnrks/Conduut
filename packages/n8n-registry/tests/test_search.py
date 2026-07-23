import json

from n8n_registry.loader import parse_nodes_json
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


def _anthropic_chat_model_raw() -> dict:
    return {
        "name": "@n8n/n8n-nodes-langchain.lmChatAnthropic",
        "displayName": "Anthropic Chat Model",
        "description": "Anthropic chat model",
        "version": [1, 1.1, 1.2, 1.3],
        "properties": [
            {
                "displayName": "Model",
                "name": "model",
                "type": "options",
                "default": "claude-3-5-sonnet-20241022",
                "options": [
                    {"name": "Claude 3 Haiku", "value": "claude-3-haiku-20240307"},
                    {"name": "Claude 3.5 Sonnet", "value": "claude-3-5-sonnet-20241022"},
                ],
                "displayOptions": {"show": {"@version": [{"_cnd": {"lte": 1.2}}]}},
            },
            {
                "displayName": "Model",
                "name": "model",
                "type": "resourceLocator",
                "default": {
                    "mode": "list",
                    "value": "claude-sonnet-4-5-20250929",
                    "cachedResultName": "Claude Sonnet 4.5",
                },
                "required": True,
                "modes": [
                    {
                        "displayName": "From List",
                        "name": "list",
                        "type": "list",
                        "typeOptions": {
                            "searchListMethod": "searchModels",
                            "searchable": True,
                        },
                    },
                    {"displayName": "ID", "name": "id", "type": "string"},
                ],
                "displayOptions": {"show": {"@version": [{"_cnd": {"gte": 1.3}}]}},
            },
            {
                "displayName": "Options",
                "name": "options",
                "type": "collection",
                "default": {},
            },
        ],
    }


def test_anthropic_chat_model_schema_keeps_latest_resource_locator_model():
    node = parse_nodes_json([_anthropic_chat_model_raw()])[0]
    schema = build_schema_response(node)

    model_param = next(param for param in schema["keyParameters"] if param["name"] == "model")

    assert schema["type"] == "@n8n/n8n-nodes-langchain.lmChatAnthropic"
    assert schema["typeVersion"] == 1.3
    assert model_param["type"] == "resourceLocator"
    assert model_param["default"]["value"] == "claude-sonnet-4-5-20250929"
    assert model_param["modes"][0]["typeOptions"]["searchListMethod"] == "searchModels"
    assert "claude-3-haiku-20240307" not in json.dumps(model_param)
    assert schema["exampleNode"]["parameters"]["model"] == {
        "__rl": True,
        "mode": "list",
        "value": "claude-sonnet-4-5-20250929",
    }


def test_display_options_version_conditions_filter_latest_parameters():
    raw = {
        "name": "n8n-nodes-base.versioned",
        "displayName": "Versioned",
        "description": "Version condition test",
        "version": [1, 1.1, 1.2, 1.3],
        "properties": [
            {
                "displayName": "Included By Show",
                "name": "includedByShow",
                "type": "string",
                "default": "",
                "displayOptions": {"show": {"@version": [{"_cnd": {"gte": 1.3}}]}},
            },
            {
                "displayName": "Old Show",
                "name": "oldShow",
                "type": "string",
                "default": "",
                "displayOptions": {"show": {"@version": [{"_cnd": {"lte": 1.2}}]}},
            },
            {
                "displayName": "Included By Hide",
                "name": "includedByHide",
                "type": "string",
                "default": "",
                "displayOptions": {"hide": {"@version": [{"_cnd": {"lte": 1.1}}]}},
            },
            {
                "displayName": "Hidden Latest",
                "name": "hiddenLatest",
                "type": "string",
                "default": "",
                "displayOptions": {"hide": {"@version": [{"_cnd": {"gte": 1.2}}]}},
            },
            {
                "displayName": "Resource Conditional",
                "name": "resourceConditional",
                "type": "string",
                "default": "",
                "displayOptions": {"show": {"resource": ["message"]}},
            },
        ],
    }

    node = parse_nodes_json([raw])[0]
    names = {param["name"] for param in node.key_properties}

    assert "includedByShow" in names
    assert "includedByHide" in names
    assert "oldShow" not in names
    assert "hiddenLatest" not in names
    assert "resourceConditional" not in names


def test_if_schema_includes_operator_object_conditions_example():
    schema = build_schema_response(
        NodeInfo(
            type_name="n8n-nodes-base.if",
            display_name="If",
            description="Branch on conditions",
            type_version=2.2,
            credentials=[],
            category="Core Nodes",
            is_trigger=False,
            key_properties=[
                {
                    "name": "conditions",
                    "displayName": "Conditions",
                    "type": "fixedCollection",
                }
            ],
        )
    )

    rule = schema["exampleNode"]["parameters"]["conditions"]["conditions"][0]

    assert rule["operator"] == {"type": "string", "operation": "equals"}
    assert schema["exampleNode"]["parameters"]["conditions"]["combinator"] == "and"
    assert schema["exampleNode"]["parameters"]["conditions"]["options"]["version"] == 2
    assert schema["usageHints"]


def test_filter_schema_includes_operator_object_conditions_example():
    schema = build_schema_response(
        NodeInfo(
            type_name="n8n-nodes-base.filter",
            display_name="Filter",
            description="Keep matching items",
            type_version=2.1,
            credentials=[],
            category="Core Nodes",
            is_trigger=False,
            key_properties=[],
        )
    )

    rule = schema["exampleNode"]["parameters"]["conditions"]["conditions"][0]

    assert rule["operator"] == {"type": "string", "operation": "equals"}
    assert schema["exampleNode"]["parameters"]["conditions"]["combinator"] == "and"
    assert schema["exampleNode"]["parameters"]["conditions"]["options"]["version"] == 2
    assert "single-path row elimination" in " ".join(schema["usageHints"])


def test_code_schema_adds_jscode_and_canonical_javascript_example_despite_display_options():
    raw = {
        "name": "n8n-nodes-base.code",
        "displayName": "Code",
        "description": "Run custom code",
        "version": [1, 2],
        "properties": [
            {
                "displayName": "Mode",
                "name": "mode",
                "type": "options",
                "default": "runOnceForAllItems",
                "options": [{"name": "Run Once", "value": "runOnceForAllItems"}],
            },
            {
                "displayName": "Language",
                "name": "language",
                "type": "options",
                "default": "javaScript",
                "options": [
                    {"name": "JavaScript", "value": "javaScript"},
                    {"name": "Python", "value": "python"},
                    {"name": "Python (Native)", "value": "pythonNative"},
                ],
            },
            {
                "displayName": "JavaScript Code",
                "name": "jsCode",
                "type": "string",
                "default": "",
                "displayOptions": {"show": {"language": ["javaScript"]}},
            },
            {
                "displayName": "Python Code",
                "name": "pythonCode",
                "type": "string",
                "default": "",
                "displayOptions": {"show": {"language": ["python"]}},
            },
        ],
    }

    node = parse_nodes_json([raw])[0]
    schema = build_schema_response(node)

    js_code = next(param for param in schema["keyParameters"] if param["name"] == "jsCode")
    language = next(param for param in schema["keyParameters"] if param["name"] == "language")

    assert language["default"] == "javaScript"
    assert js_code["name"] == "jsCode"
    assert schema["exampleNode"]["parameters"]["language"] == "javaScript"
    assert "jsCode" in schema["exampleNode"]["parameters"]
