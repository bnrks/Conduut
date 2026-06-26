"""Tests for credentials.json parsing + OAuth/generic classification."""

from n8n_registry.loader import parse_credentials_json
from n8n_registry.registry import NodeRegistry


def _raw():
    return [
        {
            "name": "anthropicApi",
            "displayName": "Anthropic",
            "iconUrl": "icons/anthropic.svg",
            "properties": [
                {"displayName": "API Key", "name": "apiKey", "type": "string",
                 "typeOptions": {"password": True}, "required": True, "default": ""},
                {"displayName": "Base URL", "name": "url", "type": "string",
                 "default": "https://api.anthropic.com"},
            ],
        },
        {"name": "slackOAuth2Api", "displayName": "Slack OAuth2 API",
         "extends": ["oAuth2Api"], "properties": [{"name": "scope", "type": "string"}]},
        {"name": "googleSheetsOAuth2Api", "displayName": "Google Sheets OAuth2 API",
         "extends": ["googleOAuth2Api"], "properties": [{"name": "scope", "type": "string"}]},
        {"name": "httpHeaderAuth", "displayName": "Header Auth", "genericAuth": True,
         "properties": [{"name": "name", "type": "string"}]},
    ]


def test_parse_basic_fields():
    by_name = {c.name: c for c in parse_credentials_json(_raw())}
    a = by_name["anthropicApi"]
    assert a.display_name == "Anthropic"
    assert a.icon_url == "icons/anthropic.svg"
    assert a.is_oauth is False
    assert a.generic_auth is False
    assert len(a.properties) == 2


def test_oauth_detected_by_name_extends_and_signature():
    by_name = {c.name: c for c in parse_credentials_json(_raw())}
    assert by_name["slackOAuth2Api"].is_oauth is True       # name + extends
    assert by_name["googleSheetsOAuth2Api"].is_oauth is True  # extends chain only
    assert by_name["anthropicApi"].is_oauth is False


def test_generic_auth_flag():
    by_name = {c.name: c for c in parse_credentials_json(_raw())}
    assert by_name["httpHeaderAuth"].generic_auth is True


def _registry():
    reg = NodeRegistry()
    reg._credentials = parse_credentials_json(_raw())
    return reg


def test_list_credential_catalog_excludes_oauth_and_generic():
    reg = _registry()
    catalog = reg.list_credential_catalog()
    types = [c["type"] for c in catalog]
    assert types == ["anthropicApi"]  # oauth + generic excluded; sorted by label
    assert catalog[0]["label"] == "Anthropic"
    assert catalog[0]["icon_url"] == "icons/anthropic.svg"


def test_list_credential_catalog_query_filters():
    reg = _registry()
    assert [c["type"] for c in reg.list_credential_catalog("anth")] == ["anthropicApi"]
    assert reg.list_credential_catalog("zzz") == []


def test_get_credential_definition():
    reg = _registry()
    assert reg.get_credential_definition("anthropicApi").display_name == "Anthropic"
    assert reg.get_credential_definition("missing") is None


def test_icon_url_handles_object_and_string_forms():
    raw = [
        {"name": "openAiApi", "displayName": "OpenAi",
         "iconUrl": {"light": "icons/openai.svg", "dark": "icons/openai.dark.svg"}},
        {"name": "slackApi", "displayName": "Slack", "iconUrl": "icons/slack.svg"},
        {"name": "noIcon", "displayName": "No Icon"},
    ]
    by_name = {c.name: c for c in parse_credentials_json(raw)}
    assert by_name["openAiApi"].icon_url == "icons/openai.svg"  # light picked from object
    assert by_name["slackApi"].icon_url == "icons/slack.svg"
    assert by_name["noIcon"].icon_url == ""
