"""Pydantic AI agent factory and tool registrations."""

from time import perf_counter
from typing import Any

import structlog
from pydantic_ai import Agent, ModelRetry, RunContext

from src import executions, n8n_client, store
from src.agent.assurance import workflow_fingerprint
from src.agent.claim_policy import claim_exceeds_evidence, safe_evidence_summary
from src.agent.platform_profile import render_static_profile
from src.agent.platform_state import platform_state_instructions
from src.agent.schemas import (
    AgentDeps,
    ArtifactPreviewAttachment,
    PlatformActionPlan,
    UserInputChoice,
    UserInputRequestAttachment,
    UserInputRequestData,
    WorkflowInputField,
    WorkflowNode,
    WorkflowOutputField,
    WorkflowPreviewAttachment,
    WorkflowPreviewData,
    dump_workflow_nodes,
)
from src.agent.tools.build_pipeline import _validated_runtime_workflow
from src.agent.tools.common import (
    _credential_suggestion_instruction,
    _missing_credentials_instruction,
    _research_credential_instruction,
    _safe_error,
    _waiting_for_user_input_result,
)
from src.agent.tools.credentials import (
    add_service_credential_payload,
    attach_credential_payload,
    list_credentials_payload,
    prepare_api_credential_payload,
)
from src.agent.tools.output_schema import save_workflow_output_metadata
from src.agent.tools.prompt import SYSTEM_PROMPT
from src.agent.tools.readiness import (
    _emit_missing_credentials,
    _get_workflow_for_reference,
    analyze_workflow_readiness_payload,
)
from src.agent.tools.runtime_inputs import (
    _input_schema_payload,
    _validated_workflow_input,
    _workflow_input_schema_from_metadata,
)
from src.agent.tools.workflow_runner import execution_retry_guard, run_workflow_with_input
from src.config import settings
from src.platforms.actions import run_platform_action_payload
from src.registry import registry

log = structlog.get_logger()

_AWAITING_APPROVAL_SUMMARY = (
    "Önizleme hazır. Henüz gerçek bir gönderim veya güncelleme yapılmadı. "
    "Devam etmek ya da vazgeçmek için aşağıdaki onay seçeneklerini kullan."
)
_AWAITING_INPUT_SUMMARY = (
    "Bu işlem devam etmek için kullanıcı girdisi bekliyor. "
    "Henüz doğrulanmış bir çalıştırma veya dış sistem değişikliği yok."
)


def _tool_status(result: Any) -> str:
    if isinstance(result, dict):
        if result.get("error"):
            return "error"
        if result.get("status") in {"waiting_for_user", "error", "failed"}:
            return str(result["status"])
        if result.get("ready") is False or result.get("success") is False:
            return "needs_attention"
    if (
        isinstance(result, list)
        and result
        and isinstance(result[0], dict)
        and result[0].get("error")
    ):
        return "error"
    return "success"


def _log_tool_finished(tool: str, started_at: float, result: Any) -> None:
    result_keys = list(result.keys()) if isinstance(result, dict) else None
    log.info(
        "agent_tool_call_finished",
        tool=tool,
        duration_ms=round((perf_counter() - started_at) * 1000, 2),
        status=_tool_status(result),
        result_keys=result_keys,
    )


def _take_workflow_preview_decision(
    deps: AgentDeps,
    workflow_id: str,
    explicit_token: str | None,
) -> tuple[str | None, bool]:
    """Resolve one structured approval without putting its token in prompt text."""

    if workflow_id in deps.workflow_preview_cancellations:
        deps.workflow_preview_cancellations.discard(workflow_id)
        deps.workflow_preview_approvals.pop(workflow_id, None)
        return None, True
    approved_token = deps.workflow_preview_approvals.pop(workflow_id, None)
    return approved_token or explicit_token, False


async def _request_workflow_run_approval(
    ctx: RunContext[AgentDeps],
    *,
    workflow_id: str,
    preview: dict[str, Any],
) -> dict[str, Any]:
    """Emit a persisted approval request whose opaque id survives chat turns."""

    preview_token = str(preview.get("preview_token") or "")
    masked_targets = [
        str(action.get("target"))
        for action in preview.get("actions") or []
        if isinstance(action, dict) and action.get("target")
    ]
    target_summary = f" Masked targets: {', '.join(masked_targets[:5])}." if masked_targets else ""
    question = (
        "The side-effect preview found "
        f"{preview.get('eligible_count') or 0} eligible item(s), "
        f"{preview.get('action_count') or 0} action(s), and "
        f"{preview.get('writeback_count') or 0} write-back(s)."
        f"{target_summary} Do you want to run it now?"
    )
    await ctx.deps.emit_tool_call("request_user_input")
    started_at = perf_counter()
    await ctx.deps.emit_attachment(
        UserInputRequestAttachment(
            data=UserInputRequestData(
                question=question,
                missingFields=["run_confirmation"],
                choices=[
                    UserInputChoice(label="Approve run", value="approve"),
                    UserInputChoice(label="Cancel", value="cancel"),
                ],
                allowSkip=False,
                reason="Real actions require confirmation of the safe preview.",
                requestId=preview_token,
                requestKind="workflow_run_approval",
                workflowId=workflow_id,
            )
        )
    )
    ctx.deps.awaiting_user_input = True
    ctx.deps.awaiting_user_input_summary = _AWAITING_APPROVAL_SUMMARY
    request_result = {
        "status": "waiting_for_user",
        "question": question,
        "missing_fields": ["run_confirmation"],
        "choices": ["Approve run", "Cancel"],
        "instruction": "Stop now and wait for the structured approval response.",
    }
    _log_tool_finished("request_user_input", started_at, request_result)
    return {
        "status": "waiting_for_user",
        "workflow_id": workflow_id,
        "preview_token": preview_token,
        "preview": preview,
        "instruction": (
            "Stop and wait for the user's answer. The approval token is persisted in the "
            "structured request and will be supplied automatically on the next turn. Do not "
            "ask for confirmation again unless the approval is explicitly rejected as stale."
        ),
    }


