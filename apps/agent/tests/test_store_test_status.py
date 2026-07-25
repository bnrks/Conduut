"""Test save_workflow_test_status merges into metadata resources without loss."""

import pytest

import src.store as store
from src.store import WorkflowMetadata
from src.workflow_test_policy import WORKFLOW_TEST_POLICY_VERSION


@pytest.mark.asyncio
async def test_save_workflow_test_status_preserves_input_schema(monkeypatch):
    existing = WorkflowMetadata(
        workflow_id="wf-1",
        input_schema=[{"name": "to", "label": "To"}],
        created_at="2026-01-01T00:00:00",
        updated_at="2026-01-01T00:00:00",
        resources={"sheet": "s1"},
    )

    async def fake_get(user_id, workflow_id):
        return existing

    captured = {}

    async def fake_save(user_id, workflow_id, *, input_schema, resources=None):
        captured["input_schema"] = input_schema
        captured["resources"] = resources
        return existing

    monkeypatch.setattr(store, "get_workflow_metadata", fake_get)
    monkeypatch.setattr(store, "save_workflow_metadata", fake_save)

    await store.save_workflow_test_status(
        "u1", "wf-1", status="needs_attention", findings=["body empty"]
    )

    assert captured["input_schema"] == [{"name": "to", "label": "To"}]
    assert captured["resources"]["sheet"] == "s1"  # untouched
    assert captured["resources"]["test_status"] == "needs_attention"
    assert captured["resources"]["test_findings"] == ["body empty"]
    assert captured["resources"]["assurance"]["version"] == WORKFLOW_TEST_POLICY_VERSION
