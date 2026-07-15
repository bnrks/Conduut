import pytest
from google.api_core.exceptions import Conflict

from src import store


class _Snapshot:
    def __init__(self, doc_id: str, data: dict):
        self.id = doc_id
        self._data = dict(data)
        self.exists = True

    def to_dict(self):
        return dict(self._data)


class _DocRef:
    def __init__(self, storage: dict[str, dict], doc_id: str):
        self._storage = storage
        self._doc_id = doc_id

    def create(self, data: dict):
        if self._doc_id in self._storage:
            raise Conflict("usage event already exists")
        self._storage[self._doc_id] = dict(data)

    def get(self):
        return _Snapshot(self._doc_id, self._storage[self._doc_id])


class _Query:
    def __init__(self, storage: dict[str, dict]):
        self._storage = storage
        self._start_at = ""

    def where(self, *, filter):
        self._start_at = str(filter.value)
        return self

    def order_by(self, *_args, **_kwargs):
        return self

    def stream(self):
        items = [
            (doc_id, data)
            for doc_id, data in self._storage.items()
            if str(data.get("created_at") or "") >= self._start_at
        ]
        items.sort(key=lambda item: item[1]["created_at"])
        return [_Snapshot(doc_id, data) for doc_id, data in items]


class _Collection(_Query):
    def document(self, doc_id: str):
        return _DocRef(self._storage, doc_id)


class _UserRef:
    def __init__(self, storage: dict[str, dict]):
        self._storage = storage

    def collection(self, name: str):
        assert name == "usage_events"
        return _Collection(self._storage)


@pytest.mark.asyncio
async def test_usage_events_are_idempotent_and_queryable(monkeypatch):
    storage: dict[str, dict] = {}

    async def fake_run(fn):
        return fn()

    monkeypatch.setattr(store, "_run", fake_run)
    monkeypatch.setattr(store, "_user_ref", lambda _user_id: _UserRef(storage))
    monkeypatch.setattr(store, "_now_iso", lambda: "2026-07-15T12:00:00+00:00")

    saved = await store.save_agent_usage_event(
        "user_1",
        run_id="run_1",
        conversation_id="conv_1",
        provider="deepseek",
        model="deepseek-v4-pro",
        tier="medium",
        input_tokens=1200,
        output_tokens=300,
        cache_read_tokens=800,
        model_requests=2,
        tool_calls=5,
    )
    duplicate = await store.save_agent_usage_event(
        "user_1",
        run_id="run_1",
        conversation_id="changed",
        provider="changed",
        model="changed",
        tier="hard",
        input_tokens=9999,
        output_tokens=9999,
    )

    assert len(storage) == 1
    assert duplicate == saved
    assert saved.total_tokens == 1500
    assert saved.cache_read_tokens == 800

    events = await store.list_agent_usage_events("user_1", start_at="2026-07-15T00:00:00+00:00")
    assert events == [saved]


@pytest.mark.asyncio
async def test_usage_event_normalizes_negative_counts(monkeypatch):
    storage: dict[str, dict] = {}

    async def fake_run(fn):
        return fn()

    monkeypatch.setattr(store, "_run", fake_run)
    monkeypatch.setattr(store, "_user_ref", lambda _user_id: _UserRef(storage))
    monkeypatch.setattr(store, "_now_iso", lambda: "2026-07-15T12:00:00+00:00")

    saved = await store.save_agent_usage_event(
        "user_1",
        run_id="run_negative",
        conversation_id="conv_1",
        provider="openai",
        model="gpt-5-mini",
        tier="simple",
        input_tokens=-1,
        output_tokens=-5,
        cache_write_tokens=-9,
    )

    assert saved.input_tokens == 0
    assert saved.output_tokens == 0
    assert saved.cache_write_tokens == 0
