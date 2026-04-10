"""n8n tool tanımları — LLM'e verilecek JSON schema'lar ve executor map."""
import json
from typing import Any

import structlog

from src import n8n_client

log = structlog.get_logger()

# ---------------------------------------------------------------------------
# Tool schema'lar (OpenAI function calling format — LiteLLM tüm provider'lara çevirir)
# ---------------------------------------------------------------------------

TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "list_workflows",
            "description": "Lists all n8n workflows belonging to the user.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_workflow",
            "description": "Gets the full details and node structure of a specific workflow.",
            "parameters": {
                "type": "object",
                "properties": {
                    "workflow_id": {"type": "string", "description": "The workflow ID"},
                },
                "required": ["workflow_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_workflow",
            "description": (
                "Creates a new n8n workflow. "
                "nodes is a list of n8n node objects. "
                "connections defines the data flow between nodes."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Workflow name"},
                    "nodes": {
                        "type": "array",
                        "description": "List of n8n node objects",
                        "items": {"type": "object"},
                    },
                    "connections": {
                        "type": "object",
                        "description": "n8n connections object mapping node outputs to inputs",
                    },
                },
                "required": ["name", "nodes", "connections"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "activate_workflow",
            "description": "Activates a workflow so it runs automatically on triggers.",
            "parameters": {
                "type": "object",
                "properties": {
                    "workflow_id": {"type": "string", "description": "The workflow ID to activate"},
                },
                "required": ["workflow_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "deactivate_workflow",
            "description": "Deactivates a workflow, stopping it from running automatically.",
            "parameters": {
                "type": "object",
                "properties": {
                    "workflow_id": {"type": "string", "description": "The workflow ID to deactivate"},
                },
                "required": ["workflow_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "execute_workflow",
            "description": "Manually runs a workflow once and returns the execution ID.",
            "parameters": {
                "type": "object",
                "properties": {
                    "workflow_id": {"type": "string", "description": "The workflow ID to run"},
                },
                "required": ["workflow_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_executions",
            "description": "Lists recent workflow execution history.",
            "parameters": {
                "type": "object",
                "properties": {
                    "workflow_id": {
                        "type": "string",
                        "description": "Filter by workflow ID (optional)",
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_workflow",
            "description": (
                "Updates an existing n8n workflow by replacing its nodes and connections. "
                "Use this to add, remove, or modify nodes in a workflow that already exists. "
                "You must provide the complete new nodes list and connections — not just the changes. "
                "Always call get_workflow first to retrieve the current structure, then send the full updated version."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "workflow_id": {"type": "string", "description": "The ID of the workflow to update"},
                    "name": {"type": "string", "description": "Workflow name (can be unchanged)"},
                    "nodes": {
                        "type": "array",
                        "description": "Complete updated list of n8n node objects",
                        "items": {"type": "object"},
                    },
                    "connections": {
                        "type": "object",
                        "description": "Complete updated n8n connections object",
                    },
                },
                "required": ["workflow_id", "name", "nodes", "connections"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "delete_workflow",
            "description": "Permanently deletes a workflow.",
            "parameters": {
                "type": "object",
                "properties": {
                    "workflow_id": {"type": "string", "description": "The workflow ID to delete"},
                },
                "required": ["workflow_id"],
            },
        },
    },
]


# ---------------------------------------------------------------------------
# Executor — tool adına göre doğru fonksiyonu çağırır
# ---------------------------------------------------------------------------

async def execute_tool(name: str, arguments: str) -> str:
    """Tool çağırır, sonucu JSON string olarak döner (messages'a eklenecek)."""
    try:
        args: dict[str, Any] = json.loads(arguments) if arguments else {}
    except json.JSONDecodeError:
        return json.dumps({"error": "Invalid tool arguments"})

    log.info("tool_call", tool=name, args=args)

    try:
        match name:
            case "list_workflows":
                workflows = await n8n_client.list_workflows()
                return json.dumps([
                    {"id": w.id, "name": w.name, "active": w.active}
                    for w in workflows
                ])

            case "get_workflow":
                return json.dumps(await n8n_client.get_workflow(args["workflow_id"]))

            case "create_workflow":
                workflow = await n8n_client.create_workflow(
                    name=args["name"],
                    nodes=args.get("nodes", []),
                    connections=args.get("connections", {}),
                )
                return json.dumps({"id": workflow.id, "name": workflow.name, "active": workflow.active})

            case "activate_workflow":
                await n8n_client.activate_workflow(args["workflow_id"])
                return json.dumps({"success": True, "workflow_id": args["workflow_id"]})

            case "deactivate_workflow":
                await n8n_client.deactivate_workflow(args["workflow_id"])
                return json.dumps({"success": True, "workflow_id": args["workflow_id"]})

            case "execute_workflow":
                execution = await n8n_client.execute_workflow(args["workflow_id"])
                return json.dumps({"execution_id": execution.id, "status": execution.status})

            case "list_executions":
                executions = await n8n_client.list_executions(
                    workflow_id=args.get("workflow_id"),
                    limit=10,
                )
                return json.dumps([
                    {"id": e.id, "workflow_id": e.workflow_id, "status": e.status, "started_at": e.started_at}
                    for e in executions
                ])

            case "update_workflow":
                workflow = await n8n_client.update_workflow(
                    workflow_id=args["workflow_id"],
                    name=args["name"],
                    nodes=args.get("nodes", []),
                    connections=args.get("connections", {}),
                )
                return json.dumps({"id": workflow.id, "name": workflow.name, "active": workflow.active})

            case "delete_workflow":
                await n8n_client.delete_workflow(args["workflow_id"])
                return json.dumps({"success": True, "workflow_id": args["workflow_id"]})

            case _:
                return json.dumps({"error": f"Unknown tool: {name}"})

    except Exception as e:
        log.error("tool_error", tool=name, error=str(e))
        return json.dumps({"error": str(e)})
