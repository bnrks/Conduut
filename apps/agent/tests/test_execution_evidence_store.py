import pytest

import src.store as store
from src.agent.schemas import ExecutionEvidenceEnvelope, WorkflowRunAssessment


@pytest.mark.asyncio
async def test_save_execution_evidence_is_append_only_and_sanitized(monkeypatch):
    writes: list[tuple[str, dict]] = []
    documents: dict[str, dict] = {}

    class FakeSnapshot:
        def __init__(self, data: dict | None):
            self._data = data
            self.exists = data is not None

        def to_dict(self):
            return self._data

    class FakeDoc:
        def __init__(self, doc_id: str):
            self.doc_id = doc_id

        def get(self):
            return FakeSnapshot(documents.get(self.doc_id))

        def create(self, data: dict):
            assert self.doc_id not in documents
            documents[self.doc_id] = data
            writes.append((self.doc_id, data))

    class FakeCollection:
        def document(self, doc_id: str):
            return FakeDoc(doc_id)

    class FakeUserRef:
        def collection(self, name: str):
            assert name == "execution_evidence"
            return FakeCollection()

    async def fake_run(fn):
        return fn()

    monkeypatch.setattr(store, "_user_ref", lambda _user_id: FakeUserRef())
    monkeypatch.setattr(store, "_run", fake_run)
    monkeypatch.setattr(store, "_now_iso", lambda: "2026-07-23T10:00:00+00:00")

    envelope = ExecutionEvidenceEnvelope(
        source="execution_inspect",
        workflowId="wf_1",
        executionId="exec_1",
        workflowFingerprint="fp-1",
        functionalStatus="partial",
        claimableOutcome="none",
        assessment=WorkflowRunAssessment(reasons=["2 action, 0 write-back"]),
    )

    saved_one = await store.save_execution_evidence("u1", envelope)
    saved_two = await store.save_execution_evidence("u1", envelope)

    assert saved_one.createdAt == "2026-07-23T10:00:00+00:00"
    assert saved_two.createdAt == "2026-07-23T10:00:00+00:00"
    assert len(writes) == 1
    assert saved_one.evidenceHash == saved_two.evidenceHash
    assert writes[0][0] == f"exec_1--{saved_one.evidenceHash}"
    assert writes[0][1]["source"] == "execution_inspect"
    assert writes[0][1]["functionalStatus"] == "partial"
    assert "outputs" not in writes[0][1]
    assert "response" not in writes[0][1]
