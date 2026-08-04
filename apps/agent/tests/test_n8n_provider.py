import pytest

from src import store
from src.n8n_provider import (
    N8nAuthInvalidError,
    N8nCapabilityMissingError,
    N8nClientFactory,
    N8nConfigurationError,
    N8nConnectionRequiredError,
    N8nConnectionUnreachableError,
    N8nInstanceResolver,
    N8nVersionUnsupportedError,
    N8nVersionUnverifiableError,
)
from src.secret_store import InMemorySecretStore


def _record(**overrides):
    data = {
        "id": "inst_1",
        "display_name": "Primary",
        "ownership": "customer_owned",
        "provider": "manual",
        "base_url": "https://automation.example.com",
        "webhook_base_url": "https://automation.example.com",
        "api_key_secret_ref": "u1/inst_1/api_key",
        "n8n_version": "1.121.3",
        "compatibility_status": "supported",
        "connection_status": "connected",
        "capabilities": ["workflows"],
        "verified_at": "now",
        "last_health_at": "now",
        "last_error_code": None,
        "created_at": "now",
        "updated_at": "now",
        "is_active": True,
    }
    data.update(overrides)
    return store.N8nInstanceRecord(**data)


async def test_resolve_customer_owned_target_reads_store(monkeypatch):
    secret_store = InMemorySecretStore({"u1/inst_1/api_key": "secret"})
    resolver = N8nInstanceResolver(secret_store=secret_store)

    monkeypatch.setattr("src.n8n_provider.settings.n8n_provider_mode", "customer_owned")

    async def fake_get(_user_id):
        return _record()

    monkeypatch.setattr(store, "get_active_n8n_instance", fake_get)

    context = await resolver.resolve("u1", request_id="req-1")
    assert context.target.instance_id == "inst_1"
    assert context.target.base_url == "https://automation.example.com"


async def test_resolve_customer_owned_target_requires_connection(monkeypatch):
    resolver = N8nInstanceResolver(secret_store=InMemorySecretStore())
    monkeypatch.setattr("src.n8n_provider.settings.n8n_provider_mode", "customer_owned")

    async def fake_get(_user_id):
        return None

    monkeypatch.setattr(store, "get_active_n8n_instance", fake_get)

    with pytest.raises(N8nConnectionRequiredError):
        await resolver.resolve("u1")


async def test_client_factory_reads_secret_for_target():
    factory = N8nClientFactory(secret_store=InMemorySecretStore({"secret-ref": "top-secret"}))
    client = await factory.for_target(
        type(
            "_Target",
            (),
            {
                "base_url": "https://automation.example.com",
                "webhook_base_url": "https://automation.example.com",
                "api_key_secret_ref": "secret-ref",
                "api_key": None,
                "instance_id": "inst_1",
                "ownership": "customer_owned",
            },
        )()
    )
    assert client.api_key == "top-secret"
    assert client.base_url == "https://automation.example.com"


async def test_client_factory_maps_secret_backend_failure_to_typed_error():
    class _BrokenSecretStore:
        async def get_secret(self, _secret_ref):
            raise RuntimeError("backend unavailable")

    factory = N8nClientFactory(secret_store=_BrokenSecretStore())
    target = type(
        "_Target",
        (),
        {
            "base_url": "https://automation.example.com",
            "webhook_base_url": "https://automation.example.com",
            "api_key_secret_ref": "secret-ref",
            "api_key": None,
            "instance_id": "inst_1",
            "ownership": "customer_owned",
        },
    )()

    with pytest.raises(N8nConfigurationError) as exc:
        await factory.for_target(target)
    assert exc.value.code == "n8n_configuration_error"
    assert "backend unavailable" not in exc.value.message


async def test_preflight_rejects_unsupported_version(monkeypatch):
    resolver = N8nInstanceResolver(secret_store=InMemorySecretStore())
    monkeypatch.setattr("src.n8n_provider.normalize_customer_owned_n8n_url", lambda raw: raw)
    monkeypatch.setattr("src.n8n_provider.canonical_n8n_version", lambda: "1.121.3")

    async def fake_health(self):
        return True

    async def fake_settings(self):
        return {"versionCli": "1.120.0"}

    async def fake_request(self, method, path, **kwargs):
        class _Resp:
            status_code = 200
            headers = {"content-type": "application/json"}

            def json(self):
                return {"data": []}

            def raise_for_status(self):
                return None

        return _Resp()

    monkeypatch.setattr("src.n8n_client.N8nClient.health_check", fake_health)
    monkeypatch.setattr("src.n8n_client.N8nClient.get_rest_settings", fake_settings)
    monkeypatch.setattr("src.n8n_client.N8nClient.request", fake_request)

    with pytest.raises(N8nVersionUnsupportedError):
        await resolver.preflight(base_url="https://automation.example.com", api_key="secret")


async def test_preflight_maps_auth_error(monkeypatch):
    from src import n8n_client

    resolver = N8nInstanceResolver(secret_store=InMemorySecretStore())
    monkeypatch.setattr("src.n8n_provider.normalize_customer_owned_n8n_url", lambda raw: raw)

    async def fake_health(self):
        return True

    async def fake_settings(self):
        raise n8n_client.N8nApiError(401, "invalid", method="GET", path="/rest/settings")

    monkeypatch.setattr("src.n8n_client.N8nClient.health_check", fake_health)
    monkeypatch.setattr("src.n8n_client.N8nClient.get_rest_settings", fake_settings)

    with pytest.raises(N8nAuthInvalidError):
        await resolver.preflight(base_url="https://automation.example.com", api_key="secret")


