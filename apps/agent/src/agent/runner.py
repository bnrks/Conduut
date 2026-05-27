"""Pydantic AI agent runner with the existing Conduut SSE contract."""

import asyncio
import json
from collections.abc import AsyncIterator

import structlog
from pydantic_ai import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    TextPart,
    UsageLimitExceeded,
    UsageLimits,
    UserPromptPart,
)
from pydantic_ai.exceptions import UnexpectedModelBehavior

from src import store
from src.agent.provider_factory import build_model, build_model_settings, classify_provider_error
from src.agent.schemas import AgentDeps, AgentEvent
from src.agent.tools import create_agent
from src.logging_config import bind_log_context, clear_log_context

log = structlog.get_logger()

MAX_MODEL_REQUESTS = 12
MAX_TOOL_CALLS = 32


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


def _history_from_store_messages(messages: list[dict]) -> tuple[str, list[ModelMessage]]:
    if not messages:
        return "", []

    user_prompt = _content_with_user_input_answer_context(
        messages[-1],
        _user_input_request_context(messages[-2]) if len(messages) > 1 else None,
    )
    prior_messages = messages[:-1]
    if not prior_messages:
        return user_prompt, []

    history: list[ModelMessage] = []
    pending_user_input_request: str | None = None

    for message in prior_messages:
        role = message.get("role")
        content = _content_with_attachment_context(message)
        if role == "user":
            content = _content_with_user_input_answer_context(
                message,
                pending_user_input_request,
            )
            pending_user_input_request = None
        if not content:
            continue
        if role == "user":
            history.append(ModelRequest(parts=[UserPromptPart(content=content)]))
        elif role in ("assistant", "agent"):
            history.append(ModelResponse(parts=[TextPart(content=content)]))
            pending_user_input_request = _user_input_request_context(message)

    return user_prompt, history


def _platform_resources_from_messages(messages: list[dict]) -> dict[str, dict[str, str]]:
    resources: dict[str, dict[str, str]] = {}
    for message in messages:
        attachments = message.get("attachments")
        if not isinstance(attachments, list):
            continue
        for attachment in attachments:
            if not isinstance(attachment, dict) or attachment.get("type") != "artifact_preview":
                continue
            data = attachment.get("data")
            if not isinstance(data, dict) or data.get("service") != "google_sheets":
                continue
            source = data.get("source") if isinstance(data.get("source"), dict) else {}
            spreadsheet_id = source.get("spreadsheetId")
            if not spreadsheet_id:
                continue
            resource = resources.setdefault("google_sheets", {})
            resource["spreadsheet_id"] = str(spreadsheet_id)
            if data.get("url"):
                resource["spreadsheet_url"] = str(data["url"])
            range_label = source.get("range")
            if range_label:
                resource["sheet_name"] = str(range_label).split("!", 1)[0].strip("'")
    return resources


def _user_input_request_context(message: dict | None) -> str | None:
    if not message or message.get("role") not in ("assistant", "agent"):
        return None
    attachments = message.get("attachments")
    if not isinstance(attachments, list):
        return None
    for attachment in attachments:
        if not isinstance(attachment, dict) or attachment.get("type") != "user_input_request":
            continue
        data = attachment.get("data")
        if not isinstance(data, dict):
            continue
        question = data.get("question")
        missing_fields = data.get("missingFields")
        return f"user_input_request question={question} missingFields={missing_fields}"
    return None


def _content_with_user_input_answer_context(
    message: dict,
    pending_request_context: str | None,
) -> str:
    content = str(message.get("content") or "")
    if not content or not pending_request_context:
        return content
    return (
        f"{content}\n\n"
        "[Conduut internal context: this user message answers the previous "
        f"{pending_request_context}. Treat this answer as accumulated task information and "
        "do not ask for the same missing field again unless the answer is ambiguous.]"
    )


def _content_with_attachment_context(message: dict) -> str:
    content = str(message.get("content") or "")
    attachments = message.get("attachments")
    if not isinstance(attachments, list):
        return content

    context_items: list[str] = []
    for attachment in attachments:
        if not isinstance(attachment, dict):
            continue
        data = attachment.get("data")
        if not isinstance(data, dict):
            continue
        attachment_type = attachment.get("type")
        if attachment_type == "workflow_preview":
            workflow_id = data.get("id")
            name = data.get("name")
            status = data.get("status")
            if workflow_id:
                context_items.append(
                    f"workflow_preview id={workflow_id} name={name} status={status}"
                )
        elif attachment_type == "workflow_run_result":
            workflow_id = data.get("workflowId")
            execution_id = data.get("executionId")
            status = data.get("status")
            if workflow_id:
                context_items.append(
                    "workflow_run "
                    f"workflowId={workflow_id} "
                    f"executionId={execution_id} "
                    f"status={status}"
                )
        elif attachment_type == "artifact_preview":
            title = data.get("title")
            service = data.get("service")
            source = data.get("source")
            if title:
                context_items.append(
                    f"artifact_preview service={service} title={title} source={source}"
                )
        elif attachment_type == "user_input_request":
            question = data.get("question")
            missing_fields = data.get("missingFields")
            if question:
                context_items.append(
                    f"user_input_request question={question} missingFields={missing_fields}"
                )

    if not context_items:
        return content

    return (
        f"{content}\n\n"
        "[Conduut internal context for future tool calls: " + "; ".join(context_items) + "]"
    )


