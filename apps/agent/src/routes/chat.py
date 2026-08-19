import re
from typing import Literal

import structlog
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict

from src import executions, n8n_client, store
from src.agent import runner
from src.auth import get_user_id
from src.n8n_provider import N8nClientFactory, N8nInstanceResolver, N8nProviderError

log = structlog.get_logger()
router = APIRouter()
resolver = N8nInstanceResolver()
client_factory = N8nClientFactory()


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
    intent: Literal["automation-server-setup"] | None = None
    execution_policy: Literal["safe", "fast"] | None = None
    execution_reference: ExecutionReference | None = None
    user_input_response: UserInputResponse | None = None


_SETUP_SECRET_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "private_key",
        re.compile(r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----", re.IGNORECASE),
    ),
    (
        "n8n_encryption_key",
        re.compile(r"(?im)\bN8N_ENCRYPTION_KEY\b\s*[:=]\s*\S+"),
    ),
    (
        "password_assignment",
        re.compile(r"(?im)\b(password|passwd|passphrase)\b\s*[:=]\s*\S+"),
    ),
    (
        "api_key_assignment",
        re.compile(r"(?im)\b(api[_-]?key|x-api-key)\b\s*[:=]\s*\S+"),
    ),
    (
        "token_assignment",
        re.compile(r"(?im)\b(token|access[_-]?token|refresh[_-]?token)\b\s*[:=]\s*\S+"),
    ),
    (
        "bearer_header",
        re.compile(r"(?im)\b(authorization)\b\s*:\s*bearer\s+\S+"),
    ),
)


def _requested_conversation_mode(
    body: ChatRequest,
) -> Literal["default", "automation-server-setup"]:
    return "automation-server-setup" if body.intent == "automation-server-setup" else "default"


def _detect_setup_secret(content: str) -> str | None:
    for name, pattern in _SETUP_SECRET_PATTERNS:
        if pattern.search(content):
            return name
    return None


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

    existing_conversation = (
        await store.get_conversation(user_id, body.conversation_id)
        if body.conversation_id
        else None
    )
    conversation_mode = (
        existing_conversation.conversation_mode
        if existing_conversation is not None
        else _requested_conversation_mode(body)
    )
    setup_stage_reply_available = bool(
        existing_conversation is not None
        and existing_conversation.conversation_mode == "automation-server-setup"
        and existing_conversation.setup_stage_locked
    )
    if (
        existing_conversation is not None
        and body.intent is not None
        and conversation_mode != _requested_conversation_mode(body)
    ):
        raise HTTPException(
            status_code=409,
            detail={
                "code": "conversation_mode_locked",
                "message": "This conversation is locked to the existing mode.",
                "conversation_mode": conversation_mode,
            },
        )

    if conversation_mode == "automation-server-setup":
        secret_kind = _detect_setup_secret(body.content)
        if secret_kind is not None:
            raise HTTPException(
                status_code=422,
                detail={
                    "code": "setup_secret_not_allowed",
                    "message": (
                        "Secrets are not accepted in automation-server setup chat. "
                        "Rotate the secret if needed and continue without pasting it here."
                    ),
                    "secret_kind": secret_kind,
                },
            )

    resolved_n8n_context = None
    resolved_n8n = None
    resolved_n8n_error: Exception | None = None
    if conversation_mode != "automation-server-setup":
        try:
            resolved_n8n_context = await resolver.resolve(user_id, request_id=request_id)
            resolved_n8n = await client_factory.for_request_context(resolved_n8n_context)
        except N8nProviderError as exc:
            resolved_n8n_error = exc

    attachments: list[dict] = []
    if body.execution_reference:
        try:
            if resolved_n8n is None:
                raise HTTPException(
                    status_code=getattr(resolved_n8n_error, "status_code", 404),
                    detail={
                        "message": str(resolved_n8n_error or "No active n8n instance is connected.")
                    },
                )
            run = await executions.get_run(
                user_id,
                body.execution_reference.execution_id,
                n8n=resolved_n8n,
            )
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
        conversation_mode=conversation_mode,
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
    if body.intent is not None and conv.conversation_mode != _requested_conversation_mode(body):
        raise HTTPException(
            status_code=409,
            detail={
                "code": "conversation_mode_locked",
                "message": "This conversation is locked to the existing mode.",
                "conversation_mode": conv.conversation_mode,
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
            conversation_mode=conv.conversation_mode,
            setup_stage_reply_available=setup_stage_reply_available,
            n8n_context=resolved_n8n_context,
            n8n=resolved_n8n,
            n8n_error=resolved_n8n_error,
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "X-Conversation-Id": conv.id,
            "X-Execution-Policy": conv.execution_policy,
            "X-Execution-Policy-Locked": str(conv.execution_policy_locked).lower(),
            "X-Conversation-Mode": conv.conversation_mode,
        },
    )
