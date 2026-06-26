"""Credential readiness analysis for n8n workflows."""

from typing import Any

import structlog
from pydantic_ai import RunContext

from src import n8n_client, store
from src.agent.credential_catalog import match_credentials_by_type, parse_schema_fields
from src.agent.credential_types import (
    credential_type_catalog,
    is_supported_http_type,
    match_credentials,
    normalize_host,
)
from src.agent.schemas import (
    AgentAttachment,
    AgentDeps,
    CredentialField,
    CredentialRequestAttachment,
    CredentialRequestData,
    CredentialTypeOption,
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
from src.platforms.capabilities import connection_has_capability
from src.registry import registry

log = structlog.get_logger()

_HTTP_REQUEST_NODE_TYPE = "n8n-nodes-base.httpRequest"


def _is_http_request_node(node: dict[str, Any]) -> bool:
    """Whether this is an outbound HTTP Request node (host-matched custom creds)."""

    return node.get("type") == _HTTP_REQUEST_NODE_TYPE


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
        if authentication == "genericcredentialtype":
            generic = str(parameters.get("genericAuthType") or "").strip()
            # n8n requires a credential of `generic` type whenever it is set, even
            # though the node's static schema credentials (e.g. ['httpSslAuth'])
            # never enumerate the conditional generic auth types.
            if generic:
                return [generic]
            return [item for item in credential_types if is_supported_http_type(item)]
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
            "authorize_path": "/api/oauth/google/authorize?service=gmail",
            "capability": gmail_capability,
        }
    sheets_capability = _sheets_required_capability(node, credential_type)
    if sheets_capability:
        return {
            "connection_id": _GOOGLE_SHEETS_CONNECTION_ID,
            "credential_type": _GOOGLE_SHEETS_CREDENTIAL_TYPE,
            "service": "Google Sheets",
            "description": "Grant Google Workspace access so Conduut can use Sheets in workflows.",
            "authorize_path": "/api/oauth/google/authorize?service=sheets",
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
    if not connection_has_capability(_connection_capabilities(connection), config["capability"]):
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
    log.info(
        "managed_connection_attached",
        workflow_id=workflow_id,
        node=node_name,
        connection_id=config["connection_id"],
        credential_type=credential_type,
        capability=config["capability"],
    )
    return True


# Credential types provisioned through the Google OAuth broker (ADR-0003); these
# keep using the managed-connection / OAuth-prompt path, not the reuse bridge.
_MANAGED_CREDENTIAL_TYPES = {"gmailOAuth2", "googleSheetsOAuth2"}


async def _discover_existing_credential(
    credential_type: str, skip_workflow_id: str
) -> tuple[str, str] | None:
    """Find a credential of this type already bound to some other workflow.

    Single-tenant bridge: the n8n public API can't list credentials, but it can
    read workflows. Until the per-user credential broker exists, reuse a
    credential the user already bound (e.g. their one OpenAI account) so
    agent-built AI workflows run without manual credential binding.
    """

    # n8n list cevabı her workflow'un node'larını (credentials dahil) zaten
    # döndürür → tek çağrıyla tara, per-workflow get_workflow (N+1) atma.
    try:
        workflows = await n8n_client.list_workflows_raw()
    except Exception:
        return None
    for full in workflows:
        if not isinstance(full, dict) or full.get("id") == skip_workflow_id:
            continue
        for other in full.get("nodes", []):
            credentials = other.get("credentials") if isinstance(other, dict) else None
            entry = credentials.get(credential_type) if isinstance(credentials, dict) else None
            credential_id = entry.get("id") if isinstance(entry, dict) else None
            if credential_id:
                return str(credential_id), str(entry.get("name") or "")
    return None


async def _attach_existing_credential_if_available(
    workflow_id: str, node: dict[str, Any], credential_type: str
) -> bool:
    if not workflow_id or credential_type in _MANAGED_CREDENTIAL_TYPES:
        return False
    node_name = str(node.get("name") or "")
    if not node_name:
        return False
    found = await _discover_existing_credential(credential_type, workflow_id)
    if not found:
        return False
    credential_id, credential_name = found
    await n8n_client.attach_credential_to_workflow(
        workflow_id,
        node_name,
        credential_type,
        credential_id,
        credential_name,
    )
    node.setdefault("credentials", {})[credential_type] = {
        "id": credential_id,
        "name": credential_name,
    }
    log.info(
        "existing_credential_reused",
        workflow_id=workflow_id,
        node=node_name,
        credential_type=credential_type,
        credential_id=credential_id,
    )
    return True


def _fields_from_schema(schema: dict[str, Any]) -> list[CredentialField]:
    # Moved to credential_catalog.parse_schema_fields (shared with the catalog);
    # kept as a thin alias so existing call sites stay unchanged.
    return parse_schema_fields(schema)


def _http_credential_request(
    workflow_id: str,
    workflow_name: str | None,
    node: dict[str, Any],
    credential_type: str,
) -> CredentialRequestAttachment:
    """Build a credential card for a generic HTTP Request auth node.

    Shows a type picker only when the node uses genericCredentialType without a
    chosen genericAuthType; otherwise the specific selected type is used.
    """

    node_name = node.get("name", "Workflow node")
    parameters = node.get("parameters") if isinstance(node.get("parameters"), dict) else {}
    host = normalize_host(parameters.get("url"))
    authentication = str(parameters.get("authentication") or "").lower()
    generic = str(parameters.get("genericAuthType") or "").strip()
    catalog = {entry["type"]: entry for entry in credential_type_catalog()}
    if generic in catalog:
        allowed_specs = [catalog[generic]]
    elif authentication == "genericcredentialtype":
        allowed_specs = list(catalog.values())  # ambiguous -> full picker
    elif credential_type in catalog:
        allowed_specs = [catalog[credential_type]]
    else:
        allowed_specs = list(catalog.values())
    primary = allowed_specs[0]["type"]
    return CredentialRequestAttachment(
        data=CredentialRequestData(
            workflowId=workflow_id,
            workflowName=workflow_name,
            nodeName=node_name,
            service=host or "HTTP API",
            credentialType=primary,
            credentialName=f"{host or 'HTTP API'} - Conduut",
            fields=[CredentialField(**field) for field in catalog[primary]["fields"]],
            allowedTypes=[
                CredentialTypeOption(
                    type=entry["type"],
                    label=entry["label"],
                    fields=[CredentialField(**field) for field in entry["fields"]],
                )
                for entry in allowed_specs
            ],
            host=host,
            submitPath="/api/credentials",
            description="This API call needs authentication. Add or pick a credential below.",
        )
    )


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

    if is_supported_http_type(credential_type) and _is_http_request_node(node):
        return _http_credential_request(workflow_id, workflow_name, node, credential_type)

    definition = registry.get_credential_definition(credential_type)
    if definition is not None and not definition.is_oauth and not definition.generic_auth:
        from src.agent.credential_catalog import credential_fields_from_definition

        fields = credential_fields_from_definition(definition)
        icon_url = definition.icon_url or None
    else:
        try:
            schema = await n8n_client.get_credential_schema(credential_type)
            fields = _fields_from_schema(schema)
        except Exception:
            fields = [
                CredentialField(name="apiKey", label="API Key", type="password", required=True)
            ]
        icon_url = None

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
            matchKind="type",
            iconUrl=icon_url,
        )
    )


