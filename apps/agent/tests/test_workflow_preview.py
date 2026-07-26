from types import SimpleNamespace

import pytest

import src.agent.workflow_preview as preview
from src.agent.sandbox import SandboxTestResult
from src.agent.schemas import OracleContract

_WORKFLOW = {
    "id": "wf-1",
    "name": "Reminder",
    "nodes": [
        {
            "name": "Send",
            "type": "n8n-nodes-base.gmail",
            "parameters": {"operation": "send"},
        }
    ],
    "connections": {},
}


@pytest.mark.asyncio
async def test_preview_issues_token_after_safe_probe(monkeypatch):
    calls = {"sandbox": 0}

    async def fake_metadata(user_id, workflow_id):
        return None

    async def fake_sandbox(*args, **kwargs):
        calls["sandbox"] += 1
        assert kwargs["input_payload"] == {"customer": "1"}
        return SandboxTestResult(
            passed=True,
            status="passed",
            coverage="full",
            eligible_count=1,
            action_count=1,
            writeback_count=0,
            preview_actions=[{"kind": "gmail_send", "target": "a***@example.com"}],
        )

    async def fake_save(*args, **kwargs):
        assert kwargs["execution_policy"] == "safe"
        assert kwargs["preview_basis"] == "safe_sandbox"
        return SimpleNamespace(token="token-1", expires_at="2030-01-01T00:00:00+00:00")

    monkeypatch.setattr(preview.store, "get_workflow_metadata", fake_metadata)
    monkeypatch.setattr(preview, "run_sandbox_test", fake_sandbox)
    monkeypatch.setattr(preview.store, "save_workflow_run_preview", fake_save)
    result = await preview.preview_workflow_run(
        _WORKFLOW, user_id="u1", input_payload={"customer": "1"}
    )
    assert result["ready"] is True
    assert result["preview_token"] == "token-1"
    assert result["actions"][0]["target"] == "a***@example.com"
    assert calls["sandbox"] == 1


@pytest.mark.asyncio
async def test_failed_probe_does_not_issue_token(monkeypatch):
    async def fake_metadata(user_id, workflow_id):
        return None

    async def fake_sandbox(*args, **kwargs):
        return SandboxTestResult(
            passed=False,
            status="needs_attention",
            coverage="full",
            findings=["identity missing"],
        )

    monkeypatch.setattr(preview.store, "get_workflow_metadata", fake_metadata)
    monkeypatch.setattr(preview, "run_sandbox_test", fake_sandbox)
    result = await preview.preview_workflow_run(_WORKFLOW, user_id="u1", input_payload={})
    assert result["ready"] is False
    assert "preview_token" not in result


@pytest.mark.asyncio
async def test_preview_is_bound_to_fingerprint_and_input(monkeypatch):
    captured = {}

    async def fake_metadata(user_id, workflow_id):
        return None

    async def fake_consume(user_id, token, **kwargs):
        captured.update(kwargs)
        return object()

    monkeypatch.setattr(preview.store, "get_workflow_metadata", fake_metadata)
    monkeypatch.setattr(preview.store, "consume_workflow_run_preview", fake_consume)
    ok = await preview.consume_workflow_preview(
        _WORKFLOW,
        user_id="u1",
        input_payload={"customer": "1"},
        preview_token="token-1",
        conversation_id="conv-1",
        execution_policy="safe",
    )
    assert ok is True
    assert captured["workflow_id"] == "wf-1"
    assert captured["input_payload"] == {"customer": "1"}
    assert captured["conversation_id"] == "conv-1"
    assert captured["execution_policy"] == "safe"
    assert captured["preview_basis"] == "safe_sandbox"


@pytest.mark.asyncio
async def test_missing_runtime_input_does_not_consume_preview(monkeypatch):
    async def fake_metadata(user_id, workflow_id):
        return SimpleNamespace(
            input_schema=[
                {
                    "name": "to",
                    "label": "Recipient email",
                    "type": "email",
                    "required": True,
                }
            ]
        )

    async def fail_consume(*args, **kwargs):
        raise AssertionError("invalid input must be rejected before consuming the token")

    monkeypatch.setattr(preview.store, "get_workflow_metadata", fake_metadata)
    monkeypatch.setattr(preview.store, "consume_workflow_run_preview", fail_consume)

    with pytest.raises(ValueError, match="Recipient email"):
        await preview.consume_workflow_preview(
            _WORKFLOW,
            user_id="u1",
            input_payload={},
            preview_token="token-1",
        )


@pytest.mark.asyncio
async def test_batch_preview_aggregates_rows_into_one_token(monkeypatch):
    async def fake_metadata(user_id, workflow_id):
        return None

    async def fake_sandbox(*args, **kwargs):
        return SandboxTestResult(
            passed=True,
            status="passed",
            coverage="full",
            eligible_count=1,
            action_count=1,
            writeback_count=1,
        )

    captured = {}

    async def fake_save(*args, **kwargs):
        captured.update(kwargs)
        return SimpleNamespace(token="batch-token", expires_at="2030-01-01T00:00:00+00:00")

    monkeypatch.setattr(preview.store, "get_workflow_metadata", fake_metadata)
    monkeypatch.setattr(preview, "run_sandbox_test", fake_sandbox)
    monkeypatch.setattr(preview.store, "save_workflow_run_preview", fake_save)
    rows = [
        {"rowNumber": 2, "input": {"customer": "1"}},
        {"rowNumber": 3, "input": {"customer": "2"}},
    ]
    result = await preview.preview_workflow_batch(_WORKFLOW, user_id="u1", rows=rows)
    assert result["preview_token"] == "batch-token"
    assert result["action_count"] == 2
    assert result["writeback_count"] == 2
    assert captured["input_payload"] == {"rows": rows}
    assert captured["execution_policy"] == "safe"
    assert captured["preview_basis"] == "safe_sandbox"


@pytest.mark.asyncio
async def test_fast_preview_uses_static_basis_without_sandbox(monkeypatch):
    async def fake_metadata(user_id, workflow_id):
        raise AssertionError("fast preview must not read sandbox input metadata")

    async def fail_sandbox(*args, **kwargs):
        raise AssertionError("fast preview must not execute sandbox")

    async def fake_save(*args, **kwargs):
        assert kwargs["execution_policy"] == "fast"
        assert kwargs["preview_basis"] == "fast_static"
        return SimpleNamespace(token="fast-token", expires_at="2030-01-01T00:00:00+00:00")

    monkeypatch.setattr(preview.store, "get_workflow_metadata", fake_metadata)
    monkeypatch.setattr(preview, "run_sandbox_test", fail_sandbox)
    monkeypatch.setattr(preview.store, "save_workflow_run_preview", fake_save)
    monkeypatch.setattr(
        preview,
        "analyze_workflow_semantics",
        lambda *_args, **_kwargs: SimpleNamespace(findings=(), blocking_findings=()),
    )
    monkeypatch.setattr(
        preview,
        "build_oracle_contract",
        lambda *_args, **_kwargs: OracleContract(
            fingerprint="fp-1",
            contextSource="current",
            contractCoverage="full",
            actionNodes=["Send"],
            writebackNodes=[],
            mutationNodes=["Send"],
            claimScope=["action_verified"],
        ),
    )

    result = await preview.preview_workflow_run(
        _WORKFLOW,
        user_id="u1",
        input_payload={"customer": "1"},
        conversation_id="conv-fast",
        execution_policy="fast",
    )

    assert result["ready"] is True
    assert result["preview_basis"] == "fast_static"
    assert result["execution_policy"] == "fast"
    assert result["preview_token"] == "fast-token"
