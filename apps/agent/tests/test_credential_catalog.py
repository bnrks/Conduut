"""Tests for the predefined credential catalog (type discovery + classification)."""

from dataclasses import dataclass

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


def test_friendly_label_prefers_shortest_node_name():
    assert cc.friendly_label("openAiApi", ["OpenAI Chat Model", "OpenAI"]) == "OpenAI"
    assert cc.friendly_label("stripeApi", []) == "Stripe"


def test_build_catalog_excludes_oauth_filters_and_sorts():
    raw = [
        {"type": "openAiApi", "nodes": ["OpenAI"]},
        {"type": "slackOAuth2Api", "nodes": ["Slack"]},
        {"type": "anthropicApi", "nodes": ["Anthropic Chat Model"]},
    ]
    full = cc.build_catalog(raw)
    # OAuth excluded, sorted by label
    assert [c["type"] for c in full] == ["anthropicApi", "openAiApi"]
    assert all(c["fillable"] is True for c in full)
    filtered = cc.build_catalog(raw, query="open")
    assert [c["type"] for c in filtered] == ["openAiApi"]


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
