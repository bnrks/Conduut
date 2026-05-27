import pytest

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


class _FakeQuery:
    def __init__(self, storage: dict[str, dict]):
        self._storage = storage
        self._limit = 50

    def order_by(self, *_args, **_kwargs):
        return self

    def limit(self, limit: int):
        self._limit = limit
        return self

    def stream(self):
        items = sorted(
            self._storage.items(),
            key=lambda item: item[1].get("created_at", ""),
            reverse=True,
        )
        return [_FakeDocSnapshot(doc_id, data) for doc_id, data in items[: self._limit]]


class _FakeCollection(_FakeQuery):
    def document(self, doc_id: str):
        return _FakeDocRef(self._storage, doc_id)


class _FakeUserRef:
    def __init__(self, storage: dict[str, dict]):
        self._storage = storage

    def collection(self, name: str):
        assert name == "artifacts"
        return _FakeCollection(self._storage)


@pytest.mark.asyncio
async def test_save_and_list_artifacts_persists_preview_shape_and_sorts(monkeypatch):
    storage: dict[str, dict] = {}
    times = iter(["2026-05-27T10:00:00+00:00", "2026-05-27T11:00:00+00:00"])

    async def fake_run(fn):
        return fn()

    monkeypatch.setattr(store, "_run", fake_run)
    monkeypatch.setattr(store, "_user_ref", lambda _user_id: _FakeUserRef(storage))
    monkeypatch.setattr(store, "_now_iso", lambda: next(times))

    first = await store.save_artifact(
        "user_1",
        {
            "service": "google_sheets",
            "title": "Google Sheets row added",
            "url": "https://sheet.test",
            "source": {"spreadsheetId": "sheet_1", "range": "Log!A1"},
            "table": {"columns": ["Email"], "rows": [{"Email": "person@example.com"}]},
        },
        origin={"kind": "chat", "conversationId": "conv_1"},
    )
    second = await store.save_artifact(
        "user_1",
        {
            "service": "google_sheets",
            "title": "Google Sheets range updated",
            "url": "https://sheet.test",
            "source": {"spreadsheetId": "sheet_1", "range": "Log!A2"},
        },
        origin={"kind": "workflow_run", "workflow_id": "wf_1", "execution_id": "exec_1"},
    )

    assert first.id.startswith("art_")
    assert second.type == "table_preview"
    assert storage[first.id]["origin"] == {"kind": "chat", "conversationId": "conv_1"}
    assert storage[second.id]["origin"] == {
        "kind": "workflow_run",
        "workflowId": "wf_1",
        "executionId": "exec_1",
    }

    artifacts = await store.list_artifacts("user_1")

    assert [artifact.id for artifact in artifacts] == [second.id, first.id]
    assert artifacts[0].created_at == "2026-05-27T11:00:00+00:00"


@pytest.mark.asyncio
async def test_save_artifact_persists_gmail_message_preview(monkeypatch):
    storage: dict[str, dict] = {}

    async def fake_run(fn):
        return fn()

    monkeypatch.setattr(store, "_run", fake_run)
    monkeypatch.setattr(store, "_user_ref", lambda _user_id: _FakeUserRef(storage))
    monkeypatch.setattr(store, "_now_iso", lambda: "2026-05-27T12:00:00+00:00")

    saved = await store.save_artifact(
        "user_1",
        {
            "service": "gmail",
            "title": "Gmail message sent",
            "url": "https://mail.google.com/mail/u/0/#all/msg_123",
            "source": {"action": "gmail.message.send", "messageId": "msg_123"},
            "message": {
                "messageId": "msg_123",
                "to": ["person@example.com"],
                "subject": "Hello",
                "bodyPreview": "Mail body",
            },
        },
        origin={"kind": "chat", "conversationId": "conv_1"},
    )

    assert saved.type == "message_preview"
    assert storage[saved.id]["message"]["subject"] == "Hello"

    artifacts = await store.list_artifacts("user_1", service="gmail")

    assert len(artifacts) == 1
    assert artifacts[0].message == {
        "messageId": "msg_123",
        "to": ["person@example.com"],
        "subject": "Hello",
        "bodyPreview": "Mail body",
    }


def test_artifact_document_id_is_stable_for_same_identity():
    artifact = {
        "service": "google_sheets",
        "title": "Google Sheets row added",
        "url": "https://sheet.test",
        "source": {"spreadsheetId": "sheet_1", "range": "Log!A1"},
    }
    origin = {"kind": "chat", "conversationId": "conv_1"}

    assert store._artifact_document_id(artifact, origin) == store._artifact_document_id(
        dict(artifact),
        dict(origin),
    )


@pytest.mark.asyncio
async def test_delete_artifact_removes_existing_document(monkeypatch):
    storage: dict[str, dict] = {"art_1": {"service": "gmail", "title": "Gmail message"}}

    async def fake_run(fn):
        return fn()

    monkeypatch.setattr(store, "_run", fake_run)
    monkeypatch.setattr(store, "_user_ref", lambda _user_id: _FakeUserRef(storage))

    assert await store.delete_artifact("user_1", "art_1") is True
    assert "art_1" not in storage
    assert await store.delete_artifact("user_1", "missing") is False
