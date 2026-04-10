import asyncio

from fastapi import HTTPException, Request
from firebase_admin import auth


def get_user_id(request: Request) -> str:
    header = request.headers.get("authorization", "")
    if not header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing Authorization header")

    token = header.removeprefix("Bearer ")
    try:
        decoded = asyncio.get_event_loop().run_in_executor(
            None, lambda: auth.verify_id_token(token)
        )
        # verify_id_token is sync — call directly
        decoded = auth.verify_id_token(token)
        return decoded["uid"]
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
