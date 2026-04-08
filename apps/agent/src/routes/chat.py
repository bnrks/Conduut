import json
from typing import AsyncIterator

import litellm
import structlog
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from src.auth import get_user_id
from src import store

log = structlog.get_logger()
router = APIRouter()


class ChatRequest(BaseModel):
    content: str
    conversation_id: str | None = None
    provider: str | None = None
    model: str | None = None


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


async def stream_response(
    user_id: str,
    conv_id: str,
    messages: list[dict],
    settings: store.LLMSettings,
    provider: str,
    model: str,
) -> AsyncIterator[str]:
    model = f"{settings.provider}/{settings.model}"

    try:
        response = await litellm.acompletion(
            model=model,
            messages=messages,
            api_key=settings.api_key,
            stream=True,
        )

        full_content = ""
        async for chunk in response:
            delta = chunk.choices[0].delta
            if delta.content:
                full_content += delta.content
                yield _sse("token", {"text": delta.content, "conversation_id": conv_id})

        await store.add_message(user_id, conv_id, "assistant", full_content, provider=provider, model=model)
        yield _sse("done", {"conversation_id": conv_id, "provider": provider, "model": model})

    except litellm.AuthenticationError:
        yield _sse("error", {"message": "Invalid API key"})
    except litellm.BadRequestError as e:
        yield _sse("error", {"message": str(e)})
    except Exception as e:
        log.error("stream_error", error=str(e))
        yield _sse("error", {"message": "Something went wrong"})


@router.post("/chat/send")
async def chat_send(request: Request, body: ChatRequest):
    user_id = get_user_id(request)

    settings = await store.get_llm_settings(user_id)
    if not settings:
        raise HTTPException(status_code=422, detail="LLM settings not configured. Please add your API key in Settings.")

    # Provider/model override
    if body.provider and body.provider != settings.provider:
        conn = await store.get_provider(user_id, body.provider)
        if conn:
            settings = store.LLMSettings(
                provider=body.provider,
                model=body.model or settings.model,
                api_key=conn.api_key,
            )
    elif body.model:
        settings = store.LLMSettings(
            provider=settings.provider,
            model=body.model,
            api_key=settings.api_key,
        )

    conv = await store.get_or_create_conversation(user_id, body.conversation_id)
    await store.add_message(user_id, conv.id, "user", body.content)

    # Geçmiş mesajları yükle
    msgs = await store.get_conversation_messages(user_id, conv.id)
    messages = [{"role": m.role if m.role != "agent" else "assistant", "content": m.content} for m in msgs]

    return StreamingResponse(
        stream_response(user_id, conv.id, messages, settings, settings.provider, settings.model),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "X-Conversation-Id": conv.id,
        },
    )
