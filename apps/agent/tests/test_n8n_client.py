"""Tests for n8n_client credential attachment wiring."""

import asyncio

import pytest

from src import n8n_client


class _FakeResp:
    status_code = 200
    headers = {"content-type": "application/json"}

    def json(self):
        return {}

    def raise_for_status(self):
        return None


class _JsonResp(_FakeResp):
    def __init__(self, payload):
        self.payload = payload

    def json(self):
        return self.payload


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
        if method == "PUT":
            return _JsonResp(
                {
                    "id": "wf1",
                    "name": captured["json"]["name"],
                    "active": False,
                    "nodes": captured["json"]["nodes"],
                    "connections": captured["json"]["connections"],
                    "settings": captured["json"]["settings"],
                }
            )
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


async def test_workflow_settings_injects_default_timezone(monkeypatch):
    monkeypatch.setattr(n8n_client.settings, "workflow_timezone", "Europe/Istanbul", raising=False)

    assert n8n_client._workflow_settings({"saveExecutionProgress": True}) == {
        "saveExecutionProgress": True,
        "executionOrder": "v1",
        "timezone": "Europe/Istanbul",
    }


async def test_workflow_settings_preserves_explicit_timezone(monkeypatch):
    monkeypatch.setattr(n8n_client.settings, "workflow_timezone", "Europe/Istanbul", raising=False)

    assert n8n_client._workflow_settings({"timezone": "UTC"})["timezone"] == "UTC"


async def test_attach_same_credential_is_noop(monkeypatch):
    workflow = {
        "id": "wf1",
        "name": "WF",
        "active": True,
        "nodes": [
            {
                "name": "Gmail",
                "parameters": {},
                "credentials": {"gmailOAuth2": {"id": "c2", "name": "Old name"}},
            }
        ],
        "connections": {},
        "settings": {"executionOrder": "v1"},
    }

    async def fake_get_workflow(_workflow_id):
        return workflow

    async def fail_request(*_args, **_kwargs):
        raise AssertionError("same credential must not PUT or cycle activation")

    monkeypatch.setattr(n8n_client, "get_workflow", fake_get_workflow)
    monkeypatch.setattr(n8n_client, "_request", fail_request)

    result = await n8n_client.attach_credential_to_workflow(
        "wf1", "Gmail", "gmailOAuth2", "c2", "New name"
    )

    assert result is workflow


async def test_attach_different_credential_reregisters_active_workflow(monkeypatch):
    workflow = {
        "id": "wf1",
        "name": "WF",
        "active": True,
        "nodes": [
            {
                "name": "Gmail",
                "parameters": {},
                "credentials": {"gmailOAuth2": {"id": "stale", "name": "Stale"}},
            }
        ],
        "connections": {},
        "settings": {"executionOrder": "v1", "timezone": "Europe/Istanbul"},
    }
    calls: list[tuple[str, str]] = []

    async def fake_get_workflow(_workflow_id):
        return workflow

    async def fake_request(method, path, **_kwargs):
        calls.append((method, path))
        if method == "PUT":
            payload = _kwargs["json"]
            workflow["nodes"] = payload["nodes"]
            workflow["connections"] = payload["connections"]
            workflow["settings"] = payload["settings"]
            workflow["name"] = payload["name"]
            return _JsonResp({**workflow})
        return _JsonResp({})

    monkeypatch.setattr(n8n_client, "get_workflow", fake_get_workflow)
    monkeypatch.setattr(n8n_client, "_request", fake_request)

    await n8n_client.attach_credential_to_workflow("wf1", "Gmail", "gmailOAuth2", "fresh", "Fresh")

    assert calls == [
        ("PUT", "/workflows/wf1"),
        ("POST", "/workflows/wf1/deactivate"),
        ("POST", "/workflows/wf1/activate"),
    ]
    assert workflow["nodes"][0]["credentials"]["gmailOAuth2"]["id"] == "fresh"


async def test_update_active_workflow_puts_then_reregisters(monkeypatch):
    calls: list[tuple[str, str]] = []

    async def fake_get_workflow(_workflow_id):
        return {"id": "wf1", "active": True}

    async def fake_request(method, path, **_kwargs):
        calls.append((method, path))
        if method == "PUT":
            return _JsonResp({"id": "wf1", "name": "Updated", "active": True})
        return _JsonResp({})

    monkeypatch.setattr(n8n_client, "get_workflow", fake_get_workflow)
    monkeypatch.setattr(n8n_client, "_request", fake_request)

    result = await n8n_client.update_workflow("wf1", "Updated", [], {})

    assert result.active is True
    assert calls == [
        ("PUT", "/workflows/wf1"),
        ("POST", "/workflows/wf1/deactivate"),
        ("POST", "/workflows/wf1/activate"),
    ]


