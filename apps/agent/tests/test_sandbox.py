"""Tests for the sandbox workflow test engine (agent.sandbox)."""

from types import SimpleNamespace

import pytest

import src.agent.sandbox as sandbox
import src.n8n_client as n8n_client
from src.agent.sandbox import (
    JudgeVerdict,
    _action_summaries,
    _build_test_clone,
    _check_empty_outputs,
    _sample_input_for_schema,
)
from src.agent.schemas import WorkflowInputField


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
        "nodes": [{"name": "Start", "type": "n8n-nodes-base.manualTrigger", "parameters": {}}],
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
        "nodes": [{"name": "Cron", "type": "n8n-nodes-base.scheduleTrigger", "parameters": {}}],
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
    detail = _detail_with_run_data({"Build": [{"data": {"main": [[{"json": {"text": ""}}]]}}]})
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
    detail = _detail_with_run_data({"Build": [{"data": {"main": [[{"json": {"text": "hello"}}]]}}]})
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
    detail = _detail_with_run_data({"Build": [{"data": {"main": [[{"json": {"text": "hello"}}]]}}]})
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


def _success_detail():
    return {
        "id": "exec-1",
        "status": "success",
        "finished": True,
        "workflowId": "clone-1",
        "data": {
            "resultData": {
                "runData": {"Build": [{"data": {"main": [[{"json": {"text": "hello"}}]]}}]}
            }
        },
    }


def _wire_fake_n8n(monkeypatch, detail):
    created = {}

    async def fake_create(name, nodes, connections, settings=None):
        created["nodes"] = nodes
        return SimpleNamespace(id="clone-1", name=name, active=False)

    deleted = {"called": False}

    async def fake_delete(workflow_id):
        deleted["called"] = True

    async def fake_activate(workflow_id):
        return None

    async def fake_webhook(path, payload=None):
        return SimpleNamespace(status_code=200)

    async def fake_list(workflow_id=None, limit=10):
        return [SimpleNamespace(id="exec-1")]

    async def fake_get_detail(execution_id):
        return detail

    monkeypatch.setattr(n8n_client, "create_workflow", fake_create)
    monkeypatch.setattr(n8n_client, "delete_workflow", fake_delete)
    monkeypatch.setattr(n8n_client, "activate_workflow", fake_activate)
    monkeypatch.setattr(n8n_client, "call_webhook", fake_webhook)
    monkeypatch.setattr(n8n_client, "list_executions", fake_list)
    monkeypatch.setattr(n8n_client, "get_execution_detail", fake_get_detail)
    return created, deleted


_DEMO_WORKFLOW = {
    "id": "real-1",
    "name": "Demo",
    "nodes": [
        {"name": "Hook", "type": "n8n-nodes-base.webhook", "parameters": {"path": "p"}},
        {"name": "Build", "type": "n8n-nodes-base.code", "parameters": {}},
        {"name": "Send", "type": "n8n-nodes-base.gmail", "parameters": {"operation": "send"}},
    ],
    "connections": {
        "Hook": {"main": [[{"node": "Build", "type": "main", "index": 0}]]},
        "Build": {"main": [[{"node": "Send", "type": "main", "index": 0}]]},
    },
}


@pytest.mark.asyncio
async def test_run_sandbox_test_passes_and_deletes_clone(monkeypatch):
    created, deleted = _wire_fake_n8n(monkeypatch, _success_detail())

    async def fake_judge(intent, summaries):
        return JudgeVerdict(ok=True)

    monkeypatch.setattr(sandbox, "_run_judge", fake_judge)
    result = await sandbox.run_sandbox_test(
        _DEMO_WORKFLOW, user_id="u1", input_schema=[], intent="Demo"
    )
    assert result.passed is True
    assert deleted["called"] is True
    # The action node must be neutralized in the clone that was created.
    send = next(n for n in created["nodes"] if n["name"] == "Send")
    assert send["disabled"] is True


@pytest.mark.asyncio
async def test_run_sandbox_test_flags_execution_error(monkeypatch):
    detail = {
        "id": "exec-2",
        "status": "error",
        "workflowId": "clone-1",
        "data": {"resultData": {"error": {"message": "Boom", "node": {"name": "Build"}}}},
    }
    _wire_fake_n8n(monkeypatch, detail)
    result = await sandbox.run_sandbox_test(
        _DEMO_WORKFLOW, user_id="u1", input_schema=[], intent="Demo"
    )
    assert result.passed is False
    assert result.failed_node == "Build"


@pytest.mark.asyncio
async def test_run_sandbox_test_skips_schedule_only(monkeypatch):
    workflow = {
        "id": "real-9",
        "name": "Cron",
        "nodes": [{"name": "Cron", "type": "n8n-nodes-base.scheduleTrigger", "parameters": {}}],
        "connections": {},
    }
    result = await sandbox.run_sandbox_test(workflow, user_id="u1", input_schema=[], intent="Cron")
    assert result.skipped is True
