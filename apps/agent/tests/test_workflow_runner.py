"""Workflow run, batch execution, and execution-summary tests."""

from types import SimpleNamespace

import httpx
import pytest

from src import store
from src.agent.tools import (
    _summarize_execution,
    iter_workflow_batch_with_input,
    run_workflow_batch_with_input,
    run_workflow_with_input,
)


@pytest.mark.asyncio
async def test_run_workflow_with_input_sends_payload_to_webhook(monkeypatch):
    sent: dict = {}

    async def fake_get_workflow_metadata(_user_id: str, workflow_id: str):
        return store.WorkflowMetadata(
            workflow_id=workflow_id,
            input_schema=[
                {
                    "name": "to",
                    "label": "Recipient email",
                    "type": "email",
                    "required": True,
                }
            ],
            created_at="now",
            updated_at="now",
        )

    async def fake_activate(_workflow_id: str):
        sent["activated"] = True

    async def fake_update_workflow(**kwargs):
        sent["updated_nodes"] = kwargs["nodes"]
        return SimpleNamespace(id=kwargs["workflow_id"])

    async def fake_get_workflow(_workflow_id: str):
        return {
            "id": "wf_1",
            "name": "Runtime workflow",
            "active": False,
            "nodes": sent["updated_nodes"],
        }

    async def fake_call_webhook(path: str, payload: dict):
        sent["path"] = path
        sent["payload"] = payload
        return httpx.Response(200, json={"ok": True})

    async def fake_list_executions(*_args, **_kwargs):
        return []

    monkeypatch.setattr("src.agent.tools.store.get_workflow_metadata", fake_get_workflow_metadata)
    monkeypatch.setattr("src.agent.tools.n8n_client.activate_workflow", fake_activate)
    monkeypatch.setattr("src.agent.tools.n8n_client.update_workflow", fake_update_workflow)
    monkeypatch.setattr("src.agent.tools.n8n_client.get_workflow", fake_get_workflow)
    monkeypatch.setattr("src.agent.tools.n8n_client.call_webhook", fake_call_webhook)
    monkeypatch.setattr("src.agent.tools.n8n_client.list_executions", fake_list_executions)
    monkeypatch.setattr("src.agent.tools.registry.get_node_schema", lambda _node_type: None)

    result = await run_workflow_with_input(
        {
            "id": "wf_1",
            "name": "Runtime workflow",
            "active": False,
            "nodes": [
                {
                    "name": "Webhook",
                    "type": "n8n-nodes-base.webhook",
                    "parameters": {"path": "runtime-test"},
                }
            ],
        },
        user_id="user_1",
        input_payload={"to": "person@example.com"},
    )

    assert sent["activated"] is True
    assert sent["updated_nodes"][0]["parameters"]["httpMethod"] == "POST"
    assert sent["path"] == "runtime-test"
    assert sent["payload"] == {"to": "person@example.com"}
    assert result.status == "triggered"


@pytest.mark.asyncio
async def test_run_workflow_with_input_summarizes_execution_after_webhook_error(monkeypatch):
    async def fake_get_workflow_metadata(_user_id: str, workflow_id: str):
        return store.WorkflowMetadata(
            workflow_id=workflow_id,
            input_schema=[
                {
                    "name": "to",
                    "label": "Recipient email",
                    "type": "email",
                    "required": True,
                }
            ],
            created_at="now",
            updated_at="now",
        )

    async def fake_readiness(_workflow: dict, *, user_id: str):
        assert user_id == "user_1"
        return {"webhook_nodes": [{"parameters": {"path": "runtime-test", "httpMethod": "POST"}}]}

    async def fake_call_webhook(_path: str, _payload: dict):
        return httpx.Response(500, json={"message": "Error in workflow"})

    async def fake_list_executions(*_args, **_kwargs):
        return [SimpleNamespace(id="exec_1")]

    async def fake_get_execution_detail(_execution_id: str):
        return {
            "id": "exec_1",
            "workflowId": "wf_1",
            "status": "error",
            "data": {
                "resultData": {
                    "lastNodeExecuted": "Gmail",
                    "error": {
                        "node": {"name": "Gmail"},
                        "message": "Gmail credential token is invalid or expired.",
                    },
                    "runData": {},
                }
            },
        }

    monkeypatch.setattr("src.agent.tools.store.get_workflow_metadata", fake_get_workflow_metadata)
    monkeypatch.setattr(
        "src.agent.tools.workflow_runner.analyze_workflow_readiness_payload",
        fake_readiness,
    )
    monkeypatch.setattr("src.agent.tools.n8n_client.call_webhook", fake_call_webhook)
    monkeypatch.setattr("src.agent.tools.n8n_client.list_executions", fake_list_executions)
    monkeypatch.setattr(
        "src.agent.tools.n8n_client.get_execution_detail", fake_get_execution_detail
    )

    result = await run_workflow_with_input(
        {
            "id": "wf_1",
            "name": "Runtime workflow",
            "active": True,
            "nodes": [
                {
                    "name": "Webhook",
                    "type": "n8n-nodes-base.webhook",
                    "parameters": {"path": "runtime-test", "httpMethod": "POST"},
                },
                {
                    "name": "Gmail",
                    "type": "n8n-nodes-base.gmail",
                    "parameters": {"resource": "message", "operation": "send"},
                },
            ],
        },
        user_id="user_1",
        input_payload={"to": "person@example.com"},
    )

    assert result.status == "error"
    assert result.executionId == "exec_1"
    assert result.failedNode == "Gmail"
    assert result.error == "Gmail credential token is invalid or expired."
    assert "Gmail credential token" in result.summary


