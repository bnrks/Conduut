import asyncio
import json
from types import SimpleNamespace

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
from src.agent.platform_state import ConnectionSummary, UserPlatformState
from src.agent.schemas import (
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


class _BlockingRun:
    def __init__(self, deps, cancelled: asyncio.Event):
        self._deps = deps
        self._cancelled = cancelled
        self.ctx = object()
        self.result = FakeResult()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return False

    async def __aiter__(self):
        await self._deps.emit_tool_call("blocking_tool")
        try:
            await asyncio.Future()
        except asyncio.CancelledError:
            self._cancelled.set()
            raise
        yield  # pragma: no cover - cancellation is the expected exit


class _BlockingAgent:
    def __init__(self, cancelled: asyncio.Event):
        self._cancelled = cancelled

    def iter(self, _prompt, *, deps, message_history, model_settings, usage_limits):
        return _BlockingRun(deps, self._cancelled)


def _recognize_fake_model_node(monkeypatch):
    monkeypatch.setattr(
        runner.Agent,
        "is_model_request_node",
        staticmethod(lambda node: isinstance(node, _FakeModelRequestNode)),
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("guarded", [False, True])
async def test_closing_stream_cancels_inner_model_task(monkeypatch, make_agent_deps, guarded):
    cancelled = asyncio.Event()
    monkeypatch.setattr(runner, "create_agent", lambda _model: _BlockingAgent(cancelled))
    choice = SimpleNamespace(request_limit=3, tool_calls_limit=3)
    deps = make_agent_deps()
    common = {
        "choice": choice,
        "model": object(),
        "model_settings": {},
        "deps": deps,
        "user_prompt": "wait",
        "message_history": [],
    }
    if guarded:
        stream = runner._run_guarded_attempt(**common)
    else:
        stream = runner._run_live(
            **common,
            tier=Tier.MEDIUM,
            user_id="user",
            conv_id="conversation",
            attempt_id="attempt",
        )

    first = await asyncio.wait_for(anext(stream), timeout=1)
    assert "blocking_tool" in str(first)
    await stream.aclose()

    await asyncio.wait_for(cancelled.wait(), timeout=1)


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


class _ProviderError(Exception):
    def __init__(self, message: str, status_code: int):
        super().__init__(message)
        self.status_code = status_code


def test_provider_retry_disposition_treats_auth_quota_and_missing_model_as_terminal():
    assert runner._provider_error_is_terminal(_ProviderError("unauthorized", 401))
    assert runner._provider_error_is_terminal(_ProviderError("insufficient_quota", 429))
    assert runner._provider_error_is_terminal(_ProviderError("model not found", 404))


def test_provider_retry_disposition_allows_rate_limit_and_timeout_retry():
    assert not runner._provider_error_is_terminal(_ProviderError("rate limit", 429))
    assert not runner._provider_error_is_terminal(TimeoutError("read timed out"))


@pytest.fixture(autouse=True)
def _stub_platform_state(monkeypatch):
    """Keep runner tests offline: never hit real Firestore/n8n for user state."""

    async def _empty(*_a, **_k):
        return UserPlatformState()

    monkeypatch.setattr(runner, "gather_user_state", _empty)


@pytest.mark.asyncio
async def test_agent_deps_deduplicates_identical_attachments(make_agent_deps):
    deps = make_agent_deps()
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


def test_agent_deps_real_action_flag_defaults_false(make_agent_deps):
    deps = make_agent_deps(user_id="u", conversation_id="c")
    assert deps.real_action_executed is False


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


def test_history_from_store_messages_adds_latest_execution_reference_to_prompt():
    prompt, history = runner._history_from_store_messages(
        [
            {
                "role": "user",
                "content": "Bu basarisiz calistirmayi incele ve duzelt.",
                "attachments": [
                    {
                        "type": "execution_reference",
                        "data": {
                            "executionId": "exec_42",
                            "workflowId": "wf_7",
                            "status": "error",
                            "intent": "diagnose_and_fix",
                        },
                    }
                ],
            }
        ]
    )

    assert history == []
    assert prompt.startswith("Bu basarisiz calistirmayi incele")
    assert "execution_reference executionId=exec_42 workflowId=wf_7" in prompt
    assert "Inspect this exact execution before changing anything" in prompt


def test_history_from_store_messages_preserves_prior_user_attachment_context():
    _prompt, history = runner._history_from_store_messages(
        [
            {
                "role": "user",
                "content": "Run'i duzelt",
                "attachments": [
                    {
                        "type": "execution_reference",
                        "data": {
                            "executionId": "exec_42",
                            "workflowId": "wf_7",
                            "status": "error",
                            "intent": "diagnose_and_fix",
                        },
                    }
                ],
            },
            {"role": "assistant", "content": "Inceliyorum."},
            {"role": "user", "content": "devam et"},
        ]
    )

    assert "execution_reference executionId=exec_42" in history[0].parts[0].content


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

    # This test pins the MEDIUM tier to Anthropic Sonnet (adaptive thinking) to
    # exercise the thinking+text streaming contract, so it must run on the
    # "default" profile regardless of the branch's default (CONDUUT_MODEL_PROFILE).
    monkeypatch.setattr(runner.settings, "model_profile", "default")
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


def _text_events(text: str):
    return [PartStartEvent(index=0, part=TextPart(content=text))]


@pytest.mark.asyncio
async def test_live_guard_streams_then_recovers_to_clean_attempt(monkeypatch):
    saved = {}

    async def fake_add_message(*args, **kwargs):
        saved["content"] = args[3]

    async def fake_classify(*_a, **_k):
        return Tier.MEDIUM

    # Force the DeepSeek guarded path.
    monkeypatch.setattr(runner.settings, "model_profile", "deepseek")
    monkeypatch.setattr(runner.settings, "enable_reliability_guard", True)
    monkeypatch.setattr(runner, "classify_tier", fake_classify)
    monkeypatch.setattr(runner, "key_for_provider", lambda *_a: "key")
    monkeypatch.setattr(runner, "build_model", lambda *_a: object())

    agents = iter(
        [
            FakeStreamingAgent(_text_events("execute_workflow({'workflow_id': 'x'})")),
            FakeStreamingAgent(_text_events("Hazır, workflow'u çalıştırdım.")),
        ]
    )
    monkeypatch.setattr(runner, "create_agent", lambda _m: next(agents))
    monkeypatch.setattr(runner.store, "add_message", fake_add_message)
    _recognize_fake_model_node(monkeypatch)

    events = [
        _parse_sse(raw)
        async for raw in runner.run("u1", "c1", [{"role": "user", "content": "kur ve çalıştır"}])
        if raw.startswith("event:")
    ]
    names = [e for e, _ in events]
    recovery = next(d for e, d in events if e == "recovery")
    clean_attempt = recovery["next_attempt_id"]
    clean_token_text = "".join(
        d["text"] for e, d in events if e == "token" and d["attempt_id"] == clean_attempt
    )

    assert names[-1] == "done"
    assert recovery["retrying"] is True
    assert recovery["reason_code"] == "tool-call-as-text:execute_workflow"
    assert "execute_workflow(" not in "".join(d["text"] for e, d in events if e == "token")
    assert clean_token_text == "Hazır, workflow'u çalıştırdım."
    assert all(d.get("attempt_id") for e, d in events if e != "recovery")
    assert saved["content"] == "Hazır, workflow'u çalıştırdım."


@pytest.mark.asyncio
async def test_live_guard_no_retry_after_replay_unsafe_action(monkeypatch):
    async def fake_add_message(*_a, **_k):
        return None

    async def fake_classify(*_a, **_k):
        return Tier.MEDIUM

    async def emit_action(deps):
        deps.real_action_executed = True  # simulate execute_workflow having run

    monkeypatch.setattr(runner.settings, "model_profile", "deepseek")
    monkeypatch.setattr(runner, "classify_tier", fake_classify)
    monkeypatch.setattr(runner, "key_for_provider", lambda *_a: "key")
    monkeypatch.setattr(runner, "build_model", lambda *_a: object())

    calls = {"n": 0}

    def make_agent(_m):
        calls["n"] += 1
        return FakeStreamingAgent(_text_events("execute_workflow({'x':1})"), emit=emit_action)

    monkeypatch.setattr(runner, "create_agent", make_agent)
    monkeypatch.setattr(runner.store, "add_message", fake_add_message)
    _recognize_fake_model_node(monkeypatch)

    events = [
        _parse_sse(raw)
        async for raw in runner.run("u1", "c1", [{"role": "user", "content": "çalıştır"}])
        if raw.startswith("event:")
    ]
    names = [e for e, _ in events]
    recovery = next(d for e, d in events if e == "recovery")
    final_attempt = recovery["failed_attempt_id"]
    final_tokens = [
        d["text"] for e, d in events if e == "token" and d["attempt_id"] == final_attempt
    ]

    assert names[-1] == "done"  # graceful, not an error loop
    assert calls["n"] == 1  # NO retry — a real action had run
    assert recovery["retrying"] is False
    assert final_tokens[-1] == runner.DEGRADED_MESSAGE


@pytest.mark.asyncio
async def test_terminal_provider_error_after_unsafe_action_uses_degraded_recovery(monkeypatch):
    async def fake_attempt(**kwargs):
        kwargs["deps"].real_action_executed = True
        kwargs["deps"].replay_unsafe_tool = "execute_workflow"
        yield (
            "",
            "provider-error",
            _ProviderError("insufficient_quota", 429),
            None,
            [],
            {},
        )

    async def fake_persist(*_args, **kwargs):
        yield runner._sse("done", {"attempt_id": kwargs["attempt_id"]})

    monkeypatch.setattr(runner, "_run_guarded_attempt", fake_attempt)
    monkeypatch.setattr(runner, "_persist_and_done", fake_persist)

    def make_deps(attempt_id):
        from src.agent.schemas import AgentDeps

        return AgentDeps(
            user_id="u1",
            conversation_id="c1",
            event_queue=asyncio.Queue(),
            attempt_id=attempt_id,
        )

    events = [
        _parse_sse(raw)
        async for raw in runner._run_guarded_with_retry(
            choice=SimpleNamespace(provider="deepseek", model="deepseek-v4-pro"),
            tier=Tier.MEDIUM,
            model=object(),
            model_settings=None,
            make_deps=make_deps,
            user_prompt="run it",
            message_history=[],
            user_id="u1",
            conv_id="c1",
            initial_attempt_id="attempt-1",
        )
        if raw.startswith("event:")
    ]

    recovery = next(data for event, data in events if event == "recovery")
    assert recovery["retrying"] is False
    assert recovery["message"] == runner.DEGRADED_MESSAGE
    assert all(event != "error" for event, _data in events)


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
async def test_persist_and_done_records_completed_agent_usage(monkeypatch, make_agent_deps):
    recorded = []

    async def fake_save_usage(user_id: str, **kwargs):
        recorded.append((user_id, kwargs))

    async def fake_add_message(*_args, **_kwargs):
        return None

    monkeypatch.setattr(runner.store, "save_agent_usage_event", fake_save_usage)
    monkeypatch.setattr(runner.store, "add_message", fake_add_message)

    usage = SimpleNamespace(
        input_tokens=1200,
        output_tokens=300,
        cache_read_tokens=800,
        cache_write_tokens=25,
        requests=2,
        tool_calls=5,
    )
    choice = SimpleNamespace(provider="deepseek", model="deepseek-v4-pro")
    deps = make_agent_deps(user_id="user_1", conversation_id="conv_1")

    events = [
        _parse_sse(raw)
        async for raw in runner._persist_and_done(
            deps,
            "Done.",
            choice,
            Tier.MEDIUM,
            "user_1",
            "conv_1",
            usage=usage,
            attempt_id="attempt_1",
            run_id="run_1",
        )
    ]

    assert events[-1][0] == "done"
    assert recorded == [
        (
            "user_1",
            {
                "run_id": "run_1",
                "conversation_id": "conv_1",
                "provider": "deepseek",
                "model": "deepseek-v4-pro",
                "tier": "medium",
                "input_tokens": 1200,
                "output_tokens": 300,
                "cache_read_tokens": 800,
                "cache_write_tokens": 25,
                "model_requests": 2,
                "tool_calls": 5,
            },
        )
    ]


@pytest.mark.asyncio
async def test_usage_persist_failure_does_not_break_done_event(monkeypatch, make_agent_deps):
    async def fail_usage(*_args, **_kwargs):
        raise RuntimeError("firestore unavailable")

    async def fake_add_message(*_args, **_kwargs):
        return None

    monkeypatch.setattr(runner.store, "save_agent_usage_event", fail_usage)
    monkeypatch.setattr(runner.store, "add_message", fake_add_message)

    usage = SimpleNamespace(
        input_tokens=1,
        output_tokens=2,
        cache_read_tokens=0,
        cache_write_tokens=0,
        requests=1,
        tool_calls=0,
    )
    choice = SimpleNamespace(provider="openai", model="gpt-5-mini")
    deps = make_agent_deps(user_id="user_1", conversation_id="conv_1")

    events = [
        _parse_sse(raw)
        async for raw in runner._persist_and_done(
            deps,
            "Done.",
            choice,
            Tier.SIMPLE,
            "user_1",
            "conv_1",
            usage=usage,
            attempt_id="attempt_1",
        )
    ]

    assert events[-1][0] == "done"


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


# ---------------------------------------------------------------------------
# Task 3: StepAssembler wired into runner — segmented steps persistence tests
# ---------------------------------------------------------------------------


class _FakeMultiRoundRun:
    """agent.iter() taklidi: her tur için bir model-request node yield eder,
    turdan SONRA (varsa) tool emit eder -> token...tool_call...token sırası."""

    def __init__(self, deps, rounds):
        self._deps = deps
        self._rounds = rounds
        self.ctx = object()
        self.result = FakeResult()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_a):
        return False

    async def __aiter__(self):
        for events, emit in self._rounds:
            yield _FakeModelRequestNode(events)
            if emit is not None:
                await emit(self._deps)


class FakeMultiRoundAgent:
    def __init__(self, rounds):
        self._rounds = rounds

    def iter(self, _prompt, *, deps, message_history, model_settings, usage_limits):
        return _FakeMultiRoundRun(deps, self._rounds)


@pytest.mark.asyncio
async def test_runner_persists_segmented_steps_multi_round(monkeypatch):
    saved = {}

    async def fake_add_message(*args, **kwargs):
        saved["content"] = args[3]
        saved["steps"] = kwargs.get("steps")

    async def fake_classify(*_a, **_k):
        return Tier.MEDIUM

    async def emit_creds(deps):
        await deps.emit_tool_call("list_credentials")

    rounds = [
        (_text_events("Önce kontrol edeyim."), emit_creds),
        (_text_events("Hazır."), None),
    ]

    monkeypatch.setattr(runner.settings, "model_profile", "default")  # live path
    monkeypatch.setattr(runner, "classify_tier", fake_classify)
    monkeypatch.setattr(runner, "key_for_provider", lambda *_a: "key")
    monkeypatch.setattr(runner, "build_model", lambda *_a: object())
    monkeypatch.setattr(runner, "create_agent", lambda _m: FakeMultiRoundAgent(rounds))
    monkeypatch.setattr(runner.store, "add_message", fake_add_message)
    _recognize_fake_model_node(monkeypatch)

    _ = [
        raw
        async for raw in runner.run("u", "c", [{"role": "user", "content": "x"}])
        if raw.startswith("event:")
    ]

    assert saved["content"] == "Önce kontrol edeyim.Hazır."  # content preserved
    assert saved["steps"] == [
        {"kind": "text", "text": "Önce kontrol edeyim."},
        {"kind": "activity", "actions": ["list_credentials"]},
        {"kind": "text", "text": "Hazır."},
    ]


@pytest.mark.asyncio
async def test_runner_single_round_persists_no_steps(monkeypatch):
    saved = {}

    async def fake_add_message(*args, **kwargs):
        saved["content"] = args[3]
        saved["steps"] = kwargs.get("steps")

    async def fake_classify(*_a, **_k):
        return Tier.MEDIUM

    monkeypatch.setattr(runner.settings, "model_profile", "default")
    monkeypatch.setattr(runner, "classify_tier", fake_classify)
    monkeypatch.setattr(runner, "key_for_provider", lambda *_a: "key")
    monkeypatch.setattr(runner, "build_model", lambda *_a: object())
    monkeypatch.setattr(
        runner, "create_agent", lambda _m: FakeMultiRoundAgent([(_text_events("Tek cevap."), None)])
    )
    monkeypatch.setattr(runner.store, "add_message", fake_add_message)
    _recognize_fake_model_node(monkeypatch)

    _ = [
        raw
        async for raw in runner.run("u", "c", [{"role": "user", "content": "x"}])
        if raw.startswith("event:")
    ]

    assert saved["content"] == "Tek cevap."
    assert saved["steps"] is None  # single text step -> not segmented -> not stored


@pytest.mark.asyncio
async def test_buffered_path_persists_segmented_steps(monkeypatch):
    saved = {}

    async def fake_add_message(*args, **kwargs):
        saved["steps"] = kwargs.get("steps")

    async def fake_classify(*_a, **_k):
        return Tier.MEDIUM

    async def emit_create(deps):
        await deps.emit_tool_call("create_workflow")

    rounds = [
        (_text_events("Oluşturuyorum."), emit_create),
        (_text_events("Bitti."), None),
    ]

    monkeypatch.setattr(runner.settings, "model_profile", "deepseek")  # buffered path
    monkeypatch.setattr(runner.settings, "enable_reliability_guard", True)
    monkeypatch.setattr(runner, "classify_tier", fake_classify)
    monkeypatch.setattr(runner, "key_for_provider", lambda *_a: "key")
    monkeypatch.setattr(runner, "build_model", lambda *_a: object())
    monkeypatch.setattr(runner, "create_agent", lambda _m: FakeMultiRoundAgent(rounds))
    monkeypatch.setattr(runner.store, "add_message", fake_add_message)
    _recognize_fake_model_node(monkeypatch)

    _ = [
        raw
        async for raw in runner.run("u", "c", [{"role": "user", "content": "kur"}])
        if raw.startswith("event:")
    ]

    assert saved["steps"] == [
        {"kind": "text", "text": "Oluşturuyorum."},
        {"kind": "activity", "actions": ["create_workflow"]},
        {"kind": "text", "text": "Bitti."},
    ]


# --- internal-context echo strip (model imitates [Conduut internal context ...]) ---


def test_strip_internal_context_removes_future_tool_calls_annotation():
    text = (
        "Nasıl ilerlemek istersin?\n\n"
        "[Conduut internal context for future tool calls: "
        "user_input_request question=Nasıl ilerlemek istersin? missingFields=['AI servisi kararı']]"
    )
    assert runner.strip_internal_context(text) == "Nasıl ilerlemek istersin?"


def test_strip_internal_context_removes_answer_annotation():
    text = (
        "Tamam, devam ediyorum.\n\n"
        "[Conduut internal context: this user message answers the previous "
        "user_input_request question=X. Treat this answer as accumulated task information.]"
    )
    assert runner.strip_internal_context(text) == "Tamam, devam ediyorum."


def test_strip_internal_context_leaves_clean_text_untouched():
    text = "Sadece normal bir cevap [köşeli parantez] içeren."
    assert runner.strip_internal_context(text) == text


def test_strip_internal_context_handles_annotation_only():
    text = "[Conduut internal context for future tool calls: workflow_preview id=wf_1]"
    assert runner.strip_internal_context(text) == ""


@pytest.mark.asyncio
async def test_buffered_path_strips_echoed_internal_context(monkeypatch):
    saved = {}

    async def fake_add_message(*args, **kwargs):
        saved["content"] = args[3]

    async def fake_classify(*_a, **_k):
        return Tier.MEDIUM

    echoed = (
        "Hazır, ne yapmak istersin?\n\n"
        "[Conduut internal context for future tool calls: "
        "user_input_request question=Q missingFields=['x']]"
    )

    monkeypatch.setattr(runner.settings, "model_profile", "deepseek")  # buffered path
    monkeypatch.setattr(runner.settings, "enable_reliability_guard", True)
    monkeypatch.setattr(runner, "classify_tier", fake_classify)
    monkeypatch.setattr(runner, "key_for_provider", lambda *_a: "key")
    monkeypatch.setattr(runner, "build_model", lambda *_a: object())
    monkeypatch.setattr(runner, "create_agent", lambda _m: FakeStreamingAgent(_text_events(echoed)))
    monkeypatch.setattr(runner.store, "add_message", fake_add_message)
    _recognize_fake_model_node(monkeypatch)

    events = [
        _parse_sse(raw)
        async for raw in runner.run("u", "c", [{"role": "user", "content": "x"}])
        if raw.startswith("event:")
    ]
    token_text = "".join(d["text"] for e, d in events if e == "token")

    assert "[Conduut internal context" not in token_text  # buffered replay stripped
    assert token_text == "Hazır, ne yapmak istersin?"
    assert "[Conduut internal context" not in saved["content"]  # persisted content stripped
    assert saved["content"] == "Hazır, ne yapmak istersin?"


@pytest.mark.asyncio
async def test_guarded_path_strips_internal_context_split_across_deltas(monkeypatch):
    saved = {}

    async def fake_add_message(*args, **kwargs):
        saved["content"] = args[3]

    async def fake_classify(*_a, **_k):
        return Tier.MEDIUM

    events = [
        PartStartEvent(index=0, part=TextPart(content="Hazır.\n\n[Conduut internal")),
        PartDeltaEvent(
            index=0,
            delta=TextPartDelta(content_delta=" context for future tool calls: secret]"),
        ),
    ]
    monkeypatch.setattr(runner.settings, "model_profile", "deepseek")
    monkeypatch.setattr(runner.settings, "enable_reliability_guard", True)
    monkeypatch.setattr(runner, "classify_tier", fake_classify)
    monkeypatch.setattr(runner, "key_for_provider", lambda *_a: "key")
    monkeypatch.setattr(runner, "build_model", lambda *_a: object())
    monkeypatch.setattr(runner, "create_agent", lambda _m: FakeStreamingAgent(events))
    monkeypatch.setattr(runner.store, "add_message", fake_add_message)
    _recognize_fake_model_node(monkeypatch)

    parsed = [
        _parse_sse(raw)
        async for raw in runner.run("u", "c", [{"role": "user", "content": "x"}])
        if raw.startswith("event:")
    ]
    token_text = "".join(data["text"] for event, data in parsed if event == "token")

    assert token_text == "Hazır."
    assert saved["content"] == "Hazır."


@pytest.mark.asyncio
async def test_runner_injects_gathered_state_into_deps(monkeypatch):
    captured = {}

    async def fake_classify(*_a, **_k):
        return Tier.MEDIUM

    async def fake_add_message(*_a, **_k):
        return None

    state = UserPlatformState(
        connections=[
            ConnectionSummary(service="gmail", account_email="u@x.com", status="connected")
        ]
    )

    async def fake_gather(*_a, **_k):
        return state

    class CapturingAgent(FakeStreamingAgent):
        def iter(self, _prompt, *, deps, message_history, model_settings, usage_limits):
            captured["platform_state"] = deps.platform_state
            return super().iter(
                _prompt,
                deps=deps,
                message_history=message_history,
                model_settings=model_settings,
                usage_limits=usage_limits,
            )

    monkeypatch.setattr(runner.settings, "model_profile", "default")
    monkeypatch.setattr(runner, "classify_tier", fake_classify)
    monkeypatch.setattr(runner, "gather_user_state", fake_gather)  # overrides autouse stub
    monkeypatch.setattr(runner, "key_for_provider", lambda *_a: "key")
    monkeypatch.setattr(runner, "build_model", lambda *_a: object())
    monkeypatch.setattr(runner, "create_agent", lambda _m: CapturingAgent(_text_events("ok")))
    monkeypatch.setattr(runner.store, "add_message", fake_add_message)
    _recognize_fake_model_node(monkeypatch)

    _ = [raw async for raw in runner.run("u1", "c1", [{"role": "user", "content": "hi"}])]

    assert captured["platform_state"] is state
    assert captured["platform_state"].connections[0].service == "gmail"