def _workflow_result_with_readiness(
    workflow: Any,
    readiness: dict[str, Any],
    *,
    timezone: str,
) -> dict[str, Any]:
    """Build a create/update result, surfacing missing creds or reuse suggestions."""

    base: dict[str, Any] = {
        "id": workflow.id,
        "name": workflow.name,
        "active": workflow.active,
        "timezone": timezone,
    }
    missing_count = readiness.get("missing_count", 0)
    suggestions = readiness.get("reuse_candidates", [])
    research = readiness.get("research_candidates", [])
    if not missing_count and not suggestions and not research:
        return base
    base["ready"] = False
    base["missing_credentials"] = missing_count
    if research:
        base["needs_api_credential"] = research
        base["instruction"] = _research_credential_instruction()
    elif suggestions:
        base["credential_suggestions"] = suggestions
        base["instruction"] = _credential_suggestion_instruction()
    else:
        base["instruction"] = _missing_credentials_instruction()
    return base


def _effective_workflow_timezone(workflow: dict[str, Any]) -> str:
    """The timezone n8n will use for this workflow's Schedule Triggers."""

    workflow_settings = workflow.get("settings")
    if isinstance(workflow_settings, dict):
        explicit_timezone = workflow_settings.get("timezone")
        if isinstance(explicit_timezone, str) and explicit_timezone.strip():
            return explicit_timezone.strip()
    return settings.workflow_timezone


def _should_run_sandbox_test(result: dict[str, Any], *, awaiting: bool) -> bool:
    """Sandbox-test only genuinely-complete builds (credential-ready, not waiting)."""

    if awaiting:
        return False
    # _workflow_result_with_readiness adds ready=False only when blocked.
    return "ready" not in result


def _needs_pretest(
    metadata: store.WorkflowMetadata | None, workflow: dict[str, Any] | None = None
) -> bool:
    """Whether a workflow should be sandbox-tested before its first real run.

    Workflows that were credential-blocked at build time never got tested, so the
    structure is unverified. Run the test once before executing for real; skip it
    when a prior test already passed (test_status='passed').
    """

    status = metadata.resources.get("test_status") if metadata else None
    if status not in {"passed", "no_action", "partial_coverage"}:
        return True
    if workflow is None:
        return False
    assurance = metadata.resources.get("assurance") if metadata else None
    stored = assurance.get("workflow_fingerprint") if isinstance(assurance, dict) else None
    return stored != workflow_fingerprint(workflow)


