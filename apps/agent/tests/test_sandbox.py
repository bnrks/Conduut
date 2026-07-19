"""Tests for the sandbox workflow test engine (agent.sandbox)."""

from types import SimpleNamespace

import pytest

import src.agent.sandbox as sandbox
import src.n8n_client as n8n_client
from src.agent.sandbox import (
    JudgeVerdict,
    _action_summaries,
    _build_test_clone,
    _check_empty_outputs,
    _evaluate_sandbox_run,
    _looks_like_placeholder_business_output,
    _sample_input_for_schema,
)
from src.agent.schemas import WorkflowInputField


def test_sample_input_is_type_aware():
    schema = [
        WorkflowInputField(name="to", label="To", type="email"),
        WorkflowInputField(name="subject", label="Subject", type="string"),
        WorkflowInputField(name="body", label="Body", type="textarea"),
    ]
    sample = _sample_input_for_schema(schema)
    assert sample["to"] == "test@example.com"
    assert isinstance(sample["subject"], str) and sample["subject"]
    assert isinstance(sample["body"], str) and sample["body"]


def test_sample_input_empty_schema():
    assert _sample_input_for_schema([]) == {}


def test_build_test_clone_from_webhook_assigns_fresh_path():
    workflow = {
        "id": "real-1",
        "name": "Demo",
        "nodes": [
            {
                "name": "Hook",
                "type": "n8n-nodes-base.webhook",
                "parameters": {"httpMethod": "GET", "path": "live-path"},
            }
        ],
        "connections": {},
    }
    clone = _build_test_clone(workflow)
    assert clone is not None
    nodes, _connections, path = clone
    assert path.startswith("conduut-test-")
    assert path != "live-path"  # never clash with the live webhook
    hook = nodes[0]["parameters"]
    assert hook["httpMethod"] == "POST"
    assert hook["responseMode"] == "lastNode"
    assert hook["path"] == path


def test_build_test_clone_uses_response_node_with_respond_to_webhook():
    # A Respond to Webhook node needs responseMode=responseNode; forcing lastNode
    # in the clone makes n8n reject the test run as "Unused Respond to Webhook".
    workflow = {
        "id": "real-3",
        "name": "Quote",
        "nodes": [
            {"name": "Hook", "type": "n8n-nodes-base.webhook", "parameters": {"path": "p"}},
            {"name": "Respond", "type": "n8n-nodes-base.respondToWebhook", "parameters": {}},
        ],
        "connections": {"Hook": {"main": [[{"node": "Respond", "type": "main", "index": 0}]]}},
    }
    clone = _build_test_clone(workflow)
    assert clone is not None
    nodes, _connections, _path = clone
    hook = next(n for n in nodes if n["name"] == "Hook")
    assert hook["parameters"]["responseMode"] == "responseNode"


def test_build_test_clone_converts_manual_trigger():
    workflow = {
        "id": "real-2",
        "name": "Demo",
        "nodes": [{"name": "Start", "type": "n8n-nodes-base.manualTrigger", "parameters": {}}],
        "connections": {},
    }
    clone = _build_test_clone(workflow)
    assert clone is not None
    nodes, _connections, path = clone
    assert nodes[0]["type"] == "n8n-nodes-base.webhook"
    assert nodes[0]["parameters"]["path"] == path


def test_build_test_clone_converts_schedule_trigger():
    workflow = {
        "id": "real-3",
        "name": "Demo",
        "nodes": [{"name": "Cron", "type": "n8n-nodes-base.scheduleTrigger", "parameters": {}}],
        "connections": {},
    }
    clone = _build_test_clone(workflow)
    assert clone is not None
    nodes, _connections, path = clone
    assert nodes[0]["type"] == "n8n-nodes-base.webhook"
    assert nodes[0]["parameters"]["path"] == path


def _detail_with_run_data(run_data):
    return {"data": {"resultData": {"runData": run_data}}}


def test_check_empty_outputs_flags_empty_upstream():
    clone = {
        "nodes": [
            {"name": "Build", "type": "n8n-nodes-base.code"},
            {"name": "Send", "type": "n8n-nodes-base.gmail"},
        ],
        "connections": {"Build": {"main": [[{"node": "Send", "type": "main", "index": 0}]]}},
    }
    detail = _detail_with_run_data({"Build": [{"data": {"main": [[{"json": {"text": ""}}]]}}]})
    findings = _check_empty_outputs(detail, clone, ["Send"])
    assert findings and "Send" in findings[0]


