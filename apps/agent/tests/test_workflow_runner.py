"""Workflow run, batch execution, and execution-summary tests."""

from types import SimpleNamespace

import httpx
import pytest

from src import store
from src.agent.assurance.models import AssurancePlan, AssuranceReport
from src.agent.tools import (
    _summarize_execution,
    iter_workflow_batch_with_input,
    run_workflow_batch_with_input,
    run_workflow_with_input,
)
from src.agent.tools.read_after_write import _literal_or_output, verify_sheets_read_after_write


@pytest.fixture(autouse=True)
def _stub_execution_evidence_store(monkeypatch):
    async def fake_save_execution_evidence(*_args, **_kwargs):
        return None

    monkeypatch.setattr(
        "src.agent.tools.workflow_runner.store.save_execution_evidence",
        fake_save_execution_evidence,
    )


@pytest.mark.asyncio
async def test_external_trigger_run_reports_conduut_limit_and_editor_alternative(monkeypatch):
    async def fake_get_workflow_metadata(_user_id: str, workflow_id: str):
        return store.WorkflowMetadata(
            workflow_id=workflow_id,
            input_schema=[],
            resources={},
            created_at="now",
            updated_at="now",
        )

    monkeypatch.setattr("src.agent.tools.store.get_workflow_metadata", fake_get_workflow_metadata)
    monkeypatch.setattr("src.agent.tools.registry.get_node_schema", lambda _node_type: None)

    with pytest.raises(ValueError) as exc_info:
        await run_workflow_with_input(
            {
                "id": "wf_external",
                "name": "Incoming Gmail",
                "active": True,
                "nodes": [
                    {
                        "name": "Gmail Trigger",
                        "type": "n8n-nodes-base.gmailTrigger",
                        "parameters": {"event": "messageReceived"},
                    }
                ],
                "connections": {},
            },
            user_id="user_1",
            input_payload={},
        )

    message = str(exc_info.value)
    assert "Conduut chat cannot start it manually yet" in message
    assert "Execute workflow in the n8n editor" in message


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
async def test_run_workflow_with_input_normalizes_no_item_webhook_as_no_action(monkeypatch):
    async def fake_get_workflow_metadata(_user_id: str, workflow_id: str):
        return store.WorkflowMetadata(
            workflow_id=workflow_id,
            input_schema=[],
            resources={},
            created_at="now",
            updated_at="now",
        )

    async def fake_readiness(_workflow: dict, *, user_id: str):
        assert user_id == "user_1"
        return {"webhook_nodes": [{"parameters": {"path": "runtime-test"}}]}

    async def fake_call_webhook(_path: str, _payload: dict):
        return httpx.Response(500, json={"message": "No item to return was found"})

    async def fake_list_executions(*_args, **_kwargs):
        return [SimpleNamespace(id="exec_no_action")]

    async def fake_get_execution_detail(_execution_id: str):
        return {
            "id": "exec_no_action",
            "workflowId": "wf_1",
            "status": "success",
            "finished": True,
            "data": {
                "resultData": {
                    "runData": {
                        "Webhook": [
                            {
                                "executionStatus": "success",
                                "data": {"main": [[{"json": {"body": {}}}]]},
                            }
                        ],
                        "Read Sheet": [
                            {
                                "executionStatus": "success",
                                "data": {
                                    "main": [
                                        [
                                            {
                                                "json": {
                                                    "musteri_no": 1001,
                                                    "tanıtım maili atıldı mı": "Evet",
                                                }
                                            }
                                        ]
                                    ]
                                },
                            }
                        ],
                        "Filter": [
                            {
                                "executionStatus": "success",
                                "data": {
                                    "main": [
                                        [],
                                        [
                                            {
                                                "json": {
                                                    "musteri_no": 1001,
                                                    "tanıtım maili atıldı mı": "Evet",
                                                }
                                            }
                                        ],
                                    ]
                                },
                            }
                        ],
                    }
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
                    "parameters": {
                        "path": "runtime-test",
                        "httpMethod": "POST",
                        "responseMode": "lastNode",
                    },
                },
                {
                    "name": "Read Sheet",
                    "type": "n8n-nodes-base.googleSheets",
                    "parameters": {"resource": "sheet", "operation": "read"},
                },
                {
                    "name": "Filter",
                    "type": "n8n-nodes-base.filter",
                    "parameters": {},
                },
                {
                    "name": "AI Agent",
                    "type": "@n8n/n8n-nodes-langchain.agent",
                    "parameters": {},
                },
                {
                    "name": "Gmail Send",
                    "type": "n8n-nodes-base.gmail",
                    "parameters": {"resource": "message", "operation": "send"},
                },
                {
                    "name": "Sheets Update",
                    "type": "n8n-nodes-base.googleSheets",
                    "parameters": {
                        "resource": "sheet",
                        "operation": "update",
                        "columns": {
                            "matchingColumns": ["musteri_no"],
                            "value": {
                                "musteri_no": "={{ $('Filter').item.json.musteri_no }}",
                                "tanıtım maili atıldı mı": "Evet",
                            },
                        },
                    },
                },
            ],
            "connections": {
                "Webhook": {"main": [[{"node": "Read Sheet", "type": "main", "index": 0}]]},
                "Read Sheet": {"main": [[{"node": "Filter", "type": "main", "index": 0}]]},
                "Filter": {"main": [[{"node": "AI Agent", "type": "main", "index": 0}]]},
                "AI Agent": {"main": [[{"node": "Gmail Send", "type": "main", "index": 0}]]},
                "Gmail Send": {"main": [[{"node": "Sheets Update", "type": "main", "index": 0}]]},
            },
        },
        user_id="user_1",
        input_payload={},
    )

    assert result.status == "success"
    assert result.functionalStatus == "no_action"
    assert result.claimableOutcome == "no_action"
    assert result.summary == "Workflow run completed with no action needed."
    assert result.assessment.transportStatusCode == 500
    assert result.assessment.transportOk is True
    assert result.assessment.eligibleCount == 0
    assert result.assessment.actionCount == 0
    assert result.assessment.writebackCount == 0
    assert result.response is None


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

    assert result.status == "failed"
    assert result.succeeded == 0
    assert result.skipped == 1
    assert result.failed == 2
    assert result.unknown == 1
    assert [row.status for row in result.results] == ["triggered", "skipped", "failed"]
    assert [row.functionalStatus for row in result.results] == [
        "unknown",
        "unknown",
        "failed",
    ]
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
    assert events[2][1].status == "triggered"
    assert events[2][1].functionalStatus == "unknown"
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


