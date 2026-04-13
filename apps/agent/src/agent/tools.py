"""n8n tool tanımları — LLM'e verilecek JSON schema'lar ve executor map."""

import json
from typing import Any

import structlog

from src import n8n_client
from src.registry import registry

log = structlog.get_logger()

_CONNECTIONS_HINT = (
    "Shape: { 'NodeA': { 'main': [[{ 'node': 'NodeB', 'type': 'main', 'index': 0 }]] } }. "
    "For A→B→C: A connects to B, B connects to C. Leaf nodes are omitted."
)

_NODE_BUILD_HINT = (
    "Each node must have: id (unique string), name (string), "
    "type (exact n8n type string, e.g. 'n8n-nodes-base.gmail'), "
    "typeVersion (integer — use the version from get_node_schema), "
    "position ([x, y] starting at [250, 300], 250px apart), "
    "parameters (object). "
    "Use search_n8n_nodes + get_node_schema before building nodes you're unsure about."
)

# ---------------------------------------------------------------------------
# Tool schema'lar (OpenAI function calling format — LiteLLM tüm provider'lara çevirir)
# ---------------------------------------------------------------------------

TOOL_DEFINITIONS = [
    # --- Registry tools ---
    {
        "type": "function",
        "function": {
            "name": "search_n8n_nodes",
            "description": (
                "Search for n8n node types by keyword. "
                "Use this before building a workflow when you need to know "
                "the exact node type string for a service or action "
                "(e.g. 'gmail', 'slack', 'postgres', 'discord'). "
                "Returns a list of matching nodes with their type names and descriptions."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": (
                            "Search keywords, e.g. 'gmail', 'send slack message', "
                            "'postgres database', 'schedule trigger'"
                        ),
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_node_schema",
            "description": (
                "Get the full parameter schema for a specific n8n node type. "
                "Call this after search_n8n_nodes to get exact parameters, "
                "typeVersion, credentials required, and an example node JSON. "
                "Use the returned exampleNode as a starting point."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "node_type": {
                        "type": "string",
                        "description": (
                            "The exact node type string from search results, "
                            "e.g. 'n8n-nodes-base.gmail' or just 'gmail'"
                        ),
                    },
                },
                "required": ["node_type"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "find_workflow_template",
            "description": (
                "Find existing workflow templates similar to what the user wants. "
                "Returns up to 3 real workflow examples you can adapt. "
                "Use this for complex multi-node workflows to get a working starting point."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "description": {
                        "type": "string",
                        "description": (
                            "Short description of the workflow, "
                            "e.g. 'send gmail when form submitted', "
                            "'daily report to slack', 'sync airtable to notion'"
                        ),
                    },
                },
                "required": ["description"],
            },
        },
    },
    # --- Workflow management tools ---
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
                "Use search_n8n_nodes + get_node_schema first to get correct node types. "
                "nodes is a list of n8n node objects. "
                "connections defines the data flow between nodes."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Workflow name"},
                    "nodes": {
                        "type": "array",
                        "description": "List of n8n node objects. " + _NODE_BUILD_HINT,
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
            "name": "update_workflow",
            "description": (
                "Updates an existing n8n workflow by replacing its nodes and connections. "
                "Always call get_workflow first to retrieve the current structure, "
                "then send the full updated version."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "workflow_id": {
                        "type": "string",
                        "description": "The ID of the workflow to update",
                    },
                    "name": {"type": "string", "description": "Workflow name (can be unchanged)"},
                    "nodes": {
                        "type": "array",
                        "description": "Complete updated list of n8n node objects. "
                        + _NODE_BUILD_HINT,
                        "items": {"type": "object"},
                    },
                    "connections": {
                        "type": "object",
                        "description": "Complete updated n8n connections object. "
                        + _CONNECTIONS_HINT,
                    },
                },
                "required": ["workflow_id", "name", "nodes", "connections"],
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
                    },
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
                "Activates a workflow so it runs automatically on its trigger. "
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
# Workflow JSON validator (Pydantic kullanmadan basit doğrulama)
# ---------------------------------------------------------------------------


def _validate_workflow_nodes(nodes: list[Any]) -> list[str]:
    """
    Workflow node listesini doğrular.
    Sorun varsa hata mesajlarının listesini döner, temizse boş liste.
    """
    errors: list[str] = []
    if not nodes:
        errors.append("nodes array is empty — every workflow needs at least one trigger node")
        return errors

    seen_ids: set[str] = set()
    has_trigger = False

    for i, node in enumerate(nodes):
        if not isinstance(node, dict):
            errors.append(f"Node at index {i} is not an object")
            continue

        # Zorunlu alanlar
        for field in ("id", "name", "type", "typeVersion", "position", "parameters"):
            if field not in node:
                errors.append(f"Node '{node.get('name', i)}' missing required field: {field}")

        # id uniqueness
        node_id = node.get("id")
        if node_id:
            if node_id in seen_ids:
                errors.append(f"Duplicate node id: '{node_id}'")
            seen_ids.add(node_id)

        # type format
        node_type = node.get("type", "")
        if node_type and not (
            node_type.startswith("n8n-nodes-base.")
            or node_type.startswith("@n8n/")
            or node_type.startswith("n8n-nodes-")
        ):
            errors.append(
                f"Node '{node.get('name', i)}' has suspicious type '{node_type}' — "
                "use search_n8n_nodes to find the correct type string"
            )

        # typeVersion
        tv = node.get("typeVersion")
        if tv is not None and not isinstance(tv, int):
            errors.append(f"Node '{node.get('name', i)}' typeVersion must be an integer")

        # position
        pos = node.get("position")
        if pos is not None and (not isinstance(pos, list) or len(pos) != 2):
            errors.append(f"Node '{node.get('name', i)}' position must be [x, y]")

        # Trigger detection
        name_lower = str(node_type).lower()
        if "trigger" in name_lower or node.get("webhookId"):
            has_trigger = True

    if not has_trigger:
        errors.append(
            "No trigger node found — workflow needs a trigger "
            "(scheduleTrigger, webhook, manualTrigger, etc.)"
        )

    return errors


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
            # --- Registry tools ---
            case "search_n8n_nodes":
                query = args.get("query", "")
                results = registry.search_nodes(query)
                if not results:
                    return json.dumps({
                        "results": [],
                        "hint": (
                            "No nodes found for this query. "
                            "Try a different keyword (e.g. service name, action type). "
                            "Common types: scheduleTrigger, webhook, httpRequest, "
                            "set, if, code, gmail, slack, googleSheets"
                        ),
                    }), None
                return json.dumps({"results": results}), None

            case "get_node_schema":
                node_type = args.get("node_type", "")
                schema = registry.get_node_schema(node_type)
                if not schema:
                    return json.dumps({
                        "error": f"Node type '{node_type}' not found in registry. "
                        "Use search_n8n_nodes to find the correct type string."
                    }), None
                return json.dumps(schema), None

            case "find_workflow_template":
                description = args.get("description", "")
                results = registry.find_templates(description)
                if not results:
                    return json.dumps({
                        "templates": [],
                        "hint": "No matching templates found. Build the workflow from scratch.",
                    }), None
                return json.dumps({"templates": results}), None

            # --- Workflow management ---
            case "list_workflows":
                workflows = await n8n_client.list_workflows()
                return json.dumps(
                    [{"id": w.id, "name": w.name, "active": w.active} for w in workflows]
                ), None

            case "get_workflow":
                return json.dumps(await n8n_client.get_workflow(args["workflow_id"])), None

            case "create_workflow":
                nodes = args.get("nodes", [])
                errors = _validate_workflow_nodes(nodes)
                if errors:
                    return json.dumps({
                        "error": "Workflow validation failed — fix these issues before creating",
                        "issues": errors,
                    }), None

                workflow = await n8n_client.create_workflow(
                    name=args["name"],
                    nodes=nodes,
                    connections=args.get("connections", {}),
                )
                attachment = {
                    "type": "workflow_preview",
                    "data": {
                        "id": workflow.id,
                        "name": workflow.name,
                        "nodeCount": len(nodes),
                        "status": "active" if workflow.active else "inactive",
                    },
                }
                return json.dumps(
                    {"id": workflow.id, "name": workflow.name, "active": workflow.active}
                ), attachment

            case "update_workflow":
                nodes = args.get("nodes", [])
                errors = _validate_workflow_nodes(nodes)
                if errors:
                    return json.dumps({
                        "error": "Workflow validation failed — fix these issues before updating",
                        "issues": errors,
                    }), None

                workflow = await n8n_client.update_workflow(
                    workflow_id=args["workflow_id"],
                    name=args["name"],
                    nodes=nodes,
                    connections=args.get("connections", {}),
                )
                attachment = {
                    "type": "workflow_preview",
                    "data": {
                        "id": workflow.id,
                        "name": workflow.name,
                        "nodeCount": len(nodes),
                        "status": "active" if workflow.active else "inactive",
                    },
                }
                return json.dumps(
                    {"id": workflow.id, "name": workflow.name, "active": workflow.active}
                ), attachment

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
                        }
                        for e in executions
                    ]
                ), None

            case "delete_workflow":
                await n8n_client.delete_workflow(args["workflow_id"])
                return json.dumps({"success": True, "workflow_id": args["workflow_id"]}), None

            case _:
                return json.dumps({"error": f"Unknown tool: {name}"}), None

    except Exception as e:
        log.error("tool_error", tool=name, error=str(e))
        return json.dumps({"error": str(e)}), None
