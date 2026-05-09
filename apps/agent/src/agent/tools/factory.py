"""Pydantic AI agent factory and tool registrations."""

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
from src.agent.tools.spec_compiler import create_workflow_from_spec_payload
from src.agent.tools.validation import _validated_runtime_workflow
from src.agent.tools.workflow_runner import run_workflow_with_input
from src.registry import registry

log = structlog.get_logger()


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
        """Ask the user for required missing business information before continuing."""

        normalized_question = question.strip()
        if not normalized_question:
            normalized_question = "What information should I use to continue?"
        normalized_fields = [
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
        await ctx.deps.emit_tool_call("request_user_input")
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
        return {
            "status": "waiting_for_user",
            "question": normalized_question,
            "missing_fields": normalized_fields,
            "choices": [choice.label for choice in normalized_choices],
            "instruction": (
                "Stop now. Ask only this question and wait for the user's next message. "
                "Do not create or update workflows until the user answers."
            ),
        }

    @agent.tool
    async def list_workflows(ctx: RunContext[AgentDeps]) -> list[dict[str, Any]]:
        """List all n8n workflows in the shared MVP instance."""

        await ctx.deps.emit_tool_call("list_workflows")
        try:
            workflows = await n8n_client.list_workflows()
        except Exception as exc:
            log.error("tool_error", tool="list_workflows", error=str(exc))
            return [{"error": _safe_error(exc)}]
        return [{"id": w.id, "name": w.name, "active": w.active} for w in workflows]

    @agent.tool
    async def get_workflow(ctx: RunContext[AgentDeps], workflow_id: str) -> dict[str, Any]:
        """Get the full details and node structure of a specific n8n workflow."""

        await ctx.deps.emit_tool_call("get_workflow")
        try:
            return await n8n_client.get_workflow(workflow_id)
        except Exception as exc:
            log.error("tool_error", tool="get_workflow", error=str(exc))
            return {"error": _safe_error(exc)}

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
        return await create_workflow_from_spec_payload(
            ctx.deps,
            name,
            spec,
            input_schema,
        )

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
            return {"error": _safe_error(exc)}

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
            return {
                "id": workflow.id,
                "name": workflow.name,
                "active": workflow.active,
                "ready": False,
                "missing_credentials": missing_count,
                "instruction": _missing_credentials_instruction(),
            }
        return {"id": workflow.id, "name": workflow.name, "active": workflow.active}

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
            return {"error": _safe_error(exc)}

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
            return {
                "id": workflow.id,
                "name": workflow.name,
                "active": workflow.active,
                "ready": False,
                "missing_credentials": missing_count,
                "instruction": _missing_credentials_instruction(),
            }
        return {"id": workflow.id, "name": workflow.name, "active": workflow.active}

    @agent.tool
    async def activate_workflow(ctx: RunContext[AgentDeps], workflow_id: str) -> dict[str, Any]:
        """Activate a workflow so it runs automatically on its trigger."""

        if ctx.deps.awaiting_user_input:
            return _waiting_for_user_input_result()
        await ctx.deps.emit_tool_call("activate_workflow")
        try:
            workflow = await _get_workflow_for_reference(workflow_id)
            workflow_id = str(workflow.get("id") or workflow_id)
            missing_count = await _emit_missing_credentials(ctx, workflow)
            if missing_count:
                return {
                    "success": False,
                    "workflow_id": workflow_id,
                    "error": "Missing credentials. Ask the user to submit the credential request.",
                    "instruction": _missing_credentials_instruction(),
                }
            await n8n_client.activate_workflow(workflow_id)
            return {"success": True, "workflow_id": workflow_id}
        except Exception as exc:
            log.error("tool_error", tool="activate_workflow", error=str(exc))
            return {"error": _safe_error(exc)}

    @agent.tool
    async def deactivate_workflow(ctx: RunContext[AgentDeps], workflow_id: str) -> dict[str, Any]:
        """Deactivate a workflow so it stops running automatically."""

        if ctx.deps.awaiting_user_input:
            return _waiting_for_user_input_result()
        await ctx.deps.emit_tool_call("deactivate_workflow")
        try:
            await n8n_client.deactivate_workflow(workflow_id)
            return {"success": True, "workflow_id": workflow_id}
        except Exception as exc:
            log.error("tool_error", tool="deactivate_workflow", error=str(exc))
            return {"error": _safe_error(exc)}

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
        try:
            workflow = await _get_workflow_for_reference(workflow_id)
            workflow_id = str(workflow.get("id") or workflow_id)
            missing_count = await _emit_missing_credentials(ctx, workflow)
            if missing_count:
                return {
                    "success": False,
                    "workflow_id": workflow_id,
                    "error": "Missing credentials. Ask the user to submit the credential request.",
                    "instruction": _missing_credentials_instruction(),
                }

            metadata = await store.get_workflow_metadata(ctx.deps.user_id, workflow_id)
            input_schema = _workflow_input_schema_from_metadata(metadata)
            _validated, missing = _validated_workflow_input(input_schema, input)
            if missing:
                missing_labels = [
                    field.label for field in input_schema if field.name in set(missing)
                ]
                await request_user_input(
                    ctx,
                    question=f"What should I use for {', '.join(missing_labels or missing)}?",
                    missing_fields=missing,
                    choices=None,
                    allow_skip=False,
                    reason="This workflow needs runtime input before it can run.",
                )
                return _waiting_for_user_input_result()

            result = await run_workflow_with_input(
                workflow,
                user_id=ctx.deps.user_id,
                input_payload=input,
            )
            return result.model_dump(exclude_none=True)
        except ValueError as exc:
            return {"success": False, "workflow_id": workflow_id, "error": str(exc)}
        except Exception as exc:
            log.error("tool_error", tool="execute_workflow", error=str(exc))
            return {"error": _safe_error(exc)}

    @agent.tool
    async def analyze_workflow_readiness(
        ctx: RunContext[AgentDeps], workflow_id: str
    ) -> dict[str, Any]:
        """Check whether a workflow has credentials and can be run by Conduut."""

        await ctx.deps.emit_tool_call("analyze_workflow_readiness")
        try:
            workflow = await _get_workflow_for_reference(workflow_id)
            readiness = await analyze_workflow_readiness_payload(workflow, user_id=ctx.deps.user_id)
            for attachment in readiness["missing_credentials"]:
                await ctx.deps.emit_attachment(attachment)
            if readiness["missing_credentials"]:
                ctx.deps.awaiting_user_input = True
            return {
                "ready": readiness["ready"],
                "testable": readiness["testable"],
                "missing_credentials": len(readiness["missing_credentials"]),
                "instruction": (
                    _missing_credentials_instruction()
                    if readiness["missing_credentials"]
                    else "No missing credentials were found."
                ),
            }
        except Exception as exc:
            log.error("tool_error", tool="analyze_workflow_readiness", error=str(exc))
            return {"error": _safe_error(exc)}

    @agent.tool
    async def inspect_execution(ctx: RunContext[AgentDeps], execution_id: str) -> dict[str, Any]:
        """Read an n8n execution and return a summarized result."""

        await ctx.deps.emit_tool_call("inspect_execution")
        try:
            detail = await n8n_client.get_execution_detail(execution_id)
            result = _summarize_execution(detail)
            return result.model_dump(exclude_none=True)
        except Exception as exc:
            log.error("tool_error", tool="inspect_execution", error=str(exc))
            return {"error": _safe_error(exc)}

    @agent.tool
    async def list_executions(
        ctx: RunContext[AgentDeps], workflow_id: str | None = None
    ) -> list[dict[str, Any]]:
        """List recent workflow execution history."""

        await ctx.deps.emit_tool_call("list_executions")
        try:
            executions = await n8n_client.list_executions(workflow_id=workflow_id, limit=10)
        except Exception as exc:
            log.error("tool_error", tool="list_executions", error=str(exc))
            return [{"error": _safe_error(exc)}]
        return [
            {
                "id": e.id,
                "workflow_id": e.workflow_id,
                "status": e.status,
                "started_at": e.started_at,
            }
            for e in executions
        ]

    @agent.tool
    async def delete_workflow(ctx: RunContext[AgentDeps], workflow_id: str) -> dict[str, Any]:
        """Permanently delete a workflow."""

        if ctx.deps.awaiting_user_input:
            return _waiting_for_user_input_result()
        await ctx.deps.emit_tool_call("delete_workflow")
        try:
            await n8n_client.delete_workflow(workflow_id)
            return {"success": True, "workflow_id": workflow_id}
        except Exception as exc:
            log.error("tool_error", tool="delete_workflow", error=str(exc))
            return {"error": _safe_error(exc)}

    return agent