def test_summarize_execution_surfaces_n8n_parameter_name():
    result = _summarize_execution(
        {
            "id": "265",
            "workflowId": "wf_e2",
            "status": "error",
            "data": {
                "resultData": {
                    "error": {
                        "node": {"name": "Google Sheets"},
                        "message": "Could not get parameter",
                        "extra": {"parameterName": "columns.schema"},
                    }
                }
            },
        }
    )

    assert result.failedNode == "Google Sheets"
    assert result.error == "Could not get parameter — Parameter: columns.schema"
    assert "columns.schema" in result.summary


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

    assert result.summary == "Workflow run completed with no action needed."
    assert result.functionalStatus == "no_action"
    assert result.outputs == []
    assert result.response is None


def test_summarize_execution_marks_success_with_zero_output_mutation_as_partial():
    workflow = {
        "nodes": [
            {
                "name": "Send Email",
                "type": "n8n-nodes-base.gmail",
                "parameters": {"resource": "message", "operation": "send"},
            },
            {
                "name": "Update Status",
                "type": "n8n-nodes-base.googleSheets",
                "parameters": {"resource": "sheet", "operation": "update"},
            },
        ]
    }
    result = _summarize_execution(
        {
            "id": "320",
            "workflowId": "wf_1",
            "status": "success",
            "data": {
                "resultData": {
                    "runData": {
                        "Send Email": [
                            {
                                "executionStatus": "success",
                                "data": {
                                    "main": [
                                        [
                                            {"json": {"id": "m1", "labelIds": ["SENT"]}},
                                            {"json": {"id": "m2", "labelIds": ["SENT"]}},
                                        ]
                                    ]
                                },
                            }
                        ],
                        "Update Status": [{"executionStatus": "success", "data": {"main": []}}],
                    }
                }
            },
        },
        response={"statusCode": 500, "body": {"message": "No item to return was found"}},
        workflow=workflow,
    )

    assert result.status == "success"
    assert result.functionalStatus == "partial"
    assert result.claimableOutcome == "none"
    assert result.assessment.transportStatusCode == 500
    assert result.assessment.transportOk is False
    assert result.assessment.executionOk is True
    assert result.assessment.coverage == "partial"
    assert result.assessment.actionCount == 2
    assert result.assessment.writebackCount == 0
    assert result.assessment.postconditionsVerified is False
    assert result.assessment.duplicateRisk is True
    assert result.assessment.warnings
    assert result.assessment.evidence
    assert result.assessment.successfulMutationNodes == ["Send Email"]
    assert result.assessment.zeroOutputMutationNodes == ["Update Status"]
    assert result.outputs[-1] == {
        "nodeName": "Update Status",
        "itemCount": 0,
        "items": [],
        "mutation": True,
    }


