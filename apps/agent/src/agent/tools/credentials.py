"""Agent tool payloads for the custom (HTTP) credential library."""

from typing import Any

import structlog

from src import n8n_client, store
from src.agent.credential_types import (
    is_supported_http_type,
    match_credentials,
    normalize_host,
)
from src.agent.research import credential_type_for_scheme, research_api_auth
from src.agent.schemas import (
    AgentDeps,
    CredentialField,
    CredentialRequestAttachment,
    CredentialRequestData,
)
from src.agent.tools.common import _credential_draft_instruction, _safe_error

log = structlog.get_logger()

_SECRET_FIELD_LABELS = {
    "key": "API key / token",
    "value": "API key",
    "user": "Username",
    "password": "Password",
    "json": "Auth JSON",
}
_DEFAULT_SECRET_FIELDS = {
    "httpHeaderAuth": ["key"],
    "httpQueryAuth": ["value"],
    "httpBasicAuth": ["user", "password"],
    "httpCustomAuth": ["json"],
}


def _secret_field(name: str) -> CredentialField:
    return CredentialField(
        name=name,
        label=_SECRET_FIELD_LABELS.get(name, name.replace("_", " ").title()),
        type="json" if name == "json" else "password",
        required=True,
    )


def _draft_card(credential: store.CustomCredential) -> CredentialRequestAttachment:
    return CredentialRequestAttachment(
        data=CredentialRequestData(
            workflowId=credential.pending_workflow_id or "",
            nodeName=credential.pending_node_name or "",
            service=credential.host or "API",
            credentialType=credential.credential_type,
            credentialName=credential.label,
            fields=[_secret_field(name) for name in credential.secret_fields],
            submitPath=f"/api/credentials/{credential.id}/finalize",
            description="I prepared this credential — just enter the secret to finish.",
            draftId=credential.id,
            host=credential.host or None,
            sourceUrl=credential.source_url or None,
        )
    )


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


async def prepare_api_credential_payload(
    deps: AgentDeps,
    api_or_url: str,
    workflow_id: str | None = None,
    node_name: str | None = None,
) -> dict[str, Any]:
    """Research how an API authenticates and prepare a secret-less draft credential.

    Returns a status the agent acts on:
    - ``exists`` — a ready saved credential already covers this host.
    - ``draft_pending`` — a draft for this host already awaits its secret.
    - ``draft_created`` — researched + draft created; ``card`` collects the secret.
    - ``needs_manual`` — low confidence; fall back to the normal credential card.
    - ``no_auth`` — the API needs no authentication.
    """

    host = normalize_host(api_or_url)
    credentials = await store.list_custom_credentials(deps.user_id)
    if host:
        for credential in credentials:
            if credential.status == "ready" and normalize_host(credential.host) == host:
                return {
                    "status": "exists",
                    "host": host,
                    "label": credential.label,
                    "instruction": (
                        "A saved credential already covers this API. Use the existing "
                        "confirm-first attach flow (list_credentials / attach_credential)."
                    ),
                }
        for credential in credentials:
            if credential.status == "draft" and normalize_host(credential.host) == host:
                card = _draft_card(credential)
                return {
                    "status": "draft_pending",
                    "draftId": credential.id,
                    "card": card,
                    "instruction": _credential_draft_instruction(
                        credential.label, credential.source_url
                    ),
                }

    result = await research_api_auth(api_or_url)
    if result.scheme == "none":
        return {
            "status": "no_auth",
            "instruction": "This API needs no authentication; build the node without auth.",
        }
    credential_type = credential_type_for_scheme(result.scheme)
    if credential_type is None or result.confidence == "low":
        return {
            "status": "needs_manual",
            "host": host,
            "instruction": (
                "Could not confidently determine the auth scheme. Build the HTTP node "
                "with authentication=genericCredentialType and let the normal credential "
                "card ask the user — do not invent values."
            ),
        }

    secret_fields = result.secret_fields or _DEFAULT_SECRET_FIELDS.get(credential_type, ["key"])
    label = f"{host or api_or_url}".strip() or "API"
    draft = await store.save_draft_credential(
        deps.user_id,
        label=label,
        credential_type=credential_type,
        host=host or "",
        auth_config={"field_name": result.field_name, "value_prefix": result.value_prefix},
        secret_fields=secret_fields,
        source_url=result.source_url,
        confidence=result.confidence,
        pending_workflow_id=workflow_id or "",
        pending_node_name=node_name or "",
    )
    log.info(
        "credential_draft_prepared",
        host=host,
        credential_type=credential_type,
        draft_id=draft.id,
        confidence=result.confidence,
    )
    return {
        "status": "draft_created",
        "draftId": draft.id,
        "card": _draft_card(draft),
        "summary": result.summary,
        "instruction": _credential_draft_instruction(label, result.source_url),
    }
