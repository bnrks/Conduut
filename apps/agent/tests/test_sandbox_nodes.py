"""Tests for the side-effect action-node classifier (agent.sandbox_nodes)."""

from src.agent.sandbox_nodes import (
    find_action_nodes,
    is_side_effect_node,
    neutralize_action_nodes,
    replace_action_nodes_with_probes,
)


def test_gmail_send_is_side_effect():
    node = {"type": "n8n-nodes-base.gmail", "parameters": {"operation": "send"}}
    assert is_side_effect_node(node) is True


def test_gmail_read_is_not_side_effect():
    node = {"type": "n8n-nodes-base.gmail", "parameters": {"operation": "getAll"}}
    assert is_side_effect_node(node) is False


def test_sheets_append_is_side_effect():
    node = {"type": "n8n-nodes-base.googleSheets", "parameters": {"operation": "append"}}
    assert is_side_effect_node(node) is True


def test_sheets_read_is_not_side_effect():
    node = {"type": "n8n-nodes-base.googleSheets", "parameters": {"operation": "read"}}
    assert is_side_effect_node(node) is False


def test_http_get_is_not_side_effect():
    node = {"type": "n8n-nodes-base.httpRequest", "parameters": {"method": "GET"}}
    assert is_side_effect_node(node) is False


def test_http_post_is_side_effect():
    node = {"type": "n8n-nodes-base.httpRequest", "parameters": {"method": "POST"}}
    assert is_side_effect_node(node) is True


def test_slack_is_side_effect():
    assert is_side_effect_node({"type": "n8n-nodes-base.slack", "parameters": {}}) is True


def test_webhook_trigger_is_not_side_effect():
    assert is_side_effect_node({"type": "n8n-nodes-base.webhook", "parameters": {}}) is False


def test_neutralize_sets_disabled_and_returns_names():
    nodes = [
        {"name": "Hook", "type": "n8n-nodes-base.webhook", "parameters": {}},
        {"name": "Send", "type": "n8n-nodes-base.gmail", "parameters": {"operation": "send"}},
    ]
    neutralized = neutralize_action_nodes(nodes)
    assert neutralized == ["Send"]
    assert nodes[1]["disabled"] is True
    assert "disabled" not in nodes[0]


def test_find_action_nodes_filters():
    nodes = [
        {"name": "Hook", "type": "n8n-nodes-base.webhook", "parameters": {}},
        {"name": "Send", "type": "n8n-nodes-base.gmail", "parameters": {"operation": "send"}},
    ]
    found = find_action_nodes(nodes)
    assert [n["name"] for n in found] == ["Send"]


def test_gmail_send_is_replaced_with_output_shape_probe():
    nodes = [
        {
            "name": "Send",
            "type": "n8n-nodes-base.gmail",
            "parameters": {
                "operation": "send",
                "sendTo": "={{ $json.email }}",
                "subject": "Reminder",
                "message": "={{ $json.body }}",
            },
            "credentials": {"gmailOAuth2": {"id": "secret"}},
        }
    ]
    probes = replace_action_nodes_with_probes(nodes)
    assert probes[0].covered is True
    assert probes[0].kind == "gmail_send"
    assert nodes[0]["type"] == "n8n-nodes-base.set"
    assert "credentials" not in nodes[0]
    assignments = nodes[0]["parameters"]["assignments"]["assignments"]
    names = {item["name"] for item in assignments}
    assert names == {
        "id",
        "threadId",
        "labelIds",
        "__conduut_probe",
        "__conduut_probe_target",
        "__conduut_probe_subject",
        "__conduut_probe_message",
    }
    probe_values = {item["name"]: item["value"] for item in assignments}
    assert probe_values["__conduut_probe"] == "gmail_send"
    assert probe_values["__conduut_probe_target"] == "={{ $json.email }}"


def test_sheets_probe_uses_flat_reserved_metadata_fields():
    nodes = [
        {
            "name": "Update",
            "type": "n8n-nodes-base.googleSheets",
            "parameters": {
                "operation": "update",
                "columns": {
                    "matchingColumns": ["customer_id"],
                    "value": {"customer_id": "={{ $json.customer_id }}", "status": "sent"},
                },
            },
        }
    ]

    probes = replace_action_nodes_with_probes(nodes)
    assignments = nodes[0]["parameters"]["assignments"]["assignments"]
    probe_values = {item["name"]: item["value"] for item in assignments}

    assert probes[0].covered is True
    assert probe_values["__conduut_probe"] == "sheets_update"
    assert probe_values["__conduut_probe_matching_key_0"] == "customer_id"
    assert probe_values["__conduut_probe_matching_value_0"] == "={{ $json.customer_id }}"


def test_unsupported_action_is_disabled_and_partial():
    nodes = [{"name": "Slack", "type": "n8n-nodes-base.slack", "parameters": {}}]
    probes = replace_action_nodes_with_probes(nodes)
    assert probes[0].covered is False
    assert nodes[0]["disabled"] is True
