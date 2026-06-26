"""Tests for credentials.json parsing + OAuth/generic classification."""

from n8n_registry.loader import parse_credentials_json


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
