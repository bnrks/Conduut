"""Predefined n8n credential type catalog: discovery, OAuth filtering, fields.

The node registry references credential types by name (e.g. ``openAiApi``). This
module turns those into a friendly, searchable catalog of *fillable* (static
secret) credential types — OAuth2 types are excluded because their consent flow
cannot be driven through the n8n public API. Field schemas come live from
n8n's ``GET /credentials/schema/{type}``.
"""

import re

from src import n8n_client
from src.agent.schemas import CredentialField

# Field names that signal an OAuth2 credential (second-line defense after the
# name heuristic; the static schema then must not be offered as a fillable form).
_OAUTH_FIELD_SIGNATURES = {
    "oauthTokenData",
    "grantType",
    "authUrl",
    "accessTokenUrl",
    "authQueryParameters",
}

# Stripped from a credential type name when humanizing a label as a fallback.
_TYPE_SUFFIXES = ("OAuth2Api", "OAuth2", "Api", "Auth")


def is_oauth_type_name(type_name: str) -> bool:
    """Name heuristic: any credential type containing 'oauth' is OAuth-based."""

    return "oauth" in type_name.lower()


def schema_is_oauth(schema: dict) -> bool:
    """Whether an n8n credential schema looks OAuth-based by its field names."""

    properties = schema.get("properties") if isinstance(schema, dict) else None
    keys = set(properties.keys()) if isinstance(properties, dict) else set()
    return bool(keys & _OAUTH_FIELD_SIGNATURES)


def _humanize(type_name: str) -> str:
    base = type_name
    for suffix in _TYPE_SUFFIXES:
        if base.endswith(suffix) and len(base) > len(suffix):
            base = base[: -len(suffix)]
            break
    spaced = re.sub(r"(?<!^)(?=[A-Z])", " ", base).strip()
    words = [word for word in spaced.split() if word]
    if not words:
        return type_name
    return " ".join(word[:1].upper() + word[1:] for word in words)


def friendly_label(type_name: str, node_names: list[str]) -> str:
    """Pick a user-facing label: shortest node display name, else humanized type."""

    names = [name for name in node_names if name]
    if names:
        return sorted(names, key=lambda name: (len(name), name))[0]
    return _humanize(type_name)


def build_catalog(raw_types: list[dict], query: str | None = None) -> list[dict]:
    """Fillable predefined credential types as a searchable, label-sorted catalog.

    OAuth types (by name) are excluded. ``query`` matches the label or type name
    (case-insensitive substring).
    """

    needle = (query or "").strip().lower()
    catalog: list[dict] = []
    for entry in raw_types:
        type_name = str(entry.get("type") or "")
        if not type_name or is_oauth_type_name(type_name):
            continue
        label = friendly_label(type_name, list(entry.get("nodes") or []))
        if needle and needle not in label.lower() and needle not in type_name.lower():
            continue
        catalog.append({"type": type_name, "label": label, "fillable": True})
    catalog.sort(key=lambda item: item["label"].lower())
    return catalog


def match_credentials_by_type(credential_type: str, credentials: list) -> list:
    """Saved credentials of this exact n8n type that are ready (have an n8n cred)."""

    # Matched by credential_type + ready status only — not gated on match_kind
    # (HTTP and predefined type names never collide).
    matches = []
    for credential in credentials:
        if getattr(credential, "credential_type", None) != credential_type:
            continue
        if getattr(credential, "status", None) != "ready":
            continue
        matches.append(credential)
    return matches


def parse_schema_fields(schema: dict) -> list[CredentialField]:
    """Turn an n8n credential schema into form fields (secrets -> password)."""

    properties = schema.get("properties") if isinstance(schema, dict) else None
    required = set(schema.get("required") or []) if isinstance(schema, dict) else set()
    if not isinstance(properties, dict):
        return [CredentialField(name="apiKey", label="API Key", type="password", required=True)]

    fields: list[CredentialField] = []
    for name, meta in properties.items():
        if not isinstance(meta, dict):
            continue
        field_type = str(meta.get("type") or "string")
        if field_type not in {"string", "number", "integer", "boolean"}:
            continue
        display_name = meta.get("displayName") or name.replace("_", " ").title()
        secret = any(part in name.lower() for part in ("key", "token", "secret", "password"))
        fields.append(
            CredentialField(
                name=name,
                label=str(display_name),
                type="password" if secret else field_type,
                required=name in required or len(properties) == 1,
            )
        )

    return fields or [
        CredentialField(name="apiKey", label="API Key", type="password", required=True)
    ]


async def fetch_credential_fields(credential_type: str) -> list[CredentialField]:
    """Fetch + parse the fillable fields for a credential type from n8n."""

    schema = await n8n_client.get_credential_schema(credential_type)
    return parse_schema_fields(schema)
