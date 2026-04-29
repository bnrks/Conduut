from fastapi import HTTPException, Request
from firebase_admin import auth


def get_user_id(request: Request) -> str:
    header = request.headers.get("authorization", "")
    if not header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing Authorization header")

    token = header.removeprefix("Bearer ")
    try:
        decoded = auth.verify_id_token(token, clock_skew_seconds=5)
        return decoded["uid"]
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
