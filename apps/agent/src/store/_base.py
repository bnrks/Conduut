"""Shared base primitives for the store package."""

import asyncio
from datetime import datetime, timezone


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _now_iso() -> str:
    return _now().isoformat()


def _user_ref(user_id: str):
    # Read `db` from the package namespace (not a module-local import) so that
    # monkeypatch.setattr(store, "db", fake) reaches user-scoped collections too,
    # matching the pre-split monolith where _user_ref read the module-global store.db.
    import src.store as _pkg_store

    return _pkg_store.db.collection("users").document(user_id)


async def _run(fn):
    return await asyncio.to_thread(fn)
