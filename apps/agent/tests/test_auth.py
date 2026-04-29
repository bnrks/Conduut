import pytest
from fastapi import HTTPException

from src import auth as auth_module


class FakeRequest:
    def __init__(self, authorization: str = ""):
        self.headers = {"authorization": authorization}


def test_get_user_id_verifies_bearer_token_with_clock_skew(monkeypatch):
    def fake_verify(token: str, *, clock_skew_seconds: int):
        assert token == "token"
        assert clock_skew_seconds == 5
        return {"uid": "user_1"}

    monkeypatch.setattr(auth_module.auth, "verify_id_token", fake_verify)

    assert auth_module.get_user_id(FakeRequest("Bearer token")) == "user_1"


def test_get_user_id_rejects_missing_bearer_token():
    with pytest.raises(HTTPException) as exc:
        auth_module.get_user_id(FakeRequest())

    assert exc.value.status_code == 401


def test_get_user_id_rejects_invalid_token(monkeypatch):
    def fake_verify(_token: str, *, clock_skew_seconds: int):
        raise ValueError("bad token")

    monkeypatch.setattr(auth_module.auth, "verify_id_token", fake_verify)

    with pytest.raises(HTTPException) as exc:
        auth_module.get_user_id(FakeRequest("Bearer bad"))

    assert exc.value.status_code == 401
