from types import SimpleNamespace

import pytest

from src.agent.history import _workflow_preview_decisions_from_messages
from src.agent.tools.factory import (
    _request_workflow_run_approval,
    _take_workflow_preview_decision,
)


def test_structured_workflow_approval_is_reconstructed_without_prompt_text():
    messages = [
        {
            "role": "user",
            "content": "run_confirmation: Approve run",
            "attachments": [
                {
                    "type": "user_input_response",
                    "data": {
                        "requestId": "token-1",
                        "requestKind": "workflow_run_approval",
                        "workflowId": "wf-1",
                        "decision": "approve",
                    },
                }
            ],
        }
    ]

    approvals, cancellations = _workflow_preview_decisions_from_messages(messages)

    assert approvals == {"wf-1": "token-1"}
    assert cancellations == set()


def test_latest_cancel_removes_prior_approval():
    messages = [
        {
            "role": "user",
            "attachments": [
                {
                    "type": "user_input_response",
                    "data": {
                        "requestId": "token-1",
                        "requestKind": "workflow_run_approval",
                        "workflowId": "wf-1",
                        "decision": "approve",
                    },
                }
            ],
        },
        {
            "role": "user",
            "attachments": [
                {
                    "type": "user_input_response",
                    "data": {
                        "requestId": "token-1",
                        "requestKind": "workflow_run_approval",
                        "workflowId": "wf-1",
                        "decision": "cancel",
                    },
                }
            ],
        },
    ]

    approvals, cancellations = _workflow_preview_decisions_from_messages(messages)

    assert approvals == {}
    assert cancellations == {"wf-1"}


def test_old_approval_is_not_replayed_on_later_unrelated_turn():
    messages = [
        {
            "role": "user",
            "attachments": [
                {
                    "type": "user_input_response",
                    "data": {
                        "requestId": "token-1",
                        "requestKind": "workflow_run_approval",
                        "workflowId": "wf-1",
                        "decision": "approve",
                    },
                }
            ],
        },
        {"role": "assistant", "content": "The run completed."},
        {"role": "user", "content": "What happened in that run?"},
    ]

    approvals, cancellations = _workflow_preview_decisions_from_messages(messages)

    assert approvals == {}
    assert cancellations == set()


def test_structured_approval_wins_over_model_supplied_token_and_is_one_use():
    deps = SimpleNamespace(
        workflow_preview_approvals={"wf-1": "server-token"},
        workflow_preview_cancellations=set(),
    )

    token, cancelled = _take_workflow_preview_decision(deps, "wf-1", "invented-token")

    assert token == "server-token"
    assert cancelled is False
    assert deps.workflow_preview_approvals == {}


@pytest.mark.asyncio
async def test_approval_request_persists_opaque_id_in_attachment():
    attachments = []
    tool_calls = []

    async def emit_tool_call(tool):
        tool_calls.append(tool)

    async def emit_attachment(attachment):
        attachments.append(attachment.model_dump(exclude_none=True))

    deps = SimpleNamespace(
        emit_tool_call=emit_tool_call,
        emit_attachment=emit_attachment,
        awaiting_user_input=False,
    )
    ctx = SimpleNamespace(deps=deps)

    result = await _request_workflow_run_approval(
        ctx,
        workflow_id="wf-1",
        preview={
            "preview_token": "token-1",
            "eligible_count": 1,
            "action_count": 1,
            "writeback_count": 1,
            "actions": [{"target": "a***@example.com"}],
        },
    )

    assert tool_calls == ["request_user_input"]
    assert deps.awaiting_user_input is True
    assert result["status"] == "waiting_for_user"
    data = attachments[0]["data"]
    assert data["requestId"] == "token-1"
    assert data["requestKind"] == "workflow_run_approval"
    assert data["workflowId"] == "wf-1"
    assert [choice["value"] for choice in data["choices"]] == ["approve", "cancel"]
