from src import store


class _FakeDocSnapshot:
    def __init__(self, doc_id: str, data: dict, *, exists: bool = True):
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


class _FakeCollection:
    def __init__(self, storage: dict[str, dict]):
        self._storage = storage

    def document(self, doc_id: str):
        return _FakeDocRef(self._storage, doc_id)

    def stream(self):
        return [_FakeDocSnapshot(doc_id, data) for doc_id, data in self._storage.items()]


class _FakeUserRef:
    def __init__(self, storage: dict[str, dict], user_data: dict):
        self._storage = storage
        self._user_data = user_data

    def set(self, data: dict, *, merge: bool = False):
        if not merge:
            self._user_data.clear()
        self._user_data.update(data)

    def get(self):
        return _FakeDocSnapshot("u1", self._user_data, exists=bool(self._user_data))

    def collection(self, name: str):
        assert name == "n8n_instances"
        return _FakeCollection(self._storage)


async def test_n8n_instance_crud_and_active_switch(monkeypatch):
    storage: dict[str, dict] = {}
    user_data: dict = {}

    async def fake_run(fn):
        return fn()

    monkeypatch.setattr(store, "_run", fake_run)
    monkeypatch.setattr(store, "_user_ref", lambda _u: _FakeUserRef(storage, user_data))
    monkeypatch.setattr(store, "_now_iso", lambda: "2026-08-03T10:00:00+00:00")

    first = await store.save_n8n_instance(
        "u1",
        instance_id="inst_1",
        display_name="Primary",
        ownership="customer_owned",
        provider="manual",
        base_url="https://one.example.com",
        webhook_base_url="https://one.example.com",
        api_key_secret_ref="secret-1",
        n8n_version="1.121.3",
        compatibility_status="supported",
        connection_status="connected",
        is_active=True,
    )
    second = await store.save_n8n_instance(
        "u1",
        instance_id="inst_2",
        display_name="Secondary",
        ownership="customer_owned",
        provider="manual",
        base_url="https://two.example.com",
        webhook_base_url="https://two.example.com",
        api_key_secret_ref="secret-2",
        n8n_version="1.121.3",
        compatibility_status="supported",
        connection_status="connected",
        is_active=True,
    )

    assert first.is_active is True
    assert second.is_active is True
    active = await store.get_active_n8n_instance("u1")
    assert active is not None
    assert active.id == "inst_2"
    assert user_data["active_n8n_instance_id"] == "inst_2"
    assert storage["inst_1"]["is_active"] is False

    await store.delete_n8n_instance("u1", "inst_2")
    assert await store.get_n8n_instance("u1", "inst_2") is None
