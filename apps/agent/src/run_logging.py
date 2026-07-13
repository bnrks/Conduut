"""Human-readable, per-agent-run timeline logging."""

from __future__ import annotations

import logging
import re
import threading
import time
from contextvars import ContextVar, Token
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from src.config import settings

_CURRENT_RUN: ContextVar[RunLogSession | None] = ContextVar("conduut_run_log", default=None)
_REDACTED = "[REDACTED]"
_OMITTED_FIELDS = {
    "authorization",
    "body",
    "conversation_id",
    "content",
    "credentials",
    "event",
    "exc_info",
    "level",
    "payload",
    "prompt",
    "request_body",
    "request_id",
    "response_body",
    "run_id",
    "text",
    "timestamp",
    "user_id",
}
_OMITTED_NORMALIZED_FIELDS = {
    "".join(char for char in field if char.isalnum()) for field in _OMITTED_FIELDS
}
_ALLOWED_FIELDS = {
    "action",
    "attachment_count",
    "attachment_types",
    "attempt",
    "attempt_id",
    "batch_run_id",
    "capability",
    "clone_id",
    "content_length",
    "duration_ms",
    "error",
    "error_type",
    "execution_id",
    "max_attempts",
    "message_count",
    "method",
    "model",
    "model_requests",
    "node_count",
    "output_chars",
    "profile",
    "provider",
    "reason",
    "reason_code",
    "repairs",
    "replay_unsafe",
    "replay_unsafe_tool",
    "result_keys",
    "retrying",
    "service",
    "status",
    "status_code",
    "test_status",
    "tier",
    "tok_cache_read",
    "tok_cache_write",
    "tok_in",
    "tok_out",
    "tool",
    "usage_tool_calls",
    "workflow_id",
}
_BEARER_RE = re.compile(r"(?i)\bbearer\s+[^\s,;]+")
_JWT_RE = re.compile(r"\b[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b")
_API_KEY_RE = re.compile(
    r"\b(?:sk|rk|pk)-[A-Za-z0-9_-]{8,}\b|\bgh[pousr]_[A-Za-z0-9]{8,}\b|"
    r"\bAIza[A-Za-z0-9_-]{12,}\b|\bxox[baprs]-[A-Za-z0-9-]{8,}\b",
    re.IGNORECASE,
)
_ASSIGNMENT_RE = re.compile(
    r"(?i)\b(access[_-]?token|refresh[_-]?token|id[_-]?token|token|api[_-]?key|"
    r"password|client[_-]?secret|secret)\b(\s*[:=]\s*)([^\s,;]+)"
)


def _is_omitted_field(key: object) -> bool:
    normalized = "".join(char for char in str(key).lower() if char.isalnum())
    return normalized in _OMITTED_NORMALIZED_FIELDS


def safe_text_preview(value: object, *, max_chars: int | None = None) -> str:
    """Mask common inline secret forms, normalize whitespace, then truncate."""

    text = "".join(" " if ord(char) < 32 or ord(char) == 127 else char for char in str(value or ""))
    text = _BEARER_RE.sub(f"Bearer {_REDACTED}", text)
    text = _JWT_RE.sub(_REDACTED, text)
    text = _API_KEY_RE.sub(_REDACTED, text)
    text = _ASSIGNMENT_RE.sub(lambda match: f"{match.group(1)}{match.group(2)}{_REDACTED}", text)
    text = re.sub(r"\s+", " ", text).strip()
    limit = settings.run_log_preview_chars if max_chars is None else max_chars
    if limit <= 0:
        return ""
    if len(text) <= limit:
        return text
    return f"{text[:limit]}...[truncated {len(text) - limit} chars]"


def _safe_value(value: Any) -> Any:
    if isinstance(value, str):
        return safe_text_preview(value, max_chars=settings.log_payload_preview_chars)
    if isinstance(value, dict):
        return {
            str(key): _safe_value(item) for key, item in value.items() if not _is_omitted_field(key)
        }
    if isinstance(value, list):
        return [_safe_value(item) for item in value]
    return value


def _report_failure(event: str, exc: Exception) -> None:
    logging.getLogger(__name__).error(
        event,
        extra={"error_type": type(exc).__name__, "error": safe_text_preview(exc)},
    )


