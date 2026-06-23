import asyncio
import json

import pytest
from pydantic_ai.messages import (
    PartDeltaEvent,
    PartStartEvent,
    TextPart,
    TextPartDelta,
    ThinkingPart,
    ThinkingPartDelta,
)

from src.agent import runner
from src.agent.model_registry import Tier
from src.agent.schemas import (
    AgentDeps,
    ArtifactPreviewAttachment,
    ArtifactPreviewData,
    ArtifactPreviewTable,
    UserInputRequestAttachment,
    UserInputRequestData,
    WorkflowPreviewAttachment,
    WorkflowPreviewData,
)


class FakeResult:
    output = "Workflow created."


class _FakeModelRequestNode:
    """agent.iter() model-request node taklidi: .stream(ctx) ile delta'lar akıtır."""

    def __init__(self, events):
        self._events = events

    def stream(self, _ctx):
        events = self._events

        class _Stream:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *_a):
                return False

            async def __aiter__(self):
                for ev in events:
                    yield ev

        return _Stream()


class _FakeRun:
    """agent.iter() AgentRun + async context manager taklidi."""

    def __init__(self, deps, emit, events):
        self._deps = deps
        self._emit = emit
        self._events = events
        self.ctx = object()
        self.result = FakeResult()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_a):
        return False

    async def __aiter__(self):
        # Tool fazını taklit et (tool_call/attachment event'leri), sonra modelin
        # nihai cevabını akıtan model-request node'unu ver.
        if self._emit is not None:
            await self._emit(self._deps)
        yield _FakeModelRequestNode(self._events)


class FakeStreamingAgent:
    """create_agent yerine: agent.iter() ile thinking+text delta'ları akıtır."""

    def __init__(self, events, *, emit=None, expect_settings=None):
        self._events = events
        self._emit = emit
        self._expect_settings = expect_settings

    def iter(self, _prompt, *, deps, message_history, model_settings, usage_limits):
        assert message_history == []
        if self._expect_settings is not None:
            assert model_settings == self._expect_settings
        return _FakeRun(deps, self._emit, self._events)


def _recognize_fake_model_node(monkeypatch):
    monkeypatch.setattr(
        runner.Agent,
        "is_model_request_node",
        staticmethod(lambda node: isinstance(node, _FakeModelRequestNode)),
    )


async def _emit_workflow_tool_and_attachment(deps):
    await deps.emit_tool_call("create_workflow")
    await deps.emit_attachment(
        WorkflowPreviewAttachment(
            data=WorkflowPreviewData(id="wf_1", name="Demo", nodeCount=2, status="inactive")
        )
    )


async def _emit_sheets_artifact(deps):
    await deps.emit_attachment(
        ArtifactPreviewAttachment(
            data=ArtifactPreviewData(
                service="google_sheets",
                title="Google Sheets row added",
                url="https://sheet.test",
                source={"spreadsheetId": "sheet_1", "range": "Log!A1"},
                table=ArtifactPreviewTable(
                    columns=["Email"],
                    rows=[{"Email": "person@example.com"}],
                ),
            )
        )
    )


def _thinking_then_text_events():
    """Düşünce delta'ları + 'Workflow created.' görünür metin delta'ları."""
    return [
        PartStartEvent(index=0, part=ThinkingPart(content="planning")),
        PartDeltaEvent(index=0, delta=ThinkingPartDelta(content_delta=" steps")),
        PartStartEvent(index=1, part=TextPart(content="Workflow ")),
        PartDeltaEvent(index=1, delta=TextPartDelta(content_delta="created.")),
    ]


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

    assert prompt.startswith("run the workflow")
    assert "answers the previous user_input_request" in prompt
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

    assert prompt.startswith("burak@example.com")
    assert "answers the previous user_input_request" in prompt
    assert "do not ask for the same missing field again" in prompt
    assert "user_input_request" in history[1].parts[0].content
    assert "recipients" in history[1].parts[0].content


