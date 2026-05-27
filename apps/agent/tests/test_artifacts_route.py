import pytest

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
