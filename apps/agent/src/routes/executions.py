"""Authenticated execution-history endpoints."""

from typing import Literal

from fastapi import APIRouter, HTTPException, Query, Request

from src import executions, n8n_client
from src.auth import get_user_id
from src.n8n_provider import N8nClientFactory, N8nInstanceResolver, N8nProviderError, error_detail

router = APIRouter()
resolver = N8nInstanceResolver()
client_factory = N8nClientFactory()

ExecutionStatus = Literal[
    "error",
    "success",
    "waiting",
    "running",
    "canceled",
    "cancelled",
]


def _n8n_http_error(exc: n8n_client.N8nApiError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail={"message": exc.message})


def _provider_http_error(exc: N8nProviderError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=error_detail(exc))


async def _request_n8n(request: Request, user_id: str):
    request_state = getattr(request, "state", None)
    request_headers = getattr(request, "headers", {})
    request_id = getattr(request_state, "request_id", None) or request_headers.get("x-request-id")
    context = await resolver.resolve(user_id, request_id=request_id)
    client = await client_factory.for_request_context(context)
    return context, client


@router.get("/executions", response_model=executions.RunPage)
async def list_executions(
    request: Request,
    workflow_id: str | None = Query(default=None, min_length=1, max_length=128),
    status: ExecutionStatus | None = None,
    cursor: str | None = Query(default=None, min_length=1, max_length=500),
    limit: int = Query(default=25, ge=1, le=100),
) -> executions.RunPage:
    user_id = get_user_id(request)
    try:
        _context, client = await _request_n8n(request, user_id)
        return await executions.list_runs(
            user_id,
            workflow_id=workflow_id,
            status=status,
            cursor=cursor,
            limit=limit,
            n8n=client,
        )
    except N8nProviderError as exc:
        raise _provider_http_error(exc) from exc
    except n8n_client.N8nApiError as exc:
        raise _n8n_http_error(exc) from exc


@router.get("/executions/{execution_id}", response_model=executions.RunDetail)
async def get_execution(execution_id: str, request: Request) -> executions.RunDetail:
    user_id = get_user_id(request)
    try:
        _context, client = await _request_n8n(request, user_id)
        return await executions.get_run(user_id, execution_id, n8n=client)
    except executions.ExecutionNotFoundError as exc:
        raise HTTPException(
            status_code=404,
            detail={"message": "Execution not found."},
        ) from exc
    except N8nProviderError as exc:
        raise _provider_http_error(exc) from exc
    except n8n_client.N8nApiError as exc:
        raise _n8n_http_error(exc) from exc
