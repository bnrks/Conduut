"""Artifact preview listing endpoints."""

from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from src import store
from src.auth import get_user_id

router = APIRouter()


class ArtifactOriginOut(BaseModel):
    kind: Literal["chat", "workflow_run"]
    conversationId: str | None = None
    workflowId: str | None = None
    executionId: str | None = None


class ArtifactOut(BaseModel):
    id: str
    service: Literal["google_sheets", "gmail"]
    type: Literal["table_preview", "message_preview"]
    title: str
    description: str | None = None
    url: str | None = None
    source: dict[str, Any] = Field(default_factory=dict)
    table: dict[str, Any] | None = None
    message: dict[str, Any] | None = None
    origin: ArtifactOriginOut
    createdAt: str


class ArtifactListOut(BaseModel):
    artifacts: list[ArtifactOut]


def _artifact_payload(artifact: store.ArtifactRecord) -> ArtifactOut:
    return ArtifactOut(
        id=artifact.id,
        service=artifact.service,
        type=artifact.type,
        title=artifact.title,
        description=artifact.description,
        url=artifact.url,
        source=artifact.source,
        table=artifact.table,
        message=artifact.message,
        origin=ArtifactOriginOut(**artifact.origin),
        createdAt=artifact.created_at,
    )


@router.get("/artifacts", response_model=ArtifactListOut)
async def list_artifacts(
    request: Request,
    limit: int = Query(default=50, ge=1, le=100),
    service: Literal["google_sheets", "gmail"] | None = None,
) -> ArtifactListOut:
    """Return recent persisted artifact preview snapshots for the current user."""

    user_id = get_user_id(request)
    artifacts = await store.list_artifacts(user_id, limit=limit, service=service)
    return ArtifactListOut(artifacts=[_artifact_payload(artifact) for artifact in artifacts])


@router.delete("/artifacts/{artifact_id}", status_code=204)
async def delete_artifact(artifact_id: str, request: Request) -> None:
    """Delete one persisted artifact preview snapshot for the current user."""

    user_id = get_user_id(request)
    deleted = await store.delete_artifact(user_id, artifact_id)
    if not deleted:
        raise HTTPException(status_code=404, detail={"message": "Artifact not found."})
