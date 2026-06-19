"""Common helpers shared by agent tool modules."""

from typing import Any

import httpx

from src import n8n_client

_MAX_OUTPUT_ITEMS = 3
_MAX_OUTPUT_STRING = 1200
_MAX_OUTPUT_KEYS = 12


def _safe_error(exc: Exception) -> str:
    if isinstance(exc, n8n_client.N8nApiError):
        return exc.message
    if isinstance(exc, httpx.HTTPStatusError):
        status = exc.response.status_code
        method = exc.request.method
        path = exc.request.url.path
        return f"n8n API returned {status} for {method} {path}"
    return str(exc)[:300] or "Tool execution failed"


def _waiting_for_user_input_result() -> dict[str, Any]:
    return {
        "success": False,
        "waiting_for_user_input": True,
        "error": (
            "A user input or connection request is pending. Stop now and wait for the "
            "user's next message or connection action before making workflow changes."
        ),
    }


def _missing_credentials_instruction() -> str:
    return (
        "Stop now. A credential or app connection request was shown to the user. "
        "Tell the user the workflow was created but needs that connection before it "
        "can run. Do not activate or execute the workflow until the user connects it."
    )


def _credential_suggestion_instruction() -> str:
    return (
        "A saved credential matches this API's host (see credential_suggestions). "
        "Stop and ask the user to confirm with request_user_input, naming the "
        "credential's label; if several match a node, pass the labels as choices. "
        "When the user confirms, call attach_credential(workflow_id, node_name, "
        "credential_id) with the chosen credential. Never attach without confirmation."
    )


def _preview_value(value: Any, *, depth: int = 0) -> Any:
    if isinstance(value, str):
        return value if len(value) <= _MAX_OUTPUT_STRING else f"{value[:_MAX_OUTPUT_STRING]}..."
    if isinstance(value, int | float | bool) or value is None:
        return value
    if depth >= 4:
        return str(value)[:_MAX_OUTPUT_STRING]
    if isinstance(value, list):
        return [_preview_value(item, depth=depth + 1) for item in value[:_MAX_OUTPUT_ITEMS]]
    if isinstance(value, dict):
        preview: dict[str, Any] = {}
        for index, (key, item) in enumerate(value.items()):
            if index >= _MAX_OUTPUT_KEYS:
                preview["..."] = f"{len(value) - _MAX_OUTPUT_KEYS} more keys"
                break
            preview[str(key)] = _preview_value(item, depth=depth + 1)
        return preview
    return str(value)[:_MAX_OUTPUT_STRING]


def _response_preview(response: httpx.Response) -> dict[str, Any]:
    content_type = response.headers.get("content-type")
    body: Any | None = None
    if response.content:
        try:
            body = response.json()
        except ValueError:
            body = response.text
    return {
        "statusCode": response.status_code,
        "contentType": content_type,
        "body": _preview_value(body),
    }
