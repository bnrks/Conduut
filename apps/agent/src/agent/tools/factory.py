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
from src.agent.runtime_policy import execution_policy_from_deps
from src.agent.schemas import (
    AgentDeps,
    ArtifactPreviewAttachment,
    N8nConnectionPromptAttachment,
    N8nConnectionPromptData,
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
from src.agent.tools.build_pipeline import (
    _validated_runtime_workflow,
    _validated_runtime_workflow_with_dynamic_contracts,
)
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
from src.agent.tools.dynamic_contracts import (
    merge_lookup_resources,
    summarize_node_contract_selection,
    summarize_workflow_card,
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
from src.registry import (
    get_node_contract as registry_get_node_contract,
)
from src.registry import (
    get_workflow_card as registry_get_workflow_card,
)
from src.registry import (
    registry,
)
from src.registry import (
    search_workflow_cards as registry_search_workflow_cards,
)
from src.workflow_test_policy import WORKFLOW_TEST_POLICY_VERSION

log = structlog.get_logger()

_AWAITING_APPROVAL_SUMMARY = (
    "Önizleme hazır. Henüz gerçek bir gönderim veya güncelleme yapılmadı. "
    "Devam etmek ya da vazgeçmek için aşağıdaki onay seçeneklerini kullan."
)
_AWAITING_INPUT_SUMMARY = (
    "Bu işlem devam etmek için kullanıcı girdisi bekliyor. "
    "Henüz doğrulanmış bir çalıştırma veya dış sistem değişikliği yok."
)
_MAX_RUNTIME_PREVIEW_ATTEMPTS = 2


def _n8n_from_deps(deps: AgentDeps):
    if deps.n8n is not None:
        return deps.n8n
    if deps.n8n_error is not None:
        raise deps.n8n_error
    return n8n_client


def _deps_instance_id(deps: AgentDeps) -> str | None:
    target = getattr(deps.n8n_context, "target", None)
    instance_id = getattr(target, "instance_id", None)
    return str(instance_id) if instance_id else None


async def _get_workflow_metadata(
    deps: AgentDeps,
    workflow_id: str,
) -> store.WorkflowMetadata | None:
    return await store.get_workflow_metadata(
        deps.user_id,
        workflow_id,
        instance_id=_deps_instance_id(deps),
    )


async def _get_all_workflow_metadata(
    deps: AgentDeps,
) -> dict[str, store.WorkflowMetadata]:
    return await store.get_all_workflow_metadata(
        deps.user_id,
        instance_id=_deps_instance_id(deps),
    )


async def _ensure_workflow_mutation_allowed(
    deps: AgentDeps,
    workflow_id: str,
    *,
    action: str,
) -> store.WorkflowMetadata | None:
    metadata = await _get_workflow_metadata(deps, workflow_id)
    ownership = getattr(getattr(deps.n8n_context, "target", None), "ownership", "shared_dev")
    if ownership == "customer_owned" and metadata is None:
        raise RuntimeError(
            f"This workflow already exists in your n8n instance but has not been adopted into "
            f"Conduut yet. It is read-only until you adopt it, so I can't {action} it from chat."
        )
    return metadata


def _workflow_baseline_payload(deps: AgentDeps, workflow: dict[str, Any]) -> dict[str, Any]:
    return {
        "instance_id": getattr(getattr(deps.n8n_context, "target", None), "instance_id", ""),
        "workflow_fingerprint": workflow_fingerprint(workflow),
        "workflow_updated_at": str(workflow.get("updatedAt") or ""),
    }


def _workflow_drift_reason(
    metadata: store.WorkflowMetadata | None,
    workflow: dict[str, Any],
    deps: AgentDeps,
) -> str | None:
    if metadata is None:
        return None
    baseline = metadata.resources.get("workflow_baseline")
    if not isinstance(baseline, dict):
        return None
    expected_instance_id = str(baseline.get("instance_id") or "")
    current_instance_id = str(getattr(getattr(deps.n8n_context, "target", None), "instance_id", ""))
    if expected_instance_id and current_instance_id and expected_instance_id != current_instance_id:
        return "The workflow baseline belongs to a different n8n instance."
    expected_updated_at = str(baseline.get("workflow_updated_at") or "")
    current_updated_at = str(workflow.get("updatedAt") or "")
    if expected_updated_at and current_updated_at and expected_updated_at != current_updated_at:
        return "The workflow changed in n8n after Conduut last synced it."
    expected_fingerprint = str(baseline.get("workflow_fingerprint") or "")
    current_fingerprint = workflow_fingerprint(workflow)
    if expected_fingerprint and expected_fingerprint != current_fingerprint:
        return "The workflow structure changed in n8n after Conduut last synced it."
    return None


async def _save_workflow_baseline(deps: AgentDeps, workflow: dict[str, Any]) -> None:
    workflow_id = str(workflow.get("id") or "")
    if not workflow_id:
        return
    metadata = await _get_workflow_metadata(deps, workflow_id)
    if metadata is None:
        return
    resources = dict(metadata.resources)
    baseline = _workflow_baseline_payload(deps, workflow)
    if resources.get("workflow_baseline") == baseline:
        return
    resources["workflow_baseline"] = baseline
    await store.save_workflow_metadata(
        deps.user_id,
        workflow_id,
        input_schema=metadata.input_schema,
        resources=resources,
        instance_id=_deps_instance_id(deps),
    )


async def _emit_n8n_connection_prompt(ctx: RunContext[AgentDeps], message: str) -> dict[str, Any]:
    await ctx.deps.emit_attachment(
        N8nConnectionPromptAttachment(
            data=N8nConnectionPromptData(
                description=message,
            )
        )
    )
    ctx.deps.awaiting_user_input = True
    ctx.deps.awaiting_user_input_summary = (
        "Bu işlem için önce bir n8n bağlantısı gerekiyor. Henüz workflow değişikliği yapılmadı."
    )
    return {
        "success": False,
        "status": "waiting_for_user",
        "code": "n8n_connection_required",
        "error": message,
        "instruction": (
            "Stop now. Ask the user to connect their n8n instance from the connection prompt "
            "before attempting any workflow, execution, credential, or readiness operation."
        ),
    }


async def _require_n8n_tool(ctx: RunContext[AgentDeps], action: str) -> Any | None:
    if ctx.deps.n8n is not None:
        return ctx.deps.n8n
    return await _emit_n8n_connection_prompt(
        ctx,
        f"I can't {action} yet because no active n8n instance is connected for this account.",
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
    preview_basis = str(preview.get("preview_basis") or "safe_sandbox")
    masked_targets = [
        str(action.get("target"))
        for action in preview.get("actions") or []
        if isinstance(action, dict) and action.get("target")
    ]
    target_summary = f" Masked targets: {', '.join(masked_targets[:5])}." if masked_targets else ""
    if preview_basis == "fast_static":
        question = (
            "The static side-effect preview did not execute n8n. It expects "
            f"{preview.get('action_count') or 0} action node(s) and "
            f"{preview.get('writeback_count') or 0} write-back node(s)."
            f"{target_summary} Do you want to run it now?"
        )
    else:
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


async def _gate_failed_workflow_preview(
    deps: AgentDeps,
    *,
    workflow: dict[str, Any],
    preview: dict[str, Any],
    execution_policy: str,
) -> dict[str, Any]:
    """Drive bounded safe-preview repair without duplicating the same sandbox run."""

    workflow_id = str(workflow.get("id") or "")
    findings = [str(item) for item in preview.get("findings") or [] if str(item).strip()]
    if execution_policy == "safe":
        attempts = deps.workflow_test_attempts.get(workflow_id, 0) + 1
        deps.workflow_test_attempts[workflow_id] = attempts
        if attempts < _MAX_RUNTIME_PREVIEW_ATTEMPTS:
            details = "\n".join(f"- {item}" for item in findings) or "- Preview failed."
            raise ModelRetry(
                "The real-input safe preview found a problem before any side effect occurred:\n"
                f"{details}\n\n"
                f"Fix workflow {workflow_id} with update_workflow, then call execute_workflow "
                "again with the same real input. Do not claim it works yet. If the fix needs "
                "missing user information, ask one concise question instead."
            )

        deps.awaiting_user_input = True
        deps.terminal = True
        await store.save_workflow_test_status(
            deps.user_id,
            workflow_id,
            status="needs_attention",
            findings=findings,
            fingerprint=str(preview.get("workflow_fingerprint") or workflow_fingerprint(workflow)),
            coverage=str(preview.get("coverage") or "none"),
        )

    basis = "safe runtime" if execution_policy == "safe" else "fast static"
    return {
        "success": False,
        "workflow_id": workflow_id,
        "functional_status": "needs_attention",
        "preview": preview,
        "error": f"The {basis} preview did not pass.",
        "terminal": execution_policy == "safe",
        "instruction": (
            "Do not claim the workflow is ready or tested. Explain the preview findings "
            "without exposing internal data."
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


def _needs_pretest(
    metadata: store.WorkflowMetadata | None,
    workflow: dict[str, Any] | None = None,
) -> bool:
    """Whether activation still needs fresh runtime evidence."""

    status = metadata.resources.get("test_status") if metadata else None
    if status not in {"passed", "no_action"}:
        return True
    if workflow is None:
        return False
    assurance = metadata.resources.get("assurance") if metadata else None
    version = assurance.get("version") if isinstance(assurance, dict) else None
    if version != WORKFLOW_TEST_POLICY_VERSION:
        return True
    stored = assurance.get("workflow_fingerprint") if isinstance(assurance, dict) else None
    return stored != workflow_fingerprint(workflow)


def _workflow_test_state(
    metadata: store.WorkflowMetadata | None,
    workflow: dict[str, Any] | None = None,
    *,
    default_required: bool = True,
) -> dict[str, Any]:
    """Summarize current sandbox evidence without conflating it with credential readiness."""

    resources = metadata.resources if metadata else {}
    assurance = resources.get("assurance") if isinstance(resources, dict) else None
    test_status = resources.get("test_status") if isinstance(resources, dict) else None
    test_coverage = assurance.get("coverage") if isinstance(assurance, dict) else None
    test_required = _needs_pretest(metadata, workflow) if metadata is not None else default_required
    return {
        "test_status": test_status,
        "test_coverage": test_coverage,
        "test_required": test_required,
        "ready_for_activation": not test_required,
    }


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


def _augment_readiness_result(
    result: dict[str, Any],
    readiness: dict[str, Any],
    *,
    test_state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Add explicit test-readiness dimensions to readiness/tool payloads."""

    credential_ready = (
        readiness.get("missing_count", 0) == 0
        and not readiness.get("reuse_candidates")
        and not readiness.get("research_candidates")
    )
    out = dict(result)
    out["credential_ready"] = credential_ready
    if test_state is None:
        return out
    out["test_required"] = bool(test_state.get("test_required"))
    out["ready_for_activation"] = credential_ready and not out["test_required"]
    if test_state.get("test_status"):
        out["test_status"] = test_state["test_status"]
    if test_state.get("test_coverage"):
        out["test_coverage"] = test_state["test_coverage"]
    return out


async def _dedup_existing_workflow(
    existing_id: str | None,
    *,
    n8n: Any | None = None,
) -> dict[str, Any] | None:
    """The conversation's remembered workflow for create-dedup, or None to create
    fresh. Returns None when there is no remembered id OR the workflow was deleted
    (n8n 404) -- e.g. the user asked to delete and rebuild in the same chat, so the
    dedup id is stale. Without this, create_workflow re-reads the gone id and dies
    with "Not Found" instead of just recreating. Non-404 errors propagate."""

    if not existing_id:
        return None
    try:
        return await (n8n or n8n_client).get_workflow(existing_id)
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


def _lookup_state_bucket(deps: AgentDeps, attr_name: str) -> list[dict[str, Any]]:
    bucket = getattr(deps, attr_name, None)
    if isinstance(bucket, list):
        return bucket
    bucket = []
    setattr(deps, attr_name, bucket)
    return bucket


def _remember_lookup_entry(deps: AgentDeps, attr_name: str, entry: dict[str, Any]) -> None:
    if not entry:
        return
    bucket = _lookup_state_bucket(deps, attr_name)
    identity = (
        str(entry.get("card_id") or entry.get("contract_id") or entry.get("node_name") or ""),
        str(entry.get("hash") or ""),
    )
    for existing in bucket:
        existing_identity = (
            str(
                existing.get("card_id")
                or existing.get("contract_id")
                or existing.get("node_name")
                or ""
            ),
            str(existing.get("hash") or ""),
        )
        if existing_identity == identity:
            return
    bucket.append(entry)


async def _save_workflow_lookup_metadata(
    deps: AgentDeps,
    workflow_id: str,
    lookup_patch: dict[str, Any] | None,
) -> None:
    card_entries = list(_lookup_state_bucket(deps, "_workflow_card_selections"))
    contract_entries = list(_lookup_state_bucket(deps, "_workflow_contract_selections"))
    patch_lookup = lookup_patch.get("lookup") if isinstance(lookup_patch, dict) else None
    if isinstance(patch_lookup, dict):
        contract_entries.extend(
            item for item in (patch_lookup.get("node_contracts") or []) if isinstance(item, dict)
        )
    merged_patch = {
        "lookup": {
            "version": 1,
            "workflow_cards": card_entries,
            "node_contracts": contract_entries,
        }
    }
    metadata = await _get_workflow_metadata(deps, workflow_id)
    if metadata is None:
        return
    resources = merge_lookup_resources(metadata.resources, merged_patch)
    if resources == metadata.resources:
        return
    await store.save_workflow_metadata(
        deps.user_id,
        workflow_id,
        input_schema=metadata.input_schema,
        resources=resources,
        instance_id=_deps_instance_id(deps),
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
    """Replace unsupported claims without exposing an internal correction turn."""

    if not claim_exceeds_evidence(output, deps.claim_evidence):
        return output
    log.warning(
        "agent_claim_exceeds_evidence",
        evidence_outcomes=[item.get("outcome") for item in deps.claim_evidence],
        resolution="deterministic_replacement",
        awaiting_user_input=deps.awaiting_user_input,
    )
    if deps.awaiting_user_input:
        # The persisted attachment is the single source of truth. Retrying the
        # model can issue unrelated tools and make one approval look like two.
        return deps.awaiting_user_input_summary or _AWAITING_INPUT_SUMMARY
    # A ModelRetry is deliberately not used here. Pydantic AI exposes validator
    # retry feedback to the model as another request; models can mistake that
    # internal critic for a user correction ("Haklısınız..."), while the first
    # draft may already have streamed. The sentence stream gate and this final
    # validator share the same deterministic policy, so the safe evidence
    # summary is both the visible and persisted terminal answer.
    return safe_evidence_summary(deps.claim_evidence)


def create_agent(model: Any) -> Agent[AgentDeps, str]:
    """Create a Conduut Pydantic AI agent with all n8n tools registered."""

    agent: Agent[AgentDeps, str] = Agent(
        model,
        deps_type=AgentDeps,
        output_type=str,
        instructions=base_instructions(),
        # Headroom for bounded sandbox/build ModelRetry loops. Final claim
        # validation is deterministic and does not re-enter the model.
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
    async def search_workflow_cards(
        ctx: RunContext[AgentDeps],
        query: str,
        limit: int = 10,
        services: list[str] | None = None,
        capabilities: list[str] | None = None,
        risk_level: str | None = None,
    ) -> dict[str, Any]:
        """Search curated workflow cards for reusable topology and invariants."""

        await ctx.deps.emit_tool_call("search_workflow_cards")
        safe_limit = max(1, min(limit, 10))
        results = registry_search_workflow_cards(
            query,
            limit=safe_limit,
            services=services,
            capabilities=capabilities,
            risk_level=risk_level,
        )
        if not results:
            return {"cards": [], "hint": "No matching workflow cards found. Build from scratch."}
        return {"cards": results, "limit": safe_limit}

    @agent.tool
    async def get_workflow_card(ctx: RunContext[AgentDeps], card_id: str) -> dict[str, Any]:
        """Get one curated workflow card with its topology, constraints, and invariants."""

        await ctx.deps.emit_tool_call("get_workflow_card")
        selected_cards = _lookup_state_bucket(ctx.deps, "_workflow_card_selections")
        selected_ids = {str(item.get("card_id") or "") for item in selected_cards}
        if str(card_id) not in selected_ids and len(selected_ids) >= 3:
            return {
                "error": (
                    "Workflow-card detail budget exhausted. Select and adapt from the "
                    "three cards already inspected."
                ),
                "selectedCardIds": sorted(selected_ids),
            }
        card = registry_get_workflow_card(card_id)
        if not card:
            return {"error": f"Workflow card '{card_id}' was not found."}
        _remember_lookup_entry(
            ctx.deps,
            "_workflow_card_selections",
            summarize_workflow_card(card),
        )
        return card

    @agent.tool
    async def get_node_contract(
        ctx: RunContext[AgentDeps],
        node_type: str,
        type_version: int | float | None = None,
        resource: str | None = None,
        operation: str | None = None,
    ) -> dict[str, Any]:
        """Get a resource/operation-specific node contract when generic schema is insufficient."""

        await ctx.deps.emit_tool_call("get_node_contract")
        contract = registry_get_node_contract(
            node_type,
            type_version=type_version,
            resource=resource,
            operation=operation,
        )
        if not contract:
            return {
                "error": (
                    f"No dynamic contract found for '{node_type}'"
                    f" resource={resource or '-'} operation={operation or '-'}."
                )
            }
        _remember_lookup_entry(
            ctx.deps,
            "_workflow_contract_selections",
            summarize_node_contract_selection(
                node_name=node_type,
                node_type=node_type,
                type_version=type_version,
                resource=resource,
                operation=operation,
                contract=contract,
            ),
        )
        return contract

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
        n8n = await _require_n8n_tool(ctx, "list workflows")
        if isinstance(n8n, dict):
            _log_tool_finished("list_workflows", started_at, n8n)
            return [n8n]
        try:
            workflows = await n8n.list_workflows()
            if str(getattr(n8n, "ownership", "shared_dev") or "shared_dev") == "shared_dev":
                owned_ids = set((await _get_all_workflow_metadata(ctx.deps)).keys())
                workflows = [workflow for workflow in workflows if workflow.id in owned_ids]
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
        n8n = await _require_n8n_tool(ctx, "load this workflow")
        if isinstance(n8n, dict):
            _log_tool_finished("get_workflow", started_at, n8n)
            return n8n
        try:
            result = await _get_workflow_for_reference(
                workflow_id,
                n8n=n8n,
                user_id=ctx.deps.user_id,
            )
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
        n8n = await _require_n8n_tool(ctx, "create a workflow")
        if isinstance(n8n, dict):
            _log_tool_finished("create_workflow", started_at, n8n)
            return n8n

        # Dedup: if this conversation already built a workflow with this name,
        # update it instead of creating a duplicate (the agent often rebuilds the
        # same automation after each clarification answer).
        existing_id = ctx.deps.conversation_workflows.get(name)

        try:
            existing = await _dedup_existing_workflow(existing_id, n8n=n8n)
            requested_connections = connections or None
            (
                validated_nodes,
                validated_connections,
                runtime_schema,
                lookup_patch,
            ) = await _validated_runtime_workflow_with_dynamic_contracts(
                ctx.deps.user_id,
                nodes,
                requested_connections,
                input_schema,
                fallback_connections=(
                    existing.get("connections", {}) if existing is not None else None
                ),
                infer_missing_connections=requested_connections is not None or existing is None,
            )
            node_dicts = dump_workflow_nodes(validated_nodes)
            if existing_id and existing is not None:
                ctx.deps.mark_replay_unsafe("create_workflow")
                workflow = await n8n.update_workflow(
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
                workflow = await n8n.create_workflow(
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
        await _save_workflow_lookup_metadata(ctx.deps, workflow.id, lookup_patch)

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
        full_workflow = await n8n.get_workflow(workflow.id)
        await _save_workflow_baseline(ctx.deps, full_workflow)
        readiness = await _emit_missing_credentials(ctx, full_workflow)
        workflow_timezone = _effective_workflow_timezone(full_workflow)
        result = _workflow_result_with_readiness(
            workflow,
            readiness,
            timezone=workflow_timezone,
        )
        test_state = _workflow_test_state(
            await _get_workflow_metadata(ctx.deps, workflow.id),
            full_workflow,
        )
        result = _augment_readiness_result(result, readiness, test_state=test_state)
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
        n8n = await _require_n8n_tool(ctx, "update this workflow")
        if isinstance(n8n, dict):
            _log_tool_finished("update_workflow", started_at, n8n)
            return n8n
        try:
            existing_workflow = await n8n.get_workflow(workflow_id)
            metadata = await _ensure_workflow_mutation_allowed(
                ctx.deps,
                workflow_id,
                action="update",
            )
            drift_reason = _workflow_drift_reason(metadata, existing_workflow, ctx.deps)
            if drift_reason:
                raise RuntimeError(drift_reason)
        except Exception as exc:
            log.error("tool_error", tool="update_workflow", error=str(exc))
            result = {"error": _safe_error(exc)}
            _log_tool_finished("update_workflow", started_at, result)
            return result

        requested_connections = connections or None
        existing_connections = existing_workflow.get("connections")
        (
            validated_nodes,
            validated_connections,
            runtime_schema,
            lookup_patch,
        ) = await _validated_runtime_workflow_with_dynamic_contracts(
            ctx.deps.user_id,
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
            workflow = await n8n.update_workflow(
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
        await _save_workflow_lookup_metadata(ctx.deps, workflow.id, lookup_patch)

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
        full_workflow = await n8n.get_workflow(workflow.id)
        await _save_workflow_baseline(ctx.deps, full_workflow)
        readiness = await _emit_missing_credentials(ctx, full_workflow)
        workflow_timezone = _effective_workflow_timezone(full_workflow)
        result = _workflow_result_with_readiness(
            workflow,
            readiness,
            timezone=workflow_timezone,
        )
        test_state = _workflow_test_state(
            await _get_workflow_metadata(ctx.deps, workflow.id),
            full_workflow,
        )
        result = _augment_readiness_result(result, readiness, test_state=test_state)
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
        n8n = await _require_n8n_tool(ctx, "activate this workflow")
        if isinstance(n8n, dict):
            _log_tool_finished("activate_workflow", started_at, n8n)
            return n8n
        try:
            workflow = await _get_workflow_for_reference(
                workflow_id,
                n8n=n8n,
                user_id=ctx.deps.user_id,
            )
            metadata = await _ensure_workflow_mutation_allowed(
                ctx.deps,
                workflow_id,
                action="activate",
            )
            drift_reason = _workflow_drift_reason(metadata, workflow, ctx.deps)
            if drift_reason:
                raise RuntimeError(drift_reason)
            workflow_id = str(workflow.get("id") or workflow_id)
            readiness = await _emit_missing_credentials(
                ctx, workflow, replay_unsafe_tool="activate_workflow"
            )
            block = _readiness_block_result(workflow_id, readiness)
            if block:
                _log_tool_finished("activate_workflow", started_at, block)
                return block
            metadata = await _get_workflow_metadata(ctx.deps, workflow_id)
            test_state = _workflow_test_state(metadata, workflow)
            if _needs_pretest(metadata, workflow):
                gate = await _run_pretest_gate(ctx, workflow)
                if (
                    gate.get("test_status") not in {"passed", "no_action"}
                    or gate.get("test_coverage") != "full"
                ):
                    gate["success"] = False
                    gate["workflow_id"] = workflow_id
                    _log_tool_finished("activate_workflow", started_at, gate)
                    return gate
                test_state["test_status"] = gate.get("test_status") or test_state.get("test_status")
                test_state["test_coverage"] = gate.get("test_coverage") or test_state.get(
                    "test_coverage"
                )
                test_state["test_required"] = False
                test_state["ready_for_activation"] = True
            ctx.deps.mark_replay_unsafe("activate_workflow")
            await n8n.activate_workflow(workflow_id)
            await _save_workflow_baseline(ctx.deps, await n8n.get_workflow(workflow_id))
            ctx.deps.record_claim_evidence("workflow_activated", workflow_id=workflow_id)
            result = {
                "success": True,
                "workflow_id": workflow_id,
                "test_status": test_state.get("test_status"),
                "test_coverage": test_state.get("test_coverage"),
                "test_required": False,
                "ready_for_activation": True,
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
        n8n = await _require_n8n_tool(ctx, "deactivate this workflow")
        if isinstance(n8n, dict):
            _log_tool_finished("deactivate_workflow", started_at, n8n)
            return n8n
        try:
            workflow = await n8n.get_workflow(workflow_id)
            metadata = await _ensure_workflow_mutation_allowed(
                ctx.deps,
                workflow_id,
                action="deactivate",
            )
            drift_reason = _workflow_drift_reason(metadata, workflow, ctx.deps)
            if drift_reason:
                raise RuntimeError(drift_reason)
            ctx.deps.mark_replay_unsafe("deactivate_workflow")
            await n8n.deactivate_workflow(workflow_id)
            await _save_workflow_baseline(ctx.deps, await n8n.get_workflow(workflow_id))
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
        n8n = await _require_n8n_tool(ctx, "run this workflow")
        if isinstance(n8n, dict):
            _log_tool_finished("execute_workflow", started_at, n8n)
            return n8n
        try:
            workflow = await _get_workflow_for_reference(
                workflow_id,
                n8n=n8n,
                user_id=ctx.deps.user_id,
            )
            metadata = await _ensure_workflow_mutation_allowed(ctx.deps, workflow_id, action="run")
            drift_reason = _workflow_drift_reason(metadata, workflow, ctx.deps)
            if drift_reason:
                raise RuntimeError(drift_reason)
            workflow_id = str(workflow.get("id") or workflow_id)
            execution_policy = execution_policy_from_deps(ctx.deps)
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

            metadata = await _get_workflow_metadata(ctx.deps, workflow_id)
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

            from src.agent.sandbox import use_n8n_client as sandbox_use_n8n_client
            from src.agent.workflow_preview import (
                consume_workflow_preview,
                preview_workflow_run,
                workflow_requires_preview,
            )

            if workflow_requires_preview(workflow):
                if not preview_token:
                    with sandbox_use_n8n_client(n8n):
                        preview = await preview_workflow_run(
                            workflow,
                            user_id=ctx.deps.user_id,
                            input_payload=input,
                            conversation_id=ctx.deps.conversation_id,
                            execution_policy=execution_policy,
                            instance_id=_deps_instance_id(ctx.deps),
                        )
                    if not preview.get("ready") or not preview.get("preview_token"):
                        result = await _gate_failed_workflow_preview(
                            ctx.deps,
                            workflow=workflow,
                            preview=preview,
                            execution_policy=execution_policy,
                        )
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
                    conversation_id=ctx.deps.conversation_id,
                    execution_policy=execution_policy,
                    instance_id=_deps_instance_id(ctx.deps),
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
                n8n=n8n,
            )
            await _save_workflow_baseline(ctx.deps, await n8n.get_workflow(workflow_id))
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
        n8n = await _require_n8n_tool(ctx, "check workflow readiness")
        if isinstance(n8n, dict):
            _log_tool_finished("analyze_workflow_readiness", started_at, n8n)
            return n8n
        try:
            workflow = await _get_workflow_for_reference(
                workflow_id,
                n8n=n8n,
                user_id=ctx.deps.user_id,
            )
            readiness = await analyze_workflow_readiness_payload(
                workflow,
                user_id=ctx.deps.user_id,
                before_mutation=lambda: ctx.deps.mark_replay_unsafe("analyze_workflow_readiness"),
                n8n=n8n,
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
            test_state = _workflow_test_state(
                await _get_workflow_metadata(ctx.deps, workflow_id),
                workflow,
            )
            if readiness["ready"] and test_state["test_required"]:
                instruction = (
                    "Credentials are ready, but this workflow fingerprint still needs a "
                    "sandbox pretest before activation or a real run can be treated as ready."
                )
            result = {
                "ready": readiness["ready"],
                "testable": readiness["testable"],
                "missing_credentials": len(readiness["missing_credentials"]),
                "instruction": instruction,
            }
            result = _augment_readiness_result(result, readiness, test_state=test_state)
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
        n8n = await _require_n8n_tool(ctx, "inspect this execution")
        if isinstance(n8n, dict):
            _log_tool_finished("inspect_execution", started_at, n8n)
            return n8n
        try:
            result = await executions.inspect_run(ctx.deps.user_id, execution_id, n8n=n8n)
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
        n8n = await _require_n8n_tool(ctx, "list executions")
        if isinstance(n8n, dict):
            _log_tool_finished("list_executions", started_at, n8n)
            return [n8n]
        try:
            page = await executions.list_runs(
                ctx.deps.user_id,
                workflow_id=workflow_id,
                limit=10,
                n8n=n8n,
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
        n8n = await _require_n8n_tool(ctx, "delete this workflow")
        if isinstance(n8n, dict):
            _log_tool_finished("delete_workflow", started_at, n8n)
            return n8n
        try:
            workflow = await n8n.get_workflow(workflow_id)
            metadata = await _ensure_workflow_mutation_allowed(
                ctx.deps,
                workflow_id,
                action="delete",
            )
            drift_reason = _workflow_drift_reason(metadata, workflow, ctx.deps)
            if drift_reason:
                raise RuntimeError(drift_reason)
            ctx.deps.mark_replay_unsafe("delete_workflow")
            await n8n.delete_workflow(workflow_id)
            instance_id = _deps_instance_id(ctx.deps)
            if instance_id:
                await store.delete_workflow_metadata(
                    ctx.deps.user_id,
                    workflow_id,
                    instance_id=instance_id,
                )
            else:
                await store.delete_workflow_metadata(ctx.deps.user_id, workflow_id)
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
        guard = await _require_n8n_tool(ctx, "attach this credential")
        if isinstance(guard, dict):
            _log_tool_finished("attach_credential", started_at, guard)
            return guard
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
