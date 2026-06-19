import structlog
from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict

from src import store
from src.agent import runner
from src.auth import get_user_id

log = structlog.get_logger()
router = APIRouter()


class ChatRequest(BaseModel):
    # Tolerate stale frontend fields (provider/model/reasoning_effort) without a 422.
    model_config = ConfigDict(extra="ignore")

    content: str
    conversation_id: str | None = None


@router.post("/chat/send")
async def chat_send(request: Request, body: ChatRequest):
    user_id = get_user_id(request)
    request_state = getattr(request, "state", None)
    request_headers = getattr(request, "headers", {})
    request_id = getattr(request_state, "request_id", None) or request_headers.get(
        "x-request-id", None
    )
    log.info(
        "chat_send_started",
        user_id=user_id,
        conversation_id=body.conversation_id,
        content_length=len(body.content),
    )

    conv = await store.get_or_create_conversation(user_id, body.conversation_id)
    await store.add_message(user_id, conv.id, "user", body.content)
    log.info("chat_conversation_ready", user_id=user_id, conversation_id=conv.id)

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
        runner.run(user_id, conv.id, messages, request_id=request_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "X-Conversation-Id": conv.id,
        },
    )
