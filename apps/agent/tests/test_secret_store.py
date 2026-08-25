from types import SimpleNamespace

import pytest
from google.api_core.exceptions import NotFound

from src.secret_store import (
    EncryptedFileSecretStore,
    GoogleSecretManagerSecretStore,
    InMemorySecretStore,
    build_secret_store,
)


class _FakeSecretManagerClient:
    def __init__(self):
        self.created = []
        self.added = []
        self.accessed = []
        self.destroyed = []
        self.disabled = []
        self.deleted = []
        self.secrets: dict[str, dict[int, dict[str, object]]] = {}

    def create_secret(self, *, request):
        self.created.append(request)
        parent = request["parent"]
        secret_path = f"{parent}/secrets/{request['secret_id']}"
        self.secrets.setdefault(secret_path, {})
        return SimpleNamespace(name=secret_path)

    def list_secret_versions(self, *, request):
        assert request["filter"] == "state:ENABLED"
        versions = self.secrets.get(request["parent"])
        if versions is None:
            raise NotFound("missing")
        return [
            SimpleNamespace(name=f"{request['parent']}/versions/{version}")
            for version, payload in sorted(versions.items())
            if payload["state"] == "ENABLED"
        ]

    def add_secret_version(self, *, request):
        self.added.append(request)
        versions = self.secrets.setdefault(request["parent"], {})
        next_version = max(versions.keys(), default=0) + 1
        versions[next_version] = {
            "data": request["payload"]["data"],
            "state": "ENABLED",
        }
        return SimpleNamespace(name=f"{request['parent']}/versions/{next_version}")

    def access_secret_version(self, *, request):
        self.accessed.append(request["name"])
        secret_path, _, version_label = request["name"].rpartition("/versions/")
        versions = self.secrets.get(secret_path)
        if versions is None:
            raise NotFound("missing")
        version = int(version_label)
        payload = versions.get(version)
        if payload is None or payload["state"] != "ENABLED":
            raise NotFound("missing")
        return SimpleNamespace(payload=SimpleNamespace(data=payload["data"]))

    def disable_secret_version(self, *, request):
        self.disabled.append(request["name"])
        secret_path, _, version_label = request["name"].rpartition("/versions/")
        versions = self.secrets[secret_path]
        versions[int(version_label)]["state"] = "DISABLED"

    def destroy_secret_version(self, *, request):
        self.destroyed.append(request["name"])
        secret_path, _, version_label = request["name"].rpartition("/versions/")
        versions = self.secrets[secret_path]
        versions[int(version_label)]["state"] = "DESTROYED"

    def delete_secret(self, *, request):
        self.deleted.append(request["name"])
        if request["name"] not in self.secrets:
            raise NotFound("missing")
        self.secrets.pop(request["name"], None)


@pytest.mark.asyncio
async def test_encrypted_file_secret_store_persists_and_reuses_key(tmp_path):
    store_path = tmp_path / "n8n-secrets.json"
    store = EncryptedFileSecretStore(store_path)

    await store.put_secret("user/instance/api_key", "super-secret")

    key_path = store_path.with_suffix(".key")
    assert store_path.exists()
    assert key_path.exists()
    first_key = key_path.read_text(encoding="utf-8").strip()

    reloaded = EncryptedFileSecretStore(store_path)
    assert await reloaded.get_secret("user/instance/api_key") == "super-secret"
    assert key_path.read_text(encoding="utf-8").strip() == first_key


@pytest.mark.asyncio
async def test_encrypted_file_secret_store_does_not_write_plaintext(tmp_path):
    store_path = tmp_path / "n8n-secrets.json"
    store = EncryptedFileSecretStore(store_path)

    await store.put_secret("secret-ref", "plain-api-key")

    store_text = store_path.read_text(encoding="utf-8")
    key_text = store_path.with_suffix(".key").read_text(encoding="utf-8")

    assert "plain-api-key" not in store_text
    assert "plain-api-key" not in key_text
    assert "secret-ref" in store_text


@pytest.mark.asyncio
async def test_encrypted_file_secret_store_rotation_and_delete(tmp_path):
    store_path = tmp_path / "n8n-secrets.json"
    store = EncryptedFileSecretStore(store_path)

    await store.put_secret("secret-ref", "old-value")
    await store.put_secret_version("secret-ref", "new-value")
    assert await store.get_secret("secret-ref") == "new-value"

    await store.delete_secret("secret-ref")
    assert await store.get_secret("secret-ref") is None
    assert "secret-ref" not in store_path.read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_google_secret_store_creates_secret_with_destroy_ttl_and_verifies_roundtrip(
    monkeypatch,
):
    client = _FakeSecretManagerClient()
    secret_store = GoogleSecretManagerSecretStore(
        project_id="project-1",
        secret_prefix="conduut-n8n",
        location="europe-west3",
    )
    monkeypatch.setattr(secret_store, "_client", lambda: client)

    result = await secret_store.put_secret("user/instance/api_key", "new-secret")
    secret_path = secret_store._secret_path("user/instance/api_key")

    assert result == "user/instance/api_key"
    assert client.created[0]["secret"]["version_destroy_ttl"].seconds == 604800
    assert client.created[0]["secret"]["replication"] == {
        "user_managed": {"replicas": [{"location": "europe-west3"}]}
    }
    assert client.added[0]["payload"]["data"] == b"new-secret"
    assert client.accessed == [f"{secret_path}/versions/1"]