def test_summarize_execution_marks_unreached_mutations_as_clean_no_action():
    workflow = {
        "nodes": [
            {
                "name": "Filter",
                "type": "n8n-nodes-base.code",
                "parameters": {},
            },
            {
                "name": "Send Email",
                "type": "n8n-nodes-base.gmail",
                "parameters": {"resource": "message", "operation": "send"},
            },
        ]
    }
    result = _summarize_execution(
        {
            "id": "328",
            "workflowId": "wf_1",
            "status": "success",
            "data": {
                "resultData": {
                    "runData": {"Filter": [{"executionStatus": "success", "data": {"main": [[]]}}]}
                }
            },
        },
        response={"statusCode": 200, "body": {}},
        workflow=workflow,
    )

    assert result.status == "success"
    assert result.functionalStatus == "no_action"
    assert result.claimableOutcome == "no_action"
    assert result.assessment.executedMutationNodes == []
    assert result.assessment.configuredMutationNodes == ["Send Email"]
    assert result.assessment.coverage == "full"
    assert result.assessment.eligibleCount == 0
    assert result.assessment.postconditionsVerified is True


def test_summarize_execution_verifies_successful_mutation_evidence():
    workflow = {
        "nodes": [
            {
                "name": "Send Email",
                "type": "n8n-nodes-base.gmail",
                "parameters": {"resource": "message", "operation": "send"},
            }
        ]
    }
    result = _summarize_execution(
        {
            "id": "327",
            "workflowId": "wf_1",
            "status": "success",
            "data": {
                "resultData": {
                    "runData": {
                        "Send Email": [
                            {
                                "executionStatus": "success",
                                "data": {"main": [[{"json": {"id": "m1", "labelIds": ["SENT"]}}]]},
                            }
                        ]
                    }
                }
            },
        },
        response={"statusCode": 200, "body": {"id": "m1"}},
        workflow=workflow,
    )

    assert result.functionalStatus == "verified"
    assert result.claimableOutcome == "run_verified"
    assert result.assessment.successfulMutationNodes == ["Send Email"]
    assert result.assessment.transportOk is True
    assert result.assessment.executionOk is True
    assert result.assessment.coverage == "full"
    assert result.assessment.actionCount == 1
    assert result.assessment.writebackCount == 0
    assert result.assessment.postconditionsVerified is True
    assert result.assessment.duplicateRisk is False
    assert any(
        item.kind == "effect_verified" and item.verifier == "gmail_message_sent"
        for item in result.assessment.evidence
    )
    assert result.assessment.oracle is not None
    assert result.assessment.oracle.contextSource == "exact"
    assert result.assessment.postconditions[0].code == "exact_execution_context"
    assert result.assessment.postconditions[0].status == "verified"


def test_summarize_execution_allows_action_verified_for_partial_contract_coverage():
    workflow = {
        "nodes": [
            {"name": "Custom", "type": "n8n-nodes-community.custom", "parameters": {}},
            {
                "name": "Send Email",
                "type": "n8n-nodes-base.gmail",
                "parameters": {"resource": "message", "operation": "send"},
            },
        ],
        "connections": {"Custom": {"main": [[{"node": "Send Email", "type": "main", "index": 0}]]}},
    }
    result = _summarize_execution(
        {
            "id": "partial-coverage",
            "workflowId": "wf_1",
            "status": "success",
            "data": {
                "resultData": {
                    "runData": {
                        "Send Email": [
                            {
                                "executionStatus": "success",
                                "data": {"main": [[{"json": {"id": "m1", "labelIds": ["SENT"]}}]]},
                            }
                        ]
                    }
                }
            },
        },
        response={"statusCode": 200, "body": {"id": "m1", "labelIds": ["SENT"]}},
        workflow=workflow,
    )

    assert result.functionalStatus == "needs_attention"
    assert result.claimableOutcome == "action_verified"
    assert result.assessment.coverage == "partial"
    assert any(
        "no static output contract" in warning.message for warning in result.assessment.warnings
    )
    assert any(
        item.kind == "effect_verified" and item.nodeName == "Send Email"
        for item in result.assessment.evidence
    )


