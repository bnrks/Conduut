import pytest

from src import store


class _FakeDoc:
    def __init__(self, doc_id: str, data: dict, exists: bool = True):
        self.id = doc_id
        self._data = data
        self.exists = exists

    def to_dict(self):
        return dict(self._data)


class _FakeMsgRef:
    def __init__(self, msgs: dict, msg_id: str):
        self._msgs = msgs
        self._id = msg_id

    def set(self, data: dict):
        self._msgs[self._id] = dict(data)


class _FakeMsgCollection:
    def __init__(self, msgs: dict):
        self._msgs = msgs

    def order_by(self, _field: str):
        return self

    def stream(self):
        return [_FakeDoc(mid, data) for mid, data in self._msgs.items()]


class _FakeConvRef:
    def __init__(self, msgs: dict, conv: dict):
        self._msgs = msgs
        self._conv = conv

    def get(self):
        return _FakeDoc("conv", self._conv, exists=True)

    def update(self, upd: dict):
        self._conv.update(upd)

    def collection(self, name: str):
        assert name == "messages"
        return _FakeMsgCollection(self._msgs)


@pytest.mark.asyncio
async def test_add_message_persists_and_reads_steps(monkeypatch):
    msgs: dict = {}
    conv: dict = {"message_count": 0, "title": "x"}

    async def fake_run(fn):
        return fn()

    monkeypatch.setattr(store, "_run", fake_run)
    monkeypatch.setattr(store, "_msg_ref", lambda u, c, mid: _FakeMsgRef(msgs, mid))
    monkeypatch.setattr(store, "_conv_ref", lambda u, c: _FakeConvRef(msgs, conv))

    steps = [
        {"kind": "text", "text": "a"},
        {"kind": "activity", "actions": ["create_workflow"]},
        {"kind": "text", "text": "b"},
    ]
    returned = await store.add_message("u", "c", "assistant", "ab", steps=steps)

    assert returned.steps == steps
    assert any(doc.get("steps") == steps for doc in msgs.values())

    loaded = await store.get_conversation_messages("u", "c")
    assert loaded[0].steps == steps


@pytest.mark.asyncio
async def test_add_message_without_steps_keeps_none(monkeypatch):
    msgs: dict = {}
    conv: dict = {"message_count": 0, "title": "x"}

    async def fake_run(fn):
        return fn()

    monkeypatch.setattr(store, "_run", fake_run)
    monkeypatch.setattr(store, "_msg_ref", lambda u, c, mid: _FakeMsgRef(msgs, mid))
    monkeypatch.setattr(store, "_conv_ref", lambda u, c: _FakeConvRef(msgs, conv))

    returned = await store.add_message("u", "c", "assistant", "hi")

    assert returned.steps is None
    assert all("steps" not in doc for doc in msgs.values())
