"""Tests for the custom HTTP credential type catalog and host matching."""

from dataclasses import dataclass

from src.agent import credential_types as ct


@dataclass
class _Cred:
    id: str
    credential_type: str
    host: str


def test_catalog_has_four_v1_types():
    types = {t["type"] for t in ct.credential_type_catalog()}
    assert types == {"httpHeaderAuth", "httpBasicAuth", "httpQueryAuth", "httpCustomAuth"}


def test_catalog_entries_carry_fields_and_host_required():
    catalog = {t["type"]: t for t in ct.credential_type_catalog()}
    header = catalog["httpHeaderAuth"]
    assert header["hostRequired"] is True
    assert [f["name"] for f in header["fields"]] == ["name", "value"]
    assert catalog["httpCustomAuth"]["fields"][0]["type"] == "json"


def test_is_supported_http_type():
    assert ct.is_supported_http_type("httpHeaderAuth") is True
    assert ct.is_supported_http_type("gmailOAuth2") is False


def test_normalize_host_variants():
    assert ct.normalize_host("https://api.stripe.com/v1/charges") == "api.stripe.com"
    assert ct.normalize_host("api.stripe.com") == "api.stripe.com"
    assert ct.normalize_host("=https://api.stripe.com/{{ $json.id }}") == "api.stripe.com"
    assert ct.normalize_host("www.api.test.com:443") == "api.test.com"
    assert ct.normalize_host("={{ $json.body.url }}") is None
    assert ct.normalize_host("") is None
    assert ct.normalize_host(None) is None


def test_match_credentials_by_host_and_type():
    creds = [
        _Cred("c1", "httpHeaderAuth", "api.stripe.com"),
        _Cred("c2", "httpHeaderAuth", "api.other.com"),
        _Cred("c3", "httpBasicAuth", "https://api.stripe.com"),
    ]
    m = ct.match_credentials("https://api.stripe.com/v1", creds)
    assert {c.id for c in m} == {"c1", "c3"}
    m2 = ct.match_credentials("https://api.stripe.com/v1", creds, credential_type="httpHeaderAuth")
    assert {c.id for c in m2} == {"c1"}
    assert ct.match_credentials("={{ $json.url }}", creds) == []
    assert ct.match_credentials(None, creds) == []
