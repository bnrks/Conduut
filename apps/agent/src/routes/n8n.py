from urllib.parse import urlparse

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from src import store
from src.agent.setup_guide import get_public_setup_guide_payload
from src.auth import get_user_id
from src.n8n_provider import N8nInstanceResolver, N8nProviderError, error_detail

router = APIRouter()
resolver = N8nInstanceResolver()


class N8nConnectIn(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    base_url: str = Field(alias="baseUrl")
    api_key: str = Field(min_length=1, alias="apiKey")
    display_name: str = Field(default="My n8n", alias="displayName")
    webhook_base_url: str | None = Field(default=None, alias="webhookBaseUrl")


class N8nCheckIn(BaseModel):
    pass


class N8nRotateIn(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    api_key: str = Field(min_length=1, alias="apiKey")
    base_url: str | None = Field(default=None, alias="baseUrl")
    webhook_base_url: str | None = Field(default=None, alias="webhookBaseUrl")
    display_name: str | None = Field(default=None, alias="displayName")


def _http_error(exc: N8nProviderError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=error_detail(exc))


def _serialize_instance(instance: store.N8nInstanceRecord | None) -> dict | None:
    if instance is None:
        return None
    parsed = urlparse(instance.base_url)
    display_host = parsed.netloc + (parsed.path if parsed.path and parsed.path != "/" else "")
    return {
        "instanceId": instance.id,
        "displayName": instance.display_name,
        "displayHost": display_host,
        "status": instance.connection_status,
        "version": instance.n8n_version,
        "capabilities": instance.capabilities,
        "verifiedAt": instance.verified_at,
        "lastHealthAt": instance.last_health_at,
        "lastErrorCode": instance.last_error_code,
    }


@router.get("/n8n/instance")
async def get_active_n8n_connection(request: Request):
    user_id = get_user_id(request)
    instance = await store.get_active_n8n_instance(user_id) or await store.get_latest_n8n_instance(
        user_id
    )
    return {"instance": _serialize_instance(instance)}


@router.get("/n8n/setup-guide")
async def get_n8n_setup_guide(request: Request):
    get_user_id(request)
    return get_public_setup_guide_payload()


@router.post("/n8n/instance/check")
async def check_n8n_connection(request: Request, body: N8nCheckIn):
    user_id = get_user_id(request)
    try:
        record = await resolver.check(user_id)
    except N8nProviderError as exc:
        raise _http_error(exc) from exc
    return {"instance": _serialize_instance(record)}


@router.post("/n8n/instance")
async def connect_n8n(request: Request, body: N8nConnectIn):
    user_id = get_user_id(request)
    try:
        record = await resolver.connect(
            user_id,
            base_url=body.base_url,
            api_key=body.api_key,
            display_name=body.display_name,
            webhook_base_url=body.webhook_base_url,
        )
    except N8nProviderError as exc:
        raise _http_error(exc) from exc
    return {"instance": _serialize_instance(record)}


@router.put("/n8n/instance/key")
async def rotate_n8n(request: Request, body: N8nRotateIn):
    user_id = get_user_id(request)
    try:
        record = await resolver.rotate(
            user_id,
            api_key=body.api_key,
            base_url=body.base_url,
            webhook_base_url=body.webhook_base_url,
            display_name=body.display_name,
        )
    except N8nProviderError as exc:
        raise _http_error(exc) from exc
    return {"instance": _serialize_instance(record)}


@router.delete("/n8n/instance")
async def disconnect_n8n(request: Request):
    user_id = get_user_id(request)
    try:
        record = await resolver.disconnect(user_id)
    except N8nProviderError as exc:
        raise _http_error(exc) from exc
    return {"instance": _serialize_instance(record)}
