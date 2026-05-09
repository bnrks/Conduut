import asyncio
import json

import pytest

from src import store
from src.agent import runner
from src.agent.schemas import (
    AgentDeps,
    UserInputRequestAttachment,
    UserInputRequestData,
    WorkflowPreviewAttachment,
    WorkflowPreviewData,
)


class FakeResult:
    output = "Workflow created."


class FakeAgent:
    async def run(self, _prompt, *, deps, message_history, model_settings, usage_limits):
        assert message_history == []
        assert model_settings is None
        await deps.emit_tool_call("create_workflow")
        await deps.emit_attachment(
            WorkflowPreviewAttachment(
                data=WorkflowPreviewData(
                    id="wf_1",
                    name="Demo",
                    nodeCount=2,
                    status="inactive",
                )
            )
        )
        return FakeResult()


def _parse_sse(raw: str):
    event = None
    data = None
    for line in raw.splitlines():
        if line.startswith("event:"):
            event = line.removeprefix("event:").strip()
        if line.startswith("data:"):
            data = json.loads(line.removeprefix("data:").strip())
    return event, data


@pytest.mark.asyncio
async def test_agent_deps_deduplicates_identical_attachments():
    deps = AgentDeps(user_id="user_1", conversation_id="conv_1", event_queue=asyncio.Queue())
    attachment = WorkflowPreviewAttachment(
        data=WorkflowPreviewData(
            id="wf_1",
            name="Demo",
            nodeCount=2,
            status="inactive",
        )
    )

    await deps.emit_attachment(attachment)
    await deps.emit_attachment(attachment)

    assert len(deps.attachments) == 1
    assert deps.event_queue.qsize() == 1


def test_history_from_store_messages_keeps_only_text_user_assistant_history():
    prompt, history = runner._history_from_store_messages(
        [
            {"role": "user", "content": "first"},
            {"role": "assistant", "content": "second"},
            {"role": "tool", "content": "ignored"},
            {"role": "user", "content": "latest"},
        ]
    )

    assert prompt == "latest"
    assert [type(item).__name__ for item in history] == ["ModelRequest", "ModelResponse"]
    assert history[0].parts[0].content == "first"
    assert history[1].parts[0].content == "second"


def test_history_from_store_messages_adds_attachment_context_for_assistant():
    prompt, history = runner._history_from_store_messages(
        [
            {"role": "user", "content": "create workflow"},
            {
                "role": "assistant",
                "content": "Created and ran it.",
                "attachments": [
                    {
                        "type": "workflow_preview",
                        "data": {
                            "id": "wf_123",
                            "name": "Webhook Test Workflow",
                            "status": "inactive",
                        },
                    },
                    {
                        "type": "workflow_run_result",
                        "data": {
                            "workflowId": "wf_123",
                            "executionId": "5",
                            "status": "success",
                        },
                    },
                    {
                        "type": "user_input_request",
                        "data": {
                            "question": "Hangi alicilara gondereyim?",
                            "missingFields": ["recipients"],
                        },
                    },
                ],
            },
            {"role": "user", "content": "run the workflow"},
        ]
    )

    assert prompt == "run the workflow"
    assistant_content = history[1].parts[0].content
    assert "wf_123" in assistant_content
    assert "workflow_run workflowId=wf_123" in assistant_content
    assert "user_input_request question=Hangi alicilara gondereyim?" in assistant_content
    assert "missingFields=['recipients']" in assistant_content


def test_history_from_store_messages_adds_user_input_context_for_continuation():
    prompt, history = runner._history_from_store_messages(
        [
            {"role": "user", "content": "mail gonderen otomasyon kur"},
            {
                "role": "assistant",
                "content": "Hangi alicilara gondereyim?",
                "attachments": [
                    UserInputRequestAttachment(
                        data=UserInputRequestData(
                            question="Hangi alicilara gondereyim?",
                            missingFields=["recipients"],
                        )
                    ).model_dump()
                ],
            },
            {"role": "user", "content": "burak@example.com"},
        ]
    )

    assert prompt == "burak@example.com"
    assert "user_input_request" in history[1].parts[0].content
    assert "recipients" in history[1].parts[0].content


@pytest.mark.asyncio
async def test_runner_preserves_sse_contract(monkeypatch):
    saved = {}

    async def fake_add_message(*args, **kwargs):
        saved["args"] = args
        saved["kwargs"] = kwargs

    monkeypatch.setattr(runner, "build_model", lambda *_args: object())
    monkeypatch.setattr(runner, "create_agent", lambda _model: FakeAgent())
    monkeypatch.setattr(runner.store, "add_message", fake_add_message)

    events = [
        _parse_sse(raw)
        async for raw in runner.run(
            "user_1",
            "conv_1",
            [{"role": "user", "content": "create a demo workflow"}],
            store.LLMSettings(provider="openai", model="gpt-4o-mini", api_key="key"),
        )
        if raw.startswith("event:")
    ]

    event_names = [event for event, _data in events]
    assert event_names[:2] == ["tool_call", "attachment"]
    assert "token" in event_names
    assert event_names[-1] == "done"
    assert saved["args"][2] == "assistant"
    assert saved["kwargs"]["attachments"][0]["type"] == "workflow_preview"


@pytest.mark.asyncio
async def test_runner_reports_unsupported_provider():
    chunks = [
        raw
        async for raw in runner.run(
            "user_1",
            "conv_1",
            [{"role": "user", "content": "hello"}],
            store.LLMSettings(provider="custom", model="x", api_key="key"),
        )
    ]

    event, data = _parse_sse(chunks[0])
    assert event == "error"
    assert data["code"] == "model_config"
