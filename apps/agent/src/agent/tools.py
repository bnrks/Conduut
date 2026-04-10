"""n8n tool tanımları — LLM'e verilecek JSON schema'lar ve executor map."""

import json
from typing import Any

import structlog

from src import n8n_client

log = structlog.get_logger()

_NODE_SCHEMA_HINT = (
    "Each node must have: id (unique string), name (string), "
    "type (e.g. 'n8n-nodes-base.scheduleTrigger', 'n8n-nodes-base.webhook', "
    "'n8n-nodes-base.httpRequest', 'n8n-nodes-base.set', 'n8n-nodes-base.if', "
    "'n8n-nodes-base.gmail', 'n8n-nodes-base.googleSheets', 'n8n-nodes-base.slack', "
    "'n8n-nodes-base.code', 'n8n-nodes-base.merge', 'n8n-nodes-base.noOp'), "
    "typeVersion (integer, usually 1–4 depending on the node), "
    "position ([x, y] pixel coordinates, start at [250, 300] and space 250px apart), "
    "parameters (object with node-specific config). "
    "NEVER pass an empty nodes array — every workflow needs at least one trigger node."
)

_CONNECTIONS_HINT = (
    "Shape: { 'NodeA': { 'main': [[{ 'node': 'NodeB', 'type': 'main', 'index': 0 }]] } }. "
    "For A\u2192B\u2192C: A connects to B, B connects to C. Leaf nodes are omitted."
)

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
                        "description": "List of n8n node objects. " + _NODE_SCHEMA_HINT,
                        "items": {"type": "object"},
                    },
                    "connections": {
                        "type": "object",
                        "description": "n8n connections object. " + _CONNECTIONS_HINT,
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
                    "workflow_id": {
                        "type": "string",
                        "description": "The workflow ID to deactivate",
                    },  # noqa: E501
                },
                "required": ["workflow_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "execute_workflow",
            "description": (
                "Activates a workflow so it runs automatically on its trigger "
                "(schedule, webhook, etc.). "
                "For webhook-triggered workflows, also returns the webhook URL to call. "
                "Use this when the user asks to 'run', 'execute', or 'start' a workflow."
            ),
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
                "You must provide the complete new nodes list and connections — not just the changes. "  # noqa: E501
                "Always call get_workflow first to retrieve the current structure, then send the full updated version."  # noqa: E501
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "workflow_id": {
                        "type": "string",
                        "description": "The ID of the workflow to update",
                    },  # noqa: E501
                    "name": {"type": "string", "description": "Workflow name (can be unchanged)"},
                    "nodes": {
                        "type": "array",
                        "description": (
                            "Complete updated list of n8n node objects. " + _NODE_SCHEMA_HINT
                        ),
                        "items": {"type": "object"},
                    },
                    "connections": {
                        "type": "object",
                        "description": (
                            "Complete updated n8n connections object. " + _CONNECTIONS_HINT
                        ),
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


async def execute_tool(name: str, arguments: str) -> tuple[str, dict | None]:
    """Tool çağırır. (llm_için_json_string, opsiyonel_attachment) tuple'ı döner."""
    try:
        args: dict[str, Any] = json.loads(arguments) if arguments else {}
    except json.JSONDecodeError:
        return json.dumps({"error": "Invalid tool arguments"}), None

    log.info("tool_call", tool=name, args=args)

    try:
        match name:
            case "list_workflows":
                workflows = await n8n_client.list_workflows()
                return json.dumps(
                    [{"id": w.id, "name": w.name, "active": w.active} for w in workflows]
                ), None

            case "get_workflow":
                return json.dumps(await n8n_client.get_workflow(args["workflow_id"])), None

            case "create_workflow":
                workflow = await n8n_client.create_workflow(
                    name=args["name"],
                    nodes=args.get("nodes", []),
                    connections=args.get("connections", {}),
                )
                attachment = {
                    "type": "workflow_preview",
                    "data": {
                        "id": workflow.id,
                        "name": workflow.name,
                        "nodeCount": len(args.get("nodes", [])),
                        "status": "active" if workflow.active else "inactive",
                    },
                }
                llm_json = json.dumps(
                    {"id": workflow.id, "name": workflow.name, "active": workflow.active}
                )
                return llm_json, attachment

            case "activate_workflow":
                await n8n_client.activate_workflow(args["workflow_id"])
                return json.dumps({"success": True, "workflow_id": args["workflow_id"]}), None

            case "deactivate_workflow":
                await n8n_client.deactivate_workflow(args["workflow_id"])
                return json.dumps({"success": True, "workflow_id": args["workflow_id"]}), None

            case "execute_workflow":
                result = await n8n_client.execute_workflow(args["workflow_id"])
                return json.dumps(result), None

            case "list_executions":
                executions = await n8n_client.list_executions(
                    workflow_id=args.get("workflow_id"),
                    limit=10,
                )
                return json.dumps(
                    [
                        {
                            "id": e.id,
                            "workflow_id": e.workflow_id,
                            "status": e.status,
                            "started_at": e.started_at,
                        }  # noqa: E501
                        for e in executions
                    ]
                ), None

            case "update_workflow":
                workflow = await n8n_client.update_workflow(
                    workflow_id=args["workflow_id"],
                    name=args["name"],
                    nodes=args.get("nodes", []),
                    connections=args.get("connections", {}),
                )
                attachment = {
                    "type": "workflow_preview",
                    "data": {
                        "id": workflow.id,
                        "name": workflow.name,
                        "nodeCount": len(args.get("nodes", [])),
                        "status": "active" if workflow.active else "inactive",
                    },
                }
                llm_json = json.dumps(
                    {"id": workflow.id, "name": workflow.name, "active": workflow.active}
                )
                return llm_json, attachment

            case "delete_workflow":
                await n8n_client.delete_workflow(args["workflow_id"])
                return json.dumps({"success": True, "workflow_id": args["workflow_id"]}), None

            case _:
                return json.dumps({"error": f"Unknown tool: {name}"}), None

    except Exception as e:
        log.error("tool_error", tool=name, error=str(e))
        return json.dumps({"error": str(e)}), None
