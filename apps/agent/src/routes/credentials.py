"""Credential routes for n8n workflow credentials managed through Conduut."""

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from src import n8n_client, store
from src.auth import get_user_id

router = APIRouter()


class CredentialSubmitIn(BaseModel):
    workflow_id: str = Field(min_length=1)
    node_name: str = Field(min_length=1)
    service: str = Field(min_length=1)
    credential_type: str = Field(min_length=1)
    credential_name: str = Field(min_length=1)
    data: dict[str, Any]


@router.get("/credentials")
async def list_credentials(request: Request):
    user_id = get_user_id(request)
    credentials = await store.list_workflow_credentials(user_id)
    return {
        "credentials": [
            {
                "id": item.id,
                "service": item.service,
                "credential_type": item.credential_type,
                "credential_name": item.credential_name,
                "node_name": item.node_name,
                "workflow_id": item.workflow_id,
                "created_at": item.created_at,
            }
            for item in credentials
        ]
    }


@router.post("/credentials", status_code=201)
async def submit_credential(request: Request, body: CredentialSubmitIn):
    user_id = get_user_id(request)
    try:
        credential = await n8n_client.create_credential(
            body.credential_name,
            body.credential_type,
            body.data,
        )
        await n8n_client.attach_credential_to_workflow(
            body.workflow_id,
            body.node_name,
            body.credential_type,
            credential.id,
            credential.name,
        )
    except n8n_client.N8nApiError as exc:
        raise HTTPException(status_code=exc.status_code, detail={"message": exc.message}) from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail={"message": str(exc)}) from exc

    saved = await store.save_workflow_credential(
        user_id,
        service=body.service,
        credential_type=body.credential_type,
        credential_name=credential.name,
        n8n_credential_id=credential.id,
        node_name=body.node_name,
        workflow_id=body.workflow_id,
    )
    return {
        "credential": {
            "id": saved.id,
            "service": saved.service,
            "credential_type": saved.credential_type,
            "credential_name": saved.credential_name,
            "node_name": saved.node_name,
            "workflow_id": saved.workflow_id,
        },
        "workflow_id": body.workflow_id,
    }
