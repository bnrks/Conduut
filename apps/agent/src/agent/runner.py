"""Pydantic AI agent runner with the existing Conduut SSE contract."""

import asyncio
import json
from collections.abc import AsyncIterator

import structlog
from pydantic_ai import (
    Agent,
    ModelMessage,
    TextPart,
    UsageLimitExceeded,
    UsageLimits,
)
from pydantic_ai.exceptions import UnexpectedModelBehavior
from pydantic_ai.messages import (
    PartDeltaEvent,
    PartStartEvent,
    TextPartDelta,
    ThinkingPart,
    ThinkingPartDelta,
)

from src import store
from src.agent.history import (
    _conversation_workflows_from_messages,
    _history_from_store_messages,
    _platform_resources_from_messages,
    strip_internal_context,
)
from src.agent.model_registry import resolve
from src.agent.platform_state import gather_user_state
from src.agent.provider_factory import build_model, build_model_settings, classify_provider_error
from src.agent.reliability_guard import (
    CONDUUT_TOOL_NAMES,
    MAX_ATTEMPTS,
    REPLAY_CHUNK,
    REPLAY_DELAY,
    RUNAWAY_CHARS,
    looks_like_garbage,
)
from src.agent.router import classify_tier
from src.agent.schemas import AgentDeps, AgentEvent
from src.agent.step_assembler import StepAssembler, build_steps
from src.agent.tools import create_agent
from src.config import key_for_provider, settings
from src.logging_config import bind_log_context, clear_log_context

log = structlog.get_logger()


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


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


async def _emit_stream_event(
    event: object,
    event_queue: asyncio.Queue[AgentEvent],
    conv_id: str,
    text_chunks: list[str],
) -> None:
    """Pydantic AI model-stream event'ini SSE event'ine çevirip queue'ya koyar.

    Görünür metin -> 'token' (persist için text_chunks'a da eklenir).
    Düşünce       -> 'thinking' (ephemeral; kaydedilmez, text_chunks'a girmez).
    `PartStartEvent` parçanın ilk içeriğini, `PartDeltaEvent` sonraki delta'ları taşır.
    """
    if isinstance(event, PartStartEvent):
        part = event.part
        if isinstance(part, TextPart) and part.content:
            text_chunks.append(part.content)
            await event_queue.put(("token", {"text": part.content, "conversation_id": conv_id}))
        elif isinstance(part, ThinkingPart) and part.content:
            await event_queue.put(("thinking", {"text": part.content, "conversation_id": conv_id}))
    elif isinstance(event, PartDeltaEvent):
        delta = event.delta
        if isinstance(delta, TextPartDelta) and delta.content_delta:
            text_chunks.append(delta.content_delta)
            await event_queue.put(
                ("token", {"text": delta.content_delta, "conversation_id": conv_id})
            )
        elif isinstance(delta, ThinkingPartDelta) and delta.content_delta:
            await event_queue.put(
                ("thinking", {"text": delta.content_delta, "conversation_id": conv_id})
            )