def test_check_empty_outputs_passes_with_real_data():
    clone = {
        "nodes": [
            {"name": "Build", "type": "n8n-nodes-base.code"},
            {"name": "Send", "type": "n8n-nodes-base.gmail"},
        ],
        "connections": {"Build": {"main": [[{"node": "Send", "type": "main", "index": 0}]]}},
    }
    detail = _detail_with_run_data({"Build": [{"data": {"main": [[{"json": {"text": "hello"}}]]}}]})
    assert _check_empty_outputs(detail, clone, ["Send"]) == []


def test_check_empty_outputs_ignores_nodes_without_upstream():
    clone = {"nodes": [{"name": "Send", "type": "n8n-nodes-base.gmail"}], "connections": {}}
    detail = _detail_with_run_data({})
    assert _check_empty_outputs(detail, clone, ["Send"]) == []


def test_action_summaries_collect_would_be_input():
    clone = {
        "nodes": [
            {"name": "Build", "type": "n8n-nodes-base.code"},
            {
                "name": "Send",
                "type": "n8n-nodes-base.gmail",
                "parameters": {"subject": "Hi", "message": "={{$json.text}}"},
            },
        ],
        "connections": {"Build": {"main": [[{"node": "Send", "type": "main", "index": 0}]]}},
    }
    detail = _detail_with_run_data({"Build": [{"data": {"main": [[{"json": {"text": "hello"}}]]}}]})
    summaries = _action_summaries(detail, clone, ["Send"])
    assert summaries[0]["name"] == "Send"
    assert summaries[0]["type"] == "n8n-nodes-base.gmail"
    assert summaries[0]["would_be_input"] == [{"text": "hello"}]


def test_placeholder_business_output_only_flags_null_like_fragments():
    assert _looks_like_placeholder_business_output("title undefined / no content available")
    assert not _looks_like_placeholder_business_output("Article title: Undefined Behavior in C")


def test_upstream_expression_detection_ignores_prose_but_flags_raw_expression():
    prose = "In n8n, use $json.name to reference the incoming field in your workflow."
    raw_expression = "$json.name"

    assert sandbox._strong_placeholder_fragments(prose) == []
    assert sandbox._strong_placeholder_fragments(raw_expression) == [raw_expression]


@pytest.mark.asyncio
async def test_run_judge_uses_llm(monkeypatch):
    async def fake_llm(prompt):
        assert "Automation purpose" in prompt
        return JudgeVerdict(ok=False, issue="body empty")

    monkeypatch.setattr(sandbox, "_run_judge_llm", fake_llm)
    verdict = await sandbox._run_judge("send email", [{"name": "Send"}])
    assert verdict.ok is False
    assert verdict.issue == "body empty"


def _success_detail():
    return {
        "id": "exec-1",
        "status": "success",
        "finished": True,
        "workflowId": "clone-1",
        "data": {
            "resultData": {
                "runData": {"Build": [{"data": {"main": [[{"json": {"text": "hello"}}]]}}]}
            }
        },
    }


def _wire_fake_n8n(monkeypatch, detail):
    created = {}

    async def fake_create(name, nodes, connections, settings=None):
        created["nodes"] = nodes
        return SimpleNamespace(id="clone-1", name=name, active=False)

    deleted = {"called": False}

    async def fake_delete(workflow_id):
        deleted["called"] = True

    async def fake_activate(workflow_id):
        return None

    async def fake_webhook(path, payload=None):
        return SimpleNamespace(status_code=200)

    async def fake_list(workflow_id=None, limit=10):
        return [SimpleNamespace(id="exec-1")]

    async def fake_get_detail(execution_id):
        return detail

    monkeypatch.setattr(n8n_client, "create_workflow", fake_create)
    monkeypatch.setattr(n8n_client, "delete_workflow", fake_delete)
    monkeypatch.setattr(n8n_client, "activate_workflow", fake_activate)
    monkeypatch.setattr(n8n_client, "call_webhook", fake_webhook)
    monkeypatch.setattr(n8n_client, "list_executions", fake_list)
    monkeypatch.setattr(n8n_client, "get_execution_detail", fake_get_detail)
    return created, deleted


