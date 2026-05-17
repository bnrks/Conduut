"""Pydantic AI agent factory and tool registrations."""

from time import perf_counter
from typing import Any

import structlog
from pydantic_ai import Agent, RunContext

from src import n8n_client, store
from src.agent.schemas import (
    AgentDeps,
    UserInputChoice,
    UserInputRequestAttachment,
    UserInputRequestData,
    WorkflowInputField,
    WorkflowNode,
    WorkflowPlan,
    WorkflowPreviewAttachment,
    WorkflowPreviewData,
    WorkflowSpec,
    dump_workflow_nodes,
)
from src.agent.tools.common import (
    _missing_credentials_instruction,
    _safe_error,
    _waiting_for_user_input_result,
)
from src.agent.tools.execution import _summarize_execution
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
from src.agent.tools.spec_compiler import (
    create_workflow_from_plan_payload,
    create_workflow_from_spec_payload,
)
from src.agent.tools.validation import _validated_runtime_workflow
from src.agent.tools.workflow_runner import run_workflow_with_input
from src.registry import registry

log = structlog.get_logger()


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


def create_agent(model: Any) -> Agent[AgentDeps, str]:
    """Create a Conduut Pydantic AI agent with all n8n tools registered."""

    agent: Agent[AgentDeps, str] = Agent(
        model,
        deps_type=AgentDeps,
        output_type=str,
        instructions=SYSTEM_PROMPT,
        retries=2,
        tool_timeout=60.0,
    )

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
    async def create_workflow_from_plan(
        ctx: RunContext[AgentDeps],
        name: str,
        plan: WorkflowPlan,
    ) -> dict[str, Any]:
        """Create a supported workflow from semantic WorkflowPlan action graph."""

        if ctx.deps.awaiting_user_input:
            return _waiting_for_user_input_result()
        await ctx.deps.emit_tool_call("create_workflow_from_plan")
        started_at = perf_counter()
        result = await create_workflow_from_plan_payload(
            ctx.deps,
            name,
            plan,
        )
        _log_tool_finished("create_workflow_from_plan", started_at, result)
        return result

    @agent.tool
    async def create_workflow_from_spec(
        ctx: RunContext[AgentDeps],
        name: str,
        spec: WorkflowSpec,
        input_schema: list[WorkflowInputField] | None = None,
    ) -> dict[str, Any]:
        """Create a supported workflow from compact WorkflowSpec IR."""

        if ctx.deps.awaiting_user_input:
            return _waiting_for_user_input_result()
        await ctx.deps.emit_tool_call("create_workflow_from_spec")
        started_at = perf_counter()
        result = await create_workflow_from_spec_payload(
            ctx.deps,
            name,
            spec,
            input_schema,
        )
        _log_tool_finished("create_workflow_from_spec", started_at, result)
        return result

    @agent.tool
    async def create_workflow(
        ctx: RunContext[AgentDeps],
        name: str,
        nodes: list[WorkflowNode],
        connections: dict[str, Any],
        input_schema: list[WorkflowInputField] | None = None,
    ) -> dict[str, Any]:
        """Create a new n8n workflow after validating nodes and connections."""

        if ctx.deps.awaiting_user_input:
            return _waiting_for_user_input_result()
        await ctx.deps.emit_tool_call("create_workflow")
        started_at = perf_counter()
        validated_nodes, validated_connections, runtime_schema = _validated_runtime_workflow(
            nodes,
            connections,
            input_schema,
        )
        node_dicts = dump_workflow_nodes(validated_nodes)

        try:
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

        await store.save_workflow_metadata(
            ctx.deps.user_id,
            workflow.id,
            input_schema=_input_schema_payload(runtime_schema),
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
        missing_count = await _emit_missing_credentials(ctx, full_workflow)
        if missing_count:
            result = {
                "id": workflow.id,
                "name": workflow.name,
                "active": workflow.active,
                "ready": False,
                "missing_credentials": missing_count,
                "instruction": _missing_credentials_instruction(),
            }
            _log_tool_finished("create_workflow", started_at, result)
            return result
        result = {"id": workflow.id, "name": workflow.name, "active": workflow.active}
        _log_tool_finished("create_workflow", started_at, result)
        return result

    @agent.tool
    async def update_workflow(
        ctx: RunContext[AgentDeps],
        workflow_id: str,
        name: str,
        nodes: list[WorkflowNode],
        connections: dict[str, Any],
        input_schema: list[WorkflowInputField] | None = None,
    ) -> dict[str, Any]:
        """Update an existing n8n workflow with the complete validated structure."""

        if ctx.deps.awaiting_user_input:
            return _waiting_for_user_input_result()
        await ctx.deps.emit_tool_call("update_workflow")
        started_at = perf_counter()
        validated_nodes, validated_connections, runtime_schema = _validated_runtime_workflow(
            nodes,
            connections,
            input_schema,
        )
        node_dicts = dump_workflow_nodes(validated_nodes)

        try:
            existing_workflow = await n8n_client.get_workflow(workflow_id)
            workflow = await n8n_client.update_workflow(
                workflow_id=workflow_id,
                name=name,
                nodes=node_dicts,
                connections=validated_connections,
                settings=(
                    existing_workflow.get("settings")
                    if isinstance(existing_workflow.get("settings"), dict)
                    else None
                ),
            )
        except Exception as exc:
            log.error("tool_error", tool="update_workflow", error=str(exc))
            result = {"error": _safe_error(exc)}
            _log_tool_finished("update_workflow", started_at, result)
            return result

        await store.save_workflow_metadata(
            ctx.deps.user_id,
            workflow.id,
            input_schema=_input_schema_payload(runtime_schema),
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
        missing_count = await _emit_missing_credentials(ctx, full_workflow)
        if missing_count:
            result = {
                "id": workflow.id,
                "name": workflow.name,
                "active": workflow.active,
                "ready": False,
                "missing_credentials": missing_count,
                "instruction": _missing_credentials_instruction(),
            }
            _log_tool_finished("update_workflow", started_at, result)
            return result
        result = {"id": workflow.id, "name": workflow.name, "active": workflow.active}
        _log_tool_finished("update_workflow", started_at, result)
        return result

    @agent.tool
    async def activate_workflow(ctx: RunContext[AgentDeps], workflow_id: str) -> dict[str, Any]:
        """Activate a workflow so it runs automatically on its trigger."""

        if ctx.deps.awaiting_user_input:
            return _waiting_for_user_input_result()
        await ctx.deps.emit_tool_call("activate_workflow")
        started_at = perf_counter()
        try:
            workflow = await _get_workflow_for_reference(workflow_id)
            workflow_id = str(workflow.get("id") or workflow_id)
            missing_count = await _emit_missing_credentials(ctx, workflow)
            if missing_count:
                result = {
                    "success": False,
                    "workflow_id": workflow_id,
                    "error": "Missing credentials. Ask the user to submit the credential request.",
                    "instruction": _missing_credentials_instruction(),
                }
                _log_tool_finished("activate_workflow", started_at, result)
                return result
            await n8n_client.activate_workflow(workflow_id)
            result = {"success": True, "workflow_id": workflow_id}
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
    ) -> dict[str, Any]:
        """Run a testable workflow with optional runtime input and summarize the result."""

        if ctx.deps.awaiting_user_input:
            return _waiting_for_user_input_result()
        await ctx.deps.emit_tool_call("execute_workflow")
        started_at = perf_counter()
        try:
            workflow = await _get_workflow_for_reference(workflow_id)
            workflow_id = str(workflow.get("id") or workflow_id)
            missing_count = await _emit_missing_credentials(ctx, workflow)
            if missing_count:
                result = {
                    "success": False,
                    "workflow_id": workflow_id,
                    "error": "Missing credentials. Ask the user to submit the credential request.",
                    "instruction": _missing_credentials_instruction(),
                }
                _log_tool_finished("execute_workflow", started_at, result)
                return result

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

            result = await run_workflow_with_input(
                workflow,
                user_id=ctx.deps.user_id,
                input_payload=input,
            )
            payload = result.model_dump(exclude_none=True)
            _log_tool_finished("execute_workflow", started_at, payload)
            return payload
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
            readiness = await analyze_workflow_readiness_payload(workflow, user_id=ctx.deps.user_id)
            for attachment in readiness["missing_credentials"]:
                await ctx.deps.emit_attachment(attachment)
            if readiness["missing_credentials"]:
                ctx.deps.awaiting_user_input = True
            result = {
                "ready": readiness["ready"],
                "testable": readiness["testable"],
                "missing_credentials": len(readiness["missing_credentials"]),
                "instruction": (
                    _missing_credentials_instruction()
                    if readiness["missing_credentials"]
                    else "No missing credentials were found."
                ),
            }
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
            detail = await n8n_client.get_execution_detail(execution_id)
            result = _summarize_execution(detail)
            payload = result.model_dump(exclude_none=True)
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
            executions = await n8n_client.list_executions(workflow_id=workflow_id, limit=10)
        except Exception as exc:
            log.error("tool_error", tool="list_executions", error=str(exc))
            result = [{"error": _safe_error(exc)}]
            _log_tool_finished("list_executions", started_at, result)
            return result
        result = [
            {
                "id": e.id,
                "workflow_id": e.workflow_id,
                "status": e.status,
                "started_at": e.started_at,
            }
            for e in executions
        ]
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
            await n8n_client.delete_workflow(workflow_id)
            result = {"success": True, "workflow_id": workflow_id}
            _log_tool_finished("delete_workflow", started_at, result)
            return result
        except Exception as exc:
            log.error("tool_error", tool="delete_workflow", error=str(exc))
            result = {"error": _safe_error(exc)}
            _log_tool_finished("delete_workflow", started_at, result)
            return result

    return agent
