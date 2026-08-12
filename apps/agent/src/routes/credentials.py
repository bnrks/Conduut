"""Credential routes for the custom (HTTP) credential library managed through Conduut.

The secret value lives only in n8n's credential store (write-only; never read
back). Conduut keeps non-secret metadata (label, type, host, n8n id) per-user in
Firestore so credentials can be listed and matched to HTTP nodes by host.
"""

from typing import Any
from urllib.parse import unquote

import structlog
from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field

from src import n8n_client, store
from src.agent import credential_catalog
from src.agent.assurance import workflow_fingerprint
from src.agent.credential_types import (
    SUPPORTED_HTTP_CREDENTIAL_TYPES,
    credential_type_catalog,
    is_supported_http_type,
    normalize_host,
)
from src.auth import get_user_id
from src.n8n_provider import N8nClientFactory, N8nInstanceResolver, N8nProviderError, error_detail
from src.registry import registry

router = APIRouter()
log = structlog.get_logger()
resolver = N8nInstanceResolver()
client_factory = N8nClientFactory()


class CredentialSubmitIn(BaseModel):
    credential_type: str = Field(min_length=1)
    data: dict[str, Any]
    label: str | None = None
    credential_name: str | None = None  # legacy alias for label
    host: str | None = None
    service: str | None = None  # legacy/ignored
    workflow_id: str | None = None
    node_name: str | None = None
    generic_auth_type: str | None = None
    match_kind: str | None = None  # "host" | "type"; derived from type when absent


class CredentialFinalizeIn(BaseModel):
    data: dict[str, Any]  # the secret field values the user provided


def _build_n8n_data(credential: store.CustomCredential, secret: dict[str, Any]) -> dict[str, Any]:
    """Build the n8n credential `data` from a draft's auth_config + user secret."""

    config = credential.auth_config or {}
    field_name = str(config.get("field_name") or "")
    value_prefix = str(config.get("value_prefix") or "")
    fields = credential.secret_fields or []
    primary = str(secret.get(fields[0])) if fields else ""

    if credential.credential_type == "httpHeaderAuth":
        return {"name": field_name or "Authorization", "value": f"{value_prefix}{primary}"}
    if credential.credential_type == "httpQueryAuth":
        return {"name": field_name or "api_key", "value": primary}
    if credential.credential_type == "httpBasicAuth":
        return {"user": str(secret.get("user", "")), "password": str(secret.get("password", ""))}
    if credential.credential_type == "httpCustomAuth":
        return {"json": str(secret.get("json", ""))}
    # Fallback: pass the provided fields through verbatim.
    return {key: secret.get(key) for key in fields}


def _credential_icon_url(credential: store.CustomCredential) -> str:
    """Service (type-matched) credentials carry their n8n service icon; others none."""
    if credential.match_kind != "type":
        return ""
    definition = registry.get_credential_definition(credential.credential_type)
    return definition.icon_url if definition else ""


def _provider_http_error(exc: N8nProviderError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=error_detail(exc))


async def _request_n8n(request: Request, user_id: str):
    request_state = getattr(request, "state", None)
    request_headers = getattr(request, "headers", {})
    request_id = getattr(request_state, "request_id", None) or request_headers.get("x-request-id")
    context = await resolver.resolve(user_id, request_id=request_id)
    client = await client_factory.for_request_context(context)
    return context, client