@pytest.mark.asyncio
async def test_google_secret_rotation_destroys_previous_enabled_versions_after_verification(
    monkeypatch,
):
    client = _FakeSecretManagerClient()
    secret_store = GoogleSecretManagerSecretStore(
        project_id="project-1",
        secret_prefix="conduut-n8n",
    )
    secret_path = secret_store._secret_path("user/instance/api_key")
    client.secrets[secret_path] = {
        1: {"data": b"old-secret", "state": "ENABLED"},
        2: {"data": b"older-secret", "state": "ENABLED"},
    }
    monkeypatch.setattr(secret_store, "_client", lambda: client)

    result = await secret_store.put_secret_version("user/instance/api_key", "new-secret")

    assert result == "user/instance/api_key"
    assert client.destroyed == [
        f"{secret_path}/versions/1",
        f"{secret_path}/versions/2",
    ]
    assert await secret_store.get_secret("user/instance/api_key") == "new-secret"


@pytest.mark.asyncio
async def test_google_secret_rotation_preserves_previous_enabled_version_on_verify_failure(
    monkeypatch,
):
    client = _FakeSecretManagerClient()
    secret_store = GoogleSecretManagerSecretStore(
        project_id="project-1",
        secret_prefix="conduut-n8n",
    )
    secret_path = secret_store._secret_path("user/instance/api_key")
    client.secrets[secret_path] = {
        1: {"data": b"old-secret", "state": "ENABLED"},
    }
    monkeypatch.setattr(secret_store, "_client", lambda: client)

    original_access = client.access_secret_version

    def broken_access(*, request):
        if request["name"].endswith("/versions/2"):
            raise RuntimeError("readback failed")
        return original_access(request=request)

    monkeypatch.setattr(client, "access_secret_version", broken_access)

    with pytest.raises(RuntimeError, match="Unable to verify rotated tenant secret"):
        await secret_store.put_secret_version("user/instance/api_key", "new-secret")

    assert client.disabled == []
    assert client.destroyed == [f"{secret_path}/versions/2"]
    assert await secret_store.get_secret("user/instance/api_key") == "old-secret"


@pytest.mark.asyncio
async def test_google_secret_rotation_commits_when_previous_version_cleanup_fails(
    monkeypatch,
):
    client = _FakeSecretManagerClient()
    secret_store = GoogleSecretManagerSecretStore(
        project_id="project-1",
        secret_prefix="conduut-n8n",
    )
    secret_path = secret_store._secret_path("user/instance/api_key")
    client.secrets[secret_path] = {
        1: {"data": b"old-secret", "state": "ENABLED"},
    }
    monkeypatch.setattr(secret_store, "_client", lambda: client)

    def broken_destroy(*, request):
        raise RuntimeError("transient cleanup failure")

    monkeypatch.setattr(client, "destroy_secret_version", broken_destroy)

    result = await secret_store.put_secret_version("user/instance/api_key", "new-secret")

    assert result == "user/instance/api_key"
    assert await secret_store.get_secret("user/instance/api_key") == "new-secret"


@pytest.mark.asyncio
async def test_google_secret_get_returns_none_when_secret_missing(monkeypatch):
    client = _FakeSecretManagerClient()
    secret_store = GoogleSecretManagerSecretStore(
        project_id="project-1",
        secret_prefix="conduut-n8n",
    )
    monkeypatch.setattr(secret_store, "_client", lambda: client)

    assert await secret_store.get_secret("missing/ref") is None


def test_google_secret_name_hashes_reference_without_pii():
    secret_store = GoogleSecretManagerSecretStore(
        project_id="project-1",
        secret_prefix="conduut-n8n",
    )

    name = secret_store._secret_name("user@example.com/instance/api key")

    assert name.startswith("conduut-n8n-tenant-")
    assert "user" not in name
    assert "instance" not in name


def test_google_secret_store_rejects_invalid_prefix():
    with pytest.raises(ValueError, match="secret prefix"):
        GoogleSecretManagerSecretStore(project_id="project-1", secret_prefix="tenant/secret")


def test_build_secret_store_selects_encrypted_file_backend(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "src.secret_store.settings.n8n_secret_manager_backend",
        "encrypted_file",
        raising=False,
    )
    monkeypatch.setattr(
        "src.secret_store.settings.n8n_local_secret_store_path",
        str(tmp_path / "secrets.json"),
        raising=False,
    )

    store = build_secret_store()

    assert isinstance(store, EncryptedFileSecretStore)


def test_build_secret_store_selects_memory_backend(monkeypatch):
    monkeypatch.setattr("src.secret_store.settings.n8n_secret_manager_backend", "memory")

    store = build_secret_store()

    assert isinstance(store, InMemorySecretStore)


def test_build_secret_store_rejects_unknown_backend(monkeypatch):
    monkeypatch.setattr("src.secret_store.settings.n8n_secret_manager_backend", "bogus")

    with pytest.raises(ValueError, match="Unsupported CONDUUT_N8N_SECRET_MANAGER_BACKEND"):
        build_secret_store()
