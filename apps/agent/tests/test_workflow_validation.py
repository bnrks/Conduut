from typing import Any

from src.agent.validation import (
    normalize_workflow_connections,
    normalize_workflow_nodes,
    validate_workflow_payload,
)


class FakeRegistry:
    def __init__(self, schemas: dict[str, dict[str, Any]]):
        self.schemas = schemas

    def get_node_schema(self, node_type: str):
        if node_type in self.schemas:
            return self.schemas[node_type]
        for schema in self.schemas.values():
            if schema["type"].split(".")[-1].lower() == node_type.lower():
                return schema
        return None


SCHEMAS = {
    "n8n-nodes-base.manualTrigger": {
        "type": "n8n-nodes-base.manualTrigger",
        "typeVersion": 1,
        "isTrigger": True,
    },
    "n8n-nodes-base.set": {
        "type": "n8n-nodes-base.set",
        "typeVersion": 3.4,
        "isTrigger": False,
    },
    "n8n-nodes-base.gmail": {
        "type": "n8n-nodes-base.gmail",
        "typeVersion": 2.1,
        "isTrigger": False,
    },
    "n8n-nodes-base.googleSheets": {
        "type": "n8n-nodes-base.googleSheets",
        "typeVersion": 4.7,
        "isTrigger": False,
    },
}


