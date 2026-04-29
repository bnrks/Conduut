import json

import pytest

from src import store
from src.agent import runner
from src.agent.schemas import WorkflowPreviewAttachment, WorkflowPreviewData


class FakeResult:
    output = "Workflow created."


class FakeAgent:
    async def run(self, _prompt, *, deps, message_history, usage_limits):
        assert message_history == []
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
