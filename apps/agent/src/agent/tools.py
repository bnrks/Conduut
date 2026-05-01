"""Pydantic AI tool registration for n8n registry and workflow operations."""

from typing import Any

import httpx
import structlog
from pydantic_ai import Agent, ModelRetry, RunContext

from src import n8n_client
from src.agent.schemas import (
    AgentDeps,
    CredentialField,
    CredentialRequestAttachment,
    CredentialRequestData,
    WorkflowNode,
    WorkflowPreviewAttachment,
    WorkflowPreviewData,
    WorkflowRunResultData,
    dump_workflow_nodes,
)
from src.agent.validation import (
    normalize_workflow_connections,
    normalize_workflow_nodes,
    validate_workflow_payload,
)
from src.registry import registry

log = structlog.get_logger()

_AUTH_TO_CREDENTIAL_TYPE = {
    "basicauth": "httpBasicAuth",
    "headerauth": "httpHeaderAuth",
    "jwtauth": "jwtAuth",
}

_OPTIONAL_CREDENTIAL_NODE_TYPES = {
    "n8n-nodes-base.respondToWebhook",
}

_MAX_OUTPUT_NODES = 4
_MAX_OUTPUT_ITEMS = 3
_MAX_OUTPUT_STRING = 1200
_MAX_OUTPUT_KEYS = 12
_TECHNICAL_OUTPUT_KEYS = {
    "headers",
    "params",
    "query",
    "webhookUrl",
    "executionMode",
}
_TECHNICAL_NODE_TYPES = {
    "n8n-nodes-base.webhook",
    "n8n-nodes-base.respondToWebhook",
}

