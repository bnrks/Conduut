"""Credential routes for the custom (HTTP) credential library managed through Conduut.

The secret value lives only in n8n's credential store (write-only; never read
back). Conduut keeps non-secret metadata (label, type, host, n8n id) per-user in
Firestore so credentials can be listed and matched to HTTP nodes by host.
"""

from typing import Any

import structlog
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from src import n8n_client, store
from src.agent import credential_catalog
from src.agent.credential_types import (
    SUPPORTED_HTTP_CREDENTIAL_TYPES,
    credential_type_catalog,
    is_supported_http_type,
    normalize_host,
)
from src.auth import get_user_id
from src.registry import registry

router = APIRouter()
log = structlog.get_logger()


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


@router.get("/credentials")
async def list_credentials(request: Request):
    user_id = get_user_id(request)
    credentials = await store.list_custom_credentials(user_id)
    return {
        "credentials": [
            {
                "id": item.id,
                "label": item.label,
                "credential_type": item.credential_type,
                "host": item.host,
                "status": item.status,
                "match_kind": item.match_kind,
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


@router.get("/credentials/catalog")
async def credential_catalog_list(request: Request, q: str | None = None):
    get_user_id(request)
    return {"catalog": registry.list_credential_catalog(q)}


@router.get("/credentials/catalog/{credential_type}/schema")
async def credential_catalog_schema(request: Request, credential_type: str):
    get_user_id(request)
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
        schema = await n8n_client.get_credential_schema(credential_type)
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
    credential_type = body.credential_type
    label = (
        body.label
        or body.credential_name
        or SUPPORTED_HTTP_CREDENTIAL_TYPES.get(credential_type, {}).get("label")
        or credential_type
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
        credential = await n8n_client.create_credential(label, credential_type, body.data)
        saved = await store.save_custom_credential(
            user_id,
            label=label,
            credential_type=credential_type,
            host=host,
            n8n_credential_id=credential.id,
            n8n_credential_name=credential.name,
            match_kind=match_kind,
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
            await n8n_client.attach_credential_to_workflow(
                body.workflow_id,
                body.node_name,
                credential_type,
                credential.id,
                credential.name,
                generic_auth_type=generic,
            )
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
    }


@router.delete("/credentials/{credential_id}")
async def delete_credential(request: Request, credential_id: str):
    user_id = get_user_id(request)
    credential = await store.get_custom_credential(user_id, credential_id)
    if not credential:
        raise HTTPException(status_code=404, detail={"message": "Credential not found."})
    if credential.n8n_credential_id:
        try:
            await n8n_client.delete_credential(credential.n8n_credential_id)
        except Exception as exc:
            log.warning(
                "custom_credential_n8n_delete_failed",
                credential_id=credential_id,
                error=str(exc),
            )
    await store.delete_custom_credential(user_id, credential_id)
    return {"deleted": True}


@router.post("/credentials/{credential_id}/finalize", status_code=201)
async def finalize_credential(request: Request, credential_id: str, body: CredentialFinalizeIn):
    user_id = get_user_id(request)
    credential = await store.get_custom_credential(user_id, credential_id)
    if not credential:
        raise HTTPException(status_code=404, detail={"message": "Credential not found."})
    if credential.status != "draft":
        raise HTTPException(status_code=409, detail={"message": "Credential already completed."})

    n8n_data = _build_n8n_data(credential, body.data)
    try:
        created = await n8n_client.create_credential(
            credential.label, credential.credential_type, n8n_data
        )
        saved = await store.finalize_draft_credential(
            user_id,
            credential_id,
            n8n_credential_id=created.id,
            n8n_credential_name=created.name,
        )
        if credential.pending_workflow_id and credential.pending_node_name:
            generic = (
                credential.credential_type
                if is_supported_http_type(credential.credential_type)
                else None
            )
            await n8n_client.attach_credential_to_workflow(
                credential.pending_workflow_id,
                credential.pending_node_name,
                credential.credential_type,
                created.id,
                created.name,
                generic_auth_type=generic,
            )
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
    }
