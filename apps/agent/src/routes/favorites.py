from fastapi import APIRouter, HTTPException, Request

from src.auth import get_user_id
from src import store

router = APIRouter()


@router.get("/settings/favorites")
async def get_favorites(request: Request):
    user_id = get_user_id(request)
    return {"favorites": await store.get_favorites(user_id)}


@router.post("/settings/favorites/{provider}/{model:path}", status_code=201)
async def add_favorite(provider: str, model: str, request: Request):
    user_id = get_user_id(request)
    favorites = await store.add_favorite(user_id, provider, model)
    return {"favorites": favorites}


@router.delete("/settings/favorites/{provider}/{model:path}")
async def remove_favorite(provider: str, model: str, request: Request):
    user_id = get_user_id(request)
    favorites = await store.remove_favorite(user_id, provider, model)
    return {"favorites": favorites}