SYSTEM_PROMPT = (
    "You are Conduut, an AI assistant that helps users build and manage n8n workflow"
    " automations.\n\n"
    "You have access to tools to create, manage, and run n8n workflows.\n"
    "When a user asks you to automate something, use the tools to build it for them"
    " immediately. Do not ask for permission before acting.\n\n"
    "Guidelines:\n"
    "- Act directly. When the user asks you to create, update, run, activate, deactivate,"
    " or delete a workflow, use tools and then report what you did.\n"
    "- When reporting a workflow run, keep the message user-facing. Do not mention n8n,"
    " HTTP, headers, webhook internals, execution payloads, or node names unless the"
    " user explicitly asks for technical details. If there is no visible business"
    " output, simply say that the workflow ran successfully. Do not present a separate"
    " proof card, execution evidence, or internal verification details to the user.\n"
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
    if isinstance(exc, n8n_client.N8nApiError):
        return exc.message
    if isinstance(exc, httpx.HTTPStatusError):
        status = exc.response.status_code
        method = exc.request.method
        path = exc.request.url.path
        return f"n8n API returned {status} for {method} {path}"
    return str(exc)[:300] or "Tool execution failed"


def _preview_value(value: Any, *, depth: int = 0) -> Any:
    if isinstance(value, str):
        return value if len(value) <= _MAX_OUTPUT_STRING else f"{value[:_MAX_OUTPUT_STRING]}..."
    if isinstance(value, int | float | bool) or value is None:
        return value
    if depth >= 4:
        return str(value)[:_MAX_OUTPUT_STRING]
    if isinstance(value, list):
        return [_preview_value(item, depth=depth + 1) for item in value[:_MAX_OUTPUT_ITEMS]]
    if isinstance(value, dict):
        preview: dict[str, Any] = {}
        for index, (key, item) in enumerate(value.items()):
            if index >= _MAX_OUTPUT_KEYS:
                preview["..."] = f"{len(value) - _MAX_OUTPUT_KEYS} more keys"
                break
            preview[str(key)] = _preview_value(item, depth=depth + 1)
        return preview
    return str(value)[:_MAX_OUTPUT_STRING]


def _response_preview(response: httpx.Response) -> dict[str, Any]:
    content_type = response.headers.get("content-type")
    body: Any | None = None
    if response.content:
        try:
            body = response.json()
        except ValueError:
            body = response.text
    return {
        "statusCode": response.status_code,
        "contentType": content_type,
        "body": _preview_value(body),
    }


def _node_type_by_name(workflow: dict[str, Any] | None) -> dict[str, str]:
    if not workflow:
        return {}
    nodes = workflow.get("nodes")
    if not isinstance(nodes, list):
        return {}
    return {
        str(node.get("name")): str(node.get("type"))
        for node in nodes
        if isinstance(node, dict) and node.get("name") and node.get("type")
    }


def _strip_technical_output(value: Any) -> Any | None:
    if isinstance(value, dict):
        cleaned = {
            str(key): _strip_technical_output(item)
            for key, item in value.items()
            if key not in _TECHNICAL_OUTPUT_KEYS
        }
        cleaned = {key: item for key, item in cleaned.items() if item not in ({}, [], None, "")}
        if cleaned == {"body": {"source": "conduut_test"}}:
            return None
        if cleaned == {"source": "conduut_test"}:
            return None
        return cleaned or None
    if isinstance(value, list):
        cleaned_list = [_strip_technical_output(item) for item in value]
        cleaned_list = [item for item in cleaned_list if item not in ({}, [], None, "")]
        return cleaned_list or None
    return value


def _visible_response_body(response: dict[str, Any] | None) -> Any | None:
    if not response:
        return None
    return _strip_technical_output(response.get("body"))


def _extract_execution_outputs(
    execution: dict[str, Any],
    *,
    workflow: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    data = execution.get("data") if isinstance(execution.get("data"), dict) else {}
    result_data = data.get("resultData", {}) if isinstance(data, dict) else {}
    run_data = result_data.get("runData") if isinstance(result_data, dict) else None
    if not isinstance(run_data, dict):
        return []

    node_types = _node_type_by_name(workflow)
    outputs: list[dict[str, Any]] = []
    for node_name, runs in run_data.items():
        node_type = node_types.get(str(node_name))
        if node_type in _TECHNICAL_NODE_TYPES:
            continue
        if not isinstance(runs, list) or not runs:
            continue
        latest_run = runs[-1] if isinstance(runs[-1], dict) else {}
        node_data = latest_run.get("data") if isinstance(latest_run, dict) else None
        main_outputs = node_data.get("main") if isinstance(node_data, dict) else None
        if not isinstance(main_outputs, list):
            continue

        items: list[Any] = []
        visible_item_count = 0
        for output_index in main_outputs:
            if not isinstance(output_index, list):
                continue
            for item in output_index:
                if len(items) >= _MAX_OUTPUT_ITEMS:
                    continue
                if isinstance(item, dict) and "json" in item:
                    cleaned = _strip_technical_output(item.get("json"))
                else:
                    cleaned = _strip_technical_output(item)
                if cleaned not in ({}, [], None, ""):
                    visible_item_count += 1
                    items.append(_preview_value(cleaned))
        if items:
            outputs.append(
                {
                    "nodeName": str(node_name),
                    "itemCount": visible_item_count,
                    "items": items,
                }
            )

    return outputs[-_MAX_OUTPUT_NODES:]


def _service_name(node_type: str, node_name: str) -> str:
    service = node_type.split(".")[-1].replace("Trigger", "")
    return service[:1].upper() + service[1:] if service else node_name


def _auth_parameter_default(schema: dict[str, Any] | None) -> str:
    if not schema:
        return ""
    for parameter in schema.get("keyParameters") or []:
        if isinstance(parameter, dict) and parameter.get("name") == "authentication":
            return str(parameter.get("default") or "")
    return ""


def _required_credential_types_for_node(
    node: dict[str, Any],
    schema: dict[str, Any] | None,
) -> list[str]:
    credential_types = list(schema.get("credentials") or []) if schema else []
    if not credential_types:
        return []

    node_type = node.get("type", "")
    if node_type in _OPTIONAL_CREDENTIAL_NODE_TYPES:
        return []

    parameters = node.get("parameters", {})
    if not isinstance(parameters, dict):
        parameters = {}

    auth_default = _auth_parameter_default(schema)
    if "authentication" in parameters or auth_default:
        authentication = str(parameters.get("authentication", auth_default)).lower()
        if authentication in {"", "none", "noauth"}:
            return []
        mapped = _AUTH_TO_CREDENTIAL_TYPE.get(authentication)
        if mapped:
            return [mapped] if mapped in credential_types else []
        if "oauth" in authentication:
            return [item for item in credential_types if "oauth" in item.lower()]
        return [item for item in credential_types if "oauth" not in item.lower()]

    return credential_types


def _select_credential_type(node: dict[str, Any], credential_types: list[str]) -> str | None:
    if not credential_types:
        return None
    authentication = str(node.get("parameters", {}).get("authentication", "")).lower()
    if "oauth" in authentication:
        for credential_type in credential_types:
            if "oauth" in credential_type.lower():
                return credential_type
    for credential_type in credential_types:
        if "oauth" not in credential_type.lower():
            return credential_type
    return credential_types[0]


def _node_has_credential(node: dict[str, Any], credential_types: list[str]) -> bool:
    credentials = node.get("credentials")
    if not isinstance(credentials, dict):
        return False
    return any(credential_type in credentials for credential_type in credential_types)


def _fields_from_schema(schema: dict[str, Any]) -> list[CredentialField]:
    properties = schema.get("properties") if isinstance(schema, dict) else None
    required = set(schema.get("required") or []) if isinstance(schema, dict) else set()
    if not isinstance(properties, dict):
        return [CredentialField(name="apiKey", label="API Key", type="password", required=True)]

    fields: list[CredentialField] = []
    for name, meta in properties.items():
        if not isinstance(meta, dict):
            continue
        field_type = str(meta.get("type") or "string")
        if field_type not in {"string", "number", "integer", "boolean"}:
            continue
        display_name = meta.get("displayName") or name.replace("_", " ").title()
        secret = any(part in name.lower() for part in ("key", "token", "secret", "password"))
        fields.append(
            CredentialField(
                name=name,
                label=str(display_name),
                type="password" if secret else field_type,
                required=name in required or len(properties) == 1,
            )
        )

    return fields or [
        CredentialField(name="apiKey", label="API Key", type="password", required=True)
    ]


async def _credential_request_for_node(
    workflow_id: str,
    workflow_name: str | None,
    node: dict[str, Any],
    credential_type: str,
) -> CredentialRequestAttachment:
    try:
        schema = await n8n_client.get_credential_schema(credential_type)
        fields = _fields_from_schema(schema)
    except Exception:
        fields = [CredentialField(name="apiKey", label="API Key", type="password", required=True)]

    node_name = node.get("name", "Workflow node")
    service = _service_name(node.get("type", ""), node_name)
    credential_name = f"{service} - Conduut"
    return CredentialRequestAttachment(
        data=CredentialRequestData(
            workflowId=workflow_id,
            workflowName=workflow_name,
            nodeName=node_name,
            service=service,
            credentialType=credential_type,
            credentialName=credential_name,
            fields=fields,
            submitPath="/api/credentials",
            description=f"{node_name} needs {credential_type} credentials before it can run.",
        )
    )


async def analyze_workflow_readiness_payload(workflow: dict[str, Any]) -> dict[str, Any]:
    missing: list[CredentialRequestAttachment] = []
    for node in workflow.get("nodes", []):
        if not isinstance(node, dict):
            continue
        schema = registry.get_node_schema(node.get("type", ""))
        credential_types = _required_credential_types_for_node(node, schema)
        if not credential_types or _node_has_credential(node, credential_types):
            continue
        credential_type = _select_credential_type(node, credential_types)
        if credential_type:
            missing.append(
                await _credential_request_for_node(
                    workflow.get("id", ""),
                    workflow.get("name"),
                    node,
                    credential_type,
                )
            )

    webhook_nodes = [
        node
        for node in workflow.get("nodes", [])
        if isinstance(node, dict) and node.get("type") == "n8n-nodes-base.webhook"
    ]
    return {
        "ready": len(missing) == 0,
        "missing_credentials": missing,
        "testable": len(webhook_nodes) > 0,
        "webhook_nodes": webhook_nodes,
    }


async def _emit_missing_credentials(ctx: RunContext[AgentDeps], workflow: dict[str, Any]) -> int:
    readiness = await analyze_workflow_readiness_payload(workflow)
    missing = readiness["missing_credentials"]
    for attachment in missing:
        await ctx.deps.emit_attachment(attachment)
    return len(missing)


async def _get_workflow_for_reference(workflow_ref: str) -> dict[str, Any]:
    try:
        return await n8n_client.get_workflow(workflow_ref)
    except n8n_client.N8nApiError as exc:
        if exc.status_code != 404:
            raise
        normalized_ref = str(workflow_ref).strip().lower()
        if normalized_ref not in {"1", "current", "latest", "last", "the workflow"}:
            raise

    workflows = await n8n_client.list_workflows()
    if not workflows:
        raise n8n_client.N8nApiError(
            404,
            "No workflows were found to run.",
            method="GET",
            path="/workflows",
        )

    workflows.sort(key=lambda item: item.updated_at or item.created_at, reverse=True)
    return await n8n_client.get_workflow(workflows[0].id)


def _summarize_execution(
    execution: dict[str, Any],
    *,
    response: dict[str, Any] | None = None,
    workflow: dict[str, Any] | None = None,
) -> WorkflowRunResultData:
    status = execution.get("status") or ("success" if execution.get("finished") else "unknown")
    execution_id = str(execution.get("id", "")) or None
    data = execution.get("data") if isinstance(execution.get("data"), dict) else {}
    result_data = data.get("resultData", {}) if isinstance(data, dict) else {}
    error = result_data.get("error") if isinstance(result_data, dict) else None
    outputs = _extract_execution_outputs(execution, workflow=workflow)
    visible_response = _visible_response_body(response)
    if visible_response not in ({}, [], None, "") and not outputs:
        outputs = [
            {
                "nodeName": "Output",
                "itemCount": 1,
                "items": [_preview_value(visible_response)],
            }
        ]
    failed_node = None
    error_message = None
    if isinstance(error, dict):
        failed_node = (
            error.get("node", {}).get("name") if isinstance(error.get("node"), dict) else None
        )
        error_message = error.get("message") or error.get("description")
    output_count = sum(int(output.get("itemCount") or 0) for output in outputs)
    summary = "Workflow run completed."
    if output_count:
        summary = f"Workflow run completed with {output_count} output item(s)."
    if status in {"error", "failed"} or error_message:
        summary = f"Workflow execution failed: {error_message or 'Unknown error'}"
    return WorkflowRunResultData(
        workflowId=str(execution.get("workflowId", "")),
        executionId=execution_id,
        status=str(status),
        summary=summary,
        failedNode=failed_node,
        error=error_message,
        response=response if status in {"error", "failed"} or error_message else None,
        outputs=outputs,
    )


def _validated_workflow(
    nodes: list[WorkflowNode],
    connections: dict[str, Any],
) -> tuple[list[WorkflowNode], dict[str, Any]]:
    normalized_nodes = normalize_workflow_nodes(nodes)
    normalized_connections = normalize_workflow_connections(connections, normalized_nodes)
    _normalize_webhook_response_modes(normalized_nodes, normalized_connections)
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


def _normalize_webhook_response_modes(
    nodes: list[WorkflowNode],
    connections: dict[str, Any],
) -> None:
    respond_node_names = {
        node.name for node in nodes if node.type == "n8n-nodes-base.respondToWebhook"
    }
    if not respond_node_names:
        return

    for node in nodes:
        if node.type != "n8n-nodes-base.webhook":
            continue
        connection = connections.get(node.name)
        targets = list(_iter_connection_targets(connection))
        if any(target.get("node") in respond_node_names for target in targets):
            node.parameters["responseMode"] = "responseNode"


def _iter_connection_targets(value: Any):
    if isinstance(value, dict):
        if "node" in value:
            yield value
        for nested in value.values():
            yield from _iter_connection_targets(nested)
    elif isinstance(value, list):
        for nested in value:
            yield from _iter_connection_targets(nested)


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
        full_workflow = await n8n_client.get_workflow(workflow.id)
        missing_count = await _emit_missing_credentials(ctx, full_workflow)
        if missing_count:
            return {
                "id": workflow.id,
                "name": workflow.name,
                "active": workflow.active,
                "ready": False,
                "missing_credentials": missing_count,
            }
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
        full_workflow = await n8n_client.get_workflow(workflow.id)
        missing_count = await _emit_missing_credentials(ctx, full_workflow)
        if missing_count:
            return {
                "id": workflow.id,
                "name": workflow.name,
                "active": workflow.active,
                "ready": False,
                "missing_credentials": missing_count,
            }
        return {"id": workflow.id, "name": workflow.name, "active": workflow.active}

    @agent.tool
    async def activate_workflow(ctx: RunContext[AgentDeps], workflow_id: str) -> dict[str, Any]:
        """Activate a workflow so it runs automatically on its trigger."""

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
                }
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
        """Run a testable workflow and summarize the latest execution."""

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
                }

            readiness = await analyze_workflow_readiness_payload(workflow)
            webhook_nodes = readiness["webhook_nodes"]
            if not webhook_nodes:
                return {
                    "success": False,
                    "workflow_id": workflow_id,
                    "error": (
                        "This workflow is not testable from Conduut yet. "
                        "Only webhook-triggered workflows can be run in this phase."
                    ),
                }

            if not workflow.get("active"):
                await n8n_client.activate_workflow(workflow_id)
            path = webhook_nodes[0].get("parameters", {}).get("path")
            if not path:
                return {
                    "success": False,
                    "workflow_id": workflow_id,
                    "error": "Webhook path missing.",
                }

            webhook_response = await n8n_client.call_webhook(str(path), {"source": "conduut_test"})
            response = _response_preview(webhook_response)
            if webhook_response.status_code >= 400:
                result = WorkflowRunResultData(
                    workflowId=workflow_id,
                    status="error",
                    summary="Workflow webhook returned an error response.",
                    error=webhook_response.text[:500],
                    response=response,
                )
                return result.model_dump(exclude_none=True)
            executions = await n8n_client.list_executions(workflow_id=workflow_id, limit=1)
            if not executions:
                result = WorkflowRunResultData(
                    workflowId=workflow_id,
                    status="triggered",
                    summary=(
                        "Workflow trigger was accepted. n8n has not exposed "
                        "execution details yet."
                    ),
                    response=response,
                )
                return result.model_dump(exclude_none=True)

            detail = await n8n_client.get_execution_detail(executions[0].id)
            result = _summarize_execution(detail, response=response, workflow=workflow)
            return result.model_dump(exclude_none=True)
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
            readiness = await analyze_workflow_readiness_payload(workflow)
            for attachment in readiness["missing_credentials"]:
                await ctx.deps.emit_attachment(attachment)
            return {
                "ready": readiness["ready"],
                "testable": readiness["testable"],
                "missing_credentials": len(readiness["missing_credentials"]),
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

        await ctx.deps.emit_tool_call("delete_workflow")
        try:
            await n8n_client.delete_workflow(workflow_id)
            return {"success": True, "workflow_id": workflow_id}
        except Exception as exc:
            log.error("tool_error", tool="delete_workflow", error=str(exc))
            return {"error": _safe_error(exc)}

    return agent