async def analyze_workflow_readiness_payload(
    workflow: dict[str, Any],
    *,
    user_id: str | None = None,
) -> dict[str, Any]:
    missing: list[AgentAttachment] = []
    reuse_candidates: list[dict[str, Any]] = []
    research_candidates: list[dict[str, Any]] = []
    http_credentials: list[Any] | None = None
    workflow_id = str(workflow.get("id") or "")
    for node in workflow.get("nodes", []):
        if not isinstance(node, dict):
            continue
        schema = registry.get_node_schema(node.get("type", ""))
        credential_types = _required_credential_types_for_node(node, schema)
        if not credential_types:
            continue
        credential_type = _select_credential_type(node, credential_types)
        if not credential_type:
            continue
        has_credential = _node_has_credential(node, credential_types)
        managed_connection = _managed_google_connection_for_node(node, credential_type)
        try:
            attached = (
                await _attach_managed_connection_if_available(
                    user_id,
                    workflow_id,
                    node,
                    credential_type,
                )
                if managed_connection
                else False
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
        if attached or has_credential:
            continue

        # Custom HTTP credential: match the user's saved library by host
        # (confirm-first). Scoped to outbound HTTP Request nodes; do NOT use the
        # cross-workflow reuse bridge here.
        if is_supported_http_type(credential_type) and _is_http_request_node(node):
            if http_credentials is None:
                http_credentials = await store.list_custom_credentials(user_id) if user_id else []
            generic = str(node.get("parameters", {}).get("genericAuthType") or "").strip() or None
            url = node.get("parameters", {}).get("url")
            # Only READY credentials can be attached; drafts have no n8n credential.
            ready_credentials = [
                credential
                for credential in http_credentials
                if getattr(credential, "status", "ready") == "ready"
            ]
            matches = match_credentials(url, ready_credentials, credential_type=generic)
            if matches:
                for credential in matches:
                    reuse_candidates.append(
                        {
                            "nodeName": str(node.get("name") or ""),
                            "credentialId": credential.id,
                            "label": credential.label,
                            "credentialType": credential.credential_type,
                            "host": credential.host,
                            "matchKind": "host",
                        }
                    )
                continue
            # No saved credential: defer to the agent's prepare_api_credential
            # flow (research -> draft, or a manual fallback card) so the user sees
            # exactly one credential card, not the manual card AND the draft card.
            log.info(
                "workflow_needs_credential_research",
                workflow_id=workflow_id,
                node=node.get("name"),
                credential_type=credential_type,
            )
            research_candidates.append(
                {"nodeName": str(node.get("name") or ""), "url": str(url or "")}
            )
            continue

        # Predefined credential library (type-matched), before the reuse bridge.
        if http_credentials is None:
            http_credentials = await store.list_custom_credentials(user_id) if user_id else []
        type_matches = match_credentials_by_type(credential_type, http_credentials)
        if type_matches:
            for credential in type_matches:
                reuse_candidates.append(
                    {
                        "nodeName": str(node.get("name") or ""),
                        "credentialId": credential.id,
                        "label": credential.label,
                        "credentialType": credential.credential_type,
                        "host": credential.host,
                        "matchKind": "type",
                    }
                )
            continue

        # Non-HTTP, managed-less types (e.g. openAiApi): cross-workflow reuse bridge.
        try:
            attached = await _attach_existing_credential_if_available(
                workflow_id, node, credential_type
            )
        except Exception as exc:
            log.warning(
                "existing_credential_reuse_failed",
                workflow_id=workflow_id,
                node=node.get("name"),
                credential_type=credential_type,
                error=str(exc),
            )
            attached = False
        if attached:
            continue
        log.info(
            "workflow_missing_credential",
            workflow_id=workflow_id,
            node=node.get("name"),
            node_type=node.get("type"),
            credential_type=credential_type,
            managed_connection=bool(managed_connection),
        )
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
        "ready": len(missing) == 0 and len(reuse_candidates) == 0 and len(research_candidates) == 0,
        "missing_credentials": missing,
        "reuse_candidates": reuse_candidates,
        "research_candidates": research_candidates,
        "testable": len(webhook_nodes) > 0 or len(manual_trigger_nodes) > 0,
        "webhook_nodes": webhook_nodes,
        "manual_trigger_nodes": manual_trigger_nodes,
    }