async def test_update_inactive_workflow_does_not_cycle_activation(monkeypatch):
    calls: list[tuple[str, str]] = []

    async def fake_get_workflow(_workflow_id):
        return {"id": "wf1", "active": False}

    async def fake_request(method, path, **_kwargs):
        calls.append((method, path))
        return _JsonResp({"id": "wf1", "name": "Updated", "active": False})

    monkeypatch.setattr(n8n_client, "get_workflow", fake_get_workflow)
    monkeypatch.setattr(n8n_client, "_request", fake_request)

    result = await n8n_client.update_workflow("wf1", "Updated", [], {})

    assert result.active is False
    assert calls == [("PUT", "/workflows/wf1")]


async def test_update_does_not_reactivate_after_concurrent_deactivation(monkeypatch):
    calls: list[tuple[str, str]] = []
    snapshots = iter(
        [
            {"id": "wf1", "active": True},
            {"id": "wf1", "active": False},
        ]
    )

    async def fake_get_workflow(_workflow_id):
        return next(snapshots)

    async def fake_request(method, path, **_kwargs):
        calls.append((method, path))
        return _JsonResp({"id": "wf1", "name": "Updated", "active": True})

    monkeypatch.setattr(n8n_client, "get_workflow", fake_get_workflow)
    monkeypatch.setattr(n8n_client, "_request", fake_request)

    result = await n8n_client.update_workflow("wf1", "Updated", [], {})

    assert result.active is False
    assert calls == [("PUT", "/workflows/wf1")]


async def test_update_preserves_retained_node_credentials_and_ids(monkeypatch):
    captured: dict = {}
    workflow = {
        "id": "wf1",
        "name": "WF",
        "active": False,
        "nodes": [
            {
                "id": "stable-http-id",
                "name": "HTTP Request",
                "type": "n8n-nodes-base.httpRequest",
                "parameters": {"url": "https://old.example.com"},
                "credentials": {"httpHeaderAuth": {"id": "cred-1", "name": "Existing"}},
            },
            {
                "id": "keep-trigger-id",
                "name": "Trigger",
                "type": "n8n-nodes-base.webhook",
                "parameters": {"path": "incoming"},
            },
        ],
        "connections": {
            "Trigger": {"main": [[{"node": "HTTP Request", "type": "main", "index": 0}]]}
        },
        "settings": {"executionOrder": "v1", "timezone": "Europe/Istanbul"},
    }

    async def fake_get_workflow(_workflow_id):
        return workflow

    async def fake_request(method, path, **kwargs):
        captured["method"] = method
        captured["path"] = path
        captured["json"] = kwargs.get("json")
        return _JsonResp(
            {
                "id": "wf1",
                "name": kwargs["json"]["name"],
                "active": False,
                "nodes": kwargs["json"]["nodes"],
                "connections": kwargs["json"]["connections"],
                "settings": kwargs["json"]["settings"],
            }
        )

    monkeypatch.setattr(n8n_client, "get_workflow", fake_get_workflow)
    monkeypatch.setattr(n8n_client, "_request", fake_request)

    await n8n_client.update_workflow(
        "wf1",
        "WF updated",
        [
            {
                "id": "model-regenerated-id",
                "name": "HTTP Request",
                "type": "n8n-nodes-base.httpRequest",
                "parameters": {"url": "https://new.example.com"},
            },
            {
                "id": "brand-new-trigger-id",
                "name": "Trigger",
                "type": "n8n-nodes-base.webhook",
                "parameters": {"path": "incoming"},
            },
        ],
        None,
    )

    nodes = captured["json"]["nodes"]
    by_name = {node["name"]: node for node in nodes}
    assert by_name["HTTP Request"]["id"] == "stable-http-id"
    assert by_name["HTTP Request"]["credentials"]["httpHeaderAuth"]["id"] == "cred-1"
    assert by_name["Trigger"]["id"] == "keep-trigger-id"
    assert captured["json"]["connections"] == workflow["connections"]


