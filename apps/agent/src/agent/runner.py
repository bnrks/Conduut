"""Pydantic AI agent runner with the existing Conduut SSE contract."""

import asyncio
import json
from collections.abc import AsyncIterator
from contextlib import suppress
from uuid import uuid4

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
from src.agent.claim_policy import claim_exceeds_evidence, safe_evidence_summary
from src.agent.history import (
    _conversation_workflows_from_messages,
    _history_from_store_messages,
    _platform_resources_from_messages,
    _workflow_preview_decisions_from_messages,
    strip_internal_context,
)
from src.agent.model_registry import resolve
from src.agent.platform_state import gather_user_state
from src.agent.provider_factory import build_model, build_model_settings, classify_provider_error
from src.agent.reliability_guard import (
    MAX_ATTEMPTS,
    IncrementalReliabilityGuard,
)
from src.agent.router import classify_tier
from src.agent.schemas import AgentDeps, AgentEvent
from src.agent.step_assembler import StepAssembler
from src.agent.tool_safety import CONDUUT_TOOL_NAMES
from src.agent.tools import create_agent
from src.config import key_for_provider, settings
from src.logging_config import bind_log_context, clear_log_context
from src.run_logging import note_run_attempt, set_run_final_preview, start_run_log

log = structlog.get_logger()


async def _cancel_background_task(task: asyncio.Task) -> None:
    """Cancel and consume an inner model task when its SSE generator closes."""

    if not task.done():
        task.cancel()
    with suppress(asyncio.CancelledError, Exception):
        await task


_INTERNAL_CONTEXT_MARKER = "[Conduut internal context"


class _GuardedTextEmitter:
    """Quarantine a bounded suffix until it cannot become a leaked tool call."""

    def __init__(self, guard: IncrementalReliabilityGuard) -> None:
        self.guard = guard
        longest_tool = max((len(name) for name in CONDUUT_TOOL_NAMES), default=0)
        self._quarantine_chars = max(longest_tool + 4, len(_INTERNAL_CONTEXT_MARKER) - 1)
        self._pending = ""
        self._internal_context = False

    def feed(self, chunk: str) -> str:
        if not chunk or self.guard.reason or self._internal_context:
            return ""
        self.guard.feed(chunk)
        if self.guard.reason:
            self._pending = ""
            return ""

        self._pending += chunk
        marker_index = self._pending.find(_INTERNAL_CONTEXT_MARKER)
        if marker_index >= 0:
            safe = self._pending[:marker_index].rstrip()
            self._pending = ""
            self._internal_context = True
            return safe

        release = len(self._pending) - self._quarantine_chars
        if release <= 0:
            return ""
        safe = self._pending[:release]
        self._pending = self._pending[release:]
        return safe

    def finish_model_response(self) -> str:
        """Release a clean response tail and reset per-response sanitization."""

        if self.guard.reason or self._internal_context:
            safe = ""
        else:
            safe = strip_internal_context(self._pending)
        self._pending = ""
        self._internal_context = False
        self.guard.finish_model_response()
        return safe


