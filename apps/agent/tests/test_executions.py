import pytest

from src import executions, n8n_client


@pytest.mark.asyncio
async def test_list_runs_returns_stable_page_with_names_and_duration(monkeypatch):
    async def fake_page(**kwargs):
        assert kwargs == {
            "workflow_id": "wf_1",
            "status": "success",
            "cursor": "cursor_1",
            "limit": 20,
        }
        return n8n_client.N8nExecutionPage(
            executions=[
                n8n_client.N8nExecution(
                    id="exec_1",
                    workflow_id="wf_1",
                    status="success",
                    mode="webhook",
                    started_at="2026-07-15T10:00:00.000Z",
                    finished_at="2026-07-15T10:00:01.250Z",
                )
            ],
            next_cursor="cursor_2",
        )

    async def fake_workflows():
        return [
            n8n_client.N8nWorkflow(
                id="wf_1",
                name="Daily report",
                active=True,
                created_at="",
                updated_at="",
            )
        ]

    monkeypatch.setattr(executions.n8n_client, "list_executions_page", fake_page)
    monkeypatch.setattr(executions.n8n_client, "list_workflows", fake_workflows)

    result = await executions.list_runs(
        "user_1",
        workflow_id="wf_1",
        status="success",
        cursor="cursor_1",
        limit=20,
    )

    assert result.next_cursor == "cursor_2"
    assert result.executions[0].model_dump() == {
        "id": "exec_1",
        "workflow_id": "wf_1",
        "workflow_name": "Daily report",
        "status": "success",
        "mode": "webhook",
        "started_at": "2026-07-15T10:00:00.000Z",
        "finished_at": "2026-07-15T10:00:01.250Z",
        "duration_ms": 1250,
    }


@pytest.mark.asyncio
async def test_get_run_redacts_error_and_never_exposes_raw_data(monkeypatch):
    async def fake_detail(execution_id: str):
        assert execution_id == "exec_9"
        return {
            "id": "exec_9",
            "workflowId": "wf_9",
            "workflowData": {"name": "Broken API call", "credentials": {"token": "raw"}},
            "status": "error",
            "mode": "trigger",
            "startedAt": "2026-07-15T10:00:00Z",
            "stoppedAt": "2026-07-15T10:00:02Z",
            "data": {
                "resultData": {
                    "error": {
                        "message": "Request failed with Bearer live-token",
                        "description": "token=abc123 was rejected",
                        "node": {"name": "HTTP Request"},
                    },
                    "runData": {"HTTP Request": [{"data": {"main": [[{"json": {"x": 1}}]]}}]},
                }
            },
        }

    monkeypatch.setattr(executions.n8n_client, "get_execution_detail", fake_detail)

    result = await executions.get_run("user_1", "exec_9")
    payload = result.model_dump()

    assert payload["workflow_name"] == "Broken API call"
    assert payload["failed_node"] == "HTTP Request"
    assert payload["duration_ms"] == 2000
    assert payload["error"] == (
        "Request failed with Bearer [REDACTED] — token=[REDACTED] was rejected"
    )
    assert "data" not in payload
    assert "outputs" not in payload
    assert "credentials" not in payload


@pytest.mark.asyncio
async def test_get_run_redacts_headers_auth_schemes_and_query_secrets(monkeypatch):
    async def fake_detail(_execution_id: str):
        return {
            "id": "exec_secret",
            "workflowId": "wf_secret",
            "workflowData": {"name": "Secret-safe workflow"},
            "status": "error",
            "startedAt": "2026-07-15T10:00:00Z",
            "stoppedAt": "2026-07-15T10:00:01Z",
            "data": {
                "resultData": {
                    "error": {
                        "message": (
                            "Authorization: Basic dXNlcjpwYXNz, "
                            "X-API-Key: live-key; "
                            "Cookie: sid=cookie-secret; csrf=second-cookie-secret"
                        ),
                        "description": ("https://api.test/items?access_token=url-secret&safe=yes"),
                    }
                }
            },
        }

    monkeypatch.setattr(executions.n8n_client, "get_execution_detail", fake_detail)

    result = await executions.get_run("user_1", "exec_secret")

    assert "dXNlcjpwYXNz" not in (result.error or "")
    assert "live-key" not in (result.error or "")
    assert "cookie-secret" not in (result.error or "")
    assert "second-cookie-secret" not in (result.error or "")
    assert "url-secret" not in (result.error or "")
    assert (result.error or "").count("[REDACTED]") == 4


@pytest.mark.asyncio
async def test_inspect_run_preserves_agent_only_output_preview(monkeypatch):
    async def fake_detail(_execution_id: str):
        return {
            "id": "exec_agent",
            "workflowId": "wf_1",
            "status": "success",
            "startedAt": "2026-07-15T10:00:00Z",
            "stoppedAt": "2026-07-15T10:00:01Z",
            "data": {
                "resultData": {
                    "runData": {
                        "Transform": [
                            {"data": {"main": [[{"json": {"result": "agent evidence"}}]]}}
                        ]
                    }
                }
            },
        }

    monkeypatch.setattr(executions.n8n_client, "get_execution_detail", fake_detail)

    result = await executions.inspect_run("user_1", "exec_agent")

    assert result.status == "success"
    assert result.outputs[0]["nodeName"] == "Transform"
    assert result.outputs[0]["items"][0]["result"] == "agent evidence"


@pytest.mark.asyncio
async def test_list_and_detail_normalize_crashed_to_error(monkeypatch):
    async def fake_page(**_kwargs):
        return n8n_client.N8nExecutionPage(
            executions=[
                n8n_client.N8nExecution(
                    id="exec_crashed",
                    workflow_id="wf_1",
                    status="crashed",
                    started_at="2026-07-15T10:00:00Z",
                )
            ]
        )

    async def fake_workflows():
        return []

    async def fake_detail(_execution_id: str):
        return {
            "id": "exec_crashed",
            "workflowId": "wf_1",
            "status": "crashed",
            "startedAt": "2026-07-15T10:00:00Z",
            "data": {"resultData": {}},
        }

    monkeypatch.setattr(executions.n8n_client, "list_executions_page", fake_page)
    monkeypatch.setattr(executions.n8n_client, "list_workflows", fake_workflows)
    monkeypatch.setattr(executions.n8n_client, "get_execution_detail", fake_detail)

    page = await executions.list_runs("user_1")
    detail = await executions.get_run("user_1", "exec_crashed")

    assert page.executions[0].status == "error"
    assert detail.status == "error"
    assert detail.summary == "Workflow run failed."


@pytest.mark.asyncio
async def test_get_run_maps_n8n_404_to_domain_not_found(monkeypatch):
    async def fake_detail(_execution_id: str):
        raise n8n_client.N8nApiError(
            404,
            "missing",
            method="GET",
            path="/executions/missing",
        )

    monkeypatch.setattr(executions.n8n_client, "get_execution_detail", fake_detail)

    with pytest.raises(executions.ExecutionNotFoundError):
        await executions.get_run("user_1", "missing")


@pytest.mark.asyncio
async def test_service_requires_user_id():
    with pytest.raises(ValueError, match="user_id"):
        await executions.list_runs("")
    with pytest.raises(ValueError, match="user_id"):
        await executions.get_run("", "exec_1")
