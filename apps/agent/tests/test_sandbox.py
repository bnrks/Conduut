"""Tests for the sandbox workflow test engine (agent.sandbox)."""

import pytest

import src.agent.sandbox as sandbox
from src.agent.schemas import WorkflowInputField
from src.agent.sandbox import (
    JudgeVerdict,
    _action_summaries,
    _build_test_clone,
    _check_empty_outputs,
    _sample_input_for_schema,
)


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


def _detail_with_run_data(run_data):
    return {"data": {"resultData": {"runData": run_data}}}


def test_check_empty_outputs_flags_empty_upstream():
    clone = {
        "nodes": [
            {"name": "Build", "type": "n8n-nodes-base.code"},
            {"name": "Send", "type": "n8n-nodes-base.gmail"},
        ],
        "connections": {"Build": {"main": [[{"node": "Send", "type": "main", "index": 0}]]}},
    }
    detail = _detail_with_run_data(
        {"Build": [{"data": {"main": [[{"json": {"text": ""}}]]}}]}
    )
    findings = _check_empty_outputs(detail, clone, ["Send"])
    assert findings and "Send" in findings[0]


def test_check_empty_outputs_passes_with_real_data():
    clone = {
        "nodes": [
            {"name": "Build", "type": "n8n-nodes-base.code"},
            {"name": "Send", "type": "n8n-nodes-base.gmail"},
        ],
        "connections": {"Build": {"main": [[{"node": "Send", "type": "main", "index": 0}]]}},
    }
    detail = _detail_with_run_data(
        {"Build": [{"data": {"main": [[{"json": {"text": "hello"}}]]}}]}
    )
    assert _check_empty_outputs(detail, clone, ["Send"]) == []


def test_check_empty_outputs_ignores_nodes_without_upstream():
    clone = {"nodes": [{"name": "Send", "type": "n8n-nodes-base.gmail"}], "connections": {}}
    detail = _detail_with_run_data({})
    assert _check_empty_outputs(detail, clone, ["Send"]) == []


def test_action_summaries_collect_would_be_input():
    clone = {
        "nodes": [
            {"name": "Build", "type": "n8n-nodes-base.code"},
            {
                "name": "Send",
                "type": "n8n-nodes-base.gmail",
                "parameters": {"subject": "Hi", "message": "={{$json.text}}"},
            },
        ],
        "connections": {"Build": {"main": [[{"node": "Send", "type": "main", "index": 0}]]}},
    }
    detail = _detail_with_run_data(
        {"Build": [{"data": {"main": [[{"json": {"text": "hello"}}]]}}]}
    )
    summaries = _action_summaries(detail, clone, ["Send"])
    assert summaries[0]["name"] == "Send"
    assert summaries[0]["type"] == "n8n-nodes-base.gmail"
    assert summaries[0]["would_be_input"] == [{"text": "hello"}]


@pytest.mark.asyncio
async def test_run_judge_uses_llm(monkeypatch):
    async def fake_llm(prompt):
        assert "Automation purpose" in prompt
        return JudgeVerdict(ok=False, issue="body empty")

    monkeypatch.setattr(sandbox, "_run_judge_llm", fake_llm)
    verdict = await sandbox._run_judge("send email", [{"name": "Send"}])
    assert verdict.ok is False
    assert verdict.issue == "body empty"
