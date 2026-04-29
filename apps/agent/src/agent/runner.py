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
from src.agent.provider_factory import build_model, classify_provider_error
from src.agent.schemas import AgentDeps, AgentEvent
from src.agent.tools import create_agent

log = structlog.get_logger()

MAX_MODEL_REQUESTS = 8
MAX_TOOL_CALLS = 24


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


def _history_from_store_messages(messages: list[dict]) -> tuple[str, list[ModelMessage]]:
    if not messages:
        return "", []

    user_prompt = str(messages[-1].get("content") or "")
    prior_messages = messages[:-1]
    if not prior_messages:
        return user_prompt, []

    history: list[ModelMessage] = []

    for message in prior_messages:
        content = str(message.get("content") or "")
        if not content:
            continue
        role = message.get("role")
        if role == "user":
            history.append(ModelRequest(parts=[UserPromptPart(content=content)]))
        elif role in ("assistant", "agent"):
            history.append(ModelResponse(parts=[TextPart(content=content)]))

    return user_prompt, history


def _event_to_sse(item: AgentEvent) -> str:
    event, data = item
    return _sse(event, data)


async def _drain_events(queue: asyncio.Queue[AgentEvent]) -> AsyncIterator[str]:
    while not queue.empty():
        yield _event_to_sse(queue.get_nowait())


async def run(
    user_id: str,
    conv_id: str,
    messages: list[dict],
    settings: store.LLMSettings,
) -> AsyncIterator[str]:
    """Run the Conduut agent and stream events compatible with the existing frontend."""

    event_queue: asyncio.Queue[AgentEvent] = asyncio.Queue()
    deps = AgentDeps(user_id=user_id, conversation_id=conv_id, event_queue=event_queue)
    user_prompt, message_history = _history_from_store_messages(messages)

    try:
        model = build_model(settings.provider, settings.model, settings.api_key)
    except Exception as exc:
        yield _sse("error", {"code": "model_config", "message": classify_provider_error(exc)})
        return

    agent = create_agent(model)

    async def _agent_run():
        return await agent.run(
            user_prompt,
            deps=deps,
            message_history=message_history,
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
    except UsageLimitExceeded:
        yield _sse(
            "error",
            {
                "code": "max_rounds",
                "message": "Agent could not complete the task. Please try again.",
            },
        )
        return
    except UnexpectedModelBehavior as exc:
        log.error("agent_unexpected_model_behavior", error=str(exc))
        yield _sse(
            "error",
            {
                "code": "model_behavior",
                "message": "The model could not produce a valid response. Please try again.",
            },
        )
        return
    except Exception as exc:
        log.error("agent_run_error", error=str(exc))
        yield _sse("error", {"code": "unknown", "message": classify_provider_error(exc)})
        return

    text = result.output or ""
    full_content = ""
    chunk_size = 10
    for i in range(0, len(text), chunk_size):
        chunk = text[i : i + chunk_size]
        full_content += chunk
        yield _sse("token", {"text": chunk, "conversation_id": conv_id})

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
    except Exception as exc:
        log.error("store_add_message_error", error=str(exc))

    yield _sse(
        "done",
        {
            "conversation_id": conv_id,
            "provider": settings.provider,
            "model": settings.model,
        },
    )