def test_summarize_execution_requires_sent_label_for_gmail_action_verified():
    workflow = {
        "nodes": [
            {"name": "Custom", "type": "n8n-nodes-community.custom", "parameters": {}},
            {
                "name": "Send Email",
                "type": "n8n-nodes-base.gmail",
                "parameters": {"resource": "message", "operation": "send"},
            },
        ],
        "connections": {"Custom": {"main": [[{"node": "Send Email", "type": "main", "index": 0}]]}},
    }
    result = _summarize_execution(
        {
            "id": "missing-sent",
            "workflowId": "wf_1",
            "status": "success",
            "data": {
                "resultData": {
                    "runData": {
                        "Send Email": [
                            {
                                "executionStatus": "success",
                                "data": {"main": [[{"json": {"id": "m1", "labelIds": ["INBOX"]}}]]},
                            }
                        ]
                    }
                }
            },
        },
        response={"statusCode": 200, "body": {"id": "m1"}},
        workflow=workflow,
    )

    assert result.functionalStatus == "needs_attention"
    assert result.claimableOutcome == "none"
    assert result.assessment.coverage == "partial"
    assert not any(item.kind == "effect_verified" for item in result.assessment.evidence)


def test_summarize_execution_requires_receipt_for_each_gmail_output_item():
    workflow = {
        "nodes": [
            {"name": "Custom", "type": "n8n-nodes-community.custom", "parameters": {}},
            {
                "name": "Send Email",
                "type": "n8n-nodes-base.gmail",
                "parameters": {"resource": "message", "operation": "send"},
            },
        ],
        "connections": {"Custom": {"main": [[{"node": "Send Email", "type": "main", "index": 0}]]}},
    }
    result = _summarize_execution(
        {
            "id": "partial-gmail-receipts",
            "workflowId": "wf_1",
            "status": "success",
            "data": {
                "resultData": {
                    "runData": {
                        "Send Email": [
                            {
                                "executionStatus": "success",
                                "data": {
                                    "main": [
                                        [
                                            {"json": {"id": "m1", "labelIds": ["SENT"]}},
                                            {"json": {"id": "", "labelIds": ["SENT"]}},
                                        ]
                                    ]
                                },
                            }
                        ]
                    }
                }
            },
        },
        response={"statusCode": 200, "body": {"id": "m1"}},
        workflow=workflow,
    )

    effect_items = [item for item in result.assessment.evidence if item.kind == "effect_verified"]
    assert result.functionalStatus == "needs_attention"
    assert result.claimableOutcome == "none"
    assert effect_items[0].outputItemCount == 1
    assert effect_items[0].effectVerified is False
    assert any(
        item.code == "action_provider_receipt" and item.status == "failed"
        for item in result.assessment.postconditions
    )