@pytest.mark.asyncio
async def test_run_workflow_batch_with_input_continues_after_row_errors(monkeypatch):
    sent_payloads: list[dict] = []

    async def fake_get_workflow_metadata(_user_id: str, workflow_id: str):
        return store.WorkflowMetadata(
            workflow_id=workflow_id,
            input_schema=[
                {
                    "name": "to",
                    "label": "Recipient email",
                    "type": "email",
                    "required": True,
                }
            ],
            created_at="now",
            updated_at="now",
        )

    async def fake_readiness(_workflow: dict, *, user_id: str):
        assert user_id == "user_1"
        return {"webhook_nodes": [{"parameters": {"path": "runtime-test", "httpMethod": "POST"}}]}

    async def fake_call_webhook(_path: str, payload: dict):
        sent_payloads.append(payload)
        if payload["to"] == "broken@example.com":
            raise RuntimeError("transport failed")
        return httpx.Response(200, json={"ok": True})

    async def fake_list_executions(*_args, **_kwargs):
        return []

    monkeypatch.setattr("src.agent.tools.store.get_workflow_metadata", fake_get_workflow_metadata)
    monkeypatch.setattr(
        "src.agent.tools.workflow_runner.analyze_workflow_readiness_payload",
        fake_readiness,
    )
    monkeypatch.setattr("src.agent.tools.n8n_client.call_webhook", fake_call_webhook)
    monkeypatch.setattr("src.agent.tools.n8n_client.list_executions", fake_list_executions)

    result = await run_workflow_batch_with_input(
        {
            "id": "wf_1",
            "name": "Runtime workflow",
            "active": True,
            "nodes": [
                {
                    "name": "Webhook",
                    "type": "n8n-nodes-base.webhook",
                    "parameters": {"path": "runtime-test", "httpMethod": "POST"},
                }
            ],
        },
        user_id="user_1",
        rows=[
            {"rowNumber": 2, "input": {"to": "person@example.com"}},
            {"rowNumber": 3, "input": {"to": ""}},
            {"rowNumber": 4, "input": {"to": "broken@example.com"}},
        ],
    )

    assert result.status == "completed_with_errors"
    assert result.succeeded == 1
    assert result.skipped == 1
    assert result.failed == 1
    assert [row.status for row in result.results] == ["success", "skipped", "failed"]
    assert sent_payloads == [{"to": "person@example.com"}, {"to": "broken@example.com"}]


@pytest.mark.asyncio
async def test_iter_workflow_batch_with_input_streams_row_progress(monkeypatch):
    async def fake_get_workflow_metadata(_user_id: str, workflow_id: str):
        return store.WorkflowMetadata(
            workflow_id=workflow_id,
            input_schema=[
                {
                    "name": "to",
                    "label": "Recipient email",
                    "type": "email",
                    "required": True,
                }
            ],
            created_at="now",
            updated_at="now",
        )

    async def fake_readiness(_workflow: dict, *, user_id: str):
        assert user_id == "user_1"
        return {"webhook_nodes": [{"parameters": {"path": "runtime-test", "httpMethod": "POST"}}]}

    async def fake_call_webhook(_path: str, _payload: dict):
        return httpx.Response(200, json={"ok": True})

    async def fake_list_executions(*_args, **_kwargs):
        return []

    monkeypatch.setattr("src.agent.tools.store.get_workflow_metadata", fake_get_workflow_metadata)
    monkeypatch.setattr(
        "src.agent.tools.workflow_runner.analyze_workflow_readiness_payload",
        fake_readiness,
    )
    monkeypatch.setattr("src.agent.tools.n8n_client.call_webhook", fake_call_webhook)
    monkeypatch.setattr("src.agent.tools.n8n_client.list_executions", fake_list_executions)

    events = [
        (event, payload)
        async for event, payload in iter_workflow_batch_with_input(
            {
                "id": "wf_1",
                "name": "Runtime workflow",
                "active": True,
                "nodes": [
                    {
                        "name": "Webhook",
                        "type": "n8n-nodes-base.webhook",
                        "parameters": {"path": "runtime-test", "httpMethod": "POST"},
                    }
                ],
            },
            user_id="user_1",
            rows=[
                {"rowNumber": 2, "input": {"to": "person@example.com"}},
                {"rowNumber": 3, "input": {"to": ""}},
            ],
        )
    ]

    assert [event for event, _payload in events] == [
        "started",
        "row_started",
        "row_finished",
        "row_started",
        "row_finished",
        "completed",
    ]
    assert events[0][1]["totalRows"] == 2
    assert events[1][1] == {"rowNumber": 2, "index": 1, "totalRows": 2}
    assert events[2][1].status == "success"
    assert events[4][1].status == "skipped"
    assert events[5][1].skipped == 1


