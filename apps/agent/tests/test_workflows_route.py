import json

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


async def _stream_events(response):
    events = []
    async for chunk in response.body_iterator:
        raw = chunk.decode() if isinstance(chunk, bytes) else chunk
        for event_block in raw.strip().split("\n\n"):
            lines = event_block.splitlines()
            event = next(
                line.removeprefix("event: ").strip() for line in lines if line.startswith("event:")
            )
            data = next(
                line.removeprefix("data: ").strip() for line in lines if line.startswith("data:")
            )
            events.append((event, json.loads(data)))
    return events


@pytest.mark.asyncio
async def test_list_workflows_does_not_fetch_each_workflow(monkeypatch):
    """Listeleme N+1 yapmamalı: nodeCount n8n list cevabından gelmeli,
    her workflow için ayrı get_workflow çağrısı yapılmamalı (perf)."""
    monkeypatch.setattr(workflows_route, "get_user_id", lambda _request: "user_1")

    async def fake_list_workflows():
        return [
            workflows_route.n8n_client.N8nWorkflow(
                id="wf_1",
                name="Alpha",
                active=True,
                created_at="2026-01-01",
                updated_at="2026-01-02",
                node_count=3,
            ),
            workflows_route.n8n_client.N8nWorkflow(
                id="wf_2",
                name="Beta",
                active=False,
                created_at="2026-01-03",
                updated_at="2026-01-04",
                node_count=7,
            ),
        ]

    async def fail_get_workflow(_workflow_id: str):
        raise AssertionError("list_workflows must not fetch each workflow individually")

    async def fail_per_workflow_metadata(_user_id: str, _workflow_id: str):
        raise AssertionError("list must not fetch workflow metadata per-workflow")

    metadata_calls: list[str] = []

    async def fake_all_metadata(user_id: str):
        metadata_calls.append(user_id)
        return {}

    monkeypatch.setattr(workflows_route.n8n_client, "list_workflows", fake_list_workflows)
    monkeypatch.setattr(workflows_route.n8n_client, "get_workflow", fail_get_workflow)
    monkeypatch.setattr(workflows_route.store, "get_workflow_metadata", fail_per_workflow_metadata)
    monkeypatch.setattr(workflows_route.store, "get_all_workflow_metadata", fake_all_metadata)
    monkeypatch.setattr(workflows_route, "_workflow_input_schema_from_metadata", lambda _m: None)
    monkeypatch.setattr(workflows_route, "_input_schema_payload", lambda _s: None)

    response = await workflows_route.list_workflows(object())

    workflows = response["workflows"]
    assert [w["id"] for w in workflows] == ["wf_1", "wf_2"]
    assert [w["nodeCount"] for w in workflows] == [3, 7]
    assert [w["status"] for w in workflows] == ["active", "inactive"]
    # Metadata tek sorguda (batch) çekilmeli — workflow başına değil.
    assert metadata_calls == ["user_1"]


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
async def test_stream_batch_run_workflow_emits_progress_and_persists_artifacts(monkeypatch):
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

    async def fake_iter_batch(_workflow: dict, *, user_id: str, rows: list[dict]):
        assert user_id == "user_1"
        assert rows == [{"rowNumber": 2, "input": {"to": "person@example.com"}}]
        yield "started", {"workflowId": "wf_1", "batchRunId": "batch_1", "totalRows": 1}
        yield "row_started", {"rowNumber": 2, "index": 1, "totalRows": 1}
        row = WorkflowBatchRowResultData(
            rowNumber=2,
            status="success",
            executionId="exec_1",
            summary="Workflow run completed.",
            artifacts=[artifact],
        )
        yield "row_finished", row
        yield (
            "completed",
            WorkflowBatchRunResultData(
                workflowId="wf_1",
                batchRunId="batch_1",
                status="completed",
                totalRows=1,
                succeeded=1,
                failed=0,
                skipped=0,
                results=[row],
            ),
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
    monkeypatch.setattr(workflows_route, "iter_workflow_batch_with_input", fake_iter_batch)
    monkeypatch.setattr(workflows_route.store, "save_artifact", fake_save_artifact)

    response = await workflows_route.stream_batch_run_workflow(
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
    events = await _stream_events(response)

    assert [event for event, _payload in events] == [
        "started",
        "row_started",
        "row_finished",
        "completed",
    ]
    assert events[0][1] == {"workflowId": "wf_1", "batchRunId": "batch_1", "totalRows": 1}
    assert events[2][1]["execution_id"] == "exec_1"
    assert events[3][1]["succeeded"] == 1
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


@pytest.mark.asyncio
async def test_stream_batch_run_workflow_stops_before_stream_when_credentials_missing(monkeypatch):
    monkeypatch.setattr(workflows_route, "get_user_id", lambda _request: "user_1")

    async def fake_get_workflow(_workflow_id: str):
        return {"id": "wf_1", "name": "Runtime workflow", "nodes": []}

    async def fake_readiness(_workflow: dict, *, user_id: str):
        assert user_id == "user_1"
        return {"missing_credentials": [{"type": "oauth_prompt"}]}

    async def fail_iter_batch(*_args, **_kwargs):
        raise AssertionError("batch stream should not start with missing credentials")
        yield

    monkeypatch.setattr(workflows_route.n8n_client, "get_workflow", fake_get_workflow)
    monkeypatch.setattr(
        workflows_route,
        "analyze_workflow_readiness_payload",
        fake_readiness,
    )
    monkeypatch.setattr(workflows_route, "iter_workflow_batch_with_input", fail_iter_batch)

    with pytest.raises(HTTPException) as exc:
        await workflows_route.stream_batch_run_workflow(
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