async def _ensure_attach_allowed(user_id: str, workflow_id: str, *, context, client):
    """Reject drift when metadata exists; customer ownership needs no adoption step."""

    instance_id = context.target.instance_id
    if context.target.ownership != "customer_owned":
        return None
    metadata = await store.get_workflow_metadata(
        user_id,
        workflow_id,
        instance_id=instance_id,
    )
    workflow = await client.get_workflow(workflow_id)
    if metadata is not None:
        baseline = metadata.resources.get("workflow_baseline")
        if isinstance(baseline, dict):
            expected_instance = str(baseline.get("instance_id") or "")
            expected_updated_at = str(baseline.get("workflow_updated_at") or "")
            expected_fingerprint = str(baseline.get("workflow_fingerprint") or "")
            current_updated_at = str(workflow.get("updatedAt") or "")
            drifted = bool(expected_instance and expected_instance != instance_id)
            drifted = drifted or bool(
                expected_updated_at
                and current_updated_at
                and expected_updated_at != current_updated_at
            )
            drifted = drifted or bool(
                expected_fingerprint and expected_fingerprint != workflow_fingerprint(workflow)
            )
            if drifted:
                raise HTTPException(
                    status_code=409,
                    detail={
                        "code": "workflow_drift_detected",
                        "message": (
                            "This workflow changed in n8n. Import the remote version before "
                            "attaching a credential."
                        ),
                    },
                )
    return metadata


async def _refresh_attach_baseline(
    user_id: str,
    workflow_id: str,
    *,
    instance_id: str,
    metadata,
    client,
) -> bool:
    try:
        workflow = await client.get_workflow(workflow_id)
        resources = dict(metadata.resources) if metadata else {}
        resources["workflow_baseline"] = {
            "instance_id": instance_id,
            "workflow_fingerprint": workflow_fingerprint(workflow),
            "workflow_updated_at": str(workflow.get("updatedAt") or ""),
        }
        await store.save_workflow_metadata(
            user_id,
            workflow_id,
            input_schema=metadata.input_schema if metadata else [],
            resources=resources,
            instance_id=instance_id,
        )
    except Exception as exc:
        # The remote attachment already committed. Do not turn a local baseline
        # refresh failure into a retryable-looking 400 that could repeat it.
        log.warning(
            "credential_attach_baseline_refresh_failed",
            workflow_id=workflow_id,
            instance_id=instance_id,
            error_type=type(exc).__name__,
        )
        return False
    return True


@router.get("/credentials")
async def list_credentials(request: Request):
    user_id = get_user_id(request)
    instance = await store.get_active_n8n_instance(user_id)
    credentials = (
        await store.list_custom_credentials(user_id, instance_id=instance.id)
        if instance is not None
        else await store.list_custom_credentials(user_id)
    )
    return {
        "credentials": [
            {
                "id": item.id,
                "label": item.label,
                "credential_type": item.credential_type,
                "host": item.host,
                "status": item.status,
                "match_kind": item.match_kind,
                "icon_url": _credential_icon_url(item),
                "source_url": item.source_url,
                "secret_fields": item.secret_fields,
                "created_at": item.created_at,
            }
            for item in credentials
        ]
    }


@router.get("/credentials/types")
async def credential_types(request: Request):
    get_user_id(request)
    return {"types": credential_type_catalog()}


@router.get("/credentials/icon")
async def credential_icon(path: str, request: Request):
    """Public proxy for n8n-served credential icons (public SVG assets; <img> can't
    send a bearer token). Strictly limited to n8n's ``icons/`` path to prevent SSRF.
    """
    user_id = get_user_id(request)
    safe_path = path
    for _ in range(5):
        decoded = unquote(safe_path)
        if decoded == safe_path:
            break
        safe_path = decoded
    if not safe_path.startswith("icons/") or ".." in safe_path:
        raise HTTPException(status_code=400, detail={"message": "Invalid icon path."})
    try:
        _context, client = await _request_n8n(request, user_id)
    except N8nProviderError as exc:
        raise _provider_http_error(exc) from exc
    try:
        response = await client.fetch_public_asset(safe_path)
    except Exception as exc:
        raise HTTPException(status_code=502, detail={"message": "Icon unavailable."}) from exc
    if response.status_code != 200:
        status_code = 502 if response.status_code >= 500 else 404
        raise HTTPException(status_code=status_code, detail={"message": "Icon not found."})
    return Response(
        content=response.content,
        media_type=response.headers.get("content-type", "image/svg+xml"),
        headers={"Cache-Control": "public, max-age=86400"},
    )


