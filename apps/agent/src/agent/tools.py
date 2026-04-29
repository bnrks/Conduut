"""Pydantic AI tool registration for n8n registry and workflow operations."""

from typing import Any

import httpx
import structlog
from pydantic_ai import Agent, ModelRetry, RunContext

from src import n8n_client
from src.agent.schemas import (
    AgentDeps,
    WorkflowNode,
    WorkflowPreviewAttachment,
    WorkflowPreviewData,
    dump_workflow_nodes,
)
from src.agent.validation import (
    normalize_workflow_connections,
    normalize_workflow_nodes,
    validate_workflow_payload,
)
from src.registry import registry

log = structlog.get_logger()

SYSTEM_PROMPT = (
    "You are Conduut, an AI assistant that helps users build and manage n8n workflow"
    " automations.\n\n"
    "You have access to tools to create, manage, and run n8n workflows.\n"
    "When a user asks you to automate something, use the tools to build it for them"
    " immediately. Do not ask for permission before acting.\n\n"
    "Guidelines:\n"
    "- Act directly. When the user asks you to create, update, run, activate, deactivate,"
    " or delete a workflow, use tools and then report what you did.\n"
    "- CREATE vs UPDATE: Use create_workflow only for brand new workflows. If a workflow"
    " already exists, first call get_workflow and then update_workflow with the complete"
    " updated node and connection structure.\n"
    "- Track workflow IDs in the conversation and use those IDs for later operations.\n"
    "- If the user only wants to chat or ask questions, respond normally without tools.\n\n"
    "Building workflows - required process:\n"
    "1. For any service or node you are not 100% certain about, call search_n8n_nodes"
    " before building the workflow.\n"
    "2. Then call get_node_schema for each node to get exact type, typeVersion,"
    " credentials, parameters, and exampleNode.\n"
    "3. Optionally call find_workflow_template for complex workflows.\n"
    "4. Finally call create_workflow or update_workflow.\n\n"
    "Node rules:\n"
    "- Never call create_workflow or update_workflow with an empty nodes array.\n"
    "- Every workflow needs at least one trigger node such as manualTrigger,"
    " scheduleTrigger, or webhook.\n"
    "- Always connect nodes via the connections object; disconnected nodes do nothing.\n"
    "- In connections, source keys and target node values must use node names, not IDs.\n"
    "- Position nodes left-to-right, 250px apart.\n"
    "- Use the exact node type and typeVersion from get_node_schema.\n"
    "- For Edit Fields (Set), add fields through parameters.assignments.assignments. "
    "Do not leave the assignments list empty. A message field should look like "
    "{id: 'message', name: 'message', type: 'string', value: 'hello from Conduut'}."
)


def _safe_error(exc: Exception) -> str:
    if isinstance(exc, httpx.HTTPStatusError):
        status = exc.response.status_code
        method = exc.request.method
        path = exc.request.url.path
        return f"n8n API returned {status} for {method} {path}"
    return str(exc)[:300] or "Tool execution failed"


def _validated_workflow(
    nodes: list[WorkflowNode],
    connections: dict[str, Any],
) -> tuple[list[WorkflowNode], dict[str, Any]]:
    normalized_nodes = normalize_workflow_nodes(nodes)
    normalized_connections = normalize_workflow_connections(connections, normalized_nodes)
    errors = validate_workflow_payload(normalized_nodes, normalized_connections)
    if errors:
        log.warning(
            "workflow_validation_failed",
            errors=errors,
            node_types=[node.type for node in normalized_nodes],
            connection_sources=list(normalized_connections.keys()),
        )
        details = "\n".join(f"- {error}" for error in errors)
        raise ModelRetry(
            f"Workflow validation failed. Fix these issues before retrying:\n{details}"
        )
    return normalized_nodes, normalized_connections


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
    async def search_n8n_nodes(ctx: RunContext[AgentDeps], query: str) -> dict[str, Any]:
        """Search for n8n node types by keyword before building workflow nodes."""

        await ctx.deps.emit_tool_call("search_n8n_nodes")
        results = registry.search_nodes(query)
        if not results:
            return {
                "results": [],
                "hint": (
                    "No nodes found. Try service names or common nodes like "
                    "scheduleTrigger, webhook, httpRequest, set, if, code, gmail, slack."
                ),
            }
        return {"results": results}

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
    async def create_workflow(
        ctx: RunContext[AgentDeps],
        name: str,
        nodes: list[WorkflowNode],
        connections: dict[str, Any],
    ) -> dict[str, Any]:
        """Create a new n8n workflow after validating nodes and connections."""

        await ctx.deps.emit_tool_call("create_workflow")
        validated_nodes, validated_connections = _validated_workflow(nodes, connections)
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
        return {"id": workflow.id, "name": workflow.name, "active": workflow.active}

    @agent.tool
    async def update_workflow(
        ctx: RunContext[AgentDeps],
        workflow_id: str,
        name: str,
        nodes: list[WorkflowNode],
        connections: dict[str, Any],
    ) -> dict[str, Any]:
        """Update an existing n8n workflow with the complete validated structure."""

        await ctx.deps.emit_tool_call("update_workflow")
        validated_nodes, validated_connections = _validated_workflow(nodes, connections)
        node_dicts = dump_workflow_nodes(validated_nodes)

        try:
            workflow = await n8n_client.update_workflow(
                workflow_id=workflow_id,
                name=name,
                nodes=node_dicts,
                connections=validated_connections,
            )
        except Exception as exc:
            log.error("tool_error", tool="update_workflow", error=str(exc))
            return {"error": _safe_error(exc)}

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
        return {"id": workflow.id, "name": workflow.name, "active": workflow.active}

    @agent.tool
    async def activate_workflow(ctx: RunContext[AgentDeps], workflow_id: str) -> dict[str, Any]:
        """Activate a workflow so it runs automatically on its trigger."""

        await ctx.deps.emit_tool_call("activate_workflow")
        try:
            await n8n_client.activate_workflow(workflow_id)
            return {"success": True, "workflow_id": workflow_id}
        except Exception as exc:
            log.error("tool_error", tool="activate_workflow", error=str(exc))
            return {"error": _safe_error(exc)}

    @agent.tool
    async def deactivate_workflow(ctx: RunContext[AgentDeps], workflow_id: str) -> dict[str, Any]:
        """Deactivate a workflow so it stops running automatically."""

        await ctx.deps.emit_tool_call("deactivate_workflow")
        try:
            await n8n_client.deactivate_workflow(workflow_id)
            return {"success": True, "workflow_id": workflow_id}
        except Exception as exc:
            log.error("tool_error", tool="deactivate_workflow", error=str(exc))
            return {"error": _safe_error(exc)}

    @agent.tool
    async def execute_workflow(ctx: RunContext[AgentDeps], workflow_id: str) -> dict[str, Any]:
        """Activate a workflow and return trigger details such as webhook URL when available."""

        await ctx.deps.emit_tool_call("execute_workflow")
        try:
            return await n8n_client.execute_workflow(workflow_id)
        except Exception as exc:
            log.error("tool_error", tool="execute_workflow", error=str(exc))
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

        await ctx.deps.emit_tool_call("delete_workflow")
        try:
            await n8n_client.delete_workflow(workflow_id)
            return {"success": True, "workflow_id": workflow_id}
        except Exception as exc:
            log.error("tool_error", tool="delete_workflow", error=str(exc))
            return {"error": _safe_error(exc)}

    return agent