class _ClaimGatedTextEmitter:
    """Hold model text until a complete sentence can be checked against evidence."""

    def __init__(self, evidence: list[dict]) -> None:
        self._evidence = evidence
        self._pending = ""

    def feed(self, chunk: str) -> str:
        if not chunk:
            return ""
        self._pending += chunk
        released: list[str] = []
        start = 0
        for index, character in enumerate(self._pending):
            if character not in ".!?\n":
                continue
            sentence = self._pending[start : index + 1]
            released.append(self._gate(sentence))
            start = index + 1
        self._pending = self._pending[start:]
        return "".join(released)

    def finish_model_response(self) -> str:
        sentence = self._pending
        self._pending = ""
        return self._gate(sentence)

    def _gate(self, sentence: str) -> str:
        if not sentence or not claim_exceeds_evidence(sentence, self._evidence):
            return sentence
        log.warning(
            "agent_stream_claim_exceeds_evidence",
            evidence_outcomes=[item.get("outcome") for item in self._evidence],
        )
        leading = sentence[: len(sentence) - len(sentence.lstrip())]
        trailing = sentence[len(sentence.rstrip()) :]
        return f"{leading}{safe_evidence_summary(self._evidence)}{trailing}"


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
    *,
    attempt_id: str | None = None,
    guarded_text: _GuardedTextEmitter | None = None,
    claim_gate: _ClaimGatedTextEmitter | None = None,
) -> None:
    """Pydantic AI model-stream event'ini SSE event'ine çevirip queue'ya koyar.

    Görünür metin -> 'token' (persist için text_chunks'a da eklenir).
    Düşünce       -> 'thinking' (ephemeral; kaydedilmez, text_chunks'a girmez).
    `PartStartEvent` parçanın ilk içeriğini, `PartDeltaEvent` sonraki delta'ları taşır.
    """
    if isinstance(event, PartStartEvent):
        part = event.part
        if isinstance(part, TextPart) and part.content:
            visible = guarded_text.feed(part.content) if guarded_text else part.content
            visible = claim_gate.feed(visible) if claim_gate else visible
            text_chunks.append(visible)
            if not visible:
                return
            data = {"text": visible, "conversation_id": conv_id}
            if attempt_id:
                data["attempt_id"] = attempt_id
            await event_queue.put(("token", data))
        elif isinstance(part, ThinkingPart) and part.content:
            data = {"text": part.content, "conversation_id": conv_id}
            if attempt_id:
                data["attempt_id"] = attempt_id
            await event_queue.put(("thinking", data))
    elif isinstance(event, PartDeltaEvent):
        delta = event.delta
        if isinstance(delta, TextPartDelta) and delta.content_delta:
            visible = (
                guarded_text.feed(delta.content_delta) if guarded_text else delta.content_delta
            )
            visible = claim_gate.feed(visible) if claim_gate else visible
            text_chunks.append(visible)
            if not visible:
                return
            data = {"text": visible, "conversation_id": conv_id}
            if attempt_id:
                data["attempt_id"] = attempt_id
            await event_queue.put(("token", data))
        elif isinstance(delta, ThinkingPartDelta) and delta.content_delta:
            data = {"text": delta.content_delta, "conversation_id": conv_id}
            if attempt_id:
                data["attempt_id"] = attempt_id
            await event_queue.put(("thinking", data))


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
    user_prompt, message_history = _history_from_store_messages(messages)
    run_session = start_run_log(
        request_id=request_id,
        conversation_id=conv_id,
        task_preview=user_prompt,
    )
    if run_session is not None:
        bind_log_context(run_id=run_session.run_id)
    usage_run_id = run_session.run_id if run_session is not None else uuid4().hex
    completed = False
    terminal_status = "error"
    try:
        async for event in _run_agent_stream(
            user_id,
            conv_id,
            messages,
            user_prompt=user_prompt,
            message_history=message_history,
            run_id=usage_run_id,
        ):
            yield event
        completed = True
        terminal_status = "success" if run_session is not None and run_session.success else "error"
    except (GeneratorExit, asyncio.CancelledError):
        terminal_status = "cancelled"
        raise
    except Exception as exc:
        log.error(
            "agent_run_unhandled_error",
            error_type=type(exc).__name__,
            error=str(exc),
            exc_info=True,
        )
        terminal_status = "error"
        raise
    finally:
        if run_session is not None:
            if not completed and terminal_status != "cancelled":
                terminal_status = "error"
            run_session.finish(terminal_status)
        clear_log_context()