@router.get("/credentials/catalog")
async def credential_catalog_list(request: Request, q: str | None = None):
    get_user_id(request)
    return {"catalog": registry.list_credential_catalog(q)}


@router.get("/credentials/catalog/{credential_type}/schema")
async def credential_catalog_schema(request: Request, credential_type: str):
    user_id = get_user_id(request)
    try:
        _context, client = await _request_n8n(request, user_id)
    except N8nProviderError as exc:
        raise _provider_http_error(exc) from exc
    definition = registry.get_credential_definition(credential_type)
    if definition is not None:
        if definition.is_oauth or definition.generic_auth:
            raise HTTPException(
                status_code=422,
                detail={"message": "OAuth-based services are managed under Connections."},
            )
        fields = credential_catalog.credential_fields_from_definition(definition)
        return {
            "credentialType": credential_type,
            "label": definition.display_name,
            "iconUrl": definition.icon_url,
            "fields": [field.model_dump() for field in fields],
        }
    # Fallback: definition missing from credentials.json -> public-API schema.
    if credential_catalog.is_oauth_type_name(credential_type):
        raise HTTPException(
            status_code=422,
            detail={"message": "OAuth-based services are managed under Connections."},
        )
    try:
        schema = await client.get_credential_schema(credential_type)
    except n8n_client.N8nApiError as exc:
        raise HTTPException(status_code=exc.status_code, detail={"message": exc.message}) from exc
    if credential_catalog.schema_is_oauth(schema):
        raise HTTPException(
            status_code=422,
            detail={"message": "OAuth-based services are managed under Connections."},
        )
    fields = credential_catalog.parse_schema_fields(schema)
    return {
        "credentialType": credential_type,
        "label": credential_type,
        "iconUrl": "",
        "fields": [field.model_dump() for field in fields],
    }


@router.post("/credentials", status_code=201)
async def submit_credential(request: Request, body: CredentialSubmitIn):
    user_id = get_user_id(request)
    try:
        context, client = await _request_n8n(request, user_id)
    except N8nProviderError as exc:
        raise _provider_http_error(exc) from exc
    credential_type = body.credential_type
    label = (
        body.label
        or body.credential_name
        or SUPPORTED_HTTP_CREDENTIAL_TYPES.get(credential_type, {}).get("label")
        or credential_type
    )
    attach_metadata = None
    workflow_sync_status: str | None = None
    if body.workflow_id and body.node_name:
        attach_metadata = await _ensure_attach_allowed(
            user_id,
            body.workflow_id,
            context=context,
            client=client,
        )

    match_kind = body.match_kind or ("host" if is_supported_http_type(credential_type) else "type")

    # Host is required only for the generic HTTP (host-matched) library path.
    host = normalize_host(body.host) or ""
    host_required = (
        match_kind == "host"
        and is_supported_http_type(credential_type)
        and (body.generic_auth_type is not None or not body.workflow_id)
    )
    if host_required and not host:
        raise HTTPException(
            status_code=422,
            detail={"message": "A valid host (e.g. api.example.com) is required."},
        )

    try:
        credential = await client.create_credential(label, credential_type, body.data)
        saved = await store.save_custom_credential(
            user_id,
            label=label,
            credential_type=credential_type,
            host=host,
            n8n_credential_id=credential.id,
            n8n_credential_name=credential.name,
            match_kind=match_kind,
            instance_id=context.target.instance_id,
        )
        if body.workflow_id and body.node_name:
            generic = (
                None
                if match_kind == "type"
                else (
                    body.generic_auth_type
                    or (credential_type if is_supported_http_type(credential_type) else None)
                )
            )
            await client.attach_credential_to_workflow(
                body.workflow_id,
                body.node_name,
                credential_type,
                credential.id,
                credential.name,
                generic_auth_type=generic,
            )
            baseline_refreshed = await _refresh_attach_baseline(
                user_id,
                body.workflow_id,
                instance_id=context.target.instance_id,
                metadata=attach_metadata,
                client=client,
            )
            workflow_sync_status = "synced" if baseline_refreshed else "needs_reconcile"
    except n8n_client.N8nApiError as exc:
        raise HTTPException(status_code=exc.status_code, detail={"message": exc.message}) from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail={"message": str(exc)}) from exc

    return {
        "credential": {
            "id": saved.id,
            "label": saved.label,
            "credential_type": saved.credential_type,
            "host": saved.host,
        },
        "workflow_id": body.workflow_id,
        "workflow_sync_status": workflow_sync_status,
    }


