"""Structured diagnostic logging for the Conduut agent service."""

from __future__ import annotations

import logging
import sys
from collections.abc import Mapping
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

import structlog
from structlog.contextvars import bind_contextvars, clear_contextvars, merge_contextvars

from src.config import settings

LOG_FILE_NAME = "conduut-agent.jsonl"
_CONFIGURED = False
_MAX_COLLECTION_ITEMS = 20
_REDACTED = "[REDACTED]"

_SECRET_KEY_PARTS = (
    "apikey",
    "authorization",
    "clientsecret",
    "codeverifier",
    "idtoken",
    "password",
    "refreshtoken",
    "secret",
    "token",
)


def _normalized_key(key: object) -> str:
    return "".join(char for char in str(key).lower() if char.isalnum())


def _is_secret_key(key: object) -> bool:
    normalized = _normalized_key(key)
    return any(part in normalized for part in _SECRET_KEY_PARTS)


def _truncate_string(value: str, max_chars: int) -> str:
    if max_chars <= 0 or len(value) <= max_chars:
        return value
    return f"{value[:max_chars]}...[truncated {len(value) - max_chars} chars]"


def redact_for_logging(value: Any, *, max_chars: int | None = None) -> Any:
    """Redact secrets and shrink large values before they enter JSON logs."""

    preview_chars = max_chars if max_chars is not None else settings.log_payload_preview_chars
    if isinstance(value, str):
        return _truncate_string(value, preview_chars)
    if isinstance(value, int | float | bool) or value is None:
        return value
    if isinstance(value, Mapping):
        redacted: dict[str, Any] = {}
        items = list(value.items())
        for key, item in items[:_MAX_COLLECTION_ITEMS]:
            key_text = str(key)
            redacted[key_text] = (
                _REDACTED
                if _is_secret_key(key_text)
                else redact_for_logging(item, max_chars=preview_chars)
            )
        if len(items) > _MAX_COLLECTION_ITEMS:
            redacted["__truncated_items__"] = len(items) - _MAX_COLLECTION_ITEMS
        return redacted
    if isinstance(value, list | tuple | set | frozenset):
        items = list(value)
        redacted_items = [
            redact_for_logging(item, max_chars=preview_chars)
            for item in items[:_MAX_COLLECTION_ITEMS]
        ]
        if len(items) > _MAX_COLLECTION_ITEMS:
            redacted_items.append({"__truncated_items__": len(items) - _MAX_COLLECTION_ITEMS})
        return redacted_items
    return _truncate_string(str(value), preview_chars)


def _redact_processor(
    _logger: logging.Logger,
    _method_name: str,
    event_dict: dict[str, Any],
) -> dict[str, Any]:
    return redact_for_logging(event_dict)


def _run_log_processor(
    _logger: logging.Logger,
    _method_name: str,
    event_dict: dict[str, Any],
) -> dict[str, Any]:
    # Imported lazily so run_logging can reuse settings without creating a
    # logging_config <-> run_logging import cycle.
    from src.run_logging import capture_run_event

    capture_run_event(event_dict)
    return event_dict


def _level() -> int:
    return getattr(logging, settings.log_level.upper(), logging.INFO)


def _formatter() -> logging.Formatter:
    return structlog.stdlib.ProcessorFormatter(
        processor=structlog.processors.JSONRenderer(),
        foreign_pre_chain=[
            merge_contextvars,
            structlog.stdlib.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.format_exc_info,
            _redact_processor,
        ],
    )


def _stream_handler(level: int) -> logging.Handler:
    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(level)
    handler.setFormatter(_formatter())
    return handler


def _file_handler(level: int) -> logging.Handler | None:
    if not settings.log_file_enabled:
        return None
    log_dir = Path(settings.log_dir).expanduser()
    log_dir.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(
        log_dir / LOG_FILE_NAME,
        maxBytes=settings.log_max_bytes,
        backupCount=settings.log_backup_count,
        encoding="utf-8",
    )
    handler.setLevel(level)
    handler.setFormatter(_formatter())
    return handler


def configure_logging(*, force: bool = False) -> None:
    """Configure structlog and stdlib logging once per process."""

    global _CONFIGURED
    if _CONFIGURED and not force:
        return

    level = _level()
    root_logger = logging.getLogger()
    if force:
        for handler in list(root_logger.handlers):
            root_logger.removeHandler(handler)
            handler.close()

    handlers: list[logging.Handler] = [_stream_handler(level)]
    file_handler = _file_handler(level)
    if file_handler is not None:
        handlers.append(file_handler)

    root_logger.handlers = handlers
    root_logger.setLevel(level)

    processors = [
        merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.format_exc_info,
        _redact_processor,
        _run_log_processor,
        structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
    ]
    structlog.configure(
        processors=processors,
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=False,
    )
    _CONFIGURED = True

    if settings.run_log_enabled:
        from src.run_logging import cleanup_run_logs

        cleanup_run_logs(settings.log_dir, settings.run_log_retention_days)


def bind_log_context(**values: Any) -> dict[str, Any]:
    """Bind contextvars after redacting values that should never leak."""

    return bind_contextvars(**redact_for_logging(values))


def clear_log_context() -> None:
    clear_contextvars()