class RunLogSession:
    """One fail-open timeline file shared through a ContextVar."""

    def __init__(
        self,
        path: Path,
        *,
        run_id: str,
        request_id: str | None,
        conversation_id: str,
        task_preview: str,
    ) -> None:
        self.path = path
        self.run_id = run_id
        self.started_at = datetime.now().astimezone()
        self.started_monotonic = time.monotonic()
        self._file = path.open("x", encoding="utf-8", newline="\n")
        self._lock = threading.Lock()
        self._disabled = False
        self._closed = False
        self._token: Token[RunLogSession | None] | None = None
        self.success = False
        self.attempts = 1
        self.recovered = False
        self.final_preview = ""
        self.usage: dict[str, int] = {}
        self._seen_context: dict[str, Any] = {}
        self._write(
            "CONDUUT AGENT RUN\n"
            f"Run ID        : {run_id}\n"
            f"Started       : {self.started_at.isoformat(timespec='seconds')}\n"
            f"Request       : {safe_text_preview(request_id or '-', max_chars=160)}\n"
            f"Conversation  : {safe_text_preview(conversation_id, max_chars=160)}\n\n"
            "TASK PREVIEW\n"
            f"{safe_text_preview(task_preview) or '-'}\n\n"
            "TIMELINE\n"
        )

    def _write(self, text: str) -> None:
        if self._disabled or self._closed:
            return
        try:
            with self._lock:
                self._file.write(text)
                self._file.flush()
        except Exception as exc:
            self._disabled = True
            try:
                self._file.close()
            except Exception:
                pass
            _report_failure("run_log_write_error", exc)

    def capture(self, event_dict: dict[str, Any]) -> None:
        if self._disabled or self._closed:
            return
        level = str(event_dict.get("level", "info")).lower()
        if logging._nameToLevel.get(level.upper(), logging.INFO) < logging.INFO:
            return
        event = str(event_dict.get("event", "event"))
        if event in {"token", "thinking"}:
            return

        if event == "agent_run_finished":
            self.success = True
            for key in (
                "tok_in",
                "tok_out",
                "tok_cache_read",
                "tok_cache_write",
                "model_requests",
                "usage_tool_calls",
            ):
                if isinstance(event_dict.get(key), int):
                    self.usage[key] = event_dict[key]
        attempt = event_dict.get("attempt")
        if isinstance(attempt, int):
            self.attempts = max(self.attempts, attempt)

        fields: list[tuple[str, Any]] = []
        for key, value in event_dict.items():
            normalized = str(key).lower()
            if (
                _is_omitted_field(key)
                or normalized.startswith("_")
                or normalized not in _ALLOWED_FIELDS
            ):
                continue
            if normalized in {"provider", "model", "tier", "profile"}:
                if self._seen_context.get(normalized) == value:
                    continue
                self._seen_context[normalized] = value
            fields.append((str(key), _safe_value(value)))

        timestamp = datetime.now().astimezone().strftime("%H:%M:%S.%f")[:-3]
        lines = [f"{timestamp}  {level.upper():<8} {safe_text_preview(event, max_chars=120)}\n"]
        for key, value in fields:
            rendered = safe_text_preview(value, max_chars=settings.log_payload_preview_chars)
            lines.append(f"                        {key}: {rendered}\n")
        self._write("".join(lines))

    def note_attempt(self, attempt: int) -> None:
        self.attempts = max(self.attempts, attempt)

    def set_final_preview(self, content: str) -> None:
        self.final_preview = safe_text_preview(content)

    def finish(self, status: str) -> None:
        if self._closed:
            return
        self.recovered = status == "success" and self.attempts > 1
        duration = time.monotonic() - self.started_monotonic
        tokens = f"{self.usage.get('tok_in', 0)} input / {self.usage.get('tok_out', 0)} output"
        summary = (
            "\nSUMMARY\n"
            f"Status        : {status}\n"
            f"Duration      : {duration:.1f} s\n"
            f"Attempts      : {self.attempts}\n"
            f"Recovered     : {'yes' if self.recovered else 'no'}\n"
            f"Tokens        : {tokens}\n"
            f"Model requests: {self.usage.get('model_requests', 0)}\n"
            f"Tool calls    : {self.usage.get('usage_tool_calls', 0)}\n"
            f"Final preview : {self.final_preview or '-'}\n"
        )
        self._write(summary)
        self._closed = True
        try:
            self._file.close()
        except Exception as exc:
            _report_failure("run_log_close_error", exc)
        if self._token is not None:
            try:
                _CURRENT_RUN.reset(self._token)
            except ValueError:
                _CURRENT_RUN.set(None)


def start_run_log(
    *, request_id: str | None, conversation_id: str, task_preview: str
) -> RunLogSession | None:
    """Open and bind a per-run log, returning None on every filesystem failure."""

    if not settings.run_log_enabled:
        return None
    try:
        now = datetime.now().astimezone()
        run_id = uuid4().hex
        run_dir = Path(settings.log_dir).expanduser() / "runs" / now.strftime("%Y-%m-%d")
        run_dir.mkdir(parents=True, exist_ok=True)
        path = run_dir / f"{now.strftime('%H-%M-%S')}_{run_id[:8]}.log"
        session = RunLogSession(
            path,
            run_id=run_id,
            request_id=request_id,
            conversation_id=conversation_id,
            task_preview=task_preview,
        )
        session._token = _CURRENT_RUN.set(session)
        return session
    except Exception as exc:
        _report_failure("run_log_open_error", exc)
        return None


def capture_run_event(event_dict: dict[str, Any]) -> None:
    """Copy one already-redacted Conduut structlog event into the active run."""

    session = _CURRENT_RUN.get()
    if session is not None:
        try:
            session.capture(event_dict)
        except Exception as exc:
            session._disabled = True
            _report_failure("run_log_capture_error", exc)


def set_run_final_preview(content: str) -> None:
    session = _CURRENT_RUN.get()
    if session is not None:
        session.set_final_preview(content)


def note_run_attempt(attempt: int) -> None:
    session = _CURRENT_RUN.get()
    if session is not None:
        session.note_attempt(attempt)


def cleanup_run_logs(log_dir: str, retention_days: int) -> None:
    """Delete only expired .log files and empty directories under log_dir/runs."""

    runs_dir = Path(log_dir).expanduser() / "runs"
    if retention_days <= 0 or not runs_dir.exists():
        return
    cutoff = time.time() - retention_days * 86400
    try:
        for path in runs_dir.rglob("*.log"):
            try:
                if path.is_file() and path.stat().st_mtime < cutoff:
                    path.unlink()
            except Exception as exc:
                _report_failure("run_log_retention_file_error", exc)
        directories = sorted(
            (path for path in runs_dir.rglob("*") if path.is_dir()),
            key=lambda path: len(path.parts),
            reverse=True,
        )
        for directory in directories:
            try:
                if not any(directory.iterdir()):
                    directory.rmdir()
            except Exception as exc:
                _report_failure("run_log_retention_directory_error", exc)
    except Exception as exc:
        _report_failure("run_log_retention_error", exc)
