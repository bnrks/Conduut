import pytest
from fastapi import HTTPException

from src import store
from src.routes import artifacts as artifacts_route


@pytest.mark.asyncio
async def test_list_artifacts_returns_camel_case_payload(monkeypatch):
    monkeypatch.setattr(artifacts_route, "get_user_id", lambda _request: "user_1")

    async def fake_list_artifacts(user_id: str, *, limit: int, service: str | None):
        assert user_id == "user_1"
        assert limit == 25
        assert service == "google_sheets"
        return [
            store.ArtifactRecord(
                id="art_1",
                service="google_sheets",
                type="table_preview",
                title="Google Sheets row added",
                description="1 row",
                url="https://sheet.test",
                source={"spreadsheetId": "sheet_1"},
                table={"columns": ["Email"], "rows": [{"Email": "person@example.com"}]},
                origin={"kind": "workflow_run", "workflowId": "wf_1", "executionId": "exec_1"},
                created_at="2026-05-27T11:00:00+00:00",
            )
        ]

    monkeypatch.setattr(artifacts_route.store, "list_artifacts", fake_list_artifacts)

    response = await artifacts_route.list_artifacts(
        object(),
        limit=25,
        service="google_sheets",
    )

    payload = response.model_dump(exclude_none=True)
    assert payload["artifacts"][0]["createdAt"] == "2026-05-27T11:00:00+00:00"
    assert payload["artifacts"][0]["origin"] == {
        "kind": "workflow_run",
        "workflowId": "wf_1",
        "executionId": "exec_1",
    }


@pytest.mark.asyncio
async def test_delete_artifact_uses_current_user(monkeypatch):
    monkeypatch.setattr(artifacts_route, "get_user_id", lambda _request: "user_1")
    calls = []

    async def fake_delete_artifact(user_id: str, artifact_id: str):
        calls.append((user_id, artifact_id))
        return True

    monkeypatch.setattr(artifacts_route.store, "delete_artifact", fake_delete_artifact)

    assert await artifacts_route.delete_artifact("art_1", object()) is None
    assert calls == [("user_1", "art_1")]


@pytest.mark.asyncio
async def test_delete_artifact_returns_404_for_missing_artifact(monkeypatch):
    monkeypatch.setattr(artifacts_route, "get_user_id", lambda _request: "user_1")

    async def fake_delete_artifact(_user_id: str, _artifact_id: str):
        return False

    monkeypatch.setattr(artifacts_route.store, "delete_artifact", fake_delete_artifact)

    with pytest.raises(HTTPException) as exc:
        await artifacts_route.delete_artifact("missing", object())

    assert exc.value.status_code == 404
    assert exc.value.detail == {"message": "Artifact not found."}
