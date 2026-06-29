"""Shared base primitives for the store package."""

import asyncio
from datetime import datetime, timezone

from src.firebase import db


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _now_iso() -> str:
    return _now().isoformat()


def _user_ref(user_id: str):
    return db.collection("users").document(user_id)


async def _run(fn):
    return await asyncio.to_thread(fn)
