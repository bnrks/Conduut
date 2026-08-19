import pytest
from fastapi import HTTPException

from src import store
from src.executions import RunDetail
from src.routes import chat as chat_route


@pytest.fixture(autouse=True)
def _stub_n8n_resolution(monkeypatch):
    async def fake_resolve(*_args, **_kwargs):
        return object()

    async def fake_client(*_args, **_kwargs):
        return object()

    monkeypatch.setattr(chat_route.resolver, "resolve", fake_resolve)
    monkeypatch.setattr(chat_route.client_factory, "for_request_context", fake_client)


@pytest.mark.asyncio
async def test_chat_send_streams_runner_response(monkeypatch):
    monkeypatch.setattr(chat_route, "get_user_id", lambda _request: "user_1")
    captured_runner_args = {}
    captured_store_kwargs = {}

    async def fake_get_or_create_conversation(*_args, **_kwargs):
        captured_store_kwargs.update(_kwargs)
        return store.Conversation(
            id="conv_1",
            title="New conversation",
            message_count=0,
            created_at="now",
            updated_at="now",
            execution_policy="safe",
            execution_policy_locked=True,
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

    async def fake_runner_run(*args, **kwargs):
        captured_runner_args["messages"] = args[2]
        captured_runner_args["execution_policy"] = kwargs["execution_policy"]
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
    assert response.headers["x-execution-policy"] == "safe"
    assert response.headers["x-execution-policy-locked"] == "true"
    assert chunks == ['event: done\ndata: {"conversation_id": "conv_1"}\n\n']
    assert captured_runner_args["messages"][0]["attachments"][0]["type"] == "user_input_request"
    assert captured_runner_args["execution_policy"] == "safe"
    assert captured_store_kwargs["execution_policy"] == "safe"


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

    async def fake_get_conversation(*_args, **_kwargs):
        return store.Conversation(
            id="conv_1",
            title="New conversation",
            message_count=0,
            created_at="now",
            updated_at="now",
            execution_policy="safe",
            execution_policy_locked=True,
        )

    async def fake_get_or_create_conversation(*_args, **_kwargs):
        return store.Conversation(
            id="conv_1",
            title="New conversation",
            message_count=0,
            created_at="now",
            updated_at="now",
            execution_policy="safe",
            execution_policy_locked=True,
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
    monkeypatch.setattr(chat_route.store, "get_conversation", fake_get_conversation)
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

    async def fake_get_run(user_id: str, execution_id: str, **_kwargs):
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
            execution_policy="safe",
            execution_policy_locked=True,
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

    async def fake_get_run(_user_id: str, _execution_id: str, **_kwargs):
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


@pytest.mark.asyncio
async def test_chat_send_omitted_policy_uses_existing_fast_conversation(monkeypatch):
    monkeypatch.setattr(chat_route, "get_user_id", lambda _request: "user_1")
    captured_runner_kwargs = {}

    async def fake_get_conversation(*_args, **_kwargs):
        return store.Conversation(
            id="conv_fast",
            title="Fast conversation",
            message_count=3,
            created_at="now",
            updated_at="now",
            execution_policy="fast",
            execution_policy_locked=True,
        )

    async def fake_get_or_create_conversation(*_args, **_kwargs):
        return store.Conversation(
            id="conv_fast",
            title="Fast conversation",
            message_count=3,
            created_at="now",
            updated_at="now",
            execution_policy="fast",
            execution_policy_locked=True,
        )

    async def fake_add_message(*_args, **_kwargs):
        return None

    async def fake_get_messages(*_args, **_kwargs):
        return [store.Message(id="msg_1", role="user", content="continue", created_at="now")]

    async def fake_runner_run(*_args, **kwargs):
        captured_runner_kwargs.update(kwargs)
        yield 'event: done\ndata: {"conversation_id": "conv_fast"}\n\n'

    monkeypatch.setattr(
        chat_route.store, "get_or_create_conversation", fake_get_or_create_conversation
    )
    monkeypatch.setattr(chat_route.store, "get_conversation", fake_get_conversation)
    monkeypatch.setattr(chat_route.store, "add_message", fake_add_message)
    monkeypatch.setattr(chat_route.store, "get_conversation_messages", fake_get_messages)
    monkeypatch.setattr(chat_route.runner, "run", fake_runner_run)

    response = await chat_route.chat_send(
        object(),
        chat_route.ChatRequest(content="continue", conversation_id="conv_fast"),
    )
    _ = [chunk async for chunk in response.body_iterator]

    assert response.headers["x-execution-policy"] == "fast"
    assert captured_runner_kwargs["execution_policy"] == "fast"


@pytest.mark.asyncio
async def test_chat_send_rejects_locked_execution_policy_mismatch(monkeypatch):
    monkeypatch.setattr(chat_route, "get_user_id", lambda _request: "user_1")

    async def fake_get_conversation(*_args, **_kwargs):
        return store.Conversation(
            id="conv_safe",
            title="Safe conversation",
            message_count=1,
            created_at="now",
            updated_at="now",
            execution_policy="safe",
            execution_policy_locked=True,
        )

    async def fake_get_or_create_conversation(*_args, **_kwargs):
        return store.Conversation(
            id="conv_safe",
            title="Safe conversation",
            message_count=1,
            created_at="now",
            updated_at="now",
            execution_policy="safe",
            execution_policy_locked=True,
        )

    async def fail_add_message(*_args, **_kwargs):
        raise AssertionError("message must not be persisted on policy mismatch")

    monkeypatch.setattr(
        chat_route.store, "get_or_create_conversation", fake_get_or_create_conversation
    )
    monkeypatch.setattr(chat_route.store, "get_conversation", fake_get_conversation)
    monkeypatch.setattr(chat_route.store, "add_message", fail_add_message)

    with pytest.raises(HTTPException) as exc_info:
        await chat_route.chat_send(
            object(),
            chat_route.ChatRequest(
                content="continue",
                conversation_id="conv_safe",
                execution_policy="fast",
            ),
        )

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail == {
        "code": "execution_policy_locked",
        "message": "This conversation is locked to the existing execution policy.",
        "execution_policy": "safe",
    }


@pytest.mark.asyncio
async def test_chat_send_persists_setup_mode_on_new_conversation(monkeypatch):
    monkeypatch.setattr(chat_route, "get_user_id", lambda _request: "user_1")
    captured_store_kwargs = {}
    captured_runner_kwargs = {}

    async def fake_get_or_create_conversation(*_args, **kwargs):
        captured_store_kwargs.update(kwargs)
        return store.Conversation(
            id="conv_setup",
            title="Setup conversation",
            message_count=0,
            created_at="now",
            updated_at="now",
            execution_policy="safe",
            execution_policy_locked=True,
            conversation_mode="automation-server-setup",
            setup_next_stage="requirements",
            setup_stage_locked=False,
        )

    async def fake_add_message(*_args, **_kwargs):
        return None

    async def fake_get_messages(*_args, **_kwargs):
        return [
            store.Message(id="msg_1", role="user", content="help me set it up", created_at="now")
        ]

    async def fake_runner_run(*_args, **kwargs):
        captured_runner_kwargs.update(kwargs)
        yield 'event: done\ndata: {"conversation_id": "conv_setup"}\n\n'

    monkeypatch.setattr(
        chat_route.store, "get_or_create_conversation", fake_get_or_create_conversation
    )
    monkeypatch.setattr(chat_route.store, "add_message", fake_add_message)
    monkeypatch.setattr(chat_route.store, "get_conversation_messages", fake_get_messages)
    monkeypatch.setattr(chat_route.runner, "run", fake_runner_run)

    response = await chat_route.chat_send(
        object(),
        chat_route.ChatRequest(content="help me set it up", intent="automation-server-setup"),
    )
    _ = [chunk async for chunk in response.body_iterator]

    assert captured_store_kwargs["conversation_mode"] == "automation-server-setup"
    assert captured_runner_kwargs["conversation_mode"] == "automation-server-setup"
    assert response.headers["x-conversation-mode"] == "automation-server-setup"


@pytest.mark.asyncio
async def test_chat_send_rejects_conversation_mode_change(monkeypatch):
    monkeypatch.setattr(chat_route, "get_user_id", lambda _request: "user_1")

    async def fake_get_conversation(*_args, **_kwargs):
        return store.Conversation(
            id="conv_default",
            title="Default conversation",
            message_count=1,
            created_at="now",
            updated_at="now",
            execution_policy="safe",
            execution_policy_locked=True,
            conversation_mode="default",
        )

    async def fail_create(*_args, **_kwargs):
        raise AssertionError("conversation should not be recreated when mode is locked")

    monkeypatch.setattr(chat_route.store, "get_conversation", fake_get_conversation)
    monkeypatch.setattr(chat_route.store, "get_or_create_conversation", fail_create)

    with pytest.raises(HTTPException) as exc_info:
        await chat_route.chat_send(
            object(),
            chat_route.ChatRequest(
                content="switch to setup",
                conversation_id="conv_default",
                intent="automation-server-setup",
            ),
        )

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail == {
        "code": "conversation_mode_locked",
        "message": "This conversation is locked to the existing mode.",
        "conversation_mode": "default",
    }


@pytest.mark.asyncio
async def test_chat_send_rejects_setup_secret_before_persist(monkeypatch):
    monkeypatch.setattr(chat_route, "get_user_id", lambda _request: "user_1")

    async def fail_create(*_args, **_kwargs):
        raise AssertionError("conversation must not be created when a secret is pasted")

    async def fail_add_message(*_args, **_kwargs):
        raise AssertionError("secret message must not be persisted")

    monkeypatch.setattr(chat_route.store, "get_or_create_conversation", fail_create)
    monkeypatch.setattr(chat_route.store, "add_message", fail_add_message)

    with pytest.raises(HTTPException) as exc_info:
        await chat_route.chat_send(
            object(),
            chat_route.ChatRequest(
                content="N8N_ENCRYPTION_KEY=supersecretvalue",
                intent="automation-server-setup",
            ),
        )

    assert exc_info.value.status_code == 422
    assert exc_info.value.detail["code"] == "setup_secret_not_allowed"
    assert exc_info.value.detail["secret_kind"] == "n8n_encryption_key"


@pytest.mark.asyncio
async def test_existing_setup_conversation_infers_mode_and_exposes_reply_available(monkeypatch):
    monkeypatch.setattr(chat_route, "get_user_id", lambda _request: "user_1")
    captured_runner_kwargs = {}

    async def fake_get_conversation(*_args, **_kwargs):
        return store.Conversation(
            id="conv_setup",
            title="Setup conversation",
            message_count=2,
            created_at="now",
            updated_at="now",
            execution_policy="safe",
            execution_policy_locked=True,
            conversation_mode="automation-server-setup",
            setup_next_stage="requirements",
            setup_stage_locked=True,
            setup_last_stage="requirements",
        )

    async def fake_get_or_create_conversation(*_args, **_kwargs):
        return store.Conversation(
            id="conv_setup",
            title="Setup conversation",
            message_count=2,
            created_at="now",
            updated_at="now",
            execution_policy="safe",
            execution_policy_locked=True,
            conversation_mode="automation-server-setup",
            setup_next_stage="requirements",
            setup_stage_locked=True,
            setup_last_stage="requirements",
        )

    async def fake_add_message(*_args, **_kwargs):
        return None

    async def fake_get_messages(*_args, **_kwargs):
        return [
            store.Message(
                id="msg_1", role="user", content="automation.example.com", created_at="now"
            )
        ]

    async def fake_runner_run(*_args, **kwargs):
        captured_runner_kwargs.update(kwargs)
        yield 'event: done\ndata: {"conversation_id": "conv_setup"}\n\n'

    async def fail_save_setup_state(*_args, **_kwargs):
        raise AssertionError("route must not mutate setup stage state directly")

    monkeypatch.setattr(chat_route.store, "get_conversation", fake_get_conversation)
    monkeypatch.setattr(
        chat_route.store, "get_or_create_conversation", fake_get_or_create_conversation
    )
    monkeypatch.setattr(chat_route.store, "save_setup_stage_state", fail_save_setup_state)
    monkeypatch.setattr(chat_route.store, "add_message", fake_add_message)
    monkeypatch.setattr(chat_route.store, "get_conversation_messages", fake_get_messages)
    monkeypatch.setattr(chat_route.runner, "run", fake_runner_run)

    response = await chat_route.chat_send(
        object(),
        chat_route.ChatRequest(content="automation.example.com", conversation_id="conv_setup"),
    )
    _ = [chunk async for chunk in response.body_iterator]

    assert captured_runner_kwargs["conversation_mode"] == "automation-server-setup"
    assert captured_runner_kwargs["setup_stage_reply_available"] is True
    assert response.headers["x-conversation-mode"] == "automation-server-setup"
