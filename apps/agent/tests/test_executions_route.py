from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from src import executions, n8n_client
from src.routes import executions as executions_route


@pytest.fixture(autouse=True)
def _request_scoped_shared_n8n(monkeypatch):
    context = SimpleNamespace(
        target=SimpleNamespace(instance_id="shared_dev", ownership="shared_dev")
    )

    async def fake_request_n8n(_request, _user_id):
        return context, n8n_client

    monkeypatch.setattr(executions_route, "_request_n8n", fake_request_n8n)


@pytest.mark.asyncio
async def test_list_execution_route_passes_authenticated_user_and_filters(monkeypatch):
    monkeypatch.setattr(executions_route, "get_user_id", lambda _request: "user_1")
    captured = {}

    async def fake_list_runs(user_id: str, **kwargs):
        captured.update(user_id=user_id, **kwargs)
        return executions.RunPage(executions=[], next_cursor="next")

    monkeypatch.setattr(executions_route.executions, "list_runs", fake_list_runs)

    result = await executions_route.list_executions(
        object(),
        workflow_id="wf_1",
        status="error",
        cursor="opaque",
        limit=50,
    )

    assert captured.pop("n8n") is n8n_client
    assert captured == {
        "user_id": "user_1",
        "workflow_id": "wf_1",
        "status": "error",
        "cursor": "opaque",
        "limit": 50,
    }
    assert result.next_cursor == "next"


@pytest.mark.asyncio
async def test_execution_detail_route_returns_stable_contract(monkeypatch):
    monkeypatch.setattr(executions_route, "get_user_id", lambda _request: "user_1")

    async def fake_get_run(user_id: str, execution_id: str, **_kwargs):
        assert (user_id, execution_id) == ("user_1", "exec_1")
        return executions.RunDetail(
            id="exec_1",
            workflow_id="wf_1",
            workflow_name="Workflow",
            status="error",
            mode="webhook",
            started_at="2026-07-15T10:00:00Z",
            finished_at="2026-07-15T10:00:01Z",
            duration_ms=1000,
            summary="Workflow execution failed.",
            failed_node="HTTP Request",
            error="Bad request",
        )

    monkeypatch.setattr(executions_route.executions, "get_run", fake_get_run)

    result = await executions_route.get_execution("exec_1", object())

    assert result.workflow_id == "wf_1"
    assert result.error == "Bad request"


@pytest.mark.asyncio
async def test_execution_detail_route_returns_404_for_missing(monkeypatch):
    monkeypatch.setattr(executions_route, "get_user_id", lambda _request: "user_1")

    async def fake_get_run(_user_id: str, execution_id: str, **_kwargs):
        raise executions.ExecutionNotFoundError(execution_id)

    monkeypatch.setattr(executions_route.executions, "get_run", fake_get_run)

    with pytest.raises(HTTPException) as exc:
        await executions_route.get_execution("missing", object())

    assert exc.value.status_code == 404
    assert exc.value.detail == {"message": "Execution not found."}


@pytest.mark.asyncio
async def test_list_execution_route_preserves_n8n_error_status(monkeypatch):
    monkeypatch.setattr(executions_route, "get_user_id", lambda _request: "user_1")

    async def fake_list_runs(*_args, **_kwargs):
        raise n8n_client.N8nApiError(
            502,
            "n8n unavailable",
            method="GET",
            path="/executions",
        )

    monkeypatch.setattr(executions_route.executions, "list_runs", fake_list_runs)

    with pytest.raises(HTTPException) as exc:
        await executions_route.list_executions(
            object(), workflow_id=None, status=None, cursor=None, limit=25
        )

    assert exc.value.status_code == 502
    assert exc.value.detail == {"message": "n8n unavailable"}
