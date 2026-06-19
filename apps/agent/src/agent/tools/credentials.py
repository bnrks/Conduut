"""Agent tool payloads for the custom (HTTP) credential library."""

from typing import Any

import structlog

from src import n8n_client, store
from src.agent.credential_types import is_supported_http_type, match_credentials
from src.agent.schemas import AgentDeps
from src.agent.tools.common import _safe_error

log = structlog.get_logger()


async def list_credentials_payload(deps: AgentDeps, url: str | None = None) -> dict[str, Any]:
    """Return the user's saved custom credentials (no secrets).

    When ``url`` is given, ``matches_host`` flags credentials whose saved host
    matches the URL host so the agent can offer the right one for confirmation.
    """

    credentials = await store.list_custom_credentials(deps.user_id)
    matched_ids = {c.id for c in match_credentials(url, credentials)} if url else set()
    return {
        "credentials": [
            {
                "id": credential.id,
                "label": credential.label,
                "credential_type": credential.credential_type,
                "host": credential.host,
                "matches_host": credential.id in matched_ids,
            }
            for credential in credentials
        ]
    }


async def attach_credential_payload(
    deps: AgentDeps,
    workflow_id: str,
    node_name: str,
    credential_id: str,
) -> dict[str, Any]:
    """Attach one of the user's saved credentials to a workflow node.

    Ownership is enforced via Firestore (the credential must belong to the
    current user). For generic HTTP types the node's auth parameters are wired
    so n8n actually uses the credential.
    """

    credential = await store.get_custom_credential(deps.user_id, credential_id)
    if not credential:
        return {"error": "Credential not found for this user."}
    try:
        generic = (
            credential.credential_type
            if is_supported_http_type(credential.credential_type)
            else None
        )
        await n8n_client.attach_credential_to_workflow(
            workflow_id,
            node_name,
            credential.credential_type,
            credential.n8n_credential_id,
            credential.n8n_credential_name,
            generic_auth_type=generic,
        )
    except Exception as exc:
        log.error("tool_error", tool="attach_credential", error=str(exc))
        return {"error": _safe_error(exc)}

    log.info(
        "custom_credential_attached",
        workflow_id=workflow_id,
        node=node_name,
        credential_id=credential_id,
        credential_type=credential.credential_type,
    )
    return {
        "success": True,
        "workflow_id": workflow_id,
        "node_name": node_name,
        "credential": {"id": credential.id, "label": credential.label},
    }