@router.delete("/credentials/{credential_id}")
async def delete_credential(request: Request, credential_id: str):
    user_id = get_user_id(request)
    try:
        context, client = await _request_n8n(request, user_id)
    except N8nProviderError as exc:
        raise _provider_http_error(exc) from exc
    credential = await store.get_custom_credential(
        user_id,
        credential_id,
        instance_id=context.target.instance_id,
    )
    if not credential:
        raise HTTPException(status_code=404, detail={"message": "Credential not found."})
    if credential.n8n_credential_id:
        try:
            await client.delete_credential(credential.n8n_credential_id)
        except Exception as exc:
            log.warning(
                "custom_credential_n8n_delete_failed",
                credential_id=credential_id,
                error=str(exc),
            )
    await store.delete_custom_credential(
        user_id,
        credential_id,
        instance_id=context.target.instance_id,
    )
    return {"deleted": True}


@router.post("/credentials/{credential_id}/finalize", status_code=201)
async def finalize_credential(request: Request, credential_id: str, body: CredentialFinalizeIn):
    user_id = get_user_id(request)
    try:
        context, client = await _request_n8n(request, user_id)
    except N8nProviderError as exc:
        raise _provider_http_error(exc) from exc
    credential = await store.get_custom_credential(
        user_id,
        credential_id,
        instance_id=context.target.instance_id,
    )
    if not credential:
        raise HTTPException(status_code=404, detail={"message": "Credential not found."})
    if credential.status != "draft":
        raise HTTPException(status_code=409, detail={"message": "Credential already completed."})

    attach_metadata = None
    workflow_sync_status: str | None = None
    if credential.pending_workflow_id and credential.pending_node_name:
        attach_metadata = await _ensure_attach_allowed(
            user_id,
            credential.pending_workflow_id,
            context=context,
            client=client,
        )

    n8n_data = _build_n8n_data(credential, body.data)
    try:
        created = await client.create_credential(
            credential.label, credential.credential_type, n8n_data
        )
        saved = await store.finalize_draft_credential(
            user_id,
            credential_id,
            n8n_credential_id=created.id,
            n8n_credential_name=created.name,
            instance_id=context.target.instance_id,
        )
        if credential.pending_workflow_id and credential.pending_node_name:
            generic = (
                credential.credential_type
                if is_supported_http_type(credential.credential_type)
                else None
            )
            await client.attach_credential_to_workflow(
                credential.pending_workflow_id,
                credential.pending_node_name,
                credential.credential_type,
                created.id,
                created.name,
                generic_auth_type=generic,
            )
            baseline_refreshed = await _refresh_attach_baseline(
                user_id,
                credential.pending_workflow_id,
                instance_id=context.target.instance_id,
                metadata=attach_metadata,
                client=client,
            )
            workflow_sync_status = "synced" if baseline_refreshed else "needs_reconcile"
    except n8n_client.N8nApiError as exc:
        raise HTTPException(status_code=exc.status_code, detail={"message": exc.message}) from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail={"message": str(exc)}) from exc

    return {
        "credential": {
            "id": (saved or credential).id,
            "label": (saved or credential).label,
            "credential_type": credential.credential_type,
            "host": credential.host,
            "status": "ready",
        },
        "workflow_id": credential.pending_workflow_id or None,
        "workflow_sync_status": workflow_sync_status,
    }
