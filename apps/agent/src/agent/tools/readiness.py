"""Credential readiness analysis for n8n workflows."""

from typing import Any

import structlog
from pydantic_ai import RunContext

from src import n8n_client, store
from src.agent.schemas import (
    AgentAttachment,
    AgentDeps,
    CredentialField,
    CredentialRequestAttachment,
    CredentialRequestData,
    OAuthPromptAttachment,
    OAuthPromptData,
)
from src.agent.tools.constants import (
    _AUTH_TO_CREDENTIAL_TYPE,
    _GMAIL_MANAGED_OPERATIONS,
    _GOOGLE_GMAIL_CONNECTION_ID,
    _GOOGLE_GMAIL_CREDENTIAL_TYPE,
    _GOOGLE_SHEETS_CONNECTION_ID,
    _GOOGLE_SHEETS_CREDENTIAL_TYPE,
    _MANUAL_TRIGGER_TYPE,
    _OPTIONAL_CREDENTIAL_NODE_TYPES,
    _WEBHOOK_TRIGGER_TYPE,
)
from src.agent.tools.workflow_helpers import _workflow_trigger_nodes
from src.oauth import google
from src.registry import registry

log = structlog.get_logger()


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


def _gmail_required_capability(node: dict[str, Any], credential_type: str) -> str | None:
    if credential_type != _GOOGLE_GMAIL_CREDENTIAL_TYPE:
        return None
    if node.get("type") != "n8n-nodes-base.gmail":
        return None
    parameters = node.get("parameters")
    if not isinstance(parameters, dict):
        parameters = {}
    resource = str(parameters.get("resource") or "message").lower()
    operation = str(parameters.get("operation") or "send").lower()
    if operation not in _GMAIL_MANAGED_OPERATIONS.get(resource, set()):
        return None
    if operation in {"send", "reply", "create"}:
        return google.GOOGLE_GMAIL_SEND_CAPABILITY
    return google.GOOGLE_GMAIL_READ_CAPABILITY


def _sheets_required_capability(node: dict[str, Any], credential_type: str) -> str | None:
    if credential_type != _GOOGLE_SHEETS_CREDENTIAL_TYPE:
        return None
    if node.get("type") != "n8n-nodes-base.googleSheets":
        return None
    parameters = node.get("parameters")
    if not isinstance(parameters, dict):
        parameters = {}
    operation = str(parameters.get("operation") or "read").lower()
    if operation in {"read", "get", "getall", "lookup"}:
        return google.GOOGLE_SHEETS_READ_CAPABILITY
    return google.GOOGLE_SHEETS_WRITE_CAPABILITY


def _connection_capabilities(connection: store.AppConnection) -> list[str]:
    return connection.capabilities or google.capabilities_for_scopes(connection.scopes)


def _managed_google_connection_for_node(
    node: dict[str, Any],
    credential_type: str,
) -> dict[str, str] | None:
    gmail_capability = _gmail_required_capability(node, credential_type)
    if gmail_capability:
        return {
            "connection_id": _GOOGLE_GMAIL_CONNECTION_ID,
            "credential_type": _GOOGLE_GMAIL_CREDENTIAL_TYPE,
            "service": "Google Gmail",
            "description": "Grant Google Workspace access so Conduut can use Gmail in workflows.",
            "authorize_path": "/api/connections/google/gmail/authorize",
            "capability": gmail_capability,
        }
    sheets_capability = _sheets_required_capability(node, credential_type)
    if sheets_capability:
        return {
            "connection_id": _GOOGLE_SHEETS_CONNECTION_ID,
            "credential_type": _GOOGLE_SHEETS_CREDENTIAL_TYPE,
            "service": "Google Sheets",
            "description": "Grant Google Workspace access so Conduut can use Sheets in workflows.",
            "authorize_path": "/api/connections/google/sheets/authorize",
            "capability": sheets_capability,
        }
    return None


async def _attach_managed_connection_if_available(
    user_id: str | None,
    workflow_id: str,
    node: dict[str, Any],
    credential_type: str,
) -> bool:
    config = _managed_google_connection_for_node(node, credential_type)
    if not user_id or not workflow_id or not config:
        return False

    connection = await store.get_connection(user_id, config["connection_id"])
    if not connection or connection.status != "connected":
        return False
    if connection.credential_type != credential_type or not connection.n8n_credential_id:
        return False
    if config["capability"] not in _connection_capabilities(connection):
        return False

    node_name = str(node.get("name") or "")
    if not node_name:
        return False

    await n8n_client.attach_credential_to_workflow(
        workflow_id,
        node_name,
        credential_type,
        connection.n8n_credential_id,
        connection.n8n_credential_name,
    )
    node.setdefault("credentials", {})[credential_type] = {
        "id": connection.n8n_credential_id,
        "name": connection.n8n_credential_name,
    }
    return True


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
) -> AgentAttachment:
    node_name = node.get("name", "Workflow node")
    managed_connection = _managed_google_connection_for_node(node, credential_type)
    if managed_connection:
        return OAuthPromptAttachment(
            data=OAuthPromptData(
                service=managed_connection["service"],
                description=managed_connection["description"],
                authorizePath=managed_connection["authorize_path"],
                returnTo="/dashboard/connections",
            )
        )

    try:
        schema = await n8n_client.get_credential_schema(credential_type)
        fields = _fields_from_schema(schema)
    except Exception:
        fields = [CredentialField(name="apiKey", label="API Key", type="password", required=True)]

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


async def analyze_workflow_readiness_payload(
    workflow: dict[str, Any],
    *,
    user_id: str | None = None,
) -> dict[str, Any]:
    missing: list[AgentAttachment] = []
    workflow_id = str(workflow.get("id") or "")
    for node in workflow.get("nodes", []):
        if not isinstance(node, dict):
            continue
        schema = registry.get_node_schema(node.get("type", ""))
        credential_types = _required_credential_types_for_node(node, schema)
        if not credential_types or _node_has_credential(node, credential_types):
            continue
        credential_type = _select_credential_type(node, credential_types)
        if credential_type:
            try:
                attached = await _attach_managed_connection_if_available(
                    user_id,
                    workflow_id,
                    node,
                    credential_type,
                )
            except Exception as exc:
                log.warning(
                    "managed_connection_attach_failed",
                    workflow_id=workflow_id,
                    node=node.get("name"),
                    credential_type=credential_type,
                    error=str(exc),
                )
                attached = False
            if attached:
                continue
            missing.append(
                await _credential_request_for_node(
                    workflow.get("id", ""),
                    workflow.get("name"),
                    node,
                    credential_type,
                )
            )

    webhook_nodes = _workflow_trigger_nodes(workflow, _WEBHOOK_TRIGGER_TYPE)
    manual_trigger_nodes = _workflow_trigger_nodes(workflow, _MANUAL_TRIGGER_TYPE)
    return {
        "ready": len(missing) == 0,
        "missing_credentials": missing,
        "testable": len(webhook_nodes) > 0 or len(manual_trigger_nodes) > 0,
        "webhook_nodes": webhook_nodes,
        "manual_trigger_nodes": manual_trigger_nodes,
    }


async def _emit_missing_credentials(ctx: RunContext[AgentDeps], workflow: dict[str, Any]) -> int:
    readiness = await analyze_workflow_readiness_payload(workflow, user_id=ctx.deps.user_id)
    missing = readiness["missing_credentials"]
    for attachment in missing:
        await ctx.deps.emit_attachment(attachment)
    if missing:
        ctx.deps.awaiting_user_input = True
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
