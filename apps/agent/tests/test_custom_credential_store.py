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


async def test_draft_credential_save_and_finalize(monkeypatch):
    storage: dict[str, dict] = {}

    async def fake_run(fn):
        return fn()

    monkeypatch.setattr(store, "_run", fake_run)
    monkeypatch.setattr(store, "_user_ref", lambda _u: _FakeUserRef(storage, "credentials"))
    monkeypatch.setattr(store, "_now_iso", lambda: "2026-06-21T00:00:00+00:00")

    draft = await store.save_draft_credential(
        "u1",
        label="API Ninjas",
        credential_type="httpHeaderAuth",
        host="api.api-ninjas.com",
        auth_config={"method": "api_key", "field_name": "X-Api-Key", "value_prefix": ""},
        secret_fields=["key"],
        source_url="https://api-ninjas.com",
        confidence="high",
        pending_workflow_id="wf1",
        pending_node_name="HTTP",
    )
    assert draft.status == "draft"
    assert draft.n8n_credential_id == ""

    got = await store.get_custom_credential("u1", draft.id)
    assert got.status == "draft"
    assert got.auth_config["field_name"] == "X-Api-Key"
    assert got.secret_fields == ["key"]
    assert got.pending_workflow_id == "wf1"

    final = await store.finalize_draft_credential(
        "u1", draft.id, n8n_credential_id="n8n_9", n8n_credential_name="API Ninjas"
    )
    assert final is not None
    assert final.status == "ready"
    assert final.n8n_credential_id == "n8n_9"

    refetched = await store.get_custom_credential("u1", draft.id)
    assert refetched.status == "ready"
    assert refetched.n8n_credential_id == "n8n_9"

    # finalizing again (now ready) or an unknown id returns None
    assert (
        await store.finalize_draft_credential(
            "u1", draft.id, n8n_credential_id="x", n8n_credential_name="y"
        )
        is None
    )
    assert (
        await store.finalize_draft_credential(
            "u1", "nope", n8n_credential_id="x", n8n_credential_name="y"
        )
        is None
    )


def test_custom_credential_match_kind_defaults_to_host():
    cred = store._custom_credential_from_data(
        "c1", {"label": "X", "credential_type": "httpHeaderAuth"}
    )
    assert cred.match_kind == "host"


def test_custom_credential_match_kind_type_roundtrip():
    cred = store._custom_credential_from_data(
        "c2", {"label": "OpenAI", "credential_type": "openAiApi", "match_kind": "type"}
    )
    assert cred.match_kind == "type"
    assert cred.credential_type == "openAiApi"
