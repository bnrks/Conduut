from types import SimpleNamespace

from src.secret_store import GoogleSecretManagerSecretStore


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
