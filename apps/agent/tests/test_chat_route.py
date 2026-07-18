import pytest
from fastapi import HTTPException

from src import store
from src.executions import RunDetail
from src.routes import chat as chat_route


@pytest.mark.asyncio
async def test_chat_send_streams_runner_response(monkeypatch):
    monkeypatch.setattr(chat_route, "get_user_id", lambda _request: "user_1")
    captured_runner_args = {}

    async def fake_get_or_create_conversation(*_args, **_kwargs):
        return store.Conversation(
            id="conv_1",
            title="New conversation",
            message_count=0,
            created_at="now",
            updated_at="now",
        )

    monkeypatch.setattr(
        chat_route.store,
        "get_or_create_conversation",
        fake_get_or_create_conversation,
    )

    async def fake_add_message(*_args, **_kwargs):
        return None

    async def fake_get_messages(*_args, **_kwargs):
        return [
            store.Message(
                id="msg_0",
                role="assistant",
                content="Hangi alicilara gondereyim?",
                created_at="now",
                attachments=[
                    {
                        "type": "user_input_request",
                        "data": {
                            "question": "Hangi alicilara gondereyim?",
                            "missingFields": ["recipients"],
                        },
                    }
                ],
            ),
            store.Message(
                id="msg_1",
                role="user",
                content="hello",
                created_at="now",
            ),
        ]

    async def fake_runner_run(*args, **_kwargs):
        captured_runner_args["messages"] = args[2]
        yield 'event: done\ndata: {"conversation_id": "conv_1"}\n\n'

    monkeypatch.setattr(chat_route.store, "add_message", fake_add_message)
    monkeypatch.setattr(chat_route.store, "get_conversation_messages", fake_get_messages)
    monkeypatch.setattr(chat_route.runner, "run", fake_runner_run)

    response = await chat_route.chat_send(
        object(),
        chat_route.ChatRequest(content="hello"),
    )

    chunks = [chunk async for chunk in response.body_iterator]

    assert response.media_type == "text/event-stream"
    assert response.headers["x-conversation-id"] == "conv_1"
    assert chunks == ['event: done\ndata: {"conversation_id": "conv_1"}\n\n']
    assert captured_runner_args["messages"][0]["attachments"][0]["type"] == "user_input_request"


def test_chat_request_ignores_legacy_provider_fields():
    # The agent no longer takes provider/model from the request; a stale frontend
    # that still POSTs them must not cause a 422.
    req = chat_route.ChatRequest(
        content="hi", provider="openai", model="gpt-4o", reasoning_effort="low"
    )
    assert req.content == "hi"
    assert not hasattr(req, "provider")


@pytest.mark.asyncio
async def test_chat_send_persists_structured_workflow_approval(monkeypatch):
    monkeypatch.setattr(chat_route, "get_user_id", lambda _request: "user_1")
    captured = {}

    async def fake_get_or_create_conversation(*_args, **_kwargs):
        return store.Conversation(
            id="conv_1",
            title="New conversation",
            message_count=0,
            created_at="now",
            updated_at="now",
        )

    async def fake_add_message(*args, **kwargs):
        captured["attachments"] = kwargs.get("attachments")

    async def fake_get_messages(*_args, **_kwargs):
        return [
            store.Message(
                id="msg_1",
                role="user",
                content="run_confirmation: Approve run",
                created_at="now",
                attachments=captured["attachments"],
            )
        ]

    async def fake_runner_run(*args, **_kwargs):
        captured["messages"] = args[2]
        yield 'event: done\ndata: {"conversation_id": "conv_1"}\n\n'

    monkeypatch.setattr(
        chat_route.store,
        "get_or_create_conversation",
        fake_get_or_create_conversation,
    )
    monkeypatch.setattr(chat_route.store, "add_message", fake_add_message)
    monkeypatch.setattr(chat_route.store, "get_conversation_messages", fake_get_messages)
    monkeypatch.setattr(chat_route.runner, "run", fake_runner_run)

    response = await chat_route.chat_send(
        object(),
        chat_route.ChatRequest(
            content="run_confirmation: Approve run",
            conversation_id="conv_1",
            user_input_response={
                "request_id": "token-1",
                "request_kind": "workflow_run_approval",
                "workflow_id": "wf-1",
                "decision": "approve",
            },
        ),
    )
    _ = [chunk async for chunk in response.body_iterator]

    assert captured["attachments"] == [
        {
            "type": "user_input_response",
            "data": {
                "requestId": "token-1",
                "requestKind": "workflow_run_approval",
                "workflowId": "wf-1",
                "decision": "approve",
            },
        }
    ]
    assert captured["messages"][0]["attachments"] == captured["attachments"]