@pytest.mark.asyncio
async def test_run_workflow_with_input_returns_sheets_artifact(monkeypatch):
    async def fake_get_workflow_metadata(_user_id: str, workflow_id: str):
        return store.WorkflowMetadata(
            workflow_id=workflow_id,
            input_schema=[],
            resources={
                "log.spreadsheet": {
                    "spreadsheet_id": "sheet_123",
                    "spreadsheet_url": "https://sheet.test",
                    "sheet_name": "Log",
                }
            },
            created_at="now",
            updated_at="now",
        )

    async def fake_call_webhook(_path: str, _payload: dict):
        return httpx.Response(200, json={"ok": True})

    async def fake_list_executions(*_args, **_kwargs):
        return [SimpleNamespace(id="exec_1")]

    async def fake_get_execution_detail(_execution_id: str):
        return {
            "id": "exec_1",
            "workflowId": "wf_1",
            "status": "success",
            "data": {
                "resultData": {
                    "runData": {
                        "Prepare Sheets Row": [
                            {
                                "data": {
                                    "main": [
                                        [
                                            {
                                                "json": {
                                                    "Email": "person@example.com",
                                                    "Status": "Sent",
                                                }
                                            }
                                        ]
                                    ]
                                }
                            }
                        ]
                    }
                }
            },
        }

    monkeypatch.setattr("src.agent.tools.store.get_workflow_metadata", fake_get_workflow_metadata)
    monkeypatch.setattr("src.agent.tools.n8n_client.call_webhook", fake_call_webhook)
    monkeypatch.setattr("src.agent.tools.n8n_client.list_executions", fake_list_executions)
    monkeypatch.setattr(
        "src.agent.tools.n8n_client.get_execution_detail",
        fake_get_execution_detail,
    )
    monkeypatch.setattr("src.agent.tools.registry.get_node_schema", lambda _node_type: None)

    result = await run_workflow_with_input(
        {
            "id": "wf_1",
            "name": "Runtime workflow",
            "active": True,
            "nodes": [
                {
                    "name": "Webhook",
                    "type": "n8n-nodes-base.webhook",
                    "parameters": {"path": "runtime-test", "httpMethod": "POST"},
                }
            ],
        },
        user_id="user_1",
        input_payload={},
    )

    assert result.status == "success"
    assert result.artifacts[0].title == "Google Sheets row added"
    assert result.artifacts[0].url == "https://sheet.test"
    assert result.artifacts[0].table is not None
    assert result.artifacts[0].table.rows == [{"Email": "person@example.com", "Status": "Sent"}]


