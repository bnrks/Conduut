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
from src.agent.credential_types import (
    SUPPORTED_HTTP_CREDENTIAL_TYPES,
    credential_type_catalog,
    is_supported_http_type,
    normalize_host,
)
from src.auth import get_user_id

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
                "created_at": item.created_at,
            }
            for item in credentials
        ]
    }


@router.get("/credentials/types")
async def credential_types(request: Request):
    get_user_id(request)
    return {"types": credential_type_catalog()}


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

    host = ""
    if is_supported_http_type(credential_type):
        normalized = normalize_host(body.host)
        if not normalized:
            raise HTTPException(
                status_code=422,
                detail={"message": "A valid host (e.g. api.example.com) is required."},
            )
        host = normalized

    try:
        credential = await n8n_client.create_credential(label, credential_type, body.data)
        saved = await store.save_custom_credential(
            user_id,
            label=label,
            credential_type=credential_type,
            host=host,
            n8n_credential_id=credential.id,
            n8n_credential_name=credential.name,
        )
        if body.workflow_id and body.node_name:
            generic = body.generic_auth_type or (
                credential_type if is_supported_http_type(credential_type) else None
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
