"""Tests for the shared (global) API auth research cache store."""

from src import store


class _FakeDocSnapshot:
    def __init__(self, doc_id: str, data: dict, exists: bool = True):
        self.id = doc_id
        self._data = data
        self.exists = exists

    def to_dict(self):
        return dict(self._data)


class _FakeDocRef:
    def __init__(self, storage: dict[str, dict], doc_id: str):
        self._storage = storage
        self._doc_id = doc_id

    def set(self, data: dict):
        self._storage[self._doc_id] = dict(data)

    def get(self):
        if self._doc_id not in self._storage:
            return _FakeDocSnapshot(self._doc_id, {}, exists=False)
        return _FakeDocSnapshot(self._doc_id, self._storage[self._doc_id])

    def delete(self):
        self._storage.pop(self._doc_id, None)


class _FakeDb:
    def __init__(self, storage: dict[str, dict], expected: str):
        self._storage = storage
        self._expected = expected

    def collection(self, name: str):
        assert name == self._expected
        return _FakeCollection(self._storage)


class _FakeCollection:
    def __init__(self, storage: dict[str, dict]):
        self._storage = storage

    def document(self, doc_id: str):
        return _FakeDocRef(self._storage, doc_id)


async def test_api_auth_cache_roundtrip(monkeypatch):
    storage: dict[str, dict] = {}

    async def fake_run(fn):
        return fn()

    monkeypatch.setattr(store, "_run", fake_run)
    monkeypatch.setattr(store, "db", _FakeDb(storage, "api_auth_cache"))
    monkeypatch.setattr(store, "_now_iso", lambda: "2026-06-21T00:00:00+00:00")

    saved = await store.save_api_auth_cache(
        "api.stripe.com",
        scheme="header",
        credential_type="httpHeaderAuth",
        field_name="Authorization",
        value_prefix="Bearer ",
        secret_fields=["key"],
        summary="Stripe uses a Bearer token.",
        source_url="https://stripe.com/docs",
        confidence="high",
        model="gemini-2.5-flash",
    )
    assert saved.host == "api.stripe.com"
    assert saved.researched_at == "2026-06-21T00:00:00+00:00"

    got = await store.get_api_auth_cache("api.stripe.com")
    assert got is not None
    assert got.field_name == "Authorization"
    assert got.value_prefix == "Bearer "
    assert got.secret_fields == ["key"]
    assert got.confidence == "high"

    assert await store.get_api_auth_cache("api.unknown.com") is None

    await store.delete_api_auth_cache("api.stripe.com")
    assert await store.get_api_auth_cache("api.stripe.com") is None
