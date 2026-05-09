import pytest
from fastapi import HTTPException

from src import store
from src.routes import chat as chat_route


@pytest.mark.asyncio
async def test_chat_send_streams_runner_response(monkeypatch):
    monkeypatch.setattr(chat_route, "get_user_id", lambda _request: "user_1")
    captured_runner_args = {}

    async def fake_get_settings(_user_id: str):
        return store.LLMSettings(
            provider="openai",
            model="gpt-4o-mini",
            api_key="key",
        )

    async def fake_get_or_create_conversation(*_args, **_kwargs):
        return store.Conversation(
            id="conv_1",
            title="New conversation",
            message_count=0,
            created_at="now",
            updated_at="now",
        )

    monkeypatch.setattr(chat_route.store, "get_llm_settings", fake_get_settings)
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


@pytest.mark.asyncio
async def test_chat_send_rejects_unsupported_provider_override(monkeypatch):
    monkeypatch.setattr(chat_route, "get_user_id", lambda _request: "user_1")

    async def fake_get_settings(_user_id: str):
        return store.LLMSettings(
            provider="openai",
            model="gpt-4o-mini",
            api_key="key",
        )

    monkeypatch.setattr(chat_route.store, "get_llm_settings", fake_get_settings)

    with pytest.raises(HTTPException) as exc:
        await chat_route.chat_send(
            object(),
            chat_route.ChatRequest(content="hello", provider="custom"),
        )

    assert exc.value.status_code == 422


@pytest.mark.asyncio
async def test_chat_send_rejects_unsupported_reasoning_effort(monkeypatch):
    monkeypatch.setattr(chat_route, "get_user_id", lambda _request: "user_1")

    async def fake_get_settings(_user_id: str):
        return store.LLMSettings(
            provider="openai",
            model="gpt-4o",
            api_key="key",
        )

    monkeypatch.setattr(chat_route.store, "get_llm_settings", fake_get_settings)

    with pytest.raises(HTTPException) as exc:
        await chat_route.chat_send(
            object(),
            chat_route.ChatRequest(content="hello", reasoning_effort="medium"),
        )

    assert exc.value.status_code == 422
