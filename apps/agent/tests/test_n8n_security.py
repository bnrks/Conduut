import socket

import pytest

from src.n8n_security import (
    N8nUrlValidationError,
    normalize_customer_owned_n8n_url,
    pin_customer_owned_n8n_url,
)


def test_normalize_customer_owned_n8n_url_requires_https():
    with pytest.raises(N8nUrlValidationError, match="HTTPS"):
        normalize_customer_owned_n8n_url("http://example.com")


def test_normalize_customer_owned_n8n_url_rejects_embedded_credentials():
    with pytest.raises(N8nUrlValidationError, match="embedded credentials"):
        normalize_customer_owned_n8n_url("https://user:pass@example.com")


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com?n8n=1",
        "https://example.com/#fragment",
    ],
)
def test_normalize_customer_owned_n8n_url_rejects_query_and_fragment(url):
    with pytest.raises(N8nUrlValidationError, match="query or fragment"):
        normalize_customer_owned_n8n_url(url)


@pytest.mark.parametrize(
    "url",
    [
        "https://127.0.0.1",
        "https://10.0.0.1",
        "https://169.254.169.254",
        "https://[::1]",
        "https://[fe80::1]",
    ],
)
def test_normalize_customer_owned_n8n_url_rejects_non_public_literal_addresses(url):
    with pytest.raises(N8nUrlValidationError, match="public IP"):
        normalize_customer_owned_n8n_url(url)


def test_normalize_customer_owned_n8n_url_rejects_private_resolution(monkeypatch):
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *args, **kwargs: [(socket.AF_INET, None, None, None, ("10.0.0.5", 443))],
    )

    with pytest.raises(N8nUrlValidationError, match="public IP"):
        normalize_customer_owned_n8n_url("https://automation.example.com")


def test_normalize_customer_owned_n8n_url_returns_origin(monkeypatch):
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *args, **kwargs: [(socket.AF_INET, None, None, None, ("93.184.216.34", 443))],
    )

    assert (
        normalize_customer_owned_n8n_url("https://Automation.Example.com:8443/path")
        == "https://automation.example.com:8443/path"
    )


def test_pin_customer_owned_url_uses_validated_ip_and_preserves_tls_host(monkeypatch):
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *args, **kwargs: [(socket.AF_INET, None, None, None, ("93.184.216.34", 443))],
    )

    pinned = pin_customer_owned_n8n_url("https://automation.example.com:8443/n8n")

    assert pinned.pinned_url == "https://93.184.216.34:8443/n8n"
    assert pinned.host_header == "automation.example.com:8443"
    assert pinned.sni_hostname == "automation.example.com"