@pytest.mark.asyncio
async def test_run_workflow_with_input_returns_gmail_artifact(monkeypatch):
    async def fake_get_workflow_metadata(_user_id: str, workflow_id: str):
        return store.WorkflowMetadata(
            workflow_id=workflow_id,
            input_schema=[],
            resources={},
            created_at="now",
            updated_at="now",
        )

    async def fake_call_webhook(_path: str, _payload: dict):
        return httpx.Response(200, json={"ok": True})

    async def fake_list_executions(*_args, **_kwargs):
        return [SimpleNamespace(id="exec_1")]

    async def fake_get_execution_detail(_execution_id: str):
        return {
            "id": "exec_1",
            "workflowId": "wf_1",
            "status": "success",
            "data": {
                "resultData": {
                    "runData": {
                        "Gmail": [
                            {
                                "data": {
                                    "main": [
                                        [
                                            {
                                                "json": {
                                                    "id": "msg_123",
                                                    "threadId": "thread_123",
                                                    "labelIds": ["SENT"],
                                                }
                                            }
                                        ]
                                    ]
                                }
                            }
                        ]
                    }
                }
            },
        }

    monkeypatch.setattr("src.agent.tools.store.get_workflow_metadata", fake_get_workflow_metadata)
    monkeypatch.setattr("src.agent.tools.n8n_client.call_webhook", fake_call_webhook)
    monkeypatch.setattr("src.agent.tools.n8n_client.list_executions", fake_list_executions)
    monkeypatch.setattr(
        "src.agent.tools.n8n_client.get_execution_detail",
        fake_get_execution_detail,
    )
    monkeypatch.setattr("src.agent.tools.registry.get_node_schema", lambda _node_type: None)

    result = await run_workflow_with_input(
        {
            "id": "wf_1",
            "name": "Runtime workflow",
            "active": True,
            "nodes": [
                {
                    "name": "Webhook",
                    "type": "n8n-nodes-base.webhook",
                    "parameters": {"path": "runtime-test", "httpMethod": "POST"},
                }
            ],
        },
        user_id="user_1",
        input_payload={},
    )

    assert result.status == "success"
    assert result.artifacts[0].service == "gmail"
    assert result.artifacts[0].title == "Gmail message sent"
    assert result.artifacts[0].url == "https://mail.google.com/mail/u/0/#all/msg_123"
    assert result.artifacts[0].message is not None
    assert result.artifacts[0].message.messageId == "msg_123"


def test_summarize_execution_includes_node_output_preview():
    result = _summarize_execution(
        {
            "id": "42",
            "workflowId": "wf_1",
            "status": "success",
            "data": {
                "resultData": {
                    "runData": {
                        "Set": [
                            {
                                "data": {
                                    "main": [
                                        [
                                            {"json": {"message": "hello from Conduut"}},
                                            {"json": {"message": "second item"}},
                                        ]
                                    ]
                                }
                            }
                        ]
                    }
                }
            },
        },
        response={"statusCode": 200, "body": {"ok": True}},
    )

    assert result.summary == "Workflow run completed with 2 output item(s)."
    assert result.outputs[0]["nodeName"] == "Set"
    assert result.outputs[0]["itemCount"] == 2
    assert result.outputs[0]["items"][0]["message"] == "hello from Conduut"
    assert result.response is None


def test_summarize_execution_surfaces_error_description():
    # n8n HTTP errors put the actionable detail in `description`; the generic
    # `message` alone (e.g. "Bad request") is not enough for the user.
    result = _summarize_execution(
        {
            "id": "114",
            "workflowId": "wf_1",
            "status": "error",
            "data": {
                "resultData": {
                    "error": {
                        "node": {"name": "Get Quote"},
                        "message": "Bad request - please check your parameters",
                        "description": "category parameter is for premium subscribers only.",
                    }
                }
            },
        }
    )

    assert result.failedNode == "Get Quote"
    assert "Bad request - please check your parameters" in result.error
    assert "category parameter is for premium subscribers only." in result.error
    assert "category parameter is for premium subscribers only." in result.summary


def test_summarize_execution_hides_webhook_transport_metadata():
    result = _summarize_execution(
        {
            "id": "42",
            "workflowId": "wf_1",
            "status": "success",
            "data": {
                "resultData": {
                    "runData": {
                        "Webhook": [
                            {
                                "data": {
                                    "main": [
                                        [
                                            {
                                                "json": {
                                                    "headers": {"host": "n8n:5678"},
                                                    "params": {},
                                                    "query": {},
                                                    "body": {"source": "conduut_test"},
                                                    "webhookUrl": "http://localhost:5678/webhook/test",
                                                    "executionMode": "production",
                                                }
                                            }
                                        ]
                                    ]
                                }
                            }
                        ],
                        "Respond to Webhook": [
                            {
                                "data": {
                                    "main": [
                                        [
                                            {
                                                "json": {
                                                    "headers": {"host": "n8n:5678"},
                                                    "body": {"source": "conduut_test"},
                                                }
                                            }
                                        ]
                                    ]
                                }
                            }
                        ],
                    }
                }
            },
        },
        response={"statusCode": 200, "body": {"source": "conduut_test"}},
        workflow={
            "nodes": [
                {"name": "Webhook", "type": "n8n-nodes-base.webhook"},
                {"name": "Respond to Webhook", "type": "n8n-nodes-base.respondToWebhook"},
            ]
        },
    )

    assert result.summary == "Workflow run completed."
    assert result.outputs == []
    assert result.response is None