async def _run_agent_stream(
    user_id: str,
    conv_id: str,
    messages: list[dict],
    *,
    user_prompt: str,
    message_history: list[ModelMessage],
    run_id: str,
) -> AsyncIterator[str]:
    """Internal stream implementation owned by the outer run-log lifecycle."""

    log.info("agent_run_started", message_count=len(messages))
    initial_attempt_id = uuid4().hex
    platform_resources = _platform_resources_from_messages(messages)
    conversation_workflows = _conversation_workflows_from_messages(messages)
    workflow_preview_approvals, workflow_preview_cancellations = (
        _workflow_preview_decisions_from_messages(messages)
    )

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
        yield _sse(
            "error",
            {
                "code": "model_config",
                "message": classify_provider_error(exc),
                "attempt_id": initial_attempt_id,
            },
        )
        clear_log_context()
        return

    def make_deps(attempt_id: str) -> AgentDeps:
        return AgentDeps(
            user_id=user_id,
            conversation_id=conv_id,
            event_queue=asyncio.Queue(),
            attempt_id=attempt_id,
            platform_resources=platform_resources,
            conversation_workflows=conversation_workflows,
            workflow_preview_approvals=dict(workflow_preview_approvals),
            workflow_preview_cancellations=set(workflow_preview_cancellations),
            platform_state=platform_state,
        )

    if settings.enable_reliability_guard and choice.provider == "deepseek":
        stream = _run_guarded_with_retry(
            choice=choice,
            tier=tier,
            model=model,
            model_settings=model_settings,
            make_deps=make_deps,
            user_prompt=user_prompt,
            message_history=message_history,
            user_id=user_id,
            conv_id=conv_id,
            initial_attempt_id=initial_attempt_id,
            run_id=run_id,
        )
    else:
        stream = _run_live(
            choice=choice,
            tier=tier,
            model=model,
            model_settings=model_settings,
            deps=make_deps(initial_attempt_id),
            user_prompt=user_prompt,
            message_history=message_history,
            user_id=user_id,
            conv_id=conv_id,
            attempt_id=initial_attempt_id,
            run_id=run_id,
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
    attempt_id: str,
    run_id: str | None = None,
) -> AsyncIterator[str]:
    """Stream a single agent run live to the client (non-DeepSeek path)."""

    event_queue = deps.event_queue
    agent = create_agent(model)

    # Akan görünür metni persist için biriktir (düşünce kaydedilmez).
    text_chunks: list[str] = []
    claim_gate = _ClaimGatedTextEmitter(deps.claim_evidence)

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
                            await _emit_stream_event(
                                event,
                                event_queue,
                                conv_id,
                                text_chunks,
                                attempt_id=attempt_id,
                                claim_gate=claim_gate,
                            )
                    tail = claim_gate.finish_model_response()
                    if tail:
                        text_chunks.append(tail)
                        await event_queue.put(
                            (
                                "token",
                                {
                                    "text": tail,
                                    "conversation_id": conv_id,
                                    "attempt_id": attempt_id,
                                },
                            )
                        )
            return agent_run.result

    assembler = StepAssembler()
    task = asyncio.create_task(_agent_stream())

    try:
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
    except BaseException:
        await _cancel_background_task(task)
        raise

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
                "attempt_id": attempt_id,
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
                "attempt_id": attempt_id,
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
        yield _sse(
            "error",
            {
                "code": "unknown",
                "message": classify_provider_error(exc),
                "attempt_id": attempt_id,
            },
        )
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
        deps,
        full_content,
        choice,
        tier,
        user_id,
        conv_id,
        usage=usage,
        steps=assembler.steps(),
        attempt_id=attempt_id,
        run_id=run_id,
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
    attempt_id: str | None = None,
    run_id: str | None = None,
) -> AsyncIterator[str]:
    """Log usage, persist the assistant message + artifacts, emit the done event."""

    # The model occasionally echoes the "[Conduut internal context ...]" history
    # scaffolding into its reply; strip it from everything the user sees/reloads.
    full_content = strip_internal_context(full_content)
    set_run_final_preview(full_content)

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

    if usage_fields:
        try:
            await store.save_agent_usage_event(
                user_id,
                run_id=run_id or attempt_id or uuid4().hex,
                conversation_id=conv_id,
                provider=choice.provider,
                model=choice.model,
                tier=tier.value,
                input_tokens=usage_fields["tok_in"],
                output_tokens=usage_fields["tok_out"],
                cache_read_tokens=usage_fields["tok_cache_read"],
                cache_write_tokens=usage_fields["tok_cache_write"],
                model_requests=usage_fields["model_requests"],
                tool_calls=usage_fields["usage_tool_calls"],
            )
        except Exception as exc:
            # Usage observability must never break a successful chat response.
            log.warning(
                "agent_usage_persist_error",
                error=str(exc),
                error_type=type(exc).__name__,
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
            **({"attempt_id": attempt_id} if attempt_id else {}),
        },
    )
    clear_log_context()


# --- DeepSeek reliability guard (#1244): live attempt + visible recovery ----

