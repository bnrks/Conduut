"""ADR-0017 run-side presentation resolution tests."""

from types import SimpleNamespace

import httpx
import pytest

from src import store
from src.agent.schemas import WorkflowOutputField
from src.agent.tools import _summarize_execution, run_workflow_with_input
from src.agent.tools.common import _preview_value
from src.agent.tools.execution import _resolve_presentation


def test_resolve_presentation_maps_named_fields_from_body():
    presentation = _resolve_presentation(
        {"statusCode": 200, "body": {"price": 67000, "currency": "USD", "extra": "ignored"}},
        [
            WorkflowOutputField(name="price", label="Fiyat", format="currency"),
            WorkflowOutputField(name="currency", label="Para birimi", format="text"),
        ],
    )
    assert presentation is not None
    assert presentation.title is None
    assert [(f.label, f.format, f.value) for f in presentation.fields] == [
        ("Fiyat", "currency", 67000),
        ("Para birimi", "text", "USD"),
    ]


def test_resolve_presentation_skips_missing_and_empty_fields():
    presentation = _resolve_presentation(
        {"statusCode": 200, "body": {"price": 10, "currency": ""}},
        [
            WorkflowOutputField(name="price", label="Fiyat", format="number"),
            WorkflowOutputField(name="currency", label="Para birimi"),
            WorkflowOutputField(name="absent", label="Yok"),
        ],
    )
    assert presentation is not None
    assert [f.label for f in presentation.fields] == ["Fiyat"]


def test_resolve_presentation_uses_first_item_for_list_body():
    presentation = _resolve_presentation(
        {"statusCode": 200, "body": [{"q": "first"}, {"q": "second"}]},
        [WorkflowOutputField(name="q", label="Söz")],
    )
    assert presentation is not None
    assert presentation.fields[0].value == "first"


def test_resolve_presentation_returns_none_for_empty_schema():
    assert _resolve_presentation({"statusCode": 200, "body": {"x": 1}}, []) is None


def test_resolve_presentation_returns_none_when_no_field_resolves():
    assert (
        _resolve_presentation(
            {"statusCode": 200, "body": {"other": 1}},
            [WorkflowOutputField(name="price", label="Fiyat")],
        )
        is None
    )


def test_summarize_execution_populates_presentation_from_output_schema():
    result = _summarize_execution(
        {
            "id": "7",
            "workflowId": "wf_1",
            "status": "success",
            "data": {"resultData": {"runData": {}}},
        },
        response={"statusCode": 200, "body": {"price": 67000}},
        output_schema=[WorkflowOutputField(name="price", label="Fiyat", format="currency")],
    )
    assert result.presentation is not None
    assert result.presentation.fields[0].value == 67000


def test_summarize_execution_skips_presentation_on_error():
    result = _summarize_execution(
        {
            "id": "8",
            "workflowId": "wf_1",
            "status": "error",
            "data": {"resultData": {"error": {"message": "boom"}}},
        },
        response={"statusCode": 500, "body": {"price": 1}},
        output_schema=[WorkflowOutputField(name="price", label="Fiyat")],
    )
    assert result.presentation is None


@pytest.mark.asyncio
async def test_run_workflow_with_input_builds_presentation_from_output_schema(monkeypatch):
    async def fake_get_workflow_metadata(_user_id, workflow_id, **_kwargs):
        return store.WorkflowMetadata(
            workflow_id=workflow_id,
            input_schema=[],
            created_at="now",
            updated_at="now",
            resources={
                "output_schema": [{"name": "price", "label": "Fiyat", "format": "currency"}]
            },
        )

    async def fake_activate(_workflow_id):
        return None

    async def fake_update_workflow(**kwargs):
        return SimpleNamespace(id=kwargs["workflow_id"])

    async def fake_get_workflow(_workflow_id):
        return {
            "id": "wf_1",
            "name": "Price workflow",
            "active": True,
            "nodes": [
                {
                    "name": "Webhook",
                    "type": "n8n-nodes-base.webhook",
                    "parameters": {"path": "p", "httpMethod": "POST"},
                }
            ],
        }

    async def fake_call_webhook(path, payload):
        return httpx.Response(200, json={"price": 67000})

    async def fake_list_executions(*_args, **_kwargs):
        return [SimpleNamespace(id="exec_1")]

    async def fake_get_execution_detail(_execution_id):
        return {
            "id": "exec_1",
            "workflowId": "wf_1",
            "status": "success",
            "data": {"resultData": {"runData": {}}},
        }

    async def fake_save_execution_evidence(*_args, **_kwargs):
        return None

    monkeypatch.setattr("src.agent.tools.store.get_workflow_metadata", fake_get_workflow_metadata)
    monkeypatch.setattr("src.agent.tools.n8n_client.activate_workflow", fake_activate)
    monkeypatch.setattr("src.agent.tools.n8n_client.update_workflow", fake_update_workflow)
    monkeypatch.setattr("src.agent.tools.n8n_client.get_workflow", fake_get_workflow)
    monkeypatch.setattr("src.agent.tools.n8n_client.call_webhook", fake_call_webhook)
    monkeypatch.setattr("src.agent.tools.n8n_client.list_executions", fake_list_executions)
    monkeypatch.setattr(
        "src.agent.tools.n8n_client.get_execution_detail", fake_get_execution_detail
    )
    monkeypatch.setattr(
        "src.agent.tools.store.save_execution_evidence", fake_save_execution_evidence
    )
    monkeypatch.setattr("src.agent.tools.registry.get_node_schema", lambda _t: None)

    result = await run_workflow_with_input(
        {
            "id": "wf_1",
            "name": "Price workflow",
            "active": True,
            "nodes": [
                {
                    "name": "Webhook",
                    "type": "n8n-nodes-base.webhook",
                    "parameters": {"path": "p", "httpMethod": "POST"},
                }
            ],
        },
        user_id="user_1",
        input_payload={},
    )

    assert result.presentation is not None
    assert result.presentation.fields[0].label == "Fiyat"
    assert result.presentation.fields[0].value == 67000


def test_summarize_execution_resolves_presentation_from_full_response_not_preview():
    body = {f"k{i}": i for i in range(12)}  # 12 keys; declared fields sit beyond the preview cap
    body["summary"] = "x" * 2000  # exceeds the 1200-char preview cap
    body["tags"] = ["a", "b", "c", "d", "e"]  # exceeds the 3-item preview cap
    result = _summarize_execution(
        {
            "id": "9",
            "workflowId": "wf",
            "status": "success",
            "data": {"resultData": {"runData": {}}},
        },
        response={"statusCode": 200, "body": _preview_value(body)},
        full_response={"statusCode": 200, "body": body},
        output_schema=[
            WorkflowOutputField(name="summary", label="Özet", format="longtext"),
            WorkflowOutputField(name="tags", label="Etiketler", format="list"),
        ],
    )
    assert result.presentation is not None
    values = {f.label: f.value for f in result.presentation.fields}
    assert values["Özet"] == "x" * 2000
    assert values["Etiketler"] == ["a", "b", "c", "d", "e"]
