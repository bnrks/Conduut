from src import store
from src.store.n8n_migrations import (
    N8nMigrationExecutionSummary,
    N8nMigrationItem,
    N8nMigrationRecord,
)


class _FakeSnapshot:
    def __init__(self, doc_id: str, data: dict, *, exists: bool = True):
        self.id = doc_id
        self._data = data
        self.exists = exists

    def to_dict(self):
        return dict(self._data)


class _FakeDocRef:
    def __init__(self, node: dict, doc_id: str):
        self._node = node
        self._doc_id = doc_id

    def _entry(self) -> dict:
        return self._node.setdefault(
            self._doc_id,
            {"data": {}, "subcollections": {}},
        )

    def set(self, data: dict):
        entry = self._entry()
        entry["data"] = dict(data)

    def get(self):
        entry = self._node.get(self._doc_id)
        if entry is None:
            return _FakeSnapshot(self._doc_id, {}, exists=False)
        return _FakeSnapshot(self._doc_id, entry["data"], exists=True)

    def delete(self):
        self._node.pop(self._doc_id, None)

    def collection(self, name: str):
        entry = self._entry()
        subcollections = entry["subcollections"].setdefault(name, {})
        return _FakeCollection(subcollections)


class _FakeCollection:
    def __init__(self, node: dict):
        self._node = node

    def document(self, doc_id: str):
        return _FakeDocRef(self._node, doc_id)

    def stream(self):
        return [
            _FakeSnapshot(doc_id, entry["data"], exists=True)
            for doc_id, entry in self._node.items()
        ]


class _FakeUserRef:
    def __init__(self, root: dict):
        self._root = root

    def collection(self, name: str):
        return _FakeCollection(self._root.setdefault(name, {}))


async def test_n8n_migration_store_roundtrip(monkeypatch):
    root: dict = {}

    async def fake_run(fn):
        return fn()

    monkeypatch.setattr(store, "_run", fake_run)
    monkeypatch.setattr(store, "_user_ref", lambda _u: _FakeUserRef(root))
    monkeypatch.setattr(store, "_now_iso", lambda: "2026-08-03T10:00:00+00:00")

    saved = await store.save_n8n_migration(
        N8nMigrationRecord(
            id="shared_to_inst_1",
            user_id="u1",
            source_instance_id="shared_dev",
            target_instance_id="inst_1",
            status="pending",
            created_at="",
            updated_at="",
            confirmed_at="2026-08-03T10:00:00+00:00",
            workflow_id_map={"wf1": "wf_new"},
            archived_execution_count=1,
            items=[
                N8nMigrationItem(
                    item_id="workflow:wf1",
                    kind="workflow",
                    legacy_id="wf1",
                    display_name="wf1",
                    status="customer_owned",
                    target_id="wf_new",
                )
            ],
        )
    )

    fetched = await store.get_n8n_migration("u1", "shared_to_inst_1")

    assert saved.updated_at == "2026-08-03T10:00:00+00:00"
    assert fetched is not None
    assert fetched.workflow_id_map == {"wf1": "wf_new"}
    assert fetched.items[0].target_id == "wf_new"


async def test_n8n_migration_execution_archives_are_idempotent(monkeypatch):
    root: dict = {}

    async def fake_run(fn):
        return fn()

    monkeypatch.setattr(store, "_run", fake_run)
    monkeypatch.setattr(store, "_user_ref", lambda _u: _FakeUserRef(root))

    summary = N8nMigrationExecutionSummary(
        summary_id="wf1:ex1",
        workflow_legacy_id="wf1",
        execution_id="ex1",
        status="success",
        started_at="2026-08-03T09:00:00+00:00",
        finished_at="2026-08-03T09:00:02+00:00",
        duration_ms=2000,
        mode="manual",
        error_message="",
    )
    await store.upsert_n8n_migration_execution_summaries("u1", "shared_to_inst_1", [summary])
    await store.upsert_n8n_migration_execution_summaries("u1", "shared_to_inst_1", [summary])

    archived = await store.list_n8n_migration_execution_summaries("u1", "shared_to_inst_1")

    assert len(archived) == 1
    assert archived[0].execution_id == "ex1"