def test_summarize_execution_blocking_assurance_keeps_claimable_outcome_none():
    workflow = {
        "nodes": [
            {"name": "Webhook", "type": "n8n-nodes-base.webhook", "parameters": {}},
            {
                "name": "Update Status",
                "type": "n8n-nodes-base.googleSheets",
                "parameters": {
                    "resource": "sheet",
                    "operation": "update",
                    "columns": {
                        "mappingMode": "defineBelow",
                        "matchingColumns": ["email"],
                        "value": {"status": "sent", "email": "={{ $json.email }}"},
                    },
                },
            },
            {
                "name": "Send Email",
                "type": "n8n-nodes-base.gmail",
                "parameters": {"resource": "message", "operation": "send"},
            },
        ],
        "connections": {
            "Webhook": {"main": [[{"node": "Update Status", "type": "main", "index": 0}]]},
            "Update Status": {"main": [[{"node": "Send Email", "type": "main", "index": 0}]]},
        },
    }
    result = _summarize_execution(
        {
            "id": "blocking-assurance",
            "workflowId": "wf_1",
            "status": "success",
            "data": {
                "resultData": {
                    "runData": {
                        "Update Status": [
                            {
                                "executionStatus": "success",
                                "data": {"main": [[{"json": {"updated": True}}]]},
                            }
                        ],
                        "Send Email": [
                            {
                                "executionStatus": "success",
                                "data": {"main": [[{"json": {"id": "m1", "labelIds": ["SENT"]}}]]},
                            }
                        ],
                    }
                }
            },
        },
        response={"statusCode": 200, "body": {"id": "m1"}},
        workflow=workflow,
    )

    assert result.functionalStatus == "needs_attention"
    assert result.claimableOutcome == "none"
    assert result.assessment.coverage == "partial"
    assert any(warning.severity == "error" for warning in result.assessment.warnings)


def test_summarize_execution_with_writeback_stays_action_verified_without_remote_verifier(
    monkeypatch,
):
    workflow = {
        "nodes": [
            {
                "name": "Send Email",
                "type": "n8n-nodes-base.gmail",
                "parameters": {"resource": "message", "operation": "send"},
            },
            {
                "name": "Update Status",
                "type": "n8n-nodes-base.googleSheets",
                "parameters": {
                    "resource": "sheet",
                    "operation": "update",
                    "columns": {
                        "mappingMode": "defineBelow",
                        "matchingColumns": ["record_id"],
                        "value": {"record_id": "={{ $json.record_id }}"},
                    },
                },
            },
        ],
        "connections": {
            "Send Email": {"main": [[{"node": "Update Status", "type": "main", "index": 0}]]}
        },
    }
    monkeypatch.setattr(
        "src.agent.tools.execution.analyze_workflow_semantics",
        lambda *_args, **_kwargs: AssuranceReport(
            fingerprint="fp-writeback",
            plan=AssurancePlan(
                fingerprint="fp-writeback",
                node_roles={"Send Email": "action", "Update Status": "writeback"},
                cardinality_relations=(
                    "eligible_count == action_count",
                    "action_count == writeback_count",
                ),
                identity_fields={"Update Status": ("record_id",)},
                expected_postconditions=(
                    "every action has a provider receipt",
                    "every successful action has one write-back",
                    "write-back identity is non-empty and unique",
                ),
            ),
            findings=(),
        ),
    )
    result = _summarize_execution(
        {
            "id": "writeback-unverified",
            "workflowId": "wf_1",
            "status": "success",
            "data": {
                "resultData": {
                    "runData": {
                        "Send Email": [
                            {
                                "executionStatus": "success",
                                "data": {"main": [[{"json": {"id": "m1", "labelIds": ["SENT"]}}]]},
                            }
                        ],
                        "Update Status": [
                            {
                                "executionStatus": "success",
                                "data": {"main": [[{"json": {"updated": True}}]]},
                            }
                        ],
                    }
                }
            },
        },
        response={"statusCode": 200, "body": {"id": "m1"}},
        workflow=workflow,
    )

    assert result.functionalStatus == "needs_attention"
    assert result.claimableOutcome == "action_verified"
    assert result.assessment.postconditionsVerified is False
    assert any(
        item.code == "writeback_effect_verified" and item.status == "unknown"
        for item in result.assessment.postconditions
    )


