import json

import structlog
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from src import store
from src.agent import runner
from src.agent.provider_factory import (
    UnsupportedProviderError,
    UnsupportedReasoningEffortError,
    normalize_provider,
    normalize_reasoning_effort,
)
from src.auth import get_user_id

log = structlog.get_logger()
router = APIRouter()


class ChatRequest(BaseModel):
    content: str
    conversation_id: str | None = None
    provider: str | None = None
    model: str | None = None
    reasoning_effort: str | None = None


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


@router.post("/chat/send")
async def chat_send(request: Request, body: ChatRequest):
    user_id = get_user_id(request)

    settings = await store.get_llm_settings(user_id)
    if not settings:
        raise HTTPException(
            status_code=422,
            detail="LLM settings not configured. Please add your API key in Settings.",
        )  # noqa: E501

    # Provider/model override
    provider_override = None
    if body.provider:
        try:
            provider_override = normalize_provider(body.provider)
        except UnsupportedProviderError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    if provider_override and provider_override != settings.provider:
        conn = await store.get_provider(user_id, provider_override)
        if conn:
            settings = store.LLMSettings(
                provider=provider_override,
                model=body.model or settings.model,
                api_key=conn.api_key,
                reasoning_effort=None,
            )
    elif body.model:
        settings = store.LLMSettings(
            provider=settings.provider,
            model=body.model,
            api_key=settings.api_key,
            reasoning_effort=None,
        )

    if body.reasoning_effort:
        try:
            settings.reasoning_effort = normalize_reasoning_effort(
                settings.provider, settings.model, body.reasoning_effort
            )
        except UnsupportedReasoningEffortError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    conv = await store.get_or_create_conversation(
        user_id,
        body.conversation_id,
        provider=settings.provider,
        model=settings.model,
        reasoning_effort=settings.reasoning_effort,
    )  # noqa: E501
    await store.add_message(user_id, conv.id, "user", body.content)

    msgs = await store.get_conversation_messages(user_id, conv.id)
    messages = [
        {
            "role": m.role if m.role != "agent" else "assistant",
            "content": m.content,
            "attachments": m.attachments,
        }
        for m in msgs
    ]

    return StreamingResponse(
        runner.run(user_id, conv.id, messages, settings),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "X-Conversation-Id": conv.id,
        },
    )