RECOVERY_MESSAGE = "Agent tarafında bir sorun oluştu. Baştan tekrar deniyorum…"
DEGRADED_MESSAGE = "İşlem tamamlandı; yanıtı oluştururken sorun oluştu. Aynı işlemi tekrar etmedim."
RECOVERY_INSTRUCTION = (
    "[Internal recovery instruction: the previous attempt emitted a tool call as "
    "plain text or entered an invalid loop. Restart the task from the beginning. "
    "Use structured tool calling only; never print a tool name with arguments.]"
)


def _attempt_id() -> str:
    return uuid4().hex


def _provider_error_is_terminal(exc: Exception) -> bool:
    """Auth, billing/quota and missing-model failures cannot heal on retry."""

    status = getattr(exc, "status_code", None)
    response = getattr(exc, "response", None)
    if status is None and response is not None:
        status = getattr(response, "status_code", None)
    name = type(exc).__name__.lower()
    message = str(exc).lower()
    return bool(
        status in (401, 403, 404)
        or "auth" in name
        or "unauthorized" in message
        or "notfound" in name
        or "not found" in message
        or "insufficient_quota" in message
        or "quota" in message
        or "billing" in message
    )


def _recovery_event(
    *,
    conversation_id: str,
    failed_attempt_id: str,
    next_attempt_id: str | None,
    attempt: int,
    reason: str,
    retrying: bool,
    message: str,
) -> str:
    return _sse(
        "recovery",
        {
            "conversation_id": conversation_id,
            "failed_attempt_id": failed_attempt_id,
            "next_attempt_id": next_attempt_id,
            "attempt": attempt,
            "max_attempts": MAX_ATTEMPTS,
            "reason_code": reason,
            "retrying": retrying,
            "message": message,
        },
    )


async def _run_guarded_attempt(
    *,
    choice,
    model,
    model_settings,
    deps: AgentDeps,
    user_prompt: str,
    message_history: list[ModelMessage],
) -> AsyncIterator:
    """Stream one attempt immediately and finish with an internal result marker."""

    queue = deps.event_queue
    agent = create_agent(model)
    text_chunks: list[str] = []
    assembler = StepAssembler()
    guard = IncrementalReliabilityGuard()
    guarded_text = _GuardedTextEmitter(guard)
    claim_gate = _ClaimGatedTextEmitter(deps.claim_evidence)

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
                                event,
                                queue,
                                deps.conversation_id,
                                text_chunks,
                                attempt_id=deps.attempt_id,
                                guarded_text=guarded_text,
                                claim_gate=claim_gate,
                            )
                            if guard.reason:
                                return None
                    guarded_tail = guarded_text.finish_model_response()
                    visible_tail = claim_gate.feed(guarded_tail)
                    claim_tail = claim_gate.finish_model_response()
                    tail = f"{visible_tail}{claim_tail}"
                    if tail:
                        text_chunks.append(tail)
                        await queue.put(
                            (
                                "token",
                                {
                                    "text": tail,
                                    "conversation_id": deps.conversation_id,
                                    "attempt_id": deps.attempt_id,
                                },
                            )
                        )
            return agent_run.result

    task = asyncio.create_task(_stream())
    try:
        while not task.done() or not queue.empty():
            try:
                item = await asyncio.wait_for(queue.get(), timeout=2.0)
                assembler.add(item[0], item[1])
                yield _event_to_sse(item)
            except asyncio.TimeoutError:
                if not task.done():
                    yield ": keep-alive\n\n"
    except BaseException:
        await _cancel_background_task(task)
        raise

    full_content = "".join(text_chunks)
    if guard.reason:
        yield (
            full_content,
            guard.reason,
            None,
            None,
            assembler.steps(),
            guard.diagnostics,
        )
        return

    try:
        result = task.result()
    except UsageLimitExceeded as exc:
        yield (full_content, "max-rounds", exc, None, assembler.steps(), guard.diagnostics)
        return
    except UnexpectedModelBehavior as exc:
        yield (full_content, "model-behavior", exc, None, assembler.steps(), guard.diagnostics)
        return
    except Exception as exc:
        log.error(
            "agent_run_error",
            error_type=type(exc).__name__,
            error=str(exc),
            attachment_count=len(deps.attachments),
            exc_info=True,
        )
        yield (full_content, "provider-error", exc, None, assembler.steps(), guard.diagnostics)
        return
    try:
        usage = result.usage()
    except Exception:
        usage = None
    yield (
        full_content or (result.output or ""),
        None,
        None,
        usage,
        assembler.steps(),
        guard.diagnostics,
    )


