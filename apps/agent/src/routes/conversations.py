from fastapi import APIRouter, HTTPException, Request

from src.auth import get_user_id
from src import store

router = APIRouter()


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
        "message_count": conv.message_count,
        "created_at": conv.created_at,
        "updated_at": conv.updated_at,
        "messages": [
            {
                "id": m.id,
                "role": m.role,
                "content": m.content,
                "created_at": m.created_at,
                "provider": m.provider,
                "model": m.model,
            }
            for m in (conv.messages or [])
        ],
    }


@router.delete("/conversations/{conversation_id}", status_code=204)
async def delete_conversation(conversation_id: str, request: Request):
    user_id = get_user_id(request)
    if not await store.delete_conversation(user_id, conversation_id):
        raise HTTPException(status_code=404, detail="Conversation not found")
