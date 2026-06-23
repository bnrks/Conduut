"""Tests for the sandbox test-and-gate self-repair loop (tools.sandbox_gate)."""

import asyncio
from types import SimpleNamespace

import pytest
from pydantic_ai import ModelRetry

import src.agent.tools.sandbox_gate as gate
from src.agent.sandbox import SandboxTestResult


def _ctx():
    deps = SimpleNamespace(
        user_id="u1",
        conversation_id="c1",
        workflow_test_attempts={},
        emit_tool_call=lambda tool: asyncio.sleep(0),
    )
    return SimpleNamespace(deps=deps)


_WF = {"id": "wf-1", "name": "Demo", "nodes": [], "connections": {}}
_BASE = {"id": "wf-1", "name": "Demo", "active": False}


def _patch_store(monkeypatch):
    saved = {}

    async def fake_get(user_id, workflow_id):
        return None

    async def fake_status(user_id, workflow_id, *, status, findings=None):
        saved["status"] = status
        saved["findings"] = findings

    monkeypatch.setattr(gate.store, "get_workflow_metadata", fake_get)
    monkeypatch.setattr(gate.store, "save_workflow_test_status", fake_status)
    return saved


@pytest.mark.asyncio
async def test_gate_passed_marks_status_and_returns_base(monkeypatch):
    saved = _patch_store(monkeypatch)

    async def fake_test(workflow, *, user_id, input_schema, intent):
        return SandboxTestResult(passed=True)

    monkeypatch.setattr(gate, "run_sandbox_test", fake_test)
    result = await gate._test_and_gate(_ctx(), _WF, "Demo", dict(_BASE))
    assert result == _BASE
    assert saved["status"] == "passed"


@pytest.mark.asyncio
async def test_gate_failure_within_budget_raises_model_retry(monkeypatch):
    _patch_store(monkeypatch)

    async def fake_test(workflow, *, user_id, input_schema, intent):
        return SandboxTestResult(passed=False, findings=["body empty"])

    monkeypatch.setattr(gate, "run_sandbox_test", fake_test)
    ctx = _ctx()
    with pytest.raises(ModelRetry):
        await gate._test_and_gate(ctx, _WF, "Demo", dict(_BASE))
    assert ctx.deps.workflow_test_attempts["wf-1"] == 1


@pytest.mark.asyncio
async def test_gate_failure_exhausted_returns_needs_attention(monkeypatch):
    saved = _patch_store(monkeypatch)

    async def fake_test(workflow, *, user_id, input_schema, intent):
        return SandboxTestResult(passed=False, findings=["body empty"])

    monkeypatch.setattr(gate, "run_sandbox_test", fake_test)
    ctx = _ctx()
    ctx.deps.workflow_test_attempts["wf-1"] = 2  # budget already spent
    result = await gate._test_and_gate(ctx, _WF, "Demo", dict(_BASE))
    assert result["test_status"] == "needs_attention"
    assert result["test_findings"] == ["body empty"]
    assert saved["status"] == "needs_attention"


@pytest.mark.asyncio
async def test_gate_harness_error_never_blocks_build(monkeypatch):
    _patch_store(monkeypatch)

    async def boom(workflow, *, user_id, input_schema, intent):
        raise RuntimeError("n8n down")

    monkeypatch.setattr(gate, "run_sandbox_test", boom)
    result = await gate._test_and_gate(_ctx(), _WF, "Demo", dict(_BASE))
    assert result == _BASE