async def test_update_ignores_attempted_credential_override_on_retained_node(monkeypatch):
    captured: dict = {}
    workflow = {
        "id": "wf1",
        "name": "WF",
        "active": False,
        "nodes": [
            {
                "id": "stable-http-id",
                "name": "HTTP Request",
                "type": "n8n-nodes-base.httpRequest",
                "parameters": {"url": "https://old.example.com"},
                "credentials": {"httpHeaderAuth": {"id": "cred-1", "name": "Existing"}},
            }
        ],
        "connections": {},
        "settings": {"executionOrder": "v1"},
    }

    async def fake_get_workflow(_workflow_id):
        return workflow

    async def fake_request(method, path, **kwargs):
        captured["json"] = kwargs.get("json")
        return _JsonResp(
            {
                "id": "wf1",
                "name": kwargs["json"]["name"],
                "active": False,
                "nodes": kwargs["json"]["nodes"],
                "connections": kwargs["json"]["connections"],
                "settings": kwargs["json"]["settings"],
            }
        )

    monkeypatch.setattr(n8n_client, "get_workflow", fake_get_workflow)
    monkeypatch.setattr(n8n_client, "_request", fake_request)

    await n8n_client.update_workflow(
        "wf1",
        "WF updated",
        [
            {
                "id": "model-regenerated-id",
                "name": "HTTP Request",
                "type": "n8n-nodes-base.httpRequest",
                "parameters": {"url": "https://new.example.com"},
                "credentials": {"httpHeaderAuth": {"id": "cred-override", "name": "Override"}},
            }
        ],
        {},
    )

    node = captured["json"]["nodes"][0]
    assert node["id"] == "stable-http-id"
    assert node["credentials"] == workflow["nodes"][0]["credentials"]


async def test_update_strips_credentials_from_new_node(monkeypatch):
    captured: dict = {}
    workflow = {
        "id": "wf1",
        "name": "WF",
        "active": False,
        "nodes": [],
        "connections": {},
        "settings": {"executionOrder": "v1"},
    }

    async def fake_get_workflow(_workflow_id):
        return workflow

    async def fake_request(method, path, **kwargs):
        captured["json"] = kwargs.get("json")
        return _JsonResp(
            {
                "id": "wf1",
                "name": kwargs["json"]["name"],
                "active": False,
                "nodes": kwargs["json"]["nodes"],
                "connections": kwargs["json"]["connections"],
                "settings": kwargs["json"]["settings"],
            }
        )

    monkeypatch.setattr(n8n_client, "get_workflow", fake_get_workflow)
    monkeypatch.setattr(n8n_client, "_request", fake_request)

    await n8n_client.update_workflow(
        "wf1",
        "WF updated",
        [
            {
                "id": "new-node-id",
                "name": "New HTTP",
                "type": "n8n-nodes-base.httpRequest",
                "parameters": {"url": "https://new.example.com"},
                "credentials": {"httpHeaderAuth": {"id": "cred-new", "name": "Injected"}},
            }
        ],
        {},
    )

    node = captured["json"]["nodes"][0]
    assert "credentials" not in node


async def test_concurrent_attach_credential_mutations_do_not_clobber_each_other(monkeypatch):
    state = {
        "id": "wf1",
        "name": "WF",
        "active": False,
        "nodes": [
            {"name": "HTTP One", "type": "n8n-nodes-base.httpRequest", "parameters": {}},
            {"name": "HTTP Two", "type": "n8n-nodes-base.httpRequest", "parameters": {}},
        ],
        "connections": {},
        "settings": {"executionOrder": "v1", "timezone": "Europe/Istanbul"},
    }

    async def fake_get_workflow(_workflow_id):
        return {
            "id": state["id"],
            "name": state["name"],
            "active": state["active"],
            "nodes": [dict(node) for node in state["nodes"]],
            "connections": dict(state["connections"]),
            "settings": dict(state["settings"]),
        }

    async def fake_request(method, path, **kwargs):
        if method != "PUT":
            return _JsonResp({})
        await asyncio.sleep(0.01)
        payload = kwargs["json"]
        state["name"] = payload["name"]
        state["nodes"] = payload["nodes"]
        state["connections"] = payload["connections"]
        state["settings"] = payload["settings"]
        return _JsonResp({"id": "wf1", "active": False, **payload})

    monkeypatch.setattr(n8n_client, "get_workflow", fake_get_workflow)
    monkeypatch.setattr(n8n_client, "_request", fake_request)

    await asyncio.gather(
        n8n_client.attach_credential_to_workflow(
            "wf1",
            "HTTP One",
            "httpHeaderAuth",
            "cred-1",
            "Cred One",
            generic_auth_type="httpHeaderAuth",
        ),
        n8n_client.attach_credential_to_workflow(
            "wf1",
            "HTTP Two",
            "httpHeaderAuth",
            "cred-2",
            "Cred Two",
            generic_auth_type="httpHeaderAuth",
        ),
    )

    by_name = {node["name"]: node for node in state["nodes"]}
    assert by_name["HTTP One"]["credentials"]["httpHeaderAuth"]["id"] == "cred-1"
    assert by_name["HTTP Two"]["credentials"]["httpHeaderAuth"]["id"] == "cred-2"


