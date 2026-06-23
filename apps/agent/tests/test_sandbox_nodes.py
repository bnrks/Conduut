"""Tests for the side-effect action-node classifier (agent.sandbox_nodes)."""

from src.agent.sandbox_nodes import (
    find_action_nodes,
    is_side_effect_node,
    neutralize_action_nodes,
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