async def run(
    user_id: str,
    conv_id: str,
    messages: list[dict],
    *,
    request_id: str | None = None,
) -> AsyncIterator[str]:
    """Run the Conduut agent and stream events compatible with the existing frontend."""

    clear_log_context()
    bind_log_context(request_id=request_id, user_id=user_id, conversation_id=conv_id)
    log.info("agent_run_started", message_count=len(messages))
    platform_resources = _platform_resources_from_messages(messages)
    conversation_workflows = _conversation_workflows_from_messages(messages)
    user_prompt, message_history = _history_from_store_messages(messages)

    tier, platform_state = await asyncio.gather(
        classify_tier(user_prompt, message_history),
        gather_user_state(user_id),
    )
    choice = resolve(tier)
    bind_log_context(
        tier=tier.value,
        provider=choice.provider,
        model=choice.model,
        profile=settings.model_profile,
    )
    log.info("agent_tier_selected", tier=tier.value, provider=choice.provider, model=choice.model)

    try:
        model = build_model(choice.provider, choice.model, key_for_provider(choice.provider))
        model_settings = build_model_settings(choice.provider, choice.thinking)
    except Exception as exc:
        log.error(
            "agent_model_config_error",
            error_type=type(exc).__name__,
            error=str(exc),
        )
        yield _sse("error", {"code": "model_config", "message": classify_provider_error(exc)})
        clear_log_context()
        return

    def make_deps() -> AgentDeps:
        return AgentDeps(
            user_id=user_id,
            conversation_id=conv_id,
            event_queue=asyncio.Queue(),
            platform_resources=platform_resources,
            conversation_workflows=conversation_workflows,
            platform_state=platform_state,
        )

    if settings.enable_reliability_guard and choice.provider == "deepseek":
        stream = _run_buffered_with_retry(
            choice=choice,
            tier=tier,
            model=model,
            model_settings=model_settings,
            make_deps=make_deps,
            user_prompt=user_prompt,
            message_history=message_history,
            user_id=user_id,
            conv_id=conv_id,
        )
    else:
        stream = _run_live(
            choice=choice,
            tier=tier,
            model=model,
            model_settings=model_settings,
            deps=make_deps(),
            user_prompt=user_prompt,
            message_history=message_history,
            user_id=user_id,
            conv_id=conv_id,
        )
    async for sse in stream:
        yield sse


async def _run_live(
    *,
    choice,
    tier,
    model,
    model_settings,
    deps: AgentDeps,
    user_prompt: str,
    message_history: list[ModelMessage],
    user_id: str,
    conv_id: str,
) -> AsyncIterator[str]:
    """Stream a single agent run live to the client (non-DeepSeek path)."""

    event_queue = deps.event_queue
    agent = create_agent(model)

    # Akan görünür metni persist için biriktir (düşünce kaydedilmez).
    text_chunks: list[str] = []

    async def _agent_stream():
        # agent.iter() graph'ı node-node sürer; model-request node'larında cevabı
        # gerçek zamanlı akıtırız. token/thinking event'leri tool'ların kullandığı
        # AYNI event_queue'ya gider -> sıralama, keep-alive ve drain korunur.
        async with agent.iter(
            user_prompt,
            deps=deps,
            message_history=message_history,
            model_settings=model_settings,
            usage_limits=UsageLimits(
                request_limit=choice.request_limit,
                tool_calls_limit=choice.tool_calls_limit,
            ),
        ) as agent_run:
            async for node in agent_run:
                if Agent.is_model_request_node(node):
                    async with node.stream(agent_run.ctx) as request_stream:
                        async for event in request_stream:
                            await _emit_stream_event(event, event_queue, conv_id, text_chunks)
            return agent_run.result

    assembler = StepAssembler()
    task = asyncio.create_task(_agent_stream())

    while not task.done():
        try:
            item = await asyncio.wait_for(event_queue.get(), timeout=2.0)
            assembler.add(item[0], item[1])
            yield _event_to_sse(item)
        except asyncio.TimeoutError:
            yield ": keep-alive\n\n"

    while not event_queue.empty():
        item = event_queue.get_nowait()
        assembler.add(item[0], item[1])
        yield _event_to_sse(item)

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

    # Görünür metin run sırasında queue üzerinden zaten token-token akıtıldı;
    # burada tekrar GÖNDERME. Sadece persist için biriktirilen metni kullan.
    full_content = "".join(text_chunks) or (result.output or "")
    try:
        usage = result.usage()
    except Exception:
        usage = None
    async for sse in _persist_and_done(
        deps, full_content, choice, tier, user_id, conv_id, usage=usage, steps=assembler.steps()
    ):
        yield sse


