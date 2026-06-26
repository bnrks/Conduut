"""Tests for the predefined credential catalog (type discovery + classification)."""

from dataclasses import dataclass

from n8n_registry.models import CredentialTypeInfo

from src.agent import credential_catalog as cc


@dataclass
class _Cred:
    id: str
    credential_type: str
    status: str = "ready"


def test_is_oauth_type_name():
    assert cc.is_oauth_type_name("slackOAuth2Api") is True
    assert cc.is_oauth_type_name("googleSheetsOAuth2") is True
    assert cc.is_oauth_type_name("openAiApi") is False


def test_schema_is_oauth_detects_oauth_fields():
    assert cc.schema_is_oauth({"properties": {"clientId": {}, "oauthTokenData": {}}}) is True
    assert cc.schema_is_oauth({"properties": {"apiKey": {"type": "string"}}}) is False


def test_match_credentials_by_type_only_ready():
    creds = [
        _Cred("c1", "openAiApi"),
        _Cred("c2", "openAiApi", status="draft"),
        _Cred("c3", "anthropicApi"),
    ]
    matched = cc.match_credentials_by_type("openAiApi", creds)
    assert {c.id for c in matched} == {"c1"}


def test_parse_schema_fields_marks_secrets():
    schema = {
        "properties": {
            "apiKey": {"type": "string", "displayName": "API Key"},
            "organizationId": {"type": "string", "displayName": "Org"},
        },
        "required": ["apiKey"],
    }
    fields = cc.parse_schema_fields(schema)
    by_name = {f.name: f for f in fields}
    assert by_name["apiKey"].type == "password"
    assert by_name["apiKey"].required is True
    assert by_name["organizationId"].type == "string"
    assert by_name["organizationId"].required is False


def _anthropic_definition():
    return CredentialTypeInfo(
        name="anthropicApi",
        display_name="Anthropic",
        icon_url="icons/anthropic.svg",
        properties=[
            {
                "displayName": "API Key",
                "name": "apiKey",
                "type": "string",
                "typeOptions": {"password": True},
                "required": True,
                "default": "",
            },
            {
                "displayName": "Base URL",
                "name": "url",
                "type": "string",
                "default": "https://api.anthropic.com",
                "description": "Override base URL",
            },
            {
                "displayName": "Add Custom Header",
                "name": "header",
                "type": "boolean",
                "default": False,
            },
            {
                "displayName": "Header Name",
                "name": "headerName",
                "type": "string",
                "default": "",
                "displayOptions": {"show": {"header": [True]}},
            },
            {
                "displayName": "Header Value",
                "name": "headerValue",
                "type": "string",
                "default": "",
                "typeOptions": {"password": True},
                "displayOptions": {"show": {"header": [True]}},
            },
            {"displayName": "Notice", "name": "notice", "type": "notice", "default": ""},
            {
                "displayName": "Allowed HTTP Request Domains",
                "name": "allowedHttpRequestDomains",
                "type": "options",
                "default": "all",
                "options": [{"name": "All", "value": "all"}, {"name": "None", "value": "none"}],
            },
        ],
    )


def test_credential_fields_from_definition_anthropic():
    fields = cc.credential_fields_from_definition(_anthropic_definition())
    by_name = {f.name: f for f in fields}
    assert "notice" not in by_name  # notice skipped
    assert by_name["apiKey"].type == "password"
    assert by_name["apiKey"].required is True
    assert by_name["apiKey"].advanced is False
    assert by_name["url"].default == "https://api.anthropic.com"
    assert by_name["url"].advanced is True
    assert by_name["url"].description == "Override base URL"
    assert by_name["header"].type == "boolean"
    assert by_name["headerName"].showWhen.field == "header"
    assert by_name["headerName"].showWhen.values == [True]
    assert by_name["headerValue"].type == "password"
    opts = by_name["allowedHttpRequestDomains"]
    assert opts.type == "options"
    assert opts.default == "all"
    assert [o.value for o in opts.options] == ["all", "none"]
