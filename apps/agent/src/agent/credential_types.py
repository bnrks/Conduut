"""Custom HTTP credential type catalog and host-based matching.

V1 supports the four generic n8n HTTP-node auth credential types. Secrets are
stored only in n8n; Conduut keeps non-secret metadata (label, type, host) in
Firestore and matches a saved credential to an HTTP node by URL host.
"""

from typing import Any
from urllib.parse import urlsplit

# Tip -> {label, description, fields}. fields drive the credential form; the
# `data` keys must match what n8n's credential schema expects for each type.
SUPPORTED_HTTP_CREDENTIAL_TYPES: dict[str, dict[str, Any]] = {
    "httpHeaderAuth": {
        "label": "Header Auth",
        "description": "Send a header like Authorization: Bearer <token> or X-API-Key.",
        "fields": [
            {"name": "name", "label": "Header name", "type": "string", "required": True},
            {"name": "value", "label": "Header value", "type": "password", "required": True},
        ],
    },
    "httpBasicAuth": {
        "label": "Basic Auth",
        "description": "Username and password (HTTP Basic).",
        "fields": [
            {"name": "user", "label": "Username", "type": "string", "required": True},
            {"name": "password", "label": "Password", "type": "password", "required": True},
        ],
    },
    "httpQueryAuth": {
        "label": "Query Auth",
        "description": "API key sent as a URL query parameter (?api_key=...).",
        "fields": [
            {"name": "name", "label": "Query parameter name", "type": "string", "required": True},
            {
                "name": "value",
                "label": "Query parameter value",
                "type": "password",
                "required": True,
            },
        ],
    },
    "httpCustomAuth": {
        "label": "Custom Auth",
        "description": "Custom headers/query/body defined as JSON.",
        "fields": [
            {"name": "json", "label": "Auth JSON", "type": "json", "required": True},
        ],
    },
}


def is_supported_http_type(credential_type: str) -> bool:
    """Whether this is one of the V1 generic HTTP credential types."""

    return credential_type in SUPPORTED_HTTP_CREDENTIAL_TYPES


def credential_type_catalog() -> list[dict[str, Any]]:
    """Return the V1 credential types as a UI/agent-friendly catalog."""

    return [
        {
            "type": credential_type,
            "label": spec["label"],
            "description": spec["description"],
            "hostRequired": True,
            "fields": [dict(field) for field in spec["fields"]],
        }
        for credential_type, spec in SUPPORTED_HTTP_CREDENTIAL_TYPES.items()
    ]


def normalize_host(value: str | None) -> str | None:
    """Extract a comparable hostname from a URL, bare host, or n8n expression.

    Returns the lowercase hostname (without leading ``www.`` or port), or None
    when the value is empty or fully dynamic (no literal host before any
    ``{{ }}`` expression).
    """

    if not value or not isinstance(value, str):
        return None
    raw = value.strip()
    if raw.startswith("="):  # n8n expression prefix
        raw = raw[1:].strip()
    if "{{" in raw:  # keep only the literal part before any expression
        raw = raw.split("{{", 1)[0].strip()
    if not raw:
        return None
    if "://" not in raw:
        raw = "https://" + raw
    netloc = urlsplit(raw).netloc
    host = netloc.split("@")[-1].split(":")[0].strip().lower()
    if not host or "{" in host or "}" in host or "." not in host:
        return None
    if host.startswith("www."):
        host = host[4:]
    return host


def match_credentials(
    url: str | None,
    credentials: list[Any],
    *,
    credential_type: str | None = None,
) -> list[Any]:
    """Return credentials whose host matches the URL host (deterministic).

    Each credential must expose ``.host`` and ``.credential_type`` attributes.
    When ``credential_type`` is given, results are also filtered to that type.
    Returns an empty list when the URL has no literal host (dynamic/empty).
    """

    url_host = normalize_host(url)
    if not url_host:
        return []
    matches: list[Any] = []
    for credential in credentials:
        if credential_type and getattr(credential, "credential_type", None) != credential_type:
            continue
        if normalize_host(getattr(credential, "host", None)) == url_host:
            matches.append(credential)
    return matches