def test_platform_resources_from_messages_uses_latest_sheets_artifact():
    resources = runner._platform_resources_from_messages(
        [
            {
                "role": "assistant",
                "attachments": [
                    {
                        "type": "artifact_preview",
                        "data": {
                            "service": "google_sheets",
                            "url": "https://docs.google.com/spreadsheets/d/sheet_old/edit",
                            "source": {"spreadsheetId": "sheet_old", "range": "Old"},
                        },
                    }
                ],
            },
            {
                "role": "assistant",
                "attachments": [
                    {
                        "type": "artifact_preview",
                        "data": {
                            "service": "google_sheets",
                            "url": "https://docs.google.com/spreadsheets/d/sheet_123/edit",
                            "source": {"spreadsheetId": "sheet_123", "range": "Leads"},
                        },
                    }
                ],
            },
        ]
    )

    assert resources == {
        "google_sheets": {
            "spreadsheet_id": "sheet_123",
            "spreadsheet_url": "https://docs.google.com/spreadsheets/d/sheet_123/edit",
            "sheet_name": "Leads",
        }
    }


def test_history_from_store_messages_marks_prior_user_answer_to_clarification():
    _prompt, history = runner._history_from_store_messages(
        [
            {"role": "user", "content": "sheet workflow kur"},
            {
                "role": "assistant",
                "content": "Hangi sheet bilgilerini kullanayim?",
                "attachments": [
                    UserInputRequestAttachment(
                        data=UserInputRequestData(
                            question="Hangi sheet bilgilerini kullanayim?",
                            missingFields=["Google Sheet ID", "sheet/tab name"],
                        )
                    ).model_dump()
                ],
            },
            {"role": "user", "content": "yeni dosya olustur, sekme sayfa 1"},
            {"role": "assistant", "content": "Devam ediyorum."},
            {"role": "user", "content": "son mesaj"},
        ]
    )

    answer_content = history[2].parts[0].content
    assert answer_content.startswith("yeni dosya olustur")
    assert "answers the previous user_input_request" in answer_content
    assert "Google Sheet ID" in answer_content


@pytest.mark.asyncio
async def test_runner_streams_tokens_thinking_and_preserves_sse_contract(monkeypatch):
    saved = {}

    async def fake_add_message(*args, **kwargs):
        saved["args"] = args
        saved["kwargs"] = kwargs

    async def fake_classify(*_args, **_kwargs):
        return Tier.MEDIUM

    fake_agent = FakeStreamingAgent(
        _thinking_then_text_events(),
        emit=_emit_workflow_tool_and_attachment,
        expect_settings={
            "anthropic_thinking": {"type": "adaptive"},
            "anthropic_effort": "medium",
        },
    )

    monkeypatch.setattr(runner, "classify_tier", fake_classify)
    monkeypatch.setattr(runner, "key_for_provider", lambda *_args: "key")
    monkeypatch.setattr(runner, "build_model", lambda *_args: object())
    monkeypatch.setattr(runner, "create_agent", lambda _model: fake_agent)
    monkeypatch.setattr(runner.store, "add_message", fake_add_message)
    _recognize_fake_model_node(monkeypatch)

    events = [
        _parse_sse(raw)
        async for raw in runner.run(
            "user_1",
            "conv_1",
            [{"role": "user", "content": "create a demo workflow"}],
        )
        if raw.startswith("event:")
    ]

    event_names = [event for event, _data in events]
    assert event_names[:2] == ["tool_call", "attachment"]
    assert "thinking" in event_names
    assert "token" in event_names
    assert event_names[-1] == "done"

    # Düşünce ayrı kanaldan akar; görünür metin token'larda gelir.
    thinking_text = "".join(d["text"] for e, d in events if e == "thinking")
    token_text = "".join(d["text"] for e, d in events if e == "token")
    assert thinking_text == "planning steps"
    assert token_text == "Workflow created."

    # Persist edilen içerik akan görünür metin; düşünce KAYDEDİLMEZ.
    assert saved["args"][2] == "assistant"
    assert saved["args"][3] == "Workflow created."
    assert "planning" not in saved["args"][3]
    assert saved["kwargs"]["attachments"][0]["type"] == "workflow_preview"


