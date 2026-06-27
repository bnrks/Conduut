import pytest

from src import store
from src.routes import conversations as conversations_route


@pytest.mark.asyncio
async def test_get_conversation_returns_chat_ui_message_shape(monkeypatch):
    monkeypatch.setattr(conversations_route, "get_user_id", lambda _request: "user_1")

    async def fake_get_conversation(_user_id: str, _conversation_id: str):
        return store.Conversation(
            id="conv_1",
            title="Artifact test",
            message_count=2,
            created_at="2026-05-25T12:00:00+00:00",
            updated_at="2026-05-25T12:01:00+00:00",
            provider="openai",
            model="gpt-5",
            reasoning_effort="medium",
            messages=[
                store.Message(
                    id="msg_1",
                    role="assistant",
                    content="Done.",
                    created_at="2026-05-25T12:01:00+00:00",
                    attachments=[
                        {
                            "type": "artifact_preview",
                            "data": {
                                "service": "google_sheets",
                                "title": "Google Sheets range updated",
                                "url": ("https://docs.google.com/spreadsheets/d/sheet_1/edit"),
                                "table": {
                                    "columns": ["Email"],
                                    "rows": [{"Email": "person@example.com"}],
                                },
                            },
                        }
                    ],
                )
            ],
        )

    monkeypatch.setattr(conversations_route.store, "get_conversation", fake_get_conversation)

    response = await conversations_route.get_conversation("conv_1", object())

    assert response["messageCount"] == 2
    assert response["createdAt"] == "2026-05-25T12:00:00+00:00"
    assert response["reasoningEffort"] == "medium"
    assert response["messages"][0]["role"] == "agent"
    assert response["messages"][0]["createdAt"] == "2026-05-25T12:01:00+00:00"
    assert response["messages"][0]["attachments"][0]["type"] == "artifact_preview"


@pytest.mark.asyncio
async def test_get_conversation_serializes_steps(monkeypatch):
    """GET /conversations/{id} must include the `steps` list on each message."""
    monkeypatch.setattr(conversations_route, "get_user_id", lambda _request: "user_1")

    _steps = [
        {"kind": "text", "text": "a"},
        {"kind": "activity", "actions": ["create_workflow"]},
        {"kind": "text", "text": "b"},
    ]

    async def fake_get_conversation(_user_id: str, _conversation_id: str):
        return store.Conversation(
            id="conv_2",
            title="Steps test",
            message_count=1,
            created_at="2026-06-27T10:00:00+00:00",
            updated_at="2026-06-27T10:01:00+00:00",
            provider="anthropic",
            model="claude-sonnet-4-6",
            reasoning_effort=None,
            messages=[
                store.Message(
                    id="msg_2",
                    role="assistant",
                    content="Done.",
                    created_at="2026-06-27T10:01:00+00:00",
                    attachments=None,
                    steps=_steps,
                )
            ],
        )

    monkeypatch.setattr(conversations_route.store, "get_conversation", fake_get_conversation)

    response = await conversations_route.get_conversation("conv_2", object())

    assert response["messages"][0]["steps"] == _steps
