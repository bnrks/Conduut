"""Tests for the sandbox workflow test engine (agent.sandbox)."""

from src.agent.schemas import WorkflowInputField
from src.agent.sandbox import _build_test_clone, _sample_input_for_schema


def test_sample_input_is_type_aware():
    schema = [
        WorkflowInputField(name="to", label="To", type="email"),
        WorkflowInputField(name="subject", label="Subject", type="string"),
        WorkflowInputField(name="body", label="Body", type="textarea"),
    ]
    sample = _sample_input_for_schema(schema)
    assert sample["to"] == "test@example.com"
    assert isinstance(sample["subject"], str) and sample["subject"]
    assert isinstance(sample["body"], str) and sample["body"]


def test_sample_input_empty_schema():
    assert _sample_input_for_schema([]) == {}


def test_build_test_clone_from_webhook_assigns_fresh_path():
    workflow = {
        "id": "real-1",
        "name": "Demo",
        "nodes": [
            {
                "name": "Hook",
                "type": "n8n-nodes-base.webhook",
                "parameters": {"httpMethod": "GET", "path": "live-path"},
            }
        ],
        "connections": {},
    }
    clone = _build_test_clone(workflow)
    assert clone is not None
    nodes, _connections, path = clone
    assert path.startswith("conduut-test-")
    assert path != "live-path"  # never clash with the live webhook
    hook = nodes[0]["parameters"]
    assert hook["httpMethod"] == "POST"
    assert hook["responseMode"] == "lastNode"
    assert hook["path"] == path


def test_build_test_clone_converts_manual_trigger():
    workflow = {
        "id": "real-2",
        "name": "Demo",
        "nodes": [
            {"name": "Start", "type": "n8n-nodes-base.manualTrigger", "parameters": {}}
        ],
        "connections": {},
    }
    clone = _build_test_clone(workflow)
    assert clone is not None
    nodes, _connections, path = clone
    assert nodes[0]["type"] == "n8n-nodes-base.webhook"
    assert nodes[0]["parameters"]["path"] == path


def test_build_test_clone_returns_none_for_schedule_only():
    workflow = {
        "id": "real-3",
        "name": "Demo",
        "nodes": [
            {"name": "Cron", "type": "n8n-nodes-base.scheduleTrigger", "parameters": {}}
        ],
        "connections": {},
    }
    assert _build_test_clone(workflow) is None