def _event_to_sse(item: AgentEvent) -> str:
    event, data = item
    return _sse(event, data)


async def _persist_artifact_previews(
    user_id: str,
    attachments: list[dict],
    *,
    origin: dict,
) -> None:
    for attachment in attachments:
        if not isinstance(attachment, dict) or attachment.get("type") != "artifact_preview":
            continue
        data = attachment.get("data")
        if not isinstance(data, dict):
            continue
        try:
            await store.save_artifact(user_id, data, origin=origin)
        except Exception as exc:
            log.error(
                "artifact_persist_error",
                error_type=type(exc).__name__,
                error=str(exc),
                origin=origin,
                exc_info=True,
            )


async def _drain_events(queue: asyncio.Queue[AgentEvent]) -> AsyncIterator[str]:
    while not queue.empty():
        yield _event_to_sse(queue.get_nowait())


async def run(
    user_id: str,
    conv_id: str,
    messages: list[dict],
    settings: store.LLMSettings,
    *,
    request_id: str | None = None,
) -> AsyncIterator[str]:
    """Run the Conduut agent and stream events compatible with the existing frontend."""

    clear_log_context()
    bind_log_context(
        request_id=request_id,
        user_id=user_id,
        conversation_id=conv_id,
        provider=settings.provider,
        model=settings.model,
        reasoning_effort=settings.reasoning_effort,
    )
    log.info("agent_run_started", message_count=len(messages))
    event_queue: asyncio.Queue[AgentEvent] = asyncio.Queue()
    deps = AgentDeps(
        user_id=user_id,
        conversation_id=conv_id,
        event_queue=event_queue,
        platform_resources=_platform_resources_from_messages(messages),
    )
    user_prompt, message_history = _history_from_store_messages(messages)

    try:
        model = build_model(settings.provider, settings.model, settings.api_key)
        model_settings = build_model_settings(
            settings.provider, settings.model, settings.reasoning_effort
        )
    except Exception as exc:
        log.error(
            "agent_model_config_error",
            error_type=type(exc).__name__,
            error=str(exc),
        )
        yield _sse("error", {"code": "model_config", "message": classify_provider_error(exc)})
        clear_log_context()
        return

    agent = create_agent(model)

    async def _agent_run():
        return await agent.run(
            user_prompt,
            deps=deps,
            message_history=message_history,
            model_settings=model_settings,
            usage_limits=UsageLimits(
                request_limit=MAX_MODEL_REQUESTS,
                tool_calls_limit=MAX_TOOL_CALLS,
            ),
        )

    task = asyncio.create_task(_agent_run())

    while not task.done():
        try:
            item = await asyncio.wait_for(event_queue.get(), timeout=2.0)
            yield _event_to_sse(item)
        except asyncio.TimeoutError:
            yield ": keep-alive\n\n"

    async for pending_event in _drain_events(event_queue):
        yield pending_event

    try:
        result = task.result()
    except UsageLimitExceeded as exc:
        log.warning(
            "agent_usage_limit_exceeded",
            error=str(exc),
            attachment_count=len(deps.attachments),
        )
        yield _sse(
            "error",
            {
                "code": "max_rounds",
                "message": "Agent could not complete the task. Please try again.",
            },
        )
        clear_log_context()
        return
    except UnexpectedModelBehavior as exc:
        log.error(
            "agent_unexpected_model_behavior",
            error=str(exc),
            attachment_count=len(deps.attachments),
        )
        yield _sse(
            "error",
            {
                "code": "model_behavior",
                "message": "The model could not produce a valid response. Please try again.",
            },
        )
        clear_log_context()
        return
    except Exception as exc:
        log.error(
            "agent_run_error",
            error_type=type(exc).__name__,
            error=str(exc),
            attachment_count=len(deps.attachments),
            exc_info=True,
        )
        yield _sse("error", {"code": "unknown", "message": classify_provider_error(exc)})
        clear_log_context()
        return

    text = result.output or ""
    attachment_types = [
        str(attachment.get("type"))
        for attachment in deps.attachments
        if isinstance(attachment, dict)
    ]
    log.info(
        "agent_run_finished",
        output_chars=len(text),
        attachment_types=attachment_types,
    )
    full_content = ""
    chunk_size = 10
    for i in range(0, len(text), chunk_size):
        chunk = text[i : i + chunk_size]
        full_content += chunk
        yield _sse("token", {"text": chunk, "conversation_id": conv_id})

    assistant_saved = False
    try:
        await store.add_message(
            user_id,
            conv_id,
            "assistant",
            full_content,
            provider=settings.provider,
            model=settings.model,
            attachments=deps.attachments or None,
        )
        log.info("assistant_message_saved", content_length=len(full_content))
        assistant_saved = True
    except Exception as exc:
        log.error(
            "store_add_message_error",
            error_type=type(exc).__name__,
            error=str(exc),
            exc_info=True,
        )

    if assistant_saved and deps.attachments:
        await _persist_artifact_previews(
            user_id,
            deps.attachments,
            origin={"kind": "chat", "conversationId": conv_id},
        )

    yield _sse(
        "done",
        {
            "conversation_id": conv_id,
            "provider": settings.provider,
            "model": settings.model,
            "reasoning_effort": settings.reasoning_effort,
        },
    )
    clear_log_context()