@pytest.mark.asyncio
async def test_sheets_read_after_write_promotes_only_matching_remote_rows(monkeypatch):
    workflow = {
        "nodes": [
            {
                "name": "Send Email",
                "type": "n8n-nodes-base.gmail",
                "parameters": {"resource": "message", "operation": "send"},
            },
            {
                "name": "Update Status",
                "type": "n8n-nodes-base.googleSheets",
                "parameters": {
                    "resource": "sheet",
                    "operation": "update",
                    "documentId": {"__rl": True, "mode": "id", "value": "doc-1"},
                    "sheetName": {"__rl": True, "mode": "name", "value": "Leads"},
                    "columns": {
                        "mappingMode": "defineBelow",
                        "matchingColumns": ["record_id"],
                        "value": {
                            "record_id": "={{ $('IF').item.json.record_id }}",
                            "status": "Evet",
                        },
                    },
                },
            },
        ],
        "connections": {
            "Send Email": {"main": [[{"node": "Update Status", "type": "main", "index": 0}]]}
        },
    }
    monkeypatch.setattr(
        "src.agent.tools.execution.analyze_workflow_semantics",
        lambda *_args, **_kwargs: AssuranceReport(
            fingerprint="fp-writeback",
            plan=AssurancePlan(
                fingerprint="fp-writeback",
                node_roles={"Send Email": "action", "Update Status": "writeback"},
                cardinality_relations=("action_count == writeback_count",),
                identity_fields={"Update Status": ("record_id",)},
                expected_postconditions=(
                    "every action has a provider receipt",
                    "every successful action has one write-back",
                    "write-back identity is non-empty and unique",
                ),
            ),
            findings=(),
        ),
    )
    execution = {
        "id": "writeback-verified",
        "workflowId": "wf_1",
        "status": "success",
        "data": {
            "resultData": {
                "runData": {
                    "Send Email": [
                        {
                            "executionStatus": "success",
                            "data": {"main": [[{"json": {"id": "m1", "labelIds": ["SENT"]}}]]},
                        }
                    ],
                    "Update Status": [
                        {
                            "executionStatus": "success",
                            "data": {
                                "main": [
                                    [
                                        {
                                            "json": {
                                                "record_id": "lead-1",
                                                "status": "Evet",
                                            }
                                        }
                                    ]
                                ]
                            },
                        }
                    ],
                }
            }
        },
    }
    result = _summarize_execution(execution, workflow=workflow)
    assert result.claimableOutcome == "action_verified"

    async def fake_read_range(self, *, spreadsheet_id: str, range: str):
        assert spreadsheet_id == "doc-1"
        assert range == "Leads!A1:ZZ500"
        return {"values": [["record_id", "status"], ["lead-1", "Evet"]]}

    monkeypatch.setattr(
        "src.agent.tools.read_after_write.SheetsClient.read_range",
        fake_read_range,
    )

    verified = await verify_sheets_read_after_write(
        "user-1",
        workflow=workflow,
        execution=execution,
        result=result,
    )

    assert verified.functionalStatus == "verified"
    assert verified.claimableOutcome == "run_verified"
    assert verified.assessment.postconditionsVerified is True
    assert any(
        item.verifier == "sheets_read_after_write" and item.effectVerified
        for item in verified.assessment.evidence
    )


def test_read_after_write_resolves_expressions_but_preserves_configured_literals():
    output = {"record_id": "lead-1", "status": "Hayır"}

    assert (
        _literal_or_output(
            "={{ $('IF').item.json.record_id }}",
            target="record_id",
            output=output,
        )
        == "lead-1"
    )
    assert _literal_or_output("Evet", target="status", output=output) == "Evet"


def test_summarize_execution_with_mutation_but_no_run_data_is_unknown():
    workflow = {
        "nodes": [
            {
                "name": "Send Email",
                "type": "n8n-nodes-base.gmail",
                "parameters": {"resource": "message", "operation": "send"},
            }
        ]
    }

    result = _summarize_execution(
        {"id": "missing-detail", "workflowId": "wf_1", "status": "success"},
        response={"statusCode": 200, "body": {}},
        workflow=workflow,
    )

    assert result.functionalStatus == "unknown"
    assert result.claimableOutcome == "none"


def test_summarize_execution_without_exact_context_cannot_be_verified():
    result = _summarize_execution(
        {
            "id": "contextless",
            "workflowId": "wf_1",
            "status": "success",
            "data": {
                "resultData": {
                    "runData": {
                        "Send Email": [
                            {
                                "executionStatus": "success",
                                "data": {"main": [[{"json": {"id": "m1", "labelIds": ["SENT"]}}]]},
                            }
                        ]
                    }
                }
            },
        },
        response={"statusCode": 200, "body": {"id": "m1"}},
    )

    assert result.functionalStatus == "needs_attention"
    assert result.claimableOutcome == "none"
    assert result.assessment.exactContextVerified is False
    assert result.assessment.oracle is not None
    assert result.assessment.oracle.contextSource == "missing"
    assert any(
        item.code == "exact_execution_context" and item.status == "failed"
        for item in result.assessment.postconditions
    )
