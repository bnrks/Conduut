"""Instance-scoped Google connection metadata tests."""

from src import store


class _Snapshot:
    def __init__(self, doc_id: str, data: dict | None):
        self.id = doc_id
        self._data = data or {}
        self.exists = data is not None

    def to_dict(self):
        return dict(self._data)


class _Doc:
    def __init__(self, storage: dict[str, dict], doc_id: str):
        self.storage = storage
        self.doc_id = doc_id

    def get(self):
        return _Snapshot(self.doc_id, self.storage.get(self.doc_id))

    def set(self, data: dict):
        self.storage[self.doc_id] = dict(data)

    def delete(self):
        self.storage.pop(self.doc_id, None)


class _Collection:
    def __init__(self, storage: dict[str, dict]):
        self.storage = storage

    def document(self, doc_id: str):
        return _Doc(self.storage, doc_id)

    def stream(self):
        return [_Snapshot(key, value) for key, value in self.storage.items()]


class _User:
    def __init__(self, storage: dict[str, dict]):
        self.storage = storage

    def collection(self, name: str):
        assert name == "connections"
        return _Collection(self.storage)


async def test_google_connection_metadata_coexists_per_instance(monkeypatch):
    storage: dict[str, dict] = {}

    async def fake_run(fn):
        return fn()

    monkeypatch.setattr(store, "_run", fake_run)
    monkeypatch.setattr(store, "_user_ref", lambda _user_id: _User(storage))
    monkeypatch.setattr(store, "_now_iso", lambda: "2026-08-03T00:00:00+00:00")

    common = {
        "provider": "google",
        "service": "gmail",
        "account_email": "user@example.com",
        "google_sub": "sub",
        "credential_type": "gmailOAuth2",
        "n8n_credential_name": "Gmail",
        "scopes": ["gmail.send"],
    }
    await store.save_connection(
        "u1",
        "google_gmail",
        n8n_credential_id="legacy_credential",
        instance_id="shared_dev",
        **common,
    )
    await store.save_connection(
        "u1",
        "google_gmail",
        n8n_credential_id="target_credential",
        instance_id="inst_1",
        **common,
    )

    assert set(storage) == {"google_gmail", "inst_1--google_gmail"}
    legacy = await store.get_connection("u1", "google_gmail", instance_id="shared_dev")
    target = await store.get_connection("u1", "google_gmail", instance_id="inst_1")
    assert legacy is not None and legacy.n8n_credential_id == "legacy_credential"
    assert target is not None and target.n8n_credential_id == "target_credential"