_DEMO_WORKFLOW = {
    "id": "real-1",
    "name": "Demo",
    "nodes": [
        {"name": "Hook", "type": "n8n-nodes-base.webhook", "parameters": {"path": "p"}},
        {"name": "Build", "type": "n8n-nodes-base.code", "parameters": {}},
        {"name": "Send", "type": "n8n-nodes-base.gmail", "parameters": {"operation": "send"}},
    ],
    "connections": {
        "Hook": {"main": [[{"node": "Build", "type": "main", "index": 0}]]},
        "Build": {"main": [[{"node": "Send", "type": "main", "index": 0}]]},
    },
}


@pytest.mark.asyncio
async def test_run_sandbox_test_passes_and_deletes_clone(monkeypatch):
    created, deleted = _wire_fake_n8n(monkeypatch, _success_detail())

    async def fake_judge(intent, summaries):
        return JudgeVerdict(ok=True)

    monkeypatch.setattr(sandbox, "_run_judge", fake_judge)
    result = await sandbox.run_sandbox_test(
        _DEMO_WORKFLOW, user_id="u1", input_schema=[], intent="Demo"
    )
    assert result.passed is True
    assert deleted["called"] is True
    # The action node is replaced by an expression-aware, side-effect-free probe.
    send = next(n for n in created["nodes"] if n["name"] == "Send")
    assert send["type"] == "n8n-nodes-base.set"
    assert "credentials" not in send
    assigned = send["parameters"]["assignments"]["assignments"]
    assert {item["name"] for item in assigned} >= {
        "id",
        "threadId",
        "labelIds",
        "__conduut_probe",
    }


@pytest.mark.asyncio
async def test_run_sandbox_test_flags_execution_error(monkeypatch):
    detail = {
        "id": "exec-2",
        "status": "error",
        "workflowId": "clone-1",
        "data": {"resultData": {"error": {"message": "Boom", "node": {"name": "Build"}}}},
    }
    _wire_fake_n8n(monkeypatch, detail)
    result = await sandbox.run_sandbox_test(
        _DEMO_WORKFLOW, user_id="u1", input_schema=[], intent="Demo"
    )
    assert result.passed is False
    assert result.failed_node == "Build"


@pytest.mark.asyncio
async def test_run_sandbox_test_passes_return_only_workflow_without_judge(monkeypatch):
    # A fetch-and-return workflow has no side-effect action node to neutralize, so
    # the action judge has nothing to assess and would falsely fail it ("No action
    # steps configured"). It must pass on a successful run and skip the judge.
    workflow = {
        "id": "real-2",
        "name": "Quote",
        "nodes": [
            {"name": "Hook", "type": "n8n-nodes-base.webhook", "parameters": {"path": "p"}},
            {
                "name": "Fetch",
                "type": "n8n-nodes-base.httpRequest",
                "parameters": {"method": "GET", "url": "https://e.com"},
            },
            {"name": "Respond", "type": "n8n-nodes-base.respondToWebhook", "parameters": {}},
        ],
        "connections": {
            "Hook": {"main": [[{"node": "Fetch", "type": "main", "index": 0}]]},
            "Fetch": {"main": [[{"node": "Respond", "type": "main", "index": 0}]]},
        },
    }
    _wire_fake_n8n(monkeypatch, _success_detail())
    judge_called = {"called": False}

    async def fake_judge(intent, summaries):
        judge_called["called"] = True
        return JudgeVerdict(ok=False, issue="No action steps configured")

    monkeypatch.setattr(sandbox, "_run_judge", fake_judge)
    result = await sandbox.run_sandbox_test(
        workflow, user_id="u1", input_schema=[], intent="Fetch a quote and return it"
    )
    assert result.passed is True
    assert judge_called["called"] is False


@pytest.mark.asyncio
async def test_run_sandbox_test_drives_schedule_clone(monkeypatch):
    workflow = {
        "id": "real-9",
        "name": "Cron",
        "nodes": [{"name": "Cron", "type": "n8n-nodes-base.scheduleTrigger", "parameters": {}}],
        "connections": {},
    }
    _wire_fake_n8n(monkeypatch, _success_detail())
    result = await sandbox.run_sandbox_test(workflow, user_id="u1", input_schema=[], intent="Cron")
    assert result.passed is True
    assert result.status == "passed"