@pytest.mark.asyncio
async def test_chat_send_canonicalizes_execution_reference_before_storing(monkeypatch):
    monkeypatch.setattr(chat_route, "get_user_id", lambda _request: "user_1")
    calls: dict = {}

    async def fake_get_run(user_id: str, execution_id: str):
        assert user_id == "user_1"
        assert execution_id == "exec_1"
        return RunDetail(
            id="exec_1",
            workflow_id="wf_canonical",
            workflow_name="Broken workflow",
            status="error",
            mode="webhook",
            started_at="2026-07-15T10:00:00Z",
            finished_at="2026-07-15T10:00:01Z",
            duration_ms=1000,
            summary="Workflow run failed.",
            failed_node="Send email",
            error="Authentication failed",
        )

    async def fake_get_or_create_conversation(*_args, **_kwargs):
        return store.Conversation(
            id="conv_1",
            title="New conversation",
            message_count=0,
            created_at="now",
            updated_at="now",
        )

    async def fake_add_message(*args, **kwargs):
        calls["add_message"] = (args, kwargs)

    async def fake_get_messages(*_args, **_kwargs):
        attachment = calls["add_message"][1]["attachments"]
        return [
            store.Message(
                id="msg_1",
                role="user",
                content="Fix it",
                created_at="now",
                attachments=attachment,
            )
        ]

    async def fake_runner_run(*_args, **_kwargs):
        yield 'event: done\ndata: {"conversation_id": "conv_1"}\n\n'

    monkeypatch.setattr(chat_route.executions, "get_run", fake_get_run)
    monkeypatch.setattr(
        chat_route.store,
        "get_or_create_conversation",
        fake_get_or_create_conversation,
    )
    monkeypatch.setattr(chat_route.store, "add_message", fake_add_message)
    monkeypatch.setattr(chat_route.store, "get_conversation_messages", fake_get_messages)
    monkeypatch.setattr(chat_route.runner, "run", fake_runner_run)

    response = await chat_route.chat_send(
        object(),
        chat_route.ChatRequest(
            content="Fix it",
            execution_reference={"execution_id": "exec_1", "intent": "diagnose_and_fix"},
        ),
    )
    _ = [chunk async for chunk in response.body_iterator]

    attachment = calls["add_message"][1]["attachments"][0]
    assert attachment == {
        "type": "execution_reference",
        "data": {
            "executionId": "exec_1",
            "workflowId": "wf_canonical",
            "workflowName": "Broken workflow",
            "status": "error",
            "intent": "diagnose_and_fix",
        },
    }


@pytest.mark.asyncio
async def test_chat_send_rejects_non_failed_execution_before_creating_conversation(monkeypatch):
    monkeypatch.setattr(chat_route, "get_user_id", lambda _request: "user_1")

    async def fake_get_run(_user_id: str, _execution_id: str):
        return RunDetail(
            id="exec_ok",
            workflow_id="wf_1",
            workflow_name="Healthy workflow",
            status="success",
            started_at="2026-07-15T10:00:00Z",
            summary="Workflow run completed.",
        )

    async def fail_create(*_args, **_kwargs):
        raise AssertionError("conversation must not be created")

    monkeypatch.setattr(chat_route.executions, "get_run", fake_get_run)
    monkeypatch.setattr(chat_route.store, "get_or_create_conversation", fail_create)

    with pytest.raises(HTTPException) as exc_info:
        await chat_route.chat_send(
            object(),
            chat_route.ChatRequest(
                content="Fix it",
                execution_reference={"execution_id": "exec_ok"},
            ),
        )

    assert exc_info.value.status_code == 409
