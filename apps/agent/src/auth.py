import structlog
from fastapi import HTTPException, Request
from firebase_admin import auth

log = structlog.get_logger()
_FIREBASE_CLOCK_SKEW_SECONDS = 60


def get_user_id(request: Request) -> str:
    header = request.headers.get("authorization", "")
    if not header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing Authorization header")

    token = header.removeprefix("Bearer ")
    try:
        decoded = auth.verify_id_token(
            token,
            clock_skew_seconds=_FIREBASE_CLOCK_SKEW_SECONDS,
        )
        return decoded["uid"]
    except Exception as exc:
        log.warning(
            "firebase_token_rejected",
            error_type=type(exc).__name__,
            error=str(exc),
        )
        raise HTTPException(status_code=401, detail="Invalid or expired token")