@pytest.mark.asyncio
async def test_evaluate_sandbox_run_blocks_placeholder_business_output(monkeypatch):
    detail = {
        "id": "exec-3",
        "status": "success",
        "finished": True,
        "workflowId": "clone-1",
        "data": {
            "resultData": {
                "runData": {
                    "Build": [
                        {
                            "data": {
                                "main": [[{"json": {"title": "undefined", "summary": "missing"}}]]
                            }
                        }
                    ],
                    "Send": [
                        {
                            "data": {
                                "main": [
                                    [
                                        {
                                            "json": {
                                                "__conduut_probe": "gmail_send",
                                                "__conduut_probe_target": "person@example.com",
                                                "__conduut_probe_subject": "title undefined",
                                                "__conduut_probe_message": "no content available",
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
    }
    clone_workflow = {
        "nodes": [
            {"name": "Build", "type": "n8n-nodes-base.code", "parameters": {}},
            {"name": "Send", "type": "n8n-nodes-base.gmail", "parameters": {"operation": "send"}},
        ],
        "connections": {"Build": {"main": [[{"node": "Send", "type": "main", "index": 0}]]}},
    }
    probes = [
        sandbox.ActionProbe(
            name="Send",
            kind="gmail_send",
            covered=True,
            original_type="n8n-nodes-base.gmail",
        )
    ]
    judge_called = {"called": False}

    async def fake_judge(_intent, _records):
        judge_called["called"] = True
        return JudgeVerdict(ok=True)

    monkeypatch.setattr(sandbox, "_run_judge", fake_judge)
    result = await _evaluate_sandbox_run(detail, clone_workflow, probes, "Send digest")

    assert result.passed is False
    assert result.status == "needs_attention"
    assert any("placeholder-like message content" in finding for finding in result.findings)
    assert judge_called["called"] is False


@pytest.mark.asyncio
async def test_evaluate_sandbox_run_blocks_multi_hop_upstream_placeholder_content(monkeypatch):
    detail = {
        "id": "exec-3b",
        "status": "success",
        "finished": True,
        "workflowId": "clone-1",
        "data": {
            "resultData": {
                "runData": {
                    "Build Digest": [
                        {
                            "data": {
                                "main": [
                                    [
                                        {
                                            "json": {
                                                "digest": (
                                                    "1. undefined\n"
                                                    "URL: undefined\n"
                                                    "Summary: no content available"
                                                )
                                            }
                                        }
                                    ]
                                ]
                            }
                        }
                    ],
                    "Polish Copy": [
                        {
                            "data": {
                                "main": [
                                    [
                                        {
                                            "json": {
                                                "message": (
                                                    "I could not find any usable news today, "
                                                    "so there is nothing to send right now."
                                                )
                                            }
                                        }
                                    ]
                                ]
                            }
                        }
                    ],
                    "Send": [
                        {
                            "data": {
                                "main": [
                                    [
                                        {
                                            "json": {
                                                "__conduut_probe": "gmail_send",
                                                "__conduut_probe_target": "person@example.com",
                                                "__conduut_probe_subject": "Daily digest",
                                                "__conduut_probe_message": (
                                                    "I could not find any usable news today, "
                                                    "so there is nothing to send right now."
                                                ),
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
    }
    clone_workflow = {
        "nodes": [
            {"name": "Build Digest", "type": "n8n-nodes-base.code", "parameters": {}},
            {
                "name": "Polish Copy",
                "type": "@n8n/n8n-nodes-langchain.agent",
                "parameters": {},
            },
            {"name": "Send", "type": "n8n-nodes-base.gmail", "parameters": {"operation": "send"}},
        ],
        "connections": {
            "Build Digest": {"main": [[{"node": "Polish Copy", "type": "main", "index": 0}]]},
            "Polish Copy": {"main": [[{"node": "Send", "type": "main", "index": 0}]]},
        },
    }
    probes = [
        sandbox.ActionProbe(
            name="Send",
            kind="gmail_send",
            covered=True,
            original_type="n8n-nodes-base.gmail",
        )
    ]
    judge_called = {"called": False}

    async def fake_judge(_intent, _records):
        judge_called["called"] = True
        return JudgeVerdict(ok=True)

    monkeypatch.setattr(sandbox, "_run_judge", fake_judge)
    result = await _evaluate_sandbox_run(detail, clone_workflow, probes, "Send digest")

    assert result.passed is False
    assert result.status == "needs_attention"
    assert any(
        "upstream placeholder or unresolved content" in finding for finding in result.findings
    )
    assert any("Build Digest" in finding for finding in result.findings)
    assert judge_called["called"] is False


@pytest.mark.asyncio
async def test_evaluate_sandbox_run_allows_real_business_output(monkeypatch):
    detail = {
        "id": "exec-4",
        "status": "success",
        "finished": True,
        "workflowId": "clone-1",
        "data": {
            "resultData": {
                "runData": {
                    "Build": [
                        {
                            "data": {
                                "main": [
                                    [
                                        {
                                            "json": {
                                                "title": "Quarterly results",
                                                "summary": "Revenue grew 12% year over year.",
                                            }
                                        }
                                    ]
                                ]
                            }
                        }
                    ],
                    "Send": [
                        {
                            "data": {
                                "main": [
                                    [
                                        {
                                            "json": {
                                                "__conduut_probe": "gmail_send",
                                                "__conduut_probe_target": "person@example.com",
                                                "__conduut_probe_subject": "Daily digest",
                                                "__conduut_probe_message": (
                                                    "Title: Quarterly results\n"
                                                    "Summary: Revenue grew 12% year over year."
                                                ),
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
    }
    clone_workflow = {
        "nodes": [
            {"name": "Build", "type": "n8n-nodes-base.code", "parameters": {}},
            {"name": "Send", "type": "n8n-nodes-base.gmail", "parameters": {"operation": "send"}},
        ],
        "connections": {"Build": {"main": [[{"node": "Send", "type": "main", "index": 0}]]}},
    }
    probes = [
        sandbox.ActionProbe(
            name="Send",
            kind="gmail_send",
            covered=True,
            original_type="n8n-nodes-base.gmail",
        )
    ]
    judge_called = {"called": False}

    async def fake_judge(_intent, _records):
        judge_called["called"] = True
        return JudgeVerdict(ok=True)

    monkeypatch.setattr(sandbox, "_run_judge", fake_judge)
    result = await _evaluate_sandbox_run(detail, clone_workflow, probes, "Send digest")

    assert result.passed is True
    assert result.status == "passed"
    assert result.action_count == 1
    assert judge_called["called"] is True


def test_sheets_append_probe_records_a_nonempty_row():
    probes = [
        sandbox.ActionProbe(
            name="Append",
            kind="sheets_append",
            covered=True,
            original_type="n8n-nodes-base.googleSheets",
        )
    ]
    detail = {
        "data": {
            "resultData": {
                "runData": {
                    "Append": [
                        {
                            "data": {
                                "main": [
                                    [
                                        {
                                            "json": {
                                                "device": "sensor-1",
                                                "temperature": "22.5",
                                                "__conduut_probe": "sheets_append",
                                                "__conduut_probe_columns": (
                                                    '["device", "temperature"]'
                                                ),
                                            }
                                        }
                                    ]
                                ]
                            }
                        }
                    ]
                }
            }
        }
    }

    records = sandbox._probe_records(detail, probes)

    assert records == [
        {
            "node": "Append",
            "covered": True,
            "kind": "sheets_append",
            "columns": ["device", "temperature"],
            "values": {"device": "sensor-1", "temperature": "22.5"},
        }
    ]
    assert sandbox._probe_findings(records, probes) == []
    assert sandbox._preview_actions(records) == [
        {
            "kind": "sheets_append",
            "node": "Append",
            "columns": ["device", "temperature"],
        }
    ]


def test_identity_preflight_checks_full_upstream_read_dataset():
    probes = [
        sandbox.ActionProbe(
            name="Update Status",
            kind="sheets_update",
            covered=True,
            original_type="n8n-nodes-base.googleSheets",
        )
    ]
    records = [
        {
            "node": "Update Status",
            "kind": "sheets_update",
            "matching_columns": ["email"],
            "matching_values": {"email": "masked@example.com"},
        }
    ]
    detail = {
        "data": {
            "resultData": {
                "runData": {
                    "Read Sheet": [
                        {
                            "data": {
                                "main": [
                                    [
                                        {"json": {"email": "duplicate@example.com"}},
                                        {"json": {"email": "duplicate@example.com"}},
                                    ]
                                ]
                            }
                        }
                    ]
                }
            }
        }
    }
    workflow = {
        "nodes": [
            {
                "name": "Read Sheet",
                "type": "n8n-nodes-base.googleSheets",
                "parameters": {"operation": "read"},
            },
            {
                "name": "Update Status",
                "type": "n8n-nodes-base.set",
                "parameters": {},
            },
        ],
        "connections": {
            "Read Sheet": {"main": [[{"node": "Update Status", "type": "main", "index": 0}]]}
        },
    }

    findings = sandbox._identity_preflight_findings(detail, workflow, records, probes)

    assert len(findings) == 1
    assert "not assumed unique" in findings[0]
