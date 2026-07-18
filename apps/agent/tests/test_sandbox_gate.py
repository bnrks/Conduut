"""Tests for the sandbox test-and-gate self-repair loop (tools.sandbox_gate)."""

import asyncio
from types import SimpleNamespace

import pytest
from pydantic_ai import ModelRetry

import src.agent.tools.sandbox_gate as gate
from src.agent.sandbox import SandboxTestResult
from src.agent.tools.factory import (
    _needs_pretest,
    _run_pretest_gate,
    _should_run_sandbox_test,
)
from src.store import WorkflowMetadata


def _meta(test_status):
    resources = {"test_status": test_status} if test_status else {}
    return WorkflowMetadata(
        workflow_id="w", input_schema=[], created_at="", updated_at="", resources=resources
    )


def _ctx():
    deps = SimpleNamespace(
        user_id="u1",
        conversation_id="c1",
        workflow_test_attempts={},
        awaiting_user_input=False,
        terminal=False,
        emit_tool_call=lambda tool: asyncio.sleep(0),
    )
    return SimpleNamespace(deps=deps)


_WF = {"id": "wf-1", "name": "Demo", "nodes": [], "connections": {}}
_BASE = {"id": "wf-1", "name": "Demo", "active": False}


def _patch_store(monkeypatch):
    saved = {}

    async def fake_get(user_id, workflow_id):
        return None

    async def fake_status(
        user_id,
        workflow_id,
        *,
        status,
        findings=None,
        fingerprint=None,
        coverage=None,
    ):
        saved["status"] = status
        saved["findings"] = findings
        saved["fingerprint"] = fingerprint
        saved["coverage"] = coverage

    monkeypatch.setattr(gate.store, "get_workflow_metadata", fake_get)
    monkeypatch.setattr(gate.store, "save_workflow_test_status", fake_status)
    return saved


@pytest.mark.asyncio
async def test_gate_passed_marks_status_and_returns_base(monkeypatch):
    saved = _patch_store(monkeypatch)

    async def fake_test(workflow, *, user_id, input_schema, intent):
        return SandboxTestResult(passed=True, status="passed", coverage="full")

    monkeypatch.setattr(gate, "run_sandbox_test", fake_test)
    result = await gate._test_and_gate(_ctx(), _WF, "Demo", dict(_BASE))
    assert result["test_status"] == "passed"
    assert result["test_coverage"] == "full"
    assert saved["status"] == "passed"
    assert saved["fingerprint"]


@pytest.mark.asyncio
async def test_sandbox_no_action_is_not_real_execution_evidence(monkeypatch):
    _patch_store(monkeypatch)
    evidence = []
    ctx = _ctx()
    ctx.deps.record_claim_evidence = lambda outcome, **kwargs: evidence.append(
        {"outcome": outcome, **kwargs}
    )

    async def fake_test(workflow, *, user_id, input_schema, intent):
        return SandboxTestResult(
            passed=True,
            status="no_action",
            coverage="full",
            eligible_count=0,
            action_count=0,
            writeback_count=0,
        )

    monkeypatch.setattr(gate, "run_sandbox_test", fake_test)
    result = await gate._test_and_gate(ctx, _WF, "Demo", dict(_BASE))

    assert result["test_status"] == "no_action"
    assert evidence[-1]["outcome"] == "sandbox_passed"


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
async def test_gate_forwards_real_run_input_to_sandbox(monkeypatch):
    _patch_store(monkeypatch)
    captured = {}

    async def fake_test(workflow, **kwargs):
        captured.update(kwargs)
        return SandboxTestResult(passed=True, status="passed", coverage="full")

    monkeypatch.setattr(gate, "run_sandbox_test", fake_test)
    await gate._test_and_gate(
        _ctx(),
        _WF,
        "Demo",
        dict(_BASE),
        input_payload={"to": "person@example.com"},
    )

    assert captured["input_payload"] == {"to": "person@example.com"}


@pytest.mark.asyncio
async def test_delayed_pretest_uses_real_run_input_but_activation_uses_sample(monkeypatch):
    calls = []

    async def fake_gate(ctx, workflow, name, base_result, **kwargs):
        calls.append(kwargs)
        return base_result

    monkeypatch.setattr(gate, "_test_and_gate", fake_gate)
    ctx = _ctx()

    await _run_pretest_gate(ctx, _WF)
    await _run_pretest_gate(ctx, _WF, input_payload={"to": "person@example.com"})

    assert calls == [{}, {"input_payload": {"to": "person@example.com"}}]


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
    assert result["terminal"] is True
    assert ctx.deps.awaiting_user_input is True
    assert ctx.deps.terminal is True
    assert saved["status"] == "needs_attention"


@pytest.mark.asyncio
async def test_gate_harness_error_never_blocks_build(monkeypatch):
    _patch_store(monkeypatch)

    async def boom(workflow, *, user_id, input_schema, intent):
        raise RuntimeError("n8n down")

    monkeypatch.setattr(gate, "run_sandbox_test", boom)
    result = await gate._test_and_gate(_ctx(), _WF, "Demo", dict(_BASE))
    assert result == _BASE


@pytest.mark.asyncio
async def test_gate_harness_error_blocks_known_side_effect(monkeypatch):
    saved = _patch_store(monkeypatch)

    async def boom(workflow, *, user_id, input_schema, intent):
        raise RuntimeError("n8n down")

    workflow = {
        **_WF,
        "nodes": [
            {
                "name": "Send",
                "type": "n8n-nodes-base.gmail",
                "parameters": {"operation": "send"},
            }
        ],
    }
    monkeypatch.setattr(gate, "run_sandbox_test", boom)
    ctx = _ctx()
    result = await gate._test_and_gate(ctx, workflow, "Demo", dict(_BASE))
    assert result["test_status"] == "needs_attention"
    assert ctx.deps.awaiting_user_input is True
    assert ctx.deps.terminal is True
    assert saved["status"] == "needs_attention"


def test_should_run_sandbox_test_on_clean_result():
    clean = {"id": "x", "name": "n", "active": False}
    assert _should_run_sandbox_test(clean, awaiting=False) is True


def test_should_skip_when_readiness_blocked():
    blocked = {"id": "x", "name": "n", "active": False, "ready": False, "missing_credentials": 1}
    assert _should_run_sandbox_test(blocked, awaiting=False) is False


def test_should_skip_when_awaiting_user_input():
    clean = {"id": "x", "name": "n", "active": False}
    assert _should_run_sandbox_test(clean, awaiting=True) is False


def test_needs_pretest_skips_when_already_passed():
    assert _needs_pretest(_meta("passed")) is False


def test_needs_pretest_runs_when_absent_or_not_passed():
    assert _needs_pretest(None) is True
    assert _needs_pretest(_meta(None)) is True
    assert _needs_pretest(_meta("skipped")) is True
    assert _needs_pretest(_meta("needs_attention")) is True


def test_needs_pretest_invalidates_stale_fingerprint():
    workflow = {"nodes": [], "connections": {}, "settings": {"timezone": "Europe/Istanbul"}}
    metadata = _meta("passed")
    metadata.resources["assurance"] = {"workflow_fingerprint": "stale"}
    assert _needs_pretest(metadata, workflow) is True
