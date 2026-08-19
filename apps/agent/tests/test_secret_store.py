from types import SimpleNamespace

import pytest

from src.secret_store import (
    EncryptedFileSecretStore,
    GoogleSecretManagerSecretStore,
    InMemorySecretStore,
    build_secret_store,
)


class _FakeSecretManagerClient:
    def __init__(self):
        self.added = []
        self.disabled = []

    def list_secret_versions(self, *, request):
        assert request["filter"] == "state:ENABLED"
        return [
            SimpleNamespace(name=f"{request['parent']}/versions/1"),
            SimpleNamespace(name=f"{request['parent']}/versions/2"),
        ]

    def add_secret_version(self, *, request):
        self.added.append(request)
        return SimpleNamespace(name=f"{request['parent']}/versions/3")

    def disable_secret_version(self, *, request):
        self.disabled.append(request["name"])


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


async def test_google_secret_rotation_disables_all_previous_enabled_versions(monkeypatch):
    client = _FakeSecretManagerClient()
    secret_store = GoogleSecretManagerSecretStore(
        project_id="project-1",
        secret_prefix="conduut-n8n",
    )
    monkeypatch.setattr(secret_store, "_client", lambda: client)

    result = await secret_store.put_secret_version("user/instance/api_key", "new-secret")

    assert result == "user/instance/api_key"
    assert client.added[0]["payload"]["data"] == b"new-secret"
    assert client.disabled == [
        "projects/project-1/secrets/conduut-n8n-user-instance-api_key/versions/1",
        "projects/project-1/secrets/conduut-n8n-user-instance-api_key/versions/2",
    ]


def test_google_secret_name_sanitizes_firestore_identity_characters():
    secret_store = GoogleSecretManagerSecretStore(
        project_id="project-1",
        secret_prefix="conduut-n8n",
    )

    assert secret_store._secret_name("user@example.com/instance/api key") == (
        "conduut-n8n-user-example-com-instance-api-key"
    )


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