async def _run_guarded_with_retry(
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
    initial_attempt_id: str,
    run_id: str | None = None,
) -> AsyncIterator[str]:
    """DeepSeek path: live stream each attempt and explicitly reset on retry."""

    attempt_id = initial_attempt_id
    for attempt in range(1, MAX_ATTEMPTS + 1):
        note_run_attempt(attempt)
        deps = make_deps(attempt_id)
        prompt = user_prompt if attempt == 1 else f"{user_prompt}\n\n{RECOVERY_INSTRUCTION}"
        result_marker = None
        async for item in _run_guarded_attempt(
            choice=choice,
            model=model,
            model_settings=model_settings,
            deps=deps,
            user_prompt=prompt,
            message_history=message_history,
        ):
            if isinstance(item, str):
                yield item
            else:
                result_marker = item

        full_content, reason, exc, usage, steps, guard_diagnostics = result_marker
        if reason is None:
            log.info("reliability_guard_clean", attempt=attempt, attempt_id=attempt_id)
            async for sse in _persist_and_done(
                deps,
                full_content,
                choice,
                tier,
                user_id,
                conv_id,
                usage=usage,
                steps=steps,
                attempt_id=attempt_id,
                run_id=run_id,
            ):
                yield sse
            return

        log.warning(
            "reliability_guard_garbage",
            attempt=attempt,
            attempt_id=attempt_id,
            reason=reason,
            replay_unsafe=deps.real_action_executed,
            replay_unsafe_tool=deps.replay_unsafe_tool,
            **guard_diagnostics,
        )

        if deps.real_action_executed:
            yield _recovery_event(
                conversation_id=conv_id,
                failed_attempt_id=attempt_id,
                next_attempt_id=None,
                attempt=attempt,
                reason=reason,
                retrying=False,
                message=DEGRADED_MESSAGE,
            )
            # The UI discarded the failed attempt, so publish valid cards again.
            for attachment in deps.attachments:
                data = {
                    "conversation_id": conv_id,
                    "attempt_id": attempt_id,
                    "type": attachment.get("type"),
                    "data": attachment.get("data"),
                }
                yield _sse("attachment", data)
            yield _sse(
                "token",
                {"text": DEGRADED_MESSAGE, "conversation_id": conv_id, "attempt_id": attempt_id},
            )
            async for sse in _persist_and_done(
                deps,
                DEGRADED_MESSAGE,
                choice,
                tier,
                user_id,
                conv_id,
                attempt_id=attempt_id,
                run_id=run_id,
            ):
                yield sse
            return

        if exc is not None and _provider_error_is_terminal(exc):
            yield _sse(
                "error",
                {
                    "code": "provider_error",
                    "message": classify_provider_error(exc),
                    "attempt_id": attempt_id,
                },
            )
            clear_log_context()
            return

        if attempt < MAX_ATTEMPTS:
            next_attempt_id = _attempt_id()
            yield _recovery_event(
                conversation_id=conv_id,
                failed_attempt_id=attempt_id,
                next_attempt_id=next_attempt_id,
                attempt=attempt,
                reason=reason,
                retrying=True,
                message=RECOVERY_MESSAGE,
            )
            attempt_id = next_attempt_id
            continue

        yield _recovery_event(
            conversation_id=conv_id,
            failed_attempt_id=attempt_id,
            next_attempt_id=None,
            attempt=attempt,
            reason=reason,
            retrying=False,
            message="Agent yanıtı tamamlayamadı.",
        )

    log.error("reliability_guard_exhausted", attempts=MAX_ATTEMPTS)
    yield _sse(
        "error",
        {
            "code": "model_behavior",
            "message": "The model had trouble responding. Please try again.",
            "attempt_id": attempt_id,
        },
    )
    clear_log_context()
