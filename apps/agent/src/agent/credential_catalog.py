"""Predefined n8n credential type catalog: OAuth filtering, field parsing, matching.

The node registry references credential types by name (e.g. ``openAiApi``). This
module provides helpers for OAuth detection, field schema parsing, and credential
matching. The catalog-building / label-friendly logic has been superseded by
``registry.list_credential_catalog`` + ``registry.get_credential_definition``.
"""

from n8n_registry.models import CredentialTypeInfo

from src.agent.schemas import CredentialField, CredentialFieldCondition, CredentialFieldOption

# Field names that signal an OAuth2 credential (second-line defense after the
# name heuristic; the static schema then must not be offered as a fillable form).
_OAUTH_FIELD_SIGNATURES = {
    "oauthTokenData",
    "grantType",
    "authUrl",
    "accessTokenUrl",
    "authQueryParameters",
}


def is_oauth_type_name(type_name: str) -> bool:
    """Name heuristic: any credential type containing 'oauth' is OAuth-based."""

    return "oauth" in type_name.lower()


def schema_is_oauth(schema: dict) -> bool:
    """Whether an n8n credential schema looks OAuth-based by its field names."""

    properties = schema.get("properties") if isinstance(schema, dict) else None
    keys = set(properties.keys()) if isinstance(properties, dict) else set()
    return bool(keys & _OAUTH_FIELD_SIGNATURES)


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


# n8n property types that are display-only / not user-fillable.
_SKIP_PROPERTY_TYPES = {"notice", "hidden"}


def credential_fields_from_definition(definition: CredentialTypeInfo) -> list[CredentialField]:
    """Build rich form fields from an n8n credential definition (credentials.json).

    Honors default, required (-> non-required is advanced), password, options,
    and single-key displayOptions.show (conditional visibility). Unknown property
    types fall back to a plain text input.
    """

    fields: list[CredentialField] = []
    for prop in definition.properties:
        if not isinstance(prop, dict):
            continue
        name = prop.get("name")
        if not name:
            continue
        prop_type = str(prop.get("type") or "string")
        if prop_type in _SKIP_PROPERTY_TYPES:
            continue
        is_password = bool((prop.get("typeOptions") or {}).get("password"))
        if prop_type == "string":
            field_type = "password" if is_password else "text"
        elif prop_type in {"boolean", "number", "json", "options"}:
            field_type = prop_type
        else:
            field_type = "text"  # safe fallback for unusual types

        options = None
        if field_type == "options":
            options = [
                CredentialFieldOption(
                    label=str(opt.get("name", opt.get("value", ""))),
                    value=str(opt.get("value", "")),
                )
                for opt in (prop.get("options") or [])
                if isinstance(opt, dict)
            ]

        show_when = None
        display_options = prop.get("displayOptions")
        if isinstance(display_options, dict):
            show = display_options.get("show")
            if isinstance(show, dict) and show:
                first_key = next(iter(show))
                show_when = CredentialFieldCondition(
                    field=first_key, values=list(show.get(first_key) or [])
                )

        required = bool(prop.get("required"))
        fields.append(
            CredentialField(
                name=name,
                label=str(prop.get("displayName") or name),
                type=field_type,
                required=required,
                default=prop.get("default"),
                placeholder=prop.get("placeholder") or None,
                description=prop.get("description") or None,
                advanced=not required,
                options=options,
                showWhen=show_when,
            )
        )
    return fields
