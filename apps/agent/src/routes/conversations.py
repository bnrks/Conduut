from fastapi import APIRouter, HTTPException, Request

from src import store
from src.auth import get_user_id

router = APIRouter()


def _chat_role(role: str) -> str:
    return "agent" if role in ("assistant", "agent") else role


@router.get("/conversations")
async def list_conversations(request: Request):
    user_id = get_user_id(request)
    convs = await store.list_conversations(user_id)
    return {
        "conversations": [
            {
                "id": c.id,
                "title": c.title,
                "messageCount": c.message_count,
                "lastMessageAt": c.updated_at,
                "createdAt": c.created_at,
            }
            for c in convs
        ]
    }


@router.get("/conversations/{conversation_id}")
async def get_conversation(conversation_id: str, request: Request):
    user_id = get_user_id(request)
    conv = await store.get_conversation(user_id, conversation_id)
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return {
        "id": conv.id,
        "title": conv.title,
        "messageCount": conv.message_count,
        "message_count": conv.message_count,
        "createdAt": conv.created_at,
        "created_at": conv.created_at,
        "updatedAt": conv.updated_at,
        "updated_at": conv.updated_at,
        "provider": conv.provider,
        "model": conv.model,
        "reasoning_effort": conv.reasoning_effort,
        "reasoningEffort": conv.reasoning_effort,
        "messages": [
            {
                "id": m.id,
                "role": _chat_role(m.role),
                "content": m.content,
                "createdAt": m.created_at,
                "created_at": m.created_at,
                "provider": m.provider,
                "model": m.model,
                "attachments": m.attachments,
                "steps": m.steps,
            }
            for m in (conv.messages or [])
        ],
    }


@router.delete("/conversations/{conversation_id}", status_code=204)
async def delete_conversation(conversation_id: str, request: Request):
    user_id = get_user_id(request)
    if not await store.delete_conversation(user_id, conversation_id):
        raise HTTPException(status_code=404, detail="Conversation not found")