def valid_nodes():
    return [
        {
            "id": "trigger",
            "name": "Manual Trigger",
            "type": "n8n-nodes-base.manualTrigger",
            "typeVersion": 1,
            "position": [250, 300],
            "parameters": {},
        },
        {
            "id": "set",
            "name": "Set",
            "type": "n8n-nodes-base.set",
            "typeVersion": 3.4,
            "position": [500, 300],
            "parameters": {
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
        },
    ]


def test_valid_minimal_workflow_passes():
    errors = validate_workflow_payload(
        valid_nodes(),
        {"Manual Trigger": {"main": [[{"node": "Set", "type": "main", "index": 0}]]}},
        node_registry=FakeRegistry(SCHEMAS),  # type: ignore[arg-type]
    )

    assert errors == []


def test_normalize_chat_model_wraps_model_as_resource_locator():
    # n8n's lmChat* nodes expect `model` as a resourceLocator, not a plain
    # string; a bare string raises "Could not get parameter" at run time.
    nodes = [
        {
            "name": "OpenAI Chat Model",
            "type": "@n8n/n8n-nodes-langchain.lmChatOpenAi",
            "typeVersion": 1.3,
            "position": [0, 0],
            "parameters": {"model": "gpt-4o-mini", "options": {}},
        }
    ]
    out = normalize_workflow_nodes(nodes, node_registry=FakeRegistry({}))  # type: ignore[arg-type]
    assert out[0].parameters["model"] == {"__rl": True, "mode": "list", "value": "gpt-4o-mini"}


def test_normalize_chat_model_leaves_resource_locator_untouched():
    rl = {"__rl": True, "mode": "list", "value": "gpt-4o"}
    nodes = [
        {
            "name": "OpenAI Chat Model",
            "type": "@n8n/n8n-nodes-langchain.lmChatOpenAi",
            "typeVersion": 1.3,
            "position": [0, 0],
            "parameters": {"model": rl},
        }
    ]
    out = normalize_workflow_nodes(nodes, node_registry=FakeRegistry({}))  # type: ignore[arg-type]
    assert out[0].parameters["model"] == rl


def test_normalize_connections_assigns_ai_port_type():
    # The connection type under an AI sub-node port must be the port name, not
    # "main" — otherwise n8n ignores the chat model and the agent runs empty.
    nodes = [
        {"name": "Webhook", "type": "n8n-nodes-base.webhook"},
        {"name": "OpenAI Chat Model", "type": "@n8n/n8n-nodes-langchain.lmChatOpenAi"},
        {"name": "AI Agent", "type": "@n8n/n8n-nodes-langchain.agent"},
    ]
    connections = {
        "Webhook": {"main": [[{"node": "AI Agent"}]]},
        "OpenAI Chat Model": {"ai_languageModel": [[{"node": "AI Agent"}]]},
    }
    out = normalize_workflow_connections(connections, nodes)
    assert out["OpenAI Chat Model"]["ai_languageModel"][0][0]["type"] == "ai_languageModel"
    assert out["Webhook"]["main"][0][0]["type"] == "main"


def test_empty_nodes_fail():
    errors = validate_workflow_payload([], {}, node_registry=FakeRegistry({}))  # type: ignore[arg-type]

    assert errors == ["nodes array is empty; every workflow needs at least one trigger node"]


def test_duplicate_node_ids_fail():
    nodes = valid_nodes()
    nodes[1]["id"] = "trigger"

    errors = validate_workflow_payload(nodes, {}, node_registry=FakeRegistry(SCHEMAS))  # type: ignore[arg-type]

    assert "Duplicate node id: 'trigger'" in errors


def test_missing_required_field_fails():
    nodes = valid_nodes()
    del nodes[0]["parameters"]

    errors = validate_workflow_payload(nodes, {}, node_registry=FakeRegistry(SCHEMAS))  # type: ignore[arg-type]

    assert "Node 'Manual Trigger' missing required field: parameters" in errors


def test_missing_trigger_fails():
    nodes = [valid_nodes()[1]]

    errors = validate_workflow_payload(nodes, {}, node_registry=FakeRegistry(SCHEMAS))  # type: ignore[arg-type]

    assert "No trigger node found; workflow needs a trigger node" in errors


def test_invalid_type_version_fails():
    nodes = valid_nodes()
    nodes[1]["typeVersion"] = 2

    errors = validate_workflow_payload(nodes, {}, node_registry=FakeRegistry(SCHEMAS))  # type: ignore[arg-type]

    assert "Node 'Set' typeVersion must be 3.4 for n8n-nodes-base.set" in errors


def test_non_numeric_type_version_fails():
    nodes = valid_nodes()
    nodes[1]["typeVersion"] = "3.4"

    errors = validate_workflow_payload(nodes, {}, node_registry=FakeRegistry(SCHEMAS))  # type: ignore[arg-type]

    assert "Node 'Set' typeVersion must be a number" in errors


def test_set_node_without_assignments_fails():
    nodes = valid_nodes()
    nodes[1]["parameters"] = {"mode": "manual", "options": {}}

    errors = validate_workflow_payload(nodes, {}, node_registry=FakeRegistry(SCHEMAS))  # type: ignore[arg-type]

    assert (
        "Set node 'Set' must define parameters.assignments.assignments with at least one field"
        in errors
    )


def test_set_node_assignment_missing_value_fails():
    nodes = valid_nodes()
    del nodes[1]["parameters"]["assignments"]["assignments"][0]["value"]

    errors = validate_workflow_payload(nodes, {}, node_registry=FakeRegistry(SCHEMAS))  # type: ignore[arg-type]

    assert "Set node 'Set assignment 1' missing required field: value" in errors


def test_set_node_raw_mode_requires_json_output():
    nodes = valid_nodes()
    nodes[1]["parameters"] = {"mode": "raw", "options": {}}

    errors = validate_workflow_payload(nodes, {}, node_registry=FakeRegistry(SCHEMAS))  # type: ignore[arg-type]

    assert "Set node 'Set' raw mode requires parameters.jsonOutput" in errors


def test_normalize_workflow_nodes_canonicalizes_shorthand_type_and_version():
    nodes = valid_nodes()
    nodes[1]["type"] = "set"
    nodes[1]["typeVersion"] = 1

    normalized = normalize_workflow_nodes(nodes, node_registry=FakeRegistry(SCHEMAS))  # type: ignore[arg-type]

    assert normalized[1].type == "n8n-nodes-base.set"
    assert normalized[1].typeVersion == 3.4


def test_normalize_workflow_nodes_rewrites_gmail_message_create_to_send():
    nodes = valid_nodes()
    nodes.append(
        {
            "id": "gmail",
            "name": "Gmail",
            "type": "n8n-nodes-base.gmail",
            "typeVersion": 2.1,
            "position": [750, 300],
            "parameters": {
                "resource": "message",
                "operation": "create",
                "authentication": "oAuth2",
            },
        }
    )

    normalized = normalize_workflow_nodes(nodes, node_registry=FakeRegistry(SCHEMAS))  # type: ignore[arg-type]

    assert normalized[2].parameters["operation"] == "send"


def test_normalize_workflow_nodes_maps_gmail_send_alias_parameters():
    nodes = valid_nodes()
    nodes.append(
        {
            "id": "gmail",
            "name": "Gmail",
            "type": "n8n-nodes-base.gmail",
            "typeVersion": 2.1,
            "position": [750, 300],
            "parameters": {
                "resource": "message",
                "operation": "send",
                "toEmail": "user@example.test",
                "subject": "Hello",
                "bodyContent": "Message body",
            },
        }
    )

    normalized = normalize_workflow_nodes(nodes, node_registry=FakeRegistry(SCHEMAS))  # type: ignore[arg-type]

    assert normalized[2].parameters["sendTo"] == "user@example.test"
    assert normalized[2].parameters["subject"] == "Hello"
    assert normalized[2].parameters["message"] == "Message body"
    assert "toEmail" not in normalized[2].parameters
    assert "bodyContent" not in normalized[2].parameters


def test_normalize_workflow_nodes_rewrites_google_sheets_append_resource_to_sheet():
    nodes = valid_nodes()
    nodes.append(
        {
            "id": "sheets",
            "name": "Google Sheets",
            "type": "n8n-nodes-base.googleSheets",
            "typeVersion": 4.7,
            "position": [750, 300],
            "parameters": {
                "resource": "spreadsheet",
                "operation": "append",
                "authentication": "oAuth2",
            },
        }
    )

    normalized = normalize_workflow_nodes(nodes, node_registry=FakeRegistry(SCHEMAS))  # type: ignore[arg-type]

    assert normalized[2].parameters["resource"] == "sheet"


def test_gmail_send_placeholder_recipient_fails_validation():
    nodes = valid_nodes()
    nodes.append(
        {
            "id": "gmail",
            "name": "Gmail",
            "type": "n8n-nodes-base.gmail",
            "typeVersion": 2.1,
            "position": [750, 300],
            "parameters": {
                "resource": "message",
                "operation": "send",
                "sendTo": "receiver@email.com",
                "subject": "Hello",
                "message": "Message body",
            },
        }
    )

    errors = validate_workflow_payload(nodes, {}, node_registry=FakeRegistry(SCHEMAS))  # type: ignore[arg-type]

    assert "Gmail node 'Gmail' sendTo must be a real recipient email" in errors


def test_gmail_send_runtime_expression_recipient_passes_validation():
    nodes = valid_nodes()
    nodes.append(
        {
            "id": "gmail",
            "name": "Gmail",
            "type": "n8n-nodes-base.gmail",
            "typeVersion": 2.1,
            "position": [750, 300],
            "parameters": {
                "resource": "message",
                "operation": "send",
                "sendTo": "={{$json.to}}",
                "subject": "={{$json.subject}}",
                "message": "={{$json.message}}",
            },
        }
    )

    errors = validate_workflow_payload(nodes, {}, node_registry=FakeRegistry(SCHEMAS))  # type: ignore[arg-type]

    assert errors == []


def test_gmail_send_missing_message_fails_validation():
    nodes = valid_nodes()
    nodes.append(
        {
            "id": "gmail",
            "name": "Gmail",
            "type": "n8n-nodes-base.gmail",
            "typeVersion": 2.1,
            "position": [750, 300],
            "parameters": {
                "resource": "message",
                "operation": "send",
                "sendTo": "user@example.test",
                "subject": "Hello",
            },
        }
    )

    errors = validate_workflow_payload(nodes, {}, node_registry=FakeRegistry(SCHEMAS))  # type: ignore[arg-type]

    assert "Gmail node 'Gmail' send operation requires parameters.message" in errors


def test_normalize_workflow_connections_resolves_node_ids_to_names():
    nodes = valid_nodes()
    nodes[0]["id"] = "1"
    nodes[1]["id"] = "2"

    normalized = normalize_workflow_connections(
        {"1": {"main": [[{"node": "2", "type": "main", "index": 0}]]}},
        nodes,
    )

    assert normalized == {
        "Manual Trigger": {"main": [[{"node": "Set", "type": "main", "index": 0}]]}
    }


def test_normalize_workflow_connections_resolves_ordinal_aliases_to_names():
    normalized = normalize_workflow_connections(
        {"node1": {"main": [[{"node": "node2", "type": "main", "index": 0}]]}},
        valid_nodes(),
    )

    assert normalized == {
        "Manual Trigger": {"main": [[{"node": "Set", "type": "main", "index": 0}]]}
    }


def test_normalize_workflow_connections_wraps_flat_main_targets():
    normalized = normalize_workflow_connections(
        {"Manual Trigger": {"main": [{"node": "Set", "type": "main"}]}},
        valid_nodes(),
    )

    assert normalized == {
        "Manual Trigger": {"main": [[{"node": "Set", "type": "main", "index": 0}]]}
    }


def test_normalize_workflow_connections_adds_main_for_direct_target():
    normalized = normalize_workflow_connections(
        {"Manual Trigger": {"node": "Set"}},
        valid_nodes(),
    )

    assert normalized == {
        "Manual Trigger": {"main": [[{"node": "Set", "type": "main", "index": 0}]]}
    }


def test_bad_connection_reference_fails():
    errors = validate_workflow_payload(
        valid_nodes(),
        {"Manual Trigger": {"main": [[{"node": "Missing", "type": "main", "index": 0}]]}},
        node_registry=FakeRegistry(SCHEMAS),  # type: ignore[arg-type]
    )

    assert "connections references unknown target node 'Missing'" in errors


def test_langchain_chat_model_wired_into_main_flow_fails():
    """Reproduces the empty-email bug: a langchain chat-model sub-node has no
    main output, so wiring it into the main flow yields empty downstream data.
    It must attach to an AI Agent via an ai_languageModel port instead."""
    nodes = valid_nodes()
    nodes.append(
        {
            "id": "chat",
            "name": "OpenAI Chat Model",
            "type": "@n8n/n8n-nodes-langchain.lmChatOpenAi",
            "typeVersion": 1.2,
            "position": [750, 300],
            "parameters": {"model": {"__rl": True, "mode": "list", "value": "gpt-4o-mini"}},
        }
    )
    connections = {
        "Manual Trigger": {"main": [[{"node": "OpenAI Chat Model", "type": "main", "index": 0}]]},
    }

    errors = validate_workflow_payload(
        nodes,
        connections,
        node_registry=FakeRegistry(SCHEMAS),  # type: ignore[arg-type]
    )

    assert any("OpenAI Chat Model" in error and "ai_languageModel" in error for error in errors), (
        errors
    )


def test_langchain_chat_model_as_main_source_fails():
    """A chat-model sub-node must not be a source of a main connection either."""
    nodes = valid_nodes()
    nodes.append(
        {
            "id": "chat",
            "name": "OpenAI Chat Model",
            "type": "@n8n/n8n-nodes-langchain.lmChatOpenAi",
            "typeVersion": 1.2,
            "position": [750, 300],
            "parameters": {"model": {"__rl": True, "mode": "list", "value": "gpt-4o-mini"}},
        }
    )
    connections = {
        "Manual Trigger": {"main": [[{"node": "OpenAI Chat Model", "type": "main", "index": 0}]]},
        "OpenAI Chat Model": {"main": [[{"node": "Set", "type": "main", "index": 0}]]},
    }

    errors = validate_workflow_payload(
        nodes,
        connections,
        node_registry=FakeRegistry(SCHEMAS),  # type: ignore[arg-type]
    )

    assert any("OpenAI Chat Model" in error and "ai_languageModel" in error for error in errors), (
        errors
    )


def test_langchain_chat_model_attached_via_ai_port_passes():
    """A chat model correctly attached to an AI Agent via the ai_languageModel
    port is valid and must not trigger the sub-node guard (no false positive)."""
    nodes = [
        valid_nodes()[0],
        {
            "id": "agent",
            "name": "AI Agent",
            "type": "@n8n/n8n-nodes-langchain.agent",
            "typeVersion": 1.9,
            "position": [500, 300],
            "parameters": {"promptType": "define", "text": "hello", "options": {}},
        },
        {
            "id": "chat",
            "name": "OpenAI Chat Model",
            "type": "@n8n/n8n-nodes-langchain.lmChatOpenAi",
            "typeVersion": 1.2,
            "position": [500, 520],
            "parameters": {"model": {"__rl": True, "mode": "list", "value": "gpt-4o-mini"}},
        },
    ]
    connections = {
        "Manual Trigger": {"main": [[{"node": "AI Agent", "type": "main", "index": 0}]]},
        "OpenAI Chat Model": {
            "ai_languageModel": [[{"node": "AI Agent", "type": "ai_languageModel", "index": 0}]]
        },
    }

    errors = validate_workflow_payload(
        nodes,
        connections,
        node_registry=FakeRegistry(SCHEMAS),  # type: ignore[arg-type]
    )

    assert errors == [], errors


def test_bare_input_expression_fails():
    """The agent sometimes leaks the graph-ref syntax {{input.x}} into raw JSON.
    'input' is not an n8n variable, so the field renders empty and the AI prompt
    or email loses the runtime values. It must use the trigger json.body path."""
    nodes = valid_nodes()
    nodes[1]["parameters"]["assignments"]["assignments"][0]["value"] = (
        "=Merhaba {{input.company_name}}, teklifimiz hazir."
    )

    errors = validate_workflow_payload(
        nodes,
        {"Manual Trigger": {"main": [[{"node": "Set", "type": "main", "index": 0}]]}},
        node_registry=FakeRegistry(SCHEMAS),  # type: ignore[arg-type]
    )

    assert any("input." in error and "Set" in error for error in errors), errors


def test_valid_trigger_body_expression_passes():
    """Referencing runtime input through the trigger json.body path is valid."""
    nodes = valid_nodes()
    nodes[1]["parameters"]["assignments"]["assignments"][0]["value"] = (
        "={{$('Manual Trigger').first().json.body.company_name}}"
    )

    errors = validate_workflow_payload(
        nodes,
        {"Manual Trigger": {"main": [[{"node": "Set", "type": "main", "index": 0}]]}},
        node_registry=FakeRegistry(SCHEMAS),  # type: ignore[arg-type]
    )

    assert errors == [], errors
