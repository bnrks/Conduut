"""Tests for n8n_client credential attachment wiring."""

from src import n8n_client


class _FakeResp:
    status_code = 200
    headers = {"content-type": "application/json"}

    def json(self):
        return {}

    def raise_for_status(self):
        return None


def _patch(monkeypatch, node):
    captured: dict = {}

    async def fake_get_workflow(_wid):
        return {
            "name": "WF",
            "nodes": [node],
            "connections": {},
            "settings": {"executionOrder": "v1"},
        }

    async def fake_request(method, path, **kwargs):
        captured["method"] = method
        captured["path"] = path
        captured["json"] = kwargs.get("json")
        return _FakeResp()

    monkeypatch.setattr(n8n_client, "get_workflow", fake_get_workflow)
    monkeypatch.setattr(n8n_client, "_request", fake_request)
    return captured


async def test_attach_generic_auth_sets_authentication_params(monkeypatch):
    node = {
        "name": "HTTP Request",
        "type": "n8n-nodes-base.httpRequest",
        "parameters": {"url": "https://api.x.com"},
    }
    captured = _patch(monkeypatch, node)

    await n8n_client.attach_credential_to_workflow(
        "wf1",
        "HTTP Request",
        "httpHeaderAuth",
        "c1",
        "Cred",
        generic_auth_type="httpHeaderAuth",
    )

    put_node = captured["json"]["nodes"][0]
    assert put_node["parameters"]["authentication"] == "genericCredentialType"
    assert put_node["parameters"]["genericAuthType"] == "httpHeaderAuth"
    assert put_node["credentials"]["httpHeaderAuth"] == {"id": "c1", "name": "Cred"}


async def test_attach_without_generic_auth_keeps_parameters(monkeypatch):
    node = {
        "name": "Gmail",
        "type": "n8n-nodes-base.gmail",
        "parameters": {"resource": "message"},
    }
    captured = _patch(monkeypatch, node)

    await n8n_client.attach_credential_to_workflow("wf1", "Gmail", "gmailOAuth2", "c2", "Google")

    put_node = captured["json"]["nodes"][0]
    assert "authentication" not in put_node["parameters"]
    assert "genericAuthType" not in put_node["parameters"]
    assert put_node["credentials"]["gmailOAuth2"] == {"id": "c2", "name": "Google"}


async def test_call_webhook_uses_long_timeout_for_llm_workflows(monkeypatch):
    # A synchronous webhook run (responseMode=lastNode) blocks until the WHOLE
    # workflow finishes; AI/LLM workflows routinely take 30-120s. The webhook
    # client must wait long enough or the run errors even though n8n succeeds.
    captured: dict = {}

    class _CapturingClient:
        def __init__(self, *args, timeout=None, **kwargs):
            captured["timeout"] = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def post(self, url, json=None):
            return _FakeResp()

    monkeypatch.setattr(n8n_client.httpx, "AsyncClient", _CapturingClient)
    await n8n_client.call_webhook("some/path", {"x": 1})
    assert captured["timeout"] is not None
    assert float(captured["timeout"]) >= 120


async def test_list_executions_page_forwards_filters_and_cursor(monkeypatch):
    captured = {}

    class _ExecutionResponse(_FakeResp):
        def json(self):
            return {
                "data": [
                    {
                        "id": "exec_1",
                        "workflowId": "wf_1",
                        "status": "error",
                        "mode": "webhook",
                        "startedAt": "2026-07-15T10:00:00Z",
                        "stoppedAt": "2026-07-15T10:00:01Z",
                    }
                ],
                "nextCursor": "opaque-next",
            }

    async def fake_request(method, path, **kwargs):
        captured.update(method=method, path=path, params=kwargs.get("params"))
        return _ExecutionResponse()

    monkeypatch.setattr(n8n_client, "_request", fake_request)

    page = await n8n_client.list_executions_page(
        "wf_1",
        status="error",
        cursor="opaque-current",
        limit=42,
    )

    assert captured == {
        "method": "GET",
        "path": "/executions",
        "params": {
            "limit": 42,
            "workflowId": "wf_1",
            "status": "error",
            "cursor": "opaque-current",
        },
    }
    assert page.next_cursor == "opaque-next"
    assert page.executions[0].finished_at == "2026-07-15T10:00:01Z"
    assert page.executions[0].mode == "webhook"


async def test_legacy_list_executions_returns_page_items(monkeypatch):
    expected = n8n_client.N8nExecution(
        id="exec_1",
        workflow_id="wf_1",
        status="success",
        started_at="",
    )

    async def fake_page(**kwargs):
        assert kwargs == {"workflow_id": "wf_1", "limit": 3}
        return n8n_client.N8nExecutionPage(executions=[expected], next_cursor="ignored")

    monkeypatch.setattr(n8n_client, "list_executions_page", fake_page)

    assert await n8n_client.list_executions("wf_1", limit=3) == [expected]
