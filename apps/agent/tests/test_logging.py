import json
import logging

import httpx
import pytest
import structlog
from fastapi import HTTPException
from fastapi.testclient import TestClient

from src import n8n_client
from src.config import settings
from src.logging_config import LOG_FILE_NAME, configure_logging, redact_for_logging
from src.main import app
from src.routes import connections as connections_route


def _flush_handlers() -> None:
    for handler in logging.getLogger().handlers:
        handler.flush()


def test_redaction_masks_secrets_and_truncates_large_values():
    redacted = redact_for_logging(
        {
            "api_key": "sk-secret",
            "nested": {
                "access_token": "access-token",
                "clientSecret": "client-secret",
                "normal": "abcdefghijklmnop",
            },
            "items": list(range(25)),
        },
        max_chars=8,
    )

    assert redacted["api_key"] == "[REDACTED]"
    assert redacted["nested"]["access_token"] == "[REDACTED]"
    assert redacted["nested"]["clientSecret"] == "[REDACTED]"
    assert redacted["nested"]["normal"] == "abcdefgh...[truncated 8 chars]"
    assert redacted["items"][-1] == {"__truncated_items__": 5}


def test_configure_logging_writes_jsonl_file(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "log_dir", str(tmp_path))
    monkeypatch.setattr(settings, "log_file_enabled", True)
    monkeypatch.setattr(settings, "log_level", "INFO")
    monkeypatch.setattr(settings, "log_max_bytes", 1024 * 1024)
    monkeypatch.setattr(settings, "log_backup_count", 1)

    configure_logging(force=True)
    structlog.get_logger("test").info("diagnostic_test", api_key="sk-secret", value="ok")
    _flush_handlers()

    lines = (tmp_path / LOG_FILE_NAME).read_text(encoding="utf-8").splitlines()
    payload = json.loads(lines[-1])

    assert payload["event"] == "diagnostic_test"
    assert payload["api_key"] == "[REDACTED]"
    assert payload["value"] == "ok"


def test_configure_logging_writes_stdlib_logs_as_json(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "log_dir", str(tmp_path))
    monkeypatch.setattr(settings, "log_file_enabled", True)
    monkeypatch.setattr(settings, "log_level", "INFO")

    configure_logging(force=True)
    logging.getLogger("foreign").info("foreign_log_line")
    _flush_handlers()

    lines = (tmp_path / LOG_FILE_NAME).read_text(encoding="utf-8").splitlines()
    payload = json.loads(lines[-1])

    assert payload["event"] == "foreign_log_line"
    assert payload["level"] == "info"


def test_request_middleware_sets_or_preserves_request_id():
    client = TestClient(app)

    generated = client.get("/health")
    preserved = client.get("/health", headers={"X-Request-ID": "req_test"})

    assert generated.headers["x-request-id"]
    assert preserved.headers["x-request-id"] == "req_test"


def test_n8n_error_preview_is_redacted():
    response = httpx.Response(
        400,
        json={
            "message": "Bad credential",
            "oauthTokenData": {"access_token": "access", "refresh_token": "refresh"},
            "clientSecret": "client-secret",
        },
        request=httpx.Request("POST", "http://n8n.test/api/v1/credentials"),
    )

    preview = n8n_client._response_preview(response)

    assert preview["message"] == "Bad credential"
    assert preview["oauthTokenData"] == "[REDACTED]"
    assert preview["clientSecret"] == "[REDACTED]"


@pytest.mark.asyncio
async def test_oauth_callback_rejection_does_not_log_code(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "log_dir", str(tmp_path))
    monkeypatch.setattr(settings, "log_file_enabled", True)
    configure_logging(force=True)

    async def fake_get_oauth_state(_state_id: str):
        return None

    monkeypatch.setattr(connections_route.store, "get_oauth_state", fake_get_oauth_state)

    with pytest.raises(HTTPException):
        await connections_route.google_callback(
            connections_route.GoogleCallbackIn(code="secret-code", state="secret-state")
        )

    _flush_handlers()
    content = (tmp_path / LOG_FILE_NAME).read_text(encoding="utf-8")

    assert "secret-code" not in content
    assert "secret-state" not in content
    assert "oauth_callback_rejected" in content
