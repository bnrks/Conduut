"""Authenticated agent token-usage endpoint."""

from fastapi import APIRouter, HTTPException, Query, Request

from src import usage
from src.auth import get_user_id

router = APIRouter()
_ALLOWED_DAYS = {1, 7, 30, 90}


@router.get("/usage", response_model=usage.UsageSummary)
async def get_usage(
    request: Request,
    days: int = Query(default=30),
) -> usage.UsageSummary:
    if days not in _ALLOWED_DAYS:
        raise HTTPException(
            status_code=422,
            detail="days must be one of 1, 7, 30, or 90",
        )
    return await usage.get_usage_summary(get_user_id(request), days=days)