async def _run_pretest_gate(
    ctx: RunContext[AgentDeps],
    workflow: dict[str, Any],
    *,
    input_payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Run delayed sandbox verification with real input when a run supplies it."""

    from src.agent.tools.sandbox_gate import _test_and_gate

    name = str(workflow.get("name") or "Workflow")
    if input_payload is None:
        return await _test_and_gate(ctx, workflow, name, {})
    return await _test_and_gate(ctx, workflow, name, {}, input_payload=input_payload)


def _readiness_block_result(workflow_id: str, readiness: dict[str, Any]) -> dict[str, Any] | None:
    """Block activate/execute when credentials are missing or pending confirmation."""

    missing_count = readiness.get("missing_count", 0)
    suggestions = readiness.get("reuse_candidates", [])
    research = readiness.get("research_candidates", [])
    if not missing_count and not suggestions and not research:
        return None
    result: dict[str, Any] = {
        "success": False,
        "workflow_id": workflow_id,
        "missing_credentials": missing_count,
    }
    if research:
        result["needs_api_credential"] = research
        result["error"] = "An API in this workflow needs a credential that is not set up yet."
        result["instruction"] = _research_credential_instruction()
    elif suggestions:
        result["credential_suggestions"] = suggestions
        result["error"] = "A saved credential matches this workflow but is not attached yet."
        result["instruction"] = _credential_suggestion_instruction()
    else:
        result["error"] = "Missing credentials. Ask the user to submit the credential request."
        result["instruction"] = _missing_credentials_instruction()
    return result


async def _dedup_existing_workflow(existing_id: str | None) -> dict[str, Any] | None:
    """The conversation's remembered workflow for create-dedup, or None to create
    fresh. Returns None when there is no remembered id OR the workflow was deleted
    (n8n 404) -- e.g. the user asked to delete and rebuild in the same chat, so the
    dedup id is stale. Without this, create_workflow re-reads the gone id and dies
    with "Not Found" instead of just recreating. Non-404 errors propagate."""

    if not existing_id:
        return None
    try:
        return await n8n_client.get_workflow(existing_id)
    except n8n_client.N8nApiError as exc:
        if exc.status_code == 404:
            return None
        raise


def _validated_create_or_dedup_workflow(
    nodes: list[WorkflowNode],
    connections: dict[str, Any] | None,
    input_schema: list[WorkflowInputField] | None,
    existing: dict[str, Any] | None,
) -> tuple[
    list[WorkflowNode],
    dict[str, Any],
    list[WorkflowInputField],
    dict[str, Any] | None,
]:
    """Validate create input without rebuilding a deduped workflow's topology."""

    requested_connections = connections or None
    validated_nodes, validated_connections, runtime_schema = _validated_runtime_workflow(
        nodes,
        requested_connections,
        input_schema,
        fallback_connections=(existing.get("connections", {}) if existing is not None else None),
        infer_missing_connections=requested_connections is not None or existing is None,
    )
    return validated_nodes, validated_connections, runtime_schema, requested_connections


def _normalized_user_input_request(
    question: str,
    missing_fields: list[str] | None,
    choices: list[str] | None,
    reason: str | None,
) -> tuple[str, list[str], list[UserInputChoice], str | None, list[str]]:
    normalized_question = question.strip()
    if not normalized_question:
        normalized_question = "What information should I use to continue?"
    all_fields = [
        field.strip()
        for field in (missing_fields or [])
        if isinstance(field, str) and field.strip()
    ]
    normalized_choices = [
        UserInputChoice(label=choice.strip())
        for choice in (choices or [])
        if isinstance(choice, str) and choice.strip()
    ][:4]
    normalized_reason = reason.strip() if isinstance(reason, str) and reason.strip() else None
    return (
        normalized_question,
        all_fields[:1],
        normalized_choices,
        normalized_reason,
        all_fields[1:],
    )


def base_instructions() -> str:
    """System prompt, platform profile, and authoritative runtime configuration."""

    schedule_runtime = (
        "=== Runtime scheduling facts ===\n"
        f"- Configured workflow timezone: {settings.workflow_timezone}.\n"
        "- New workflows are written with this exact settings.timezone value.\n"
        "- For an existing workflow, get_workflow.settings.timezone is authoritative; "
        "if it is absent, the configured workflow timezone above applies.\n"
        "- Host OS timezone and UTC-formatted execution timestamps do not change the "
        "Schedule Trigger wall-clock timezone. Never speculate with phrases such as "
        "'if the system uses UTC' and never convert the user's requested time to UTC."
    )
    return SYSTEM_PROMPT + "\n\n" + render_static_profile() + "\n\n" + schedule_runtime


def _validate_evidence_gated_output(deps: AgentDeps, output: str) -> str:
    """Bound success language without re-entering the agent loop while waiting."""

    if not claim_exceeds_evidence(output, deps.claim_evidence):
        return output
    log.warning(
        "agent_claim_exceeds_evidence",
        evidence_outcomes=[item.get("outcome") for item in deps.claim_evidence],
        attempt=deps.claim_validation_failures + 1,
        awaiting_user_input=deps.awaiting_user_input,
    )
    if deps.awaiting_user_input:
        # The persisted attachment is the single source of truth. Retrying the
        # model can issue unrelated tools and make one approval look like two.
        return deps.awaiting_user_input_summary or _AWAITING_INPUT_SUMMARY
    if deps.claim_validation_failures == 0:
        deps.claim_validation_failures += 1
        raise ModelRetry(
            "Your response claims a workflow ran, sent, or updated external data beyond the "
            "available tool evidence. Inspect/execute the exact workflow and report only the "
            "claimable_outcome returned by the tool."
        )
    return safe_evidence_summary(deps.claim_evidence)


def create_agent(model: Any) -> Agent[AgentDeps, str]:
    """Create a Conduut Pydantic AI agent with all n8n tools registered."""

    agent: Agent[AgentDeps, str] = Agent(
        model,
        deps_type=AgentDeps,
        output_type=str,
        instructions=base_instructions(),
        # Headroom: validation ModelRetry + the bounded sandbox test ModelRetry
        # (real bound: workflow_test_attempts, max 2) must not trip this limit.
        retries=4,
        tool_timeout=60.0,
    )

    @agent.instructions
    def _platform_state_instructions(ctx: RunContext[AgentDeps]) -> str:
        """Inject the per-conversation user state (best-effort, may be empty)."""
        return platform_state_instructions(ctx.deps.platform_state)

    @agent.output_validator
    def _evidence_gated_claims(ctx: RunContext[AgentDeps], output: str) -> str:
        return _validate_evidence_gated_output(ctx.deps, output)

    @agent.tool
    async def search_n8n_nodes(
        ctx: RunContext[AgentDeps], query: str, limit: int = 20
    ) -> dict[str, Any]:
        """Search for n8n node types by keyword before building workflow nodes.

        limit defaults to 20 and may be increased up to 50 when more candidates are needed.
        """

        await ctx.deps.emit_tool_call("search_n8n_nodes")
        safe_limit = max(1, min(limit, 50))
        results = registry.search_nodes(query, limit=safe_limit)
        if not results:
            return {
                "results": [],
                "hint": (
                    "No nodes found. Try service names or common nodes like "
                    "scheduleTrigger, webhook, httpRequest, set, if, code, gmail, slack."
                ),
            }
        return {"results": results, "limit": safe_limit}

    @agent.tool
    async def get_node_schema(ctx: RunContext[AgentDeps], node_type: str) -> dict[str, Any]:
        """Get exact parameters, credentials, type, and typeVersion for an n8n node."""

        await ctx.deps.emit_tool_call("get_node_schema")
        schema = registry.get_node_schema(node_type)
        if not schema:
            return {
                "error": (
                    f"Node type '{node_type}' was not found. Use search_n8n_nodes "
                    "to find the exact n8n type string."
                )
            }
        return schema

    @agent.tool
    async def find_workflow_template(
        ctx: RunContext[AgentDeps], description: str
    ) -> dict[str, Any]:
        """Find existing n8n workflow templates similar to the user's request."""

        await ctx.deps.emit_tool_call("find_workflow_template")
        results = registry.find_templates(description)
        if not results:
            return {"templates": [], "hint": "No matching templates found. Build from scratch."}
        return {"templates": results}

    @agent.tool
    async def run_platform_action(
        ctx: RunContext[AgentDeps],
        plan: PlatformActionPlan,
    ) -> dict[str, Any]:
        """Run a direct action against a connected platform such as Gmail or Sheets."""

        if ctx.deps.awaiting_user_input:
            return _waiting_for_user_input_result()
        await ctx.deps.emit_tool_call("run_platform_action")
        started_at = perf_counter()
        ctx.deps.mark_replay_unsafe("run_platform_action")
        result = await run_platform_action_payload(ctx.deps, plan)
        payload = result.model_dump(exclude_none=True)
        _log_tool_finished("run_platform_action", started_at, payload)
        return payload

    @agent.tool
    async def request_user_input(
        ctx: RunContext[AgentDeps],
        question: str,
        missing_fields: list[str] | None = None,
        choices: list[str] | None = None,
        allow_skip: bool = False,
        reason: str | None = None,
    ) -> dict[str, Any]:
        """Ask one required missing business detail before continuing."""

        (
            normalized_question,
            normalized_fields,
            normalized_choices,
            normalized_reason,
            remaining_fields,
        ) = _normalized_user_input_request(question, missing_fields, choices, reason)
        await ctx.deps.emit_tool_call("request_user_input")
        started_at = perf_counter()
        if remaining_fields:
            log.info(
                "user_input_request_stepwise_limited",
                requested_fields=[*normalized_fields, *remaining_fields],
                emitted_fields=normalized_fields,
                remaining_fields=remaining_fields,
            )
        await ctx.deps.emit_attachment(
            UserInputRequestAttachment(
                data=UserInputRequestData(
                    question=normalized_question,
                    missingFields=normalized_fields,
                    choices=normalized_choices,
                    allowSkip=allow_skip,
                    reason=normalized_reason,
                )
            )
        )
        ctx.deps.awaiting_user_input = True
        result = {
            "status": "waiting_for_user",
            "question": normalized_question,
            "missing_fields": normalized_fields,
            "choices": [choice.label for choice in normalized_choices],
            "remaining_missing_fields": remaining_fields,
            "instruction": (
                "Stop now. Ask only this one question and wait for the user's next "
                "message. Treat the user's answer as accumulated context, then ask "
                "the next missing detail if needed. Do not create or update workflows "
                "until enough information is available."
            ),
        }
        _log_tool_finished("request_user_input", started_at, result)
        return result

    @agent.tool
    async def list_workflows(ctx: RunContext[AgentDeps]) -> list[dict[str, Any]]:
        """List all n8n workflows in the shared MVP instance."""

        await ctx.deps.emit_tool_call("list_workflows")
        started_at = perf_counter()
        try:
            workflows = await n8n_client.list_workflows()
        except Exception as exc:
            log.error("tool_error", tool="list_workflows", error=str(exc))
            result = [{"error": _safe_error(exc)}]
            _log_tool_finished("list_workflows", started_at, result)
            return result
        result = [{"id": w.id, "name": w.name, "active": w.active} for w in workflows]
        _log_tool_finished("list_workflows", started_at, result)
        return result

    @agent.tool
    async def get_workflow(ctx: RunContext[AgentDeps], workflow_id: str) -> dict[str, Any]:
        """Get the full details and node structure of a specific n8n workflow."""

        await ctx.deps.emit_tool_call("get_workflow")
        started_at = perf_counter()
        try:
            result = await n8n_client.get_workflow(workflow_id)
            _log_tool_finished("get_workflow", started_at, result)
            return result
        except Exception as exc:
            log.error("tool_error", tool="get_workflow", error=str(exc))
            result = {"error": _safe_error(exc)}
            _log_tool_finished("get_workflow", started_at, result)
            return result

    @agent.tool
    async def create_workflow(
        ctx: RunContext[AgentDeps],
        name: str,
        nodes: list[WorkflowNode],
        connections: dict[str, Any] | None = None,
        input_schema: list[WorkflowInputField] | None = None,
        output_schema: list[WorkflowOutputField] | None = None,
    ) -> dict[str, Any]:
        """Create an n8n workflow. The single workflow builder.

        Write compact n8n JSON: per node give only name, type and parameters —
        Conduut fills id, typeVersion, position and webhookId, infers linear
        connections when you omit them, and repairs common slips (AI chat-model
        sub-nodes wired into the main flow are moved to the agent's ai_* port;
        webhook runtime inputs read as bare $json.<field> become
        $json.body.<field>). Still aim to be correct: attach langchain chat
        models / memory / tools to an AI Agent (text in its prompt), and read
        the agent answer downstream from its json.output. See the system prompt
        for worked examples.
        When the workflow returns data to the user, pass output_schema (named
        fields + friendly labels + format) and make the final node output
        exactly those names.
        """

        if ctx.deps.awaiting_user_input:
            return _waiting_for_user_input_result()
        await ctx.deps.emit_tool_call("create_workflow")
        started_at = perf_counter()

        # Dedup: if this conversation already built a workflow with this name,
        # update it instead of creating a duplicate (the agent often rebuilds the
        # same automation after each clarification answer).
        existing_id = ctx.deps.conversation_workflows.get(name)

        try:
            existing = await _dedup_existing_workflow(existing_id)
            (
                validated_nodes,
                validated_connections,
                runtime_schema,
                requested_connections,
            ) = _validated_create_or_dedup_workflow(
                nodes,
                connections,
                input_schema,
                existing,
            )
            node_dicts = dump_workflow_nodes(validated_nodes)
            if existing_id and existing is not None:
                ctx.deps.mark_replay_unsafe("create_workflow")
                workflow = await n8n_client.update_workflow(
                    workflow_id=existing_id,
                    name=name,
                    nodes=node_dicts,
                    connections=(
                        validated_connections if requested_connections is not None else None
                    ),
                    settings=None,
                )
                log.info(
                    "create_workflow_deduped_to_update",
                    name=name,
                    workflow_id=existing_id,
                    conversation_id=ctx.deps.conversation_id,
                )
            else:
                if existing_id:
                    # Remembered workflow was deleted -> forget the stale id.
                    ctx.deps.conversation_workflows.pop(name, None)
                    log.info(
                        "create_workflow_stale_dedup_recreate",
                        name=name,
                        workflow_id=existing_id,
                        conversation_id=ctx.deps.conversation_id,
                    )
                ctx.deps.mark_replay_unsafe("create_workflow")
                workflow = await n8n_client.create_workflow(
                    name=name,
                    nodes=node_dicts,
                    connections=validated_connections,
                )
        except Exception as exc:
            log.error("tool_error", tool="create_workflow", error=str(exc))
            result = {"error": _safe_error(exc)}
            _log_tool_finished("create_workflow", started_at, result)
            return result

        ctx.deps.conversation_workflows[name] = workflow.id

        await save_workflow_output_metadata(
            ctx.deps.user_id,
            workflow.id,
            input_schema_payload=_input_schema_payload(runtime_schema),
            output_schema=output_schema,
        )

        await ctx.deps.emit_attachment(
            WorkflowPreviewAttachment(
                data=WorkflowPreviewData(
                    id=workflow.id,
                    name=workflow.name,
                    nodeCount=len(node_dicts),
                    status="active" if workflow.active else "inactive",
                )
            )
        )
        full_workflow = await n8n_client.get_workflow(workflow.id)
        readiness = await _emit_missing_credentials(ctx, full_workflow)
        workflow_timezone = _effective_workflow_timezone(full_workflow)
        result = _workflow_result_with_readiness(
            workflow,
            readiness,
            timezone=workflow_timezone,
        )
        if _should_run_sandbox_test(result, awaiting=ctx.deps.awaiting_user_input):
            # Lazy import: tools/__init__ imports factory, and sandbox_gate
            # imports back into the tools package — importing it here (not at
            # module top) avoids that cycle.
            from src.agent.tools.sandbox_gate import _test_and_gate

            result = await _test_and_gate(ctx, full_workflow, name, result)
        ctx.deps.record_claim_evidence("workflow_created", workflow_id=workflow.id)
        _log_tool_finished("create_workflow", started_at, result)
        return result

    @agent.tool
    async def update_workflow(
        ctx: RunContext[AgentDeps],
        workflow_id: str,
        name: str,
        nodes: list[WorkflowNode],
        connections: dict[str, Any] | None = None,
        input_schema: list[WorkflowInputField] | None = None,
        output_schema: list[WorkflowOutputField] | None = None,
    ) -> dict[str, Any]:
        """Update an existing workflow with compact n8n JSON.

        First call get_workflow, then pass the full updated node structure. Existing
        connections are preserved when connections is omitted or empty; topology
        changes must pass the complete non-empty connection structure. Same
        compact-JSON contract and auto-repair as create_workflow
        (boilerplate filled, AI sub-nodes wired to ai_* ports, webhook inputs
        read as $json.body.<field>).
        When the workflow returns data to the user, pass output_schema (named
        fields + friendly labels + format) and make the final node output
        exactly those names.
        """

        if ctx.deps.awaiting_user_input:
            return _waiting_for_user_input_result()
        await ctx.deps.emit_tool_call("update_workflow")
        started_at = perf_counter()
        try:
            existing_workflow = await n8n_client.get_workflow(workflow_id)
        except Exception as exc:
            log.error("tool_error", tool="update_workflow", error=str(exc))
            result = {"error": _safe_error(exc)}
            _log_tool_finished("update_workflow", started_at, result)
            return result

        requested_connections = connections or None
        existing_connections = existing_workflow.get("connections")
        validated_nodes, validated_connections, runtime_schema = _validated_runtime_workflow(
            nodes,
            requested_connections,
            input_schema,
            fallback_connections=(
                existing_connections if isinstance(existing_connections, dict) else {}
            ),
            infer_missing_connections=requested_connections is not None,
        )
        node_dicts = dump_workflow_nodes(validated_nodes)

        try:
            ctx.deps.mark_replay_unsafe("update_workflow")
            workflow = await n8n_client.update_workflow(
                workflow_id=workflow_id,
                name=name,
                nodes=node_dicts,
                connections=(validated_connections if requested_connections is not None else None),
                settings=None,
            )
        except Exception as exc:
            log.error("tool_error", tool="update_workflow", error=str(exc))
            result = {"error": _safe_error(exc)}
            _log_tool_finished("update_workflow", started_at, result)
            return result

        await save_workflow_output_metadata(
            ctx.deps.user_id,
            workflow.id,
            input_schema_payload=_input_schema_payload(runtime_schema),
            output_schema=output_schema,
        )

        await ctx.deps.emit_attachment(
            WorkflowPreviewAttachment(
                data=WorkflowPreviewData(
                    id=workflow.id,
                    name=workflow.name,
                    nodeCount=len(node_dicts),
                    status="active" if workflow.active else "inactive",
                )
            )
        )
        full_workflow = await n8n_client.get_workflow(workflow.id)
        readiness = await _emit_missing_credentials(ctx, full_workflow)
        workflow_timezone = _effective_workflow_timezone(full_workflow)
        result = _workflow_result_with_readiness(
            workflow,
            readiness,
            timezone=workflow_timezone,
        )
        if _should_run_sandbox_test(result, awaiting=ctx.deps.awaiting_user_input):
            # Lazy import: tools/__init__ imports factory, and sandbox_gate
            # imports back into the tools package — importing it here (not at
            # module top) avoids that cycle.
            from src.agent.tools.sandbox_gate import _test_and_gate

            result = await _test_and_gate(ctx, full_workflow, name, result)
        ctx.deps.record_claim_evidence("workflow_created", workflow_id=workflow.id)
        _log_tool_finished("update_workflow", started_at, result)
        return result

    @agent.tool
    async def activate_workflow(ctx: RunContext[AgentDeps], workflow_id: str) -> dict[str, Any]:
        """Activate a workflow trigger; activation alone does not verify a real run."""

        if ctx.deps.awaiting_user_input:
            return _waiting_for_user_input_result()
        await ctx.deps.emit_tool_call("activate_workflow")
        started_at = perf_counter()
        try:
            workflow = await _get_workflow_for_reference(workflow_id)
            workflow_id = str(workflow.get("id") or workflow_id)
            readiness = await _emit_missing_credentials(
                ctx, workflow, replay_unsafe_tool="activate_workflow"
            )
            block = _readiness_block_result(workflow_id, readiness)
            if block:
                _log_tool_finished("activate_workflow", started_at, block)
                return block
            metadata = await store.get_workflow_metadata(ctx.deps.user_id, workflow_id)
            test_status = metadata.resources.get("test_status") if metadata else None
            assurance = metadata.resources.get("assurance") if metadata else None
            test_coverage = assurance.get("coverage") if isinstance(assurance, dict) else None
            if _needs_pretest(metadata, workflow):
                gate = await _run_pretest_gate(ctx, workflow)
                if gate.get("test_status") == "needs_attention":
                    gate["success"] = False
                    gate["workflow_id"] = workflow_id
                    _log_tool_finished("activate_workflow", started_at, gate)
                    return gate
                test_status = gate.get("test_status") or test_status
                test_coverage = gate.get("test_coverage") or test_coverage
            ctx.deps.mark_replay_unsafe("activate_workflow")
            await n8n_client.activate_workflow(workflow_id)
            ctx.deps.record_claim_evidence("workflow_activated", workflow_id=workflow_id)
            result = {
                "success": True,
                "workflow_id": workflow_id,
                "test_status": test_status,
                "test_coverage": test_coverage,
                "run_verified": False,
                "instruction": (
                    "The workflow trigger is active, but activation is not execution evidence. "
                    "You may say it is active; do not claim external data was sent or written "
                    "until execute_workflow or inspect_execution verifies a real run."
                ),
            }
            _log_tool_finished("activate_workflow", started_at, result)
            return result
        except Exception as exc:
            log.error("tool_error", tool="activate_workflow", error=str(exc))
            result = {"error": _safe_error(exc)}
            _log_tool_finished("activate_workflow", started_at, result)
            return result

    @agent.tool
    async def deactivate_workflow(ctx: RunContext[AgentDeps], workflow_id: str) -> dict[str, Any]:
        """Deactivate a workflow so it stops running automatically."""

        if ctx.deps.awaiting_user_input:
            return _waiting_for_user_input_result()
        await ctx.deps.emit_tool_call("deactivate_workflow")
        started_at = perf_counter()
        try:
            ctx.deps.mark_replay_unsafe("deactivate_workflow")
            await n8n_client.deactivate_workflow(workflow_id)
            result = {"success": True, "workflow_id": workflow_id}
            _log_tool_finished("deactivate_workflow", started_at, result)
            return result
        except Exception as exc:
            log.error("tool_error", tool="deactivate_workflow", error=str(exc))
            result = {"error": _safe_error(exc)}
            _log_tool_finished("deactivate_workflow", started_at, result)
            return result

    @agent.tool
    async def execute_workflow(
        ctx: RunContext[AgentDeps],
        workflow_id: str,
        input: dict[str, Any] | None = None,
        preview_token: str | None = None,
    ) -> dict[str, Any]:
        """Preview and run a workflow with optional runtime input.

        Side-effect workflows first create a one-use approval request. After
        the user confirms in their next message, call this tool for the same
        workflow; the exact token is restored from the structured response.
        Never invent or reuse a token.
        """

        if ctx.deps.awaiting_user_input:
            return _waiting_for_user_input_result()
        await ctx.deps.emit_tool_call("execute_workflow")
        started_at = perf_counter()
        try:
            workflow = await _get_workflow_for_reference(workflow_id)
            workflow_id = str(workflow.get("id") or workflow_id)
            preview_token, preview_cancelled = _take_workflow_preview_decision(
                ctx.deps, workflow_id, preview_token
            )
            if preview_cancelled:
                result = {
                    "success": False,
                    "status": "cancelled",
                    "workflow_id": workflow_id,
                    "functional_status": "unknown",
                    "instruction": "The user cancelled the approved run. Do not execute it.",
                }
                _log_tool_finished("execute_workflow", started_at, result)
                return result
            readiness = await _emit_missing_credentials(
                ctx, workflow, replay_unsafe_tool="execute_workflow"
            )
            block = _readiness_block_result(workflow_id, readiness)
            if block:
                _log_tool_finished("execute_workflow", started_at, block)
                return block

            metadata = await store.get_workflow_metadata(ctx.deps.user_id, workflow_id)
            input_schema = _workflow_input_schema_from_metadata(metadata)
            _validated, missing = _validated_workflow_input(input_schema, input)
            if missing:
                first_missing = missing[0]
                first_label = next(
                    (field.label for field in input_schema if field.name == first_missing),
                    first_missing,
                )
                await request_user_input(
                    ctx,
                    question=f"What should I use for {first_label}?",
                    missing_fields=[first_label],
                    choices=None,
                    allow_skip=False,
                    reason="This workflow needs runtime input before it can run.",
                )
                result = _waiting_for_user_input_result()
                _log_tool_finished("execute_workflow", started_at, result)
                return result

            # Test-before-execute: a workflow that was credential-blocked at build
            # time never got sandbox-tested. Run the test now (once) before the
            # real run; a structural failure drives a fix (ModelRetry) or blocks
            # the real execution rather than producing a bad side effect.
            if _needs_pretest(metadata, workflow):
                gate = await _run_pretest_gate(ctx, workflow, input_payload=input)
                if gate.get("test_status") == "needs_attention":
                    gate["success"] = False
                    gate["workflow_id"] = workflow_id
                    _log_tool_finished("execute_workflow", started_at, gate)
                    return gate

            from src.agent.workflow_preview import (
                consume_workflow_preview,
                preview_workflow_run,
                workflow_requires_preview,
            )

            if workflow_requires_preview(workflow):
                if not preview_token:
                    preview = await preview_workflow_run(
                        workflow,
                        user_id=ctx.deps.user_id,
                        input_payload=input,
                    )
                    if not preview.get("ready") or not preview.get("preview_token"):
                        result = {
                            "success": False,
                            "workflow_id": workflow_id,
                            "functional_status": "needs_attention",
                            "preview": preview,
                            "error": "The safe production preview did not pass.",
                        }
                        _log_tool_finished("execute_workflow", started_at, result)
                        return result
                    result = await _request_workflow_run_approval(
                        ctx,
                        workflow_id=workflow_id,
                        preview=preview,
                    )
                    _log_tool_finished("execute_workflow", started_at, result)
                    return result
                approved = await consume_workflow_preview(
                    workflow,
                    user_id=ctx.deps.user_id,
                    input_payload=input,
                    preview_token=preview_token,
                )
                if not approved:
                    # A consumed, expired or stale approval is terminal for this
                    # turn. Do not silently create another preview and trap the
                    # user in a repeated confirmation loop.
                    ctx.deps.awaiting_user_input = True
                    result = {
                        "success": False,
                        "workflow_id": workflow_id,
                        "functional_status": "needs_attention",
                        "approval_status": "invalid",
                        "error": (
                            "The preview token is missing, expired, consumed, or stale. "
                            "The workflow was not run. Start a new preview in a new turn."
                        ),
                        "instruction": (
                            "Stop this turn. Explain that the approval expired or no longer "
                            "matches; do not call execute_workflow again until the user asks "
                            "for a fresh preview."
                        ),
                    }
                    _log_tool_finished("execute_workflow", started_at, result)
                    return result

            ctx.deps.mark_replay_unsafe("execute_workflow")
            result = await run_workflow_with_input(
                workflow,
                user_id=ctx.deps.user_id,
                input_payload=input,
            )
            # Bound repeated real-execution failures: after the 2nd failure for the
            # same workflow, stop and surface the error instead of letting the model
            # thrash execute/rebuild until the request budget is exhausted.
            stop = execution_retry_guard(ctx.deps.workflow_execution_failures, workflow_id, result)
            if stop is not None:
                _log_tool_finished("execute_workflow", started_at, stop)
                return stop
            for artifact in result.artifacts:
                await ctx.deps.emit_attachment(ArtifactPreviewAttachment(data=artifact))
            payload = result.model_dump(exclude_none=True)
            verified_effects = [
                item.verifier
                for item in result.assessment.evidence
                if item.effectVerified and item.verifier
            ]
            ctx.deps.record_claim_evidence(
                result.claimableOutcome,
                workflow_id=result.workflowId,
                execution_id=result.executionId,
                effects=verified_effects,
            )
            _log_tool_finished("execute_workflow", started_at, payload)
            return payload
        except ModelRetry:
            # Let the sandbox self-repair feedback reach the model — must not be
            # swallowed by the generic handlers below.
            raise
        except ValueError as exc:
            result = {"success": False, "workflow_id": workflow_id, "error": str(exc)}
            _log_tool_finished("execute_workflow", started_at, result)
            return result
        except Exception as exc:
            log.error("tool_error", tool="execute_workflow", error=str(exc))
            result = {"error": _safe_error(exc)}
            _log_tool_finished("execute_workflow", started_at, result)
            return result

    @agent.tool
    async def analyze_workflow_readiness(
        ctx: RunContext[AgentDeps], workflow_id: str
    ) -> dict[str, Any]:
        """Check whether a workflow has credentials and can be run by Conduut."""

        await ctx.deps.emit_tool_call("analyze_workflow_readiness")
        started_at = perf_counter()
        try:
            workflow = await _get_workflow_for_reference(workflow_id)
            readiness = await analyze_workflow_readiness_payload(
                workflow,
                user_id=ctx.deps.user_id,
                before_mutation=lambda: ctx.deps.mark_replay_unsafe("analyze_workflow_readiness"),
            )
            for attachment in readiness["missing_credentials"]:
                await ctx.deps.emit_attachment(attachment)
            if readiness["missing_credentials"]:
                ctx.deps.awaiting_user_input = True
            suggestions = readiness.get("reuse_candidates", [])
            research = readiness.get("research_candidates", [])
            if readiness["missing_credentials"]:
                instruction = _missing_credentials_instruction()
            elif research:
                instruction = _research_credential_instruction()
            elif suggestions:
                instruction = _credential_suggestion_instruction()
            else:
                instruction = "No missing credentials were found."
            result = {
                "ready": readiness["ready"],
                "testable": readiness["testable"],
                "missing_credentials": len(readiness["missing_credentials"]),
                "instruction": instruction,
            }
            if suggestions:
                result["credential_suggestions"] = suggestions
            if research:
                result["needs_api_credential"] = research
            _log_tool_finished("analyze_workflow_readiness", started_at, result)
            return result
        except Exception as exc:
            log.error("tool_error", tool="analyze_workflow_readiness", error=str(exc))
            result = {"error": _safe_error(exc)}
            _log_tool_finished("analyze_workflow_readiness", started_at, result)
            return result

    @agent.tool
    async def inspect_execution(ctx: RunContext[AgentDeps], execution_id: str) -> dict[str, Any]:
        """Read an n8n execution and return a summarized result."""

        await ctx.deps.emit_tool_call("inspect_execution")
        started_at = perf_counter()
        try:
            result = await executions.inspect_run(ctx.deps.user_id, execution_id)
            payload = result.model_dump(exclude_none=True)
            verified_effects = [
                item.verifier
                for item in result.assessment.evidence
                if item.effectVerified and item.verifier
            ]
            ctx.deps.record_claim_evidence(
                result.claimableOutcome,
                workflow_id=result.workflowId,
                execution_id=result.executionId or execution_id,
                effects=verified_effects,
            )
            _log_tool_finished("inspect_execution", started_at, payload)
            return payload
        except Exception as exc:
            log.error("tool_error", tool="inspect_execution", error=str(exc))
            result = {"error": _safe_error(exc)}
            _log_tool_finished("inspect_execution", started_at, result)
            return result

    @agent.tool
    async def list_executions(
        ctx: RunContext[AgentDeps], workflow_id: str | None = None
    ) -> list[dict[str, Any]]:
        """List recent workflow execution history."""

        await ctx.deps.emit_tool_call("list_executions")
        started_at = perf_counter()
        try:
            page = await executions.list_runs(
                ctx.deps.user_id,
                workflow_id=workflow_id,
                limit=10,
            )
        except Exception as exc:
            log.error("tool_error", tool="list_executions", error=str(exc))
            result = [{"error": _safe_error(exc)}]
            _log_tool_finished("list_executions", started_at, result)
            return result
        result = [execution.model_dump(exclude_none=True) for execution in page.executions]
        _log_tool_finished("list_executions", started_at, result)
        return result

    @agent.tool
    async def delete_workflow(ctx: RunContext[AgentDeps], workflow_id: str) -> dict[str, Any]:
        """Permanently delete a workflow."""

        if ctx.deps.awaiting_user_input:
            return _waiting_for_user_input_result()
        await ctx.deps.emit_tool_call("delete_workflow")
        started_at = perf_counter()
        try:
            ctx.deps.mark_replay_unsafe("delete_workflow")
            await n8n_client.delete_workflow(workflow_id)
            result = {"success": True, "workflow_id": workflow_id}
            _log_tool_finished("delete_workflow", started_at, result)
            return result
        except Exception as exc:
            log.error("tool_error", tool="delete_workflow", error=str(exc))
            result = {"error": _safe_error(exc)}
            _log_tool_finished("delete_workflow", started_at, result)
            return result

    @agent.tool
    async def list_credentials(
        ctx: RunContext[AgentDeps],
        url: str | None = None,
        credential_type: str | None = None,
    ) -> dict[str, Any]:
        """List the user's saved credentials (labels/types/hosts only, never secrets).

        Pass the HTTP node URL to flag host matches, or credential_type (e.g.
        openAiApi) to flag the saved credential a service node can reuse.
        """

        await ctx.deps.emit_tool_call("list_credentials")
        started_at = perf_counter()
        result = await list_credentials_payload(ctx.deps, url, credential_type)
        _log_tool_finished("list_credentials", started_at, result)
        return result

    @agent.tool
    async def attach_credential(
        ctx: RunContext[AgentDeps],
        workflow_id: str,
        node_name: str,
        credential_id: str,
    ) -> dict[str, Any]:
        """Attach a saved custom credential to a workflow node after the user confirms.

        Use the credential_id from list_credentials or a create/update result's
        credential_suggestions. Only call this once the user has confirmed.
        """

        await ctx.deps.emit_tool_call("attach_credential")
        started_at = perf_counter()
        ctx.deps.mark_replay_unsafe("attach_credential")
        result = await attach_credential_payload(ctx.deps, workflow_id, node_name, credential_id)
        _log_tool_finished("attach_credential", started_at, result)
        return result

    @agent.tool
    async def prepare_api_credential(
        ctx: RunContext[AgentDeps],
        api_or_url: str,
        workflow_id: str | None = None,
        node_name: str | None = None,
    ) -> dict[str, Any]:
        """Research how an API authenticates and prepare a credential for the user.

        Call this when an HTTP node needs auth and there is no saved credential, or
        when the user asks to connect to an API. It researches the auth scheme (web
        search) and creates a draft credential; the user only enters the secret. The
        secret never passes through you. Pass workflow_id/node_name to attach on
        completion. See the result 'status' and 'instruction'.
        """

        await ctx.deps.emit_tool_call("prepare_api_credential")
        started_at = perf_counter()
        try:
            ctx.deps.mark_replay_unsafe("prepare_api_credential")
            result = await prepare_api_credential_payload(
                ctx.deps, api_or_url, workflow_id, node_name
            )
        except Exception as exc:
            log.error("tool_error", tool="prepare_api_credential", error=str(exc))
            result = {"error": _safe_error(exc)}
            _log_tool_finished("prepare_api_credential", started_at, result)
            return result
        card = result.pop("card", None)
        if card is not None:
            await ctx.deps.emit_attachment(card)
            ctx.deps.awaiting_user_input = True
        _log_tool_finished("prepare_api_credential", started_at, result)
        return result

    @agent.tool
    async def add_service_credential(
        ctx: RunContext[AgentDeps],
        service_or_type: str,
        workflow_id: str | None = None,
        node_name: str | None = None,
    ) -> dict[str, Any]:
        """Show a form to save a predefined n8n service credential (e.g. OpenAI).

        Use when a node needs a known service credential (openAiApi, anthropicApi,
        slackApi, ...) and none is saved, or when the user asks to add one. The
        user enters the secret in the card; it never passes through you. Pass
        workflow_id/node_name to help attach it afterward.
        """

        await ctx.deps.emit_tool_call("add_service_credential")
        started_at = perf_counter()
        try:
            ctx.deps.mark_replay_unsafe("add_service_credential")
            result = await add_service_credential_payload(
                ctx.deps, service_or_type, workflow_id, node_name
            )
        except Exception as exc:
            log.error("tool_error", tool="add_service_credential", error=str(exc))
            result = {"error": _safe_error(exc)}
            _log_tool_finished("add_service_credential", started_at, result)
            return result
        card = result.pop("card", None)
        if card is not None:
            await ctx.deps.emit_attachment(card)
            ctx.deps.awaiting_user_input = True
        _log_tool_finished("add_service_credential", started_at, result)
        return result

    return agent