async def test_preflight_rejects_unverifiable_version(monkeypatch):
    resolver = N8nInstanceResolver(secret_store=InMemorySecretStore())
    monkeypatch.setattr("src.n8n_provider.normalize_customer_owned_n8n_url", lambda raw: raw)

    async def fake_health(self):
        return True

    async def fake_settings(self):
        return {"deployment": "self-hosted"}

    async def fake_request(self, method, path, **kwargs):
        return type(
            "_Resp",
            (),
            {
                "status_code": 200,
                "headers": {"content-type": "application/json"},
                "json": lambda self: {"data": []},
                "raise_for_status": lambda self: None,
            },
        )()

    monkeypatch.setattr("src.n8n_client.N8nClient.health_check", fake_health)
    monkeypatch.setattr("src.n8n_client.N8nClient.get_rest_settings", fake_settings)
    monkeypatch.setattr("src.n8n_client.N8nClient.request", fake_request)

    with pytest.raises(N8nVersionUnverifiableError):
        await resolver.preflight(base_url="https://automation.example.com", api_key="secret")


async def test_preflight_maps_missing_credential_capability(monkeypatch):
    from src import n8n_client

    resolver = N8nInstanceResolver(secret_store=InMemorySecretStore())
    monkeypatch.setattr("src.n8n_provider.normalize_customer_owned_n8n_url", lambda raw: raw)

    async def fake_health(self):
        return True

    async def fake_settings(self):
        return {"versionCli": "1.121.3"}

    async def fake_request(self, method, path, **kwargs):
        if path.startswith("/credentials"):
            raise n8n_client.N8nApiError(404, "missing", method=method, path=path)
        return type(
            "_Resp",
            (),
            {
                "status_code": 200,
                "headers": {"content-type": "application/json"},
                "json": lambda self: {"data": []},
                "raise_for_status": lambda self: None,
            },
        )()

    monkeypatch.setattr("src.n8n_client.N8nClient.health_check", fake_health)
    monkeypatch.setattr("src.n8n_client.N8nClient.get_rest_settings", fake_settings)
    monkeypatch.setattr("src.n8n_client.N8nClient.request", fake_request)

    with pytest.raises(N8nCapabilityMissingError):
        await resolver.preflight(base_url="https://automation.example.com", api_key="secret")


async def test_preflight_maps_tls_failure_to_unreachable(monkeypatch):
    resolver = N8nInstanceResolver(secret_store=InMemorySecretStore())
    monkeypatch.setattr("src.n8n_provider.normalize_customer_owned_n8n_url", lambda raw: raw)

    async def fake_health(self):
        return False

    monkeypatch.setattr("src.n8n_client.N8nClient.health_check", fake_health)

    with pytest.raises(N8nConnectionUnreachableError) as exc:
        await resolver.preflight(base_url="https://automation.example.com", api_key="secret")
    assert exc.value.code == "n8n_unreachable"


async def test_two_users_resolve_to_distinct_origins_without_cross_calls(monkeypatch):
    records = {
        "alice": _record(
            id="inst_alice",
            base_url="https://alice.example.com",
            webhook_base_url="https://alice.example.com",
            api_key_secret_ref="alice/inst_alice/api_key",
        ),
        "bob": _record(
            id="inst_bob",
            base_url="https://bob.example.com",
            webhook_base_url="https://bob.example.com",
            api_key_secret_ref="bob/inst_bob/api_key",
        ),
    }
    secrets = InMemorySecretStore(
        {
            "alice/inst_alice/api_key": "alice-key",
            "bob/inst_bob/api_key": "bob-key",
        }
    )
    resolver = N8nInstanceResolver(secret_store=secrets)
    factory = N8nClientFactory(secret_store=secrets)
    monkeypatch.setattr("src.n8n_provider.settings.n8n_provider_mode", "customer_owned")

    async def fake_get(user_id):
        return records[user_id]

    monkeypatch.setattr(store, "get_active_n8n_instance", fake_get)
    calls: list[tuple[str, str]] = []

    class _ApiClient:
        def __init__(self, *_args, **_kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_exc):
            return False

        async def request(self, _method, url, **kwargs):
            calls.append((url, kwargs["headers"]["X-N8N-API-KEY"]))
            return type("_Resp", (), {"status_code": 200, "headers": {}})()

    monkeypatch.setattr(
        "src.n8n_client.N8nClient._pinned_target",
        lambda self, url, headers=None: (url, dict(headers or {}), {}),
    )
    monkeypatch.setattr("src.n8n_client.httpx.AsyncClient", _ApiClient)

    alice = await factory.for_request_context(await resolver.resolve("alice"))
    bob = await factory.for_request_context(await resolver.resolve("bob"))
    await alice.request("GET", "/workflows")
    await bob.request("GET", "/workflows")

    assert calls == [
        ("https://alice.example.com/api/v1/workflows", "alice-key"),
        ("https://bob.example.com/api/v1/workflows", "bob-key"),
    ]


async def test_customer_owned_missing_target_never_uses_shared_client(monkeypatch):
    resolver = N8nInstanceResolver(secret_store=InMemorySecretStore())
    monkeypatch.setattr("src.n8n_provider.settings.n8n_provider_mode", "customer_owned")

    async def fake_get(_user_id):
        return None

    async def fail_shared_call(*_args, **_kwargs):
        raise AssertionError("shared n8n must never be called")

    monkeypatch.setattr(store, "get_active_n8n_instance", fake_get)
    monkeypatch.setattr("src.n8n_provider.n8n_client.list_workflows", fail_shared_call)

    with pytest.raises(N8nConnectionRequiredError):
        await resolver.resolve("alice")