async def _persist_and_done(
    deps: AgentDeps,
    full_content: str,
    choice,
    tier,
    user_id: str,
    conv_id: str,
    *,
    usage=None,
    steps: list[dict] | None = None,
) -> AsyncIterator[str]:
    """Log usage, persist the assistant message + artifacts, emit the done event."""

    # The model occasionally echoes the "[Conduut internal context ...]" history
    # scaffolding into its reply; strip it from everything the user sees/reloads.
    full_content = strip_internal_context(full_content)

    attachment_types = [str(a.get("type")) for a in deps.attachments if isinstance(a, dict)]
    # Per-run token usage for cost analysis (bake-off). Field names avoid the
    # substring "token": the log redactor treats any key containing "token" as a
    # secret (see logging_config._SECRET_KEY_PARTS). Guarded — never break a run.
    usage_fields: dict[str, int] = {}
    if usage is not None:
        try:
            usage_fields = {
                "tok_in": int(usage.input_tokens or 0),
                "tok_out": int(usage.output_tokens or 0),
                "tok_cache_read": int(usage.cache_read_tokens or 0),
                "tok_cache_write": int(usage.cache_write_tokens or 0),
                "model_requests": int(usage.requests or 0),
                "usage_tool_calls": int(usage.tool_calls or 0),
            }
        except Exception as exc:
            log.warning("agent_usage_unavailable", error=str(exc), error_type=type(exc).__name__)
    log.info(
        "agent_run_finished",
        output_chars=len(full_content),
        attachment_types=attachment_types,
        **usage_fields,
    )

    persist_steps = steps if steps and len(steps) > 1 else None
    if persist_steps:
        persist_steps = [
            {**step, "text": strip_internal_context(step.get("text", ""))}
            if step.get("kind") == "text"
            else step
            for step in persist_steps
        ]
    assistant_saved = False
    try:
        await store.add_message(
            user_id,
            conv_id,
            "assistant",
            full_content,
            provider=choice.provider,
            model=choice.model,
            tier=tier.value,
            attachments=deps.attachments or None,
            steps=persist_steps,
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
            "provider": choice.provider,
            "model": choice.model,
            "tier": tier.value,
        },
    )
    clear_log_context()


# --- DeepSeek reliability guard (#1244): buffer + retry + replay ------------


async def _collect_attempt(
    *,
    choice,
    model,
    model_settings,
    deps: AgentDeps,
    user_prompt: str,
    message_history: list[ModelMessage],
) -> AsyncIterator:
    """Run one agent attempt, buffering every event instead of streaming it.

    Yields keep-alive pings (str) while the attempt runs so the connection stays
    open, then yields one final ``(buffer, full_content, error_code, usage)`` tuple.
    ``error_code`` is ``None`` on a normal finish, else "runaway"/"model_error"/
    "provider_error".
    """

    queue = deps.event_queue
    agent = create_agent(model)
    text_chunks: list[str] = []
    buffer: list[AgentEvent] = []

    async def _stream():
        async with agent.iter(
            user_prompt,
            deps=deps,
            message_history=message_history,
            model_settings=model_settings,
            usage_limits=UsageLimits(
                request_limit=choice.request_limit,
                tool_calls_limit=choice.tool_calls_limit,
            ),
        ) as agent_run:
            async for node in agent_run:
                if Agent.is_model_request_node(node):
                    async with node.stream(agent_run.ctx) as request_stream:
                        async for event in request_stream:
                            await _emit_stream_event(
                                event, queue, deps.conversation_id, text_chunks
                            )
            return agent_run.result

    task = asyncio.create_task(_stream())
    runaway = False
    while not task.done():
        try:
            item = await asyncio.wait_for(queue.get(), timeout=2.0)
            buffer.append(item)
            if sum(len(chunk) for chunk in text_chunks) > RUNAWAY_CHARS:
                runaway = True
                task.cancel()
                break
        except asyncio.TimeoutError:
            yield ": keep-alive\n\n"
    while not queue.empty():
        buffer.append(queue.get_nowait())

    full_content = "".join(text_chunks)
    if runaway:
        try:
            await task
        except (asyncio.CancelledError, Exception):
            pass
        yield (buffer, full_content, "runaway", None)
        return
    try:
        result = task.result()
    except (UsageLimitExceeded, UnexpectedModelBehavior):
        yield (buffer, full_content, "model_error", None)
        return
    except Exception as exc:
        log.error(
            "agent_run_error",
            error_type=type(exc).__name__,
            error=str(exc),
            attachment_count=len(deps.attachments),
            exc_info=True,
        )
        yield (buffer, full_content, "provider_error", None)
        return
    try:
        usage = result.usage()
    except Exception:
        usage = None
    yield (buffer, full_content, None, usage)