@pytest.mark.asyncio
async def test_runner_persists_artifact_preview_attachments(monkeypatch):
    saved_artifacts: list[dict] = []

    async def fake_add_message(*_args, **_kwargs):
        return None

    async def fake_save_artifact(user_id: str, artifact: dict, *, origin: dict):
        saved_artifacts.append({"user_id": user_id, "artifact": artifact, "origin": origin})

    async def fake_classify(*_args, **_kwargs):
        return Tier.MEDIUM

    fake_agent = FakeStreamingAgent(
        [PartStartEvent(index=0, part=TextPart(content="Workflow created."))],
        emit=_emit_sheets_artifact,
    )

    monkeypatch.setattr(runner, "classify_tier", fake_classify)
    monkeypatch.setattr(runner, "key_for_provider", lambda *_args: "key")
    monkeypatch.setattr(runner, "build_model", lambda *_args: object())
    monkeypatch.setattr(runner, "create_agent", lambda _model: fake_agent)
    monkeypatch.setattr(runner.store, "add_message", fake_add_message)
    monkeypatch.setattr(runner.store, "save_artifact", fake_save_artifact)
    _recognize_fake_model_node(monkeypatch)

    events = [
        _parse_sse(raw)
        async for raw in runner.run(
            "user_1",
            "conv_1",
            [{"role": "user", "content": "add a row"}],
        )
        if raw.startswith("event:")
    ]

    assert events[-1][0] == "done"
    assert saved_artifacts == [
        {
            "user_id": "user_1",
            "artifact": {
                "service": "google_sheets",
                "title": "Google Sheets row added",
                "url": "https://sheet.test",
                "source": {"spreadsheetId": "sheet_1", "range": "Log!A1"},
                "table": {
                    "columns": ["Email"],
                    "rows": [{"Email": "person@example.com"}],
                    "truncated": False,
                },
            },
            "origin": {"kind": "chat", "conversationId": "conv_1"},
        }
    ]


@pytest.mark.asyncio
async def test_runner_reports_model_config_error(monkeypatch):
    from src.agent.provider_factory import UnsupportedProviderError

    async def fake_classify(*_args, **_kwargs):
        return Tier.MEDIUM

    def boom(*_args):
        raise UnsupportedProviderError("Unsupported provider: custom")

    monkeypatch.setattr(runner, "classify_tier", fake_classify)
    monkeypatch.setattr(runner, "key_for_provider", lambda *_args: "key")
    monkeypatch.setattr(runner, "build_model", boom)

    chunks = [
        raw
        async for raw in runner.run(
            "user_1",
            "conv_1",
            [{"role": "user", "content": "hello"}],
        )
    ]

    event, data = _parse_sse(chunks[0])
    assert event == "error"
    assert data["code"] == "model_config"


def test_conversation_workflows_from_messages_maps_name_to_id():
    messages = [
        {"role": "user", "content": "build it"},
        {
            "role": "assistant",
            "content": "done",
            "attachments": [
                {
                    "type": "workflow_preview",
                    "data": {"id": "wf1", "name": "Teklif", "status": "inactive"},
                }
            ],
        },
        {
            "role": "assistant",
            "content": "updated",
            "attachments": [
                {
                    "type": "workflow_preview",
                    "data": {"id": "wf2", "name": "Teklif", "status": "inactive"},
                },
                {"type": "artifact_preview", "data": {"title": "x"}},
            ],
        },
    ]
    result = runner._conversation_workflows_from_messages(messages)
    # Latest id wins for a given name -> next create_workflow reuses (updates) it.
    assert result == {"Teklif": "wf2"}


def test_conversation_workflows_from_messages_ignores_non_workflow_attachments():
    messages = [
        {
            "role": "assistant",
            "content": "x",
            "attachments": [{"type": "artifact_preview", "data": {"title": "t"}}],
        },
        {"role": "assistant", "content": "y"},
    ]
    assert runner._conversation_workflows_from_messages(messages) == {}
