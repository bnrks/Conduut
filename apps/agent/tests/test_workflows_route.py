import pytest
from fastapi import HTTPException

from src.agent.schemas import (
    ArtifactPreviewData,
    ArtifactPreviewTable,
    WorkflowBatchRowResultData,
    WorkflowBatchRunResultData,
    WorkflowRunResultData,
)
from src.routes import workflows as workflows_route


@pytest.mark.asyncio
async def test_run_workflow_persists_returned_artifacts(monkeypatch):
    monkeypatch.setattr(workflows_route, "get_user_id", lambda _request: "user_1")

    async def fake_get_workflow(workflow_id: str):
        assert workflow_id == "wf_1"
        return {"id": "wf_1", "name": "Runtime workflow", "nodes": []}

    async def fake_readiness(_workflow: dict, *, user_id: str):
        assert user_id == "user_1"
        return {"missing_credentials": []}

    artifact = ArtifactPreviewData(
        service="google_sheets",
        title="Google Sheets row added",
        url="https://sheet.test",
        source={"spreadsheetId": "sheet_1", "range": "Log!A1"},
        table=ArtifactPreviewTable(
            columns=["Email"],
            rows=[{"Email": "person@example.com"}],
        ),
    )

    async def fake_run_workflow_with_input(_workflow: dict, *, user_id: str, input_payload: dict):
        assert user_id == "user_1"
        assert input_payload == {"to": "person@example.com"}
        return WorkflowRunResultData(
            workflowId="wf_1",
            executionId="exec_1",
            status="success",
            summary="Workflow run completed.",
            artifacts=[artifact],
        )

    saved: list[dict] = []

    async def fake_save_artifact(user_id: str, artifact_payload: dict, *, origin: dict):
        saved.append({"user_id": user_id, "artifact": artifact_payload, "origin": origin})

    monkeypatch.setattr(workflows_route.n8n_client, "get_workflow", fake_get_workflow)
    monkeypatch.setattr(
        workflows_route,
        "analyze_workflow_readiness_payload",
        fake_readiness,
    )
    monkeypatch.setattr(workflows_route, "run_workflow_with_input", fake_run_workflow_with_input)
    monkeypatch.setattr(workflows_route.store, "save_artifact", fake_save_artifact)

    response = await workflows_route.run_workflow(
        "wf_1",
        object(),
        workflows_route.WorkflowRunRequest(input={"to": "person@example.com"}),
    )

    assert response["artifacts"][0]["title"] == "Google Sheets row added"
    assert saved == [
        {
            "user_id": "user_1",
            "artifact": {
                "service": "google_sheets",
                "title": "Google Sheets row added",
                "url": "https://sheet.test",
                "source": {"spreadsheetId": "sheet_1", "range": "Log!A1"},
                "table": {
                    "columns": ["Email"],
                    "rows": [{"Email": "person@example.com"}],
                    "truncated": False,
                },
            },
            "origin": {
                "kind": "workflow_run",
                "workflowId": "wf_1",
                "executionId": "exec_1",
            },
        }
    ]


@pytest.mark.asyncio
async def test_batch_run_workflow_persists_row_artifacts(monkeypatch):
    monkeypatch.setattr(workflows_route, "get_user_id", lambda _request: "user_1")

    async def fake_get_workflow(workflow_id: str):
        assert workflow_id == "wf_1"
        return {"id": "wf_1", "name": "Runtime workflow", "nodes": []}

    async def fake_readiness(_workflow: dict, *, user_id: str):
        assert user_id == "user_1"
        return {"missing_credentials": []}

    artifact = ArtifactPreviewData(
        service="gmail",
        title="Gmail message sent",
        source={"messageId": "msg_1"},
    )

    async def fake_run_batch(_workflow: dict, *, user_id: str, rows: list[dict]):
        assert user_id == "user_1"
        assert rows == [{"rowNumber": 2, "input": {"to": "person@example.com"}}]
        return WorkflowBatchRunResultData(
            workflowId="wf_1",
            batchRunId="batch_1",
            status="completed",
            totalRows=1,
            succeeded=1,
            failed=0,
            skipped=0,
            results=[
                WorkflowBatchRowResultData(
                    rowNumber=2,
                    status="success",
                    executionId="exec_1",
                    summary="Workflow run completed.",
                    artifacts=[artifact],
                )
            ],
        )

    saved: list[dict] = []

    async def fake_save_artifact(user_id: str, artifact_payload: dict, *, origin: dict):
        saved.append({"user_id": user_id, "artifact": artifact_payload, "origin": origin})

    monkeypatch.setattr(workflows_route.n8n_client, "get_workflow", fake_get_workflow)
    monkeypatch.setattr(
        workflows_route,
        "analyze_workflow_readiness_payload",
        fake_readiness,
    )
    monkeypatch.setattr(workflows_route, "run_workflow_batch_with_input", fake_run_batch)
    monkeypatch.setattr(workflows_route.store, "save_artifact", fake_save_artifact)

    response = await workflows_route.batch_run_workflow(
        "wf_1",
        object(),
        workflows_route.WorkflowBatchRunRequest(
            rows=[
                workflows_route.WorkflowBatchRunRowRequest(
                    rowNumber=2,
                    input={"to": "person@example.com"},
                )
            ]
        ),
    )

    assert response["success"] is True
    assert response["batchRunId"] == "batch_1"
    assert response["results"][0]["execution_id"] == "exec_1"
    assert saved == [
        {
            "user_id": "user_1",
            "artifact": {
                "service": "gmail",
                "title": "Gmail message sent",
                "source": {"messageId": "msg_1"},
            },
            "origin": {
                "kind": "workflow_batch_run",
                "workflowId": "wf_1",
                "batchRunId": "batch_1",
                "rowNumber": 2,
                "executionId": "exec_1",
            },
        }
    ]


@pytest.mark.asyncio
async def test_batch_run_workflow_stops_before_run_when_credentials_missing(monkeypatch):
    monkeypatch.setattr(workflows_route, "get_user_id", lambda _request: "user_1")

    async def fake_get_workflow(_workflow_id: str):
        return {"id": "wf_1", "name": "Runtime workflow", "nodes": []}

    async def fake_readiness(_workflow: dict, *, user_id: str):
        assert user_id == "user_1"
        return {"missing_credentials": [{"type": "oauth_prompt"}]}

    async def fail_run_batch(*_args, **_kwargs):
        raise AssertionError("batch run should not start with missing credentials")

    monkeypatch.setattr(workflows_route.n8n_client, "get_workflow", fake_get_workflow)
    monkeypatch.setattr(
        workflows_route,
        "analyze_workflow_readiness_payload",
        fake_readiness,
    )
    monkeypatch.setattr(workflows_route, "run_workflow_batch_with_input", fail_run_batch)

    with pytest.raises(HTTPException) as exc:
        await workflows_route.batch_run_workflow(
            "wf_1",
            object(),
            workflows_route.WorkflowBatchRunRequest(
                rows=[
                    workflows_route.WorkflowBatchRunRowRequest(
                        rowNumber=2,
                        input={"to": "person@example.com"},
                    )
                ]
            ),
        )

    assert exc.value.status_code == 409