async def _replay_buffer(buffer: list[AgentEvent]) -> AsyncIterator[str]:
    """Replay buffered events as a simulated stream: non-token events immediately,
    token text re-chunked with a small delay for a live-typing feel. Consecutive
    token events (one text segment) are grouped so an echoed internal-context
    annotation that spans token boundaries is stripped before display."""

    index = 0
    total = len(buffer)
    while index < total:
        event, data = buffer[index]
        if event == "token":
            conv = data.get("conversation_id")
            text = ""
            while index < total and buffer[index][0] == "token":
                text += str(buffer[index][1].get("text", ""))
                index += 1
            text = strip_internal_context(text)
            for start in range(0, len(text), REPLAY_CHUNK):
                yield _sse(
                    "token",
                    {"text": text[start : start + REPLAY_CHUNK], "conversation_id": conv},
                )
                await asyncio.sleep(REPLAY_DELAY)
        else:
            yield _event_to_sse((event, data))
            index += 1


def _degraded_message() -> str:
    return (
        "İşlemi yaptım, ama yanıtı toparlarken bir sorun oluştu. Sonucu yukarıda "
        "görebilirsin; yine de bir şey eksikse tekrar yazar mısın?"
    )


async def _run_buffered_with_retry(
    *,
    choice,
    tier,
    model,
    model_settings,
    make_deps,
    user_prompt: str,
    message_history: list[ModelMessage],
    user_id: str,
    conv_id: str,
) -> AsyncIterator[str]:
    """DeepSeek path: buffer each attempt, retry from scratch on a #1244 failure
    when no real action ran, then replay the clean attempt as a stream."""

    attempt = 0
    while attempt < MAX_ATTEMPTS:
        attempt += 1
        deps = make_deps()
        yield ": keep-alive\n\n"

        result_marker = None
        async for item in _collect_attempt(
            choice=choice,
            model=model,
            model_settings=model_settings,
            deps=deps,
            user_prompt=user_prompt,
            message_history=message_history,
        ):
            if isinstance(item, str):
                yield item
            else:
                result_marker = item
        buffer, full_content, error_code, usage = result_marker
        reason = error_code or looks_like_garbage(full_content, CONDUUT_TOOL_NAMES)

        if reason is None:
            log.info("reliability_guard_clean", attempt=attempt)
            async for sse in _replay_buffer(buffer):
                yield sse
            async for sse in _persist_and_done(
                deps,
                full_content,
                choice,
                tier,
                user_id,
                conv_id,
                usage=usage,
                steps=build_steps(buffer),
            ):
                yield sse
            return

        log.warning(
            "reliability_guard_garbage",
            attempt=attempt,
            reason=reason,
            real_action=deps.real_action_executed,
        )

        if deps.real_action_executed:
            # A real external action ran; retrying would duplicate it. Show the
            # attachments + a graceful line instead of the garbage text.
            for event, data in buffer:
                if event == "attachment":
                    yield _event_to_sse((event, data))
            degraded = _degraded_message()
            yield _sse("token", {"text": degraded, "conversation_id": conv_id})
            async for sse in _persist_and_done(deps, degraded, choice, tier, user_id, conv_id):
                yield sse
            return
        # else: discard buffer and retry from scratch (loop)

    log.error("reliability_guard_exhausted", attempts=MAX_ATTEMPTS)
    yield _sse(
        "error",
        {
            "code": "model_behavior",
            "message": "The model had trouble responding. Please try again.",
        },
    )
    clear_log_context()