async def test_attach_verifies_committed_result_contains_requested_credential(monkeypatch):
    workflow = {
        "id": "wf1",
        "name": "WF",
        "active": False,
        "nodes": [{"name": "HTTP Request", "type": "n8n-nodes-base.httpRequest", "parameters": {}}],
        "connections": {},
        "settings": {"executionOrder": "v1"},
    }

    async def fake_get_workflow(_workflow_id):
        return workflow

    async def fake_request(method, path, **_kwargs):
        if method == "PUT":
            return _JsonResp(
                {
                    **workflow,
                    "nodes": [{"name": "HTTP Request", "type": "n8n-nodes-base.httpRequest"}],
                }
            )
        return _JsonResp({})

    monkeypatch.setattr(n8n_client, "get_workflow", fake_get_workflow)
    monkeypatch.setattr(n8n_client, "_request", fake_request)

    try:
        await n8n_client.attach_credential_to_workflow(
            "wf1",
            "HTTP Request",
            "httpHeaderAuth",
            "cred-1",
            "Cred",
            generic_auth_type="httpHeaderAuth",
        )
    except n8n_client.N8nApiError as exc:
        assert exc.status_code == 409
    else:
        raise AssertionError("expected committed credential verification to fail")


async def test_attach_verifies_committed_generic_auth_configuration(monkeypatch):
    workflow = {
        "id": "wf1",
        "name": "WF",
        "active": False,
        "nodes": [{"name": "HTTP Request", "type": "n8n-nodes-base.httpRequest", "parameters": {}}],
        "connections": {},
        "settings": {"executionOrder": "v1"},
    }

    async def fake_get_workflow(_workflow_id):
        return workflow

    async def fake_request(method, path, **_kwargs):
        if method == "PUT":
            return _JsonResp(
                {
                    **workflow,
                    "nodes": [
                        {
                            "name": "HTTP Request",
                            "type": "n8n-nodes-base.httpRequest",
                            "parameters": {},
                            "credentials": {"httpHeaderAuth": {"id": "cred-1", "name": "Cred"}},
                        }
                    ],
                }
            )
        return _JsonResp({})

    monkeypatch.setattr(n8n_client, "get_workflow", fake_get_workflow)
    monkeypatch.setattr(n8n_client, "_request", fake_request)

    with pytest.raises(n8n_client.N8nApiError) as exc_info:
        await n8n_client.attach_credential_to_workflow(
            "wf1",
            "HTTP Request",
            "httpHeaderAuth",
            "cred-1",
            "Cred",
            generic_auth_type="httpHeaderAuth",
        )

    assert exc_info.value.status_code == 409


async def test_mutations_do_not_serialize_across_different_workflows(monkeypatch):
    states = {
        "wf1": {"id": "wf1", "name": "WF 1", "active": False},
        "wf2": {"id": "wf2", "name": "WF 2", "active": False},
    }
    in_flight = 0
    both_in_flight = asyncio.Event()
    release = asyncio.Event()

    async def fake_get_workflow(workflow_id):
        state = states[workflow_id]
        return {
            "id": state["id"],
            "name": state["name"],
            "active": state["active"],
            "nodes": [],
            "connections": {},
            "settings": {"executionOrder": "v1"},
        }

    async def fake_request(method, path, **kwargs):
        nonlocal in_flight
        if method == "PUT":
            in_flight += 1
            if in_flight == 2:
                both_in_flight.set()
            await release.wait()
            in_flight -= 1
            workflow_id = path.rsplit("/", 1)[-1]
            return _JsonResp({"id": workflow_id, "active": False, **kwargs["json"]})
        return _JsonResp({})

    monkeypatch.setattr(n8n_client, "get_workflow", fake_get_workflow)
    monkeypatch.setattr(n8n_client, "_request", fake_request)

    task_one = asyncio.create_task(n8n_client.update_workflow("wf1", "WF 1 updated", [], {}))
    task_two = asyncio.create_task(n8n_client.update_workflow("wf2", "WF 2 updated", [], {}))
    await asyncio.wait_for(both_in_flight.wait(), timeout=0.2)
    release.set()
    await asyncio.gather(task_one, task_two)


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
