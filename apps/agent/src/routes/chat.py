from typing import Literal

import structlog
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict

from src import executions, n8n_client, store
from src.agent import runner
from src.auth import get_user_id

log = structlog.get_logger()
router = APIRouter()


class ExecutionReference(BaseModel):
    execution_id: str
    intent: Literal["diagnose_and_fix"] = "diagnose_and_fix"


class UserInputResponse(BaseModel):
    request_id: str
    request_kind: Literal["workflow_run_approval"]
    workflow_id: str
    decision: Literal["approve", "cancel"]


class ChatRequest(BaseModel):
    # Tolerate stale frontend fields (provider/model/reasoning_effort) without a 422.
    model_config = ConfigDict(extra="ignore")

    content: str
    conversation_id: str | None = None
    execution_policy: Literal["safe", "fast"] | None = None
    execution_reference: ExecutionReference | None = None
    user_input_response: UserInputResponse | None = None


@router.post("/chat/send")
async def chat_send(request: Request, body: ChatRequest):
    user_id = get_user_id(request)
    request_state = getattr(request, "state", None)
    request_headers = getattr(request, "headers", {})
    request_id = getattr(request_state, "request_id", None) or request_headers.get(
        "x-request-id", None
    )
    log.info(
        "chat_send_started",
        user_id=user_id,
        conversation_id=body.conversation_id,
        content_length=len(body.content),
    )

    attachments: list[dict] = []
    if body.execution_reference:
        try:
            run = await executions.get_run(user_id, body.execution_reference.execution_id)
        except executions.ExecutionNotFoundError as exc:
            raise HTTPException(status_code=404, detail={"message": "Run not found."}) from exc
        except n8n_client.N8nApiError as exc:
            raise HTTPException(
                status_code=exc.status_code,
                detail={"message": exc.message},
            ) from exc
        if run.status not in {"error", "failed", "crashed"}:
            raise HTTPException(
                status_code=409,
                detail={"message": "Only failed runs can be sent for repair."},
            )
        attachments.append(
            {
                "type": "execution_reference",
                "data": {
                    "executionId": run.id,
                    "workflowId": run.workflow_id,
                    "workflowName": run.workflow_name,
                    "status": run.status,
                    "intent": body.execution_reference.intent,
                },
            }
        )

    if body.user_input_response:
        response = body.user_input_response
        attachments.append(
            {
                "type": "user_input_response",
                "data": {
                    "requestId": response.request_id,
                    "requestKind": response.request_kind,
                    "workflowId": response.workflow_id,
                    "decision": response.decision,
                },
            }
        )

    requested_execution_policy = body.execution_policy
    conv = await store.get_or_create_conversation(
        user_id,
        body.conversation_id,
        execution_policy=requested_execution_policy or "safe",
    )
    if (
        requested_execution_policy is not None
        and requested_execution_policy != conv.execution_policy
        and conv.execution_policy_locked
    ):
        raise HTTPException(
            status_code=409,
            detail={
                "code": "execution_policy_locked",
                "message": ("This conversation is locked to the existing execution policy."),
                "execution_policy": conv.execution_policy,
            },
        )
    await store.add_message(
        user_id,
        conv.id,
        "user",
        body.content,
        attachments=attachments or None,
    )
    log.info("chat_conversation_ready", user_id=user_id, conversation_id=conv.id)

    msgs = await store.get_conversation_messages(user_id, conv.id)
    messages = [
        {
            "role": m.role if m.role != "agent" else "assistant",
            "content": m.content,
            "attachments": m.attachments,
        }
        for m in msgs
    ]

    return StreamingResponse(
        runner.run(
            user_id,
            conv.id,
            messages,
            request_id=request_id,
            execution_policy=conv.execution_policy,
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "X-Conversation-Id": conv.id,
            "X-Execution-Policy": conv.execution_policy,
            "X-Execution-Policy-Locked": str(conv.execution_policy_locked).lower(),
        },
    )