async def attach_unambiguous_reuse_candidates(
    workflow_id: str,
    user_id: str | None,
    reuse_candidates: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Attach reuse candidates for nodes with exactly one host match.

    Used on an explicit user-initiated run (dashboard Run / batch) so a
    deterministic single host match is wired without a separate chat
    confirmation. Nodes with multiple matches are left for chat confirmation.
    """

    if not user_id or not workflow_id or not reuse_candidates:
        return []
    by_node: dict[str, list[dict[str, Any]]] = {}
    for candidate in reuse_candidates:
        by_node.setdefault(str(candidate.get("nodeName") or ""), []).append(candidate)

    attached: list[dict[str, Any]] = []
    for node_name, candidates in by_node.items():
        if not node_name or len(candidates) != 1:
            continue
        candidate = candidates[0]
        credential = await store.get_custom_credential(user_id, str(candidate.get("credentialId")))
        if not credential:
            continue
        generic = (
            credential.credential_type
            if is_supported_http_type(credential.credential_type)
            else None
        )
        try:
            await n8n_client.attach_credential_to_workflow(
                workflow_id,
                node_name,
                credential.credential_type,
                credential.n8n_credential_id,
                credential.n8n_credential_name,
                generic_auth_type=generic,
            )
        except Exception as exc:
            log.warning(
                "reuse_candidate_attach_failed",
                workflow_id=workflow_id,
                node=node_name,
                error=str(exc),
            )
            continue
        log.info(
            "reuse_candidate_auto_attached",
            workflow_id=workflow_id,
            node=node_name,
            credential_id=candidate.get("credentialId"),
        )
        attached.append(candidate)
    return attached


async def _emit_missing_credentials(
    ctx: RunContext[AgentDeps], workflow: dict[str, Any]
) -> dict[str, Any]:
    """Emit missing-credential cards and return counts + reuse suggestions.

    Returns ``{"missing_count": int, "reuse_candidates": list}``. Missing cards
    set ``awaiting_user_input``; reuse candidates do not (the agent asks for
    confirmation via request_user_input, which sets the flag itself).
    """

    readiness = await analyze_workflow_readiness_payload(workflow, user_id=ctx.deps.user_id)
    missing = readiness["missing_credentials"]
    for attachment in missing:
        await ctx.deps.emit_attachment(attachment)
    if missing:
        ctx.deps.awaiting_user_input = True
    return {
        "missing_count": len(missing),
        "reuse_candidates": readiness.get("reuse_candidates", []),
        "research_candidates": readiness.get("research_candidates", []),
    }


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
