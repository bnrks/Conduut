import asyncio
import json
import logging
import os
import time
from pathlib import Path

import pytest
import structlog

from src.agent import runner
from src.config import settings
from src.logging_config import LOG_FILE_NAME, configure_logging
from src.run_logging import (
    capture_run_event,
    cleanup_run_logs,
    note_run_attempt,
    safe_text_preview,
    set_run_final_preview,
    start_run_log,
)


def _configure(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(settings, "log_dir", str(tmp_path))
    monkeypatch.setattr(settings, "log_file_enabled", False)
    monkeypatch.setattr(settings, "run_log_enabled", True)
    monkeypatch.setattr(settings, "run_log_preview_chars", 300)
    monkeypatch.setattr(settings, "run_log_retention_days", 30)
    configure_logging(force=True)


def _run_files(tmp_path: Path) -> list[Path]:
    return list((tmp_path / "runs").rglob("*.log"))


def test_run_session_writes_header_timeline_summary_and_safe_previews(monkeypatch, tmp_path):
    _configure(monkeypatch, tmp_path)
    secret = "sk-this-is-a-secret-key"
    session = start_run_log(
        request_id="req-1",
        conversation_id="conv-1",
        task_preview=f"Build workflow Bearer abcdef123456 password=hunter2 {secret}",
    )
    assert session is not None

    capture_run_event(
        {
            "event": "agent_tool_call_finished",
            "level": "info",
            "tool": "search_n8n_nodes",
            "duration_ms": 184,
            "message": "request failed password=timeline-secret",
            "payload": {"must_not": "appear"},
            "user_id": "private-user",
            "diagnostics": {"userId": "nested-private-user", "safe": "kept"},
            "response": {"value": "neutral-key-secret", "email": "private@example.com"},
        }
    )
    set_run_final_preview(f"Completed with token=top-secret {secret}")
    capture_run_event(
        {
            "event": "agent_run_finished",
            "level": "info",
            "tok_in": 4210,
            "tok_out": 816,
            "model_requests": 4,
            "usage_tool_calls": 1,
        }
    )
    session.finish("success")

    content = session.path.read_text(encoding="utf-8")
    assert content.index("TASK PREVIEW") < content.index("TIMELINE") < content.index("SUMMARY")
    assert "agent_tool_call_finished" in content
    assert "duration_ms: 184" in content
    assert "message:" not in content
    assert "Status        : success" in content
    assert "Tokens        : 4210 input / 816 output" in content
    assert "private-user" not in content
    assert "nested-private-user" not in content
    assert "diagnostics" not in content
    assert "must_not" not in content
    assert "neutral-key-secret" not in content
    assert "private@example.com" not in content
    assert secret not in content
    assert "hunter2" not in content
    assert "top-secret" not in content
    assert "timeline-secret" not in content
    assert "[REDACTED]" in content


@pytest.mark.asyncio
async def test_concurrent_contexts_keep_events_in_separate_files(monkeypatch, tmp_path):
    _configure(monkeypatch, tmp_path)

    async def worker(conversation_id: str) -> Path:
        session = start_run_log(
            request_id=None,
            conversation_id=conversation_id,
            task_preview=f"task {conversation_id}",
        )
        assert session is not None
        await asyncio.sleep(0)
        capture_run_event({"event": f"event_{conversation_id}", "level": "info"})
        session.finish("success")
        return session.path

    path_a, path_b = await asyncio.gather(worker("alpha"), worker("beta"))
    content_a = path_a.read_text(encoding="utf-8")
    content_b = path_b.read_text(encoding="utf-8")
    assert "event_alpha" in content_a and "event_beta" not in content_a
    assert "event_beta" in content_b and "event_alpha" not in content_b


def test_debug_and_stream_events_are_not_written(monkeypatch, tmp_path):
    _configure(monkeypatch, tmp_path)
    session = start_run_log(request_id=None, conversation_id="conv", task_preview="task")
    assert session is not None
    capture_run_event({"event": "debug_detail", "level": "debug", "value": "noise"})
    capture_run_event({"event": "token", "level": "info", "text": "streamed secret"})
    capture_run_event({"event": "thinking", "level": "info", "text": "internal"})
    session.finish("cancelled")
    content = session.path.read_text(encoding="utf-8")
    assert "debug_detail" not in content
    assert "streamed secret" not in content
    assert "internal" not in content
    assert "Status        : cancelled" in content


def test_attempt_summary_marks_successful_retry_as_recovered(monkeypatch, tmp_path):
    _configure(monkeypatch, tmp_path)
    session = start_run_log(request_id=None, conversation_id="conv", task_preview="task")
    assert session is not None
    note_run_attempt(2)
    capture_run_event({"event": "agent_run_finished", "level": "info"})
    session.finish("success")
    content = session.path.read_text(encoding="utf-8")
    assert "Attempts      : 2" in content
    assert "Recovered     : yes" in content


def test_retention_deletes_only_expired_log_files(monkeypatch, tmp_path):
    _configure(monkeypatch, tmp_path)
    day = tmp_path / "runs" / "2026-01-01"
    day.mkdir(parents=True)
    old_log = day / "old.log"
    current_log = day / "current.log"
    other_file = day / "keep.jsonl"
    outside = tmp_path / "outside.log"
    for path in (old_log, current_log, other_file, outside):
        path.write_text("x", encoding="utf-8")
    old_time = time.time() - 31 * 86400
    os.utime(old_log, (old_time, old_time))
    os.utime(other_file, (old_time, old_time))
    os.utime(outside, (old_time, old_time))

    cleanup_run_logs(str(tmp_path), 30)

    assert not old_log.exists()
    assert current_log.exists()
    assert other_file.exists()
    assert outside.exists()


@pytest.mark.parametrize("retention_days", [0, -1])
def test_non_positive_retention_never_deletes_logs(monkeypatch, tmp_path, retention_days):
    _configure(monkeypatch, tmp_path)
    old_log = tmp_path / "runs" / "2026-01-01" / "old.log"
    old_log.parent.mkdir(parents=True)
    old_log.write_text("keep", encoding="utf-8")
    old_time = time.time() - 365 * 86400
    os.utime(old_log, (old_time, old_time))

    cleanup_run_logs(str(tmp_path), retention_days)

    assert old_log.exists()


def test_header_identifiers_are_sanitized_and_bounded(monkeypatch, tmp_path):
    _configure(monkeypatch, tmp_path)
    request_id = "line-one\nline-two token=header-secret " + ("x" * 300)
    conversation_id = "conversation\r\nforged secret=conversation-secret"
    session = start_run_log(
        request_id=request_id,
        conversation_id=conversation_id,
        task_preview="task",
    )
    assert session is not None
    session.finish("cancelled")

    content = session.path.read_text(encoding="utf-8")
    assert "header-secret" not in content
    assert "conversation-secret" not in content
    assert "\nline-two" not in content
    request_line = next(line for line in content.splitlines() if line.startswith("Request"))
    assert len(request_line) < 220


def test_disabled_or_unwritable_run_logging_is_fail_open(monkeypatch, tmp_path):
    _configure(monkeypatch, tmp_path)
    monkeypatch.setattr(settings, "run_log_enabled", False)
    assert start_run_log(request_id=None, conversation_id="conv", task_preview="task") is None

    monkeypatch.setattr(settings, "run_log_enabled", True)
    blocked = tmp_path / "blocked"
    blocked.write_text("not a directory", encoding="utf-8")
    monkeypatch.setattr(settings, "log_dir", str(blocked))
    assert start_run_log(request_id=None, conversation_id="conv", task_preview="task") is None


def test_safe_text_preview_redacts_before_truncating(monkeypatch):
    monkeypatch.setattr(settings, "run_log_preview_chars", 20)
    preview = safe_text_preview("Bearer super-secret-value followed by text")
    assert "super-secret-value" not in preview
    assert len(preview) > 20


@pytest.mark.parametrize(
    "secret",
    [
        "Bearer abcdefghijklmnop",
        "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.signature123",
        "sk-abcdefghijklmno",
        "api_key: abcdefghijk",
        "password=hunter2",
        "secret = hidden-value",
        "access_token=oauth-value",
        "client_secret: client-value",
        "ghp_abcdefghijklmno",
        "AIzaabcdefghijklmnopqrstuvwxyz",
        "xoxb-123456789-abcdefgh",
    ],
)
def test_safe_text_preview_masks_known_inline_secret_formats(secret):
    preview = safe_text_preview(f"before {secret} after", max_chars=1000)
    assert secret not in preview
    assert "[REDACTED]" in preview


@pytest.mark.asyncio
async def test_runner_binds_run_id_into_global_jsonl(monkeypatch, tmp_path):
    _configure(monkeypatch, tmp_path)
    monkeypatch.setattr(settings, "log_file_enabled", True)
    configure_logging(force=True)
    monkeypatch.setattr(runner, "_history_from_store_messages", lambda _messages: ("task", []))

    async def fake_stream(*_args, **_kwargs):
        structlog.get_logger().info("agent_run_finished", tok_in=1, tok_out=2)
        yield "event: done\n\n"

    monkeypatch.setattr(runner, "_run_agent_stream", fake_stream)
    _ = [item async for item in runner.run("user", "conv", [], request_id="req")]
    for handler in logging.getLogger().handlers:
        handler.flush()

    payloads = [
        json.loads(line)
        for line in (tmp_path / LOG_FILE_NAME).read_text(encoding="utf-8").splitlines()
    ]
    finished = next(item for item in payloads if item.get("event") == "agent_run_finished")
    assert finished["run_id"]
    run_content = _run_files(tmp_path)[0].read_text(encoding="utf-8")
    assert f"Run ID        : {finished['run_id']}" in run_content
    assert "                        run_id:" not in run_content


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("emit_success", "close_early", "expected"),
    [(True, False, "success"), (False, False, "error"), (False, True, "cancelled")],
)
async def test_runner_owns_terminal_run_status(
    monkeypatch, tmp_path, emit_success, close_early, expected
):
    _configure(monkeypatch, tmp_path)
    monkeypatch.setattr(runner, "_history_from_store_messages", lambda _messages: ("task", []))

    async def fake_stream(*_args, **_kwargs):
        if emit_success:
            structlog.get_logger().info("agent_run_finished", tok_in=1, tok_out=2)
        yield "event: test\n\n"

    monkeypatch.setattr(runner, "_run_agent_stream", fake_stream)
    stream = runner.run("user", "conv", [], request_id="req")
    if close_early:
        await anext(stream)
        await stream.aclose()
    else:
        _ = [item async for item in stream]

    files = _run_files(tmp_path)
    assert len(files) == 1
    assert f"Status        : {expected}" in files[0].read_text(encoding="utf-8")
