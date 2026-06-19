"""Tests for the per-user custom credential metadata store."""

from src import store


class _FakeDocSnapshot:
    def __init__(self, doc_id: str, data: dict):
        self.id = doc_id
        self._data = data
        self.exists = True

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
            snapshot = _FakeDocSnapshot(self._doc_id, {})
            snapshot.exists = False
            return snapshot
        return _FakeDocSnapshot(self._doc_id, self._storage[self._doc_id])

    def delete(self):
        self._storage.pop(self._doc_id, None)


class _FakeCollection:
    def __init__(self, storage: dict[str, dict]):
        self._storage = storage

    def document(self, doc_id: str):
        return _FakeDocRef(self._storage, doc_id)

    def stream(self):
        return [_FakeDocSnapshot(doc_id, data) for doc_id, data in self._storage.items()]


class _FakeUserRef:
    def __init__(self, storage: dict[str, dict], expected: str):
        self._storage = storage
        self._expected = expected

    def collection(self, name: str):
        assert name == self._expected
        return _FakeCollection(self._storage)


async def test_custom_credential_crud(monkeypatch):
    storage: dict[str, dict] = {}

    async def fake_run(fn):
        return fn()

    monkeypatch.setattr(store, "_run", fake_run)
    monkeypatch.setattr(store, "_user_ref", lambda _u: _FakeUserRef(storage, "credentials"))
    monkeypatch.setattr(store, "_now_iso", lambda: "2026-06-19T00:00:00+00:00")

    saved = await store.save_custom_credential(
        "u1",
        label="Stripe API",
        credential_type="httpHeaderAuth",
        host="api.stripe.com",
        n8n_credential_id="n8n_1",
        n8n_credential_name="Stripe API - Conduut",
    )
    assert saved.id
    assert saved.created_at == "2026-06-19T00:00:00+00:00"

    got = await store.get_custom_credential("u1", saved.id)
    assert got is not None
    assert got.host == "api.stripe.com"
    assert got.credential_type == "httpHeaderAuth"
    assert got.n8n_credential_id == "n8n_1"

    listed = await store.list_custom_credentials("u1")
    assert [c.id for c in listed] == [saved.id]

    await store.delete_custom_credential("u1", saved.id)
    assert await store.get_custom_credential("u1", saved.id) is None


async def test_get_custom_credential_missing_returns_none(monkeypatch):
    storage: dict[str, dict] = {}

    async def fake_run(fn):
        return fn()

    monkeypatch.setattr(store, "_run", fake_run)
    monkeypatch.setattr(store, "_user_ref", lambda _u: _FakeUserRef(storage, "credentials"))

    assert await store.get_custom_credential("u1", "nope") is None
