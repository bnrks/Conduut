from __future__ import annotations

import asyncio
import re
from collections.abc import MutableMapping
from typing import Protocol

import firebase_admin
from google.api_core.exceptions import AlreadyExists

from src.config import settings


class SecretStore(Protocol):
    async def put_secret(self, secret_ref: str, secret_value: str) -> str: ...

    async def get_secret(self, secret_ref: str) -> str | None: ...

    async def delete_secret(self, secret_ref: str) -> None: ...

    async def put_secret_version(self, secret_ref: str, secret_value: str) -> str: ...


class InMemorySecretStore:
    def __init__(self, backing_store: MutableMapping[str, str] | None = None):
        self._store = backing_store if backing_store is not None else {}

    async def put_secret(self, secret_ref: str, secret_value: str) -> str:
        self._store[secret_ref] = secret_value
        return secret_ref

    async def get_secret(self, secret_ref: str) -> str | None:
        return self._store.get(secret_ref)

    async def delete_secret(self, secret_ref: str) -> None:
        self._store.pop(secret_ref, None)

    async def put_secret_version(self, secret_ref: str, secret_value: str) -> str:
        return await self.put_secret(secret_ref, secret_value)


class GoogleSecretManagerSecretStore:
    def __init__(self, *, project_id: str, secret_prefix: str):
        self._project_id = project_id
        self._secret_prefix = secret_prefix.strip("-/")

    def _client(self):
        from google.cloud import secretmanager

        return secretmanager.SecretManagerServiceClient()

    def _secret_name(self, secret_ref: str) -> str:
        suffix = re.sub(r"[^A-Za-z0-9_-]+", "-", secret_ref.strip()).strip("-")
        name = f"{self._secret_prefix}-{suffix}".strip("-")
        if not name:
            raise ValueError("Secret reference cannot be converted to a valid GSM secret id.")
        return name[:255]

    def _secret_path(self, secret_ref: str) -> str:
        name = self._secret_name(secret_ref)
        return f"projects/{self._project_id}/secrets/{name}"

    async def put_secret(self, secret_ref: str, secret_value: str) -> str:
        client = self._client()
        secret_path = self._secret_path(secret_ref)
        parent = f"projects/{self._project_id}"
        secret_id = self._secret_name(secret_ref)

        try:
            await asyncio.to_thread(
                client.create_secret,
                request={
                    "parent": parent,
                    "secret_id": secret_id,
                    "secret": {"replication": {"automatic": {}}},
                },
            )
        except AlreadyExists:
            pass

        await asyncio.to_thread(
            client.add_secret_version,
            request={
                "parent": secret_path,
                "payload": {"data": secret_value.encode("utf-8")},
            },
        )
        return secret_ref

    async def get_secret(self, secret_ref: str) -> str | None:
        client = self._client()
        secret_path = f"{self._secret_path(secret_ref)}/versions/latest"
        try:
            response = await asyncio.to_thread(
                client.access_secret_version, request={"name": secret_path}
            )
        except Exception as exc:
            raise RuntimeError(
                f"Unable to read secret '{secret_ref}' from Google Secret Manager."
            ) from exc
        return response.payload.data.decode("utf-8")

    async def delete_secret(self, secret_ref: str) -> None:
        client = self._client()
        await asyncio.to_thread(
            client.delete_secret,
            request={"name": self._secret_path(secret_ref)},
        )

    async def put_secret_version(self, secret_ref: str, secret_value: str) -> str:
        client = self._client()
        secret_path = self._secret_path(secret_ref)
        previous = await asyncio.to_thread(
            lambda: list(
                client.list_secret_versions(
                    request={"parent": secret_path, "filter": "state:ENABLED"}
                )
            )
        )
        added = await asyncio.to_thread(
            client.add_secret_version,
            request={
                "parent": secret_path,
                "payload": {"data": secret_value.encode("utf-8")},
            },
        )
        added_name = str(getattr(added, "name", "") or "")
        for version in previous:
            version_name = str(getattr(version, "name", "") or "")
            if not version_name or version_name == added_name:
                continue
            await asyncio.to_thread(
                client.disable_secret_version,
                request={"name": version_name},
            )
        return secret_ref


_secret_store_singleton: SecretStore | None = None


def build_secret_store() -> SecretStore:
    backend = str(settings.n8n_secret_manager_backend or "memory").strip().lower()
    if backend == "google_secret_manager":
        project_id = str(settings.n8n_secret_manager_project_id or "").strip()
        if not project_id and firebase_admin._apps:
            project_id = str(firebase_admin.get_app().project_id or "").strip()
        if not project_id:
            raise ValueError(
                "Missing CONDUUT_N8N_SECRET_MANAGER_PROJECT_ID for google_secret_manager backend"
            )
        return GoogleSecretManagerSecretStore(
            project_id=project_id,
            secret_prefix=str(settings.n8n_secret_manager_secret_prefix or "conduut-n8n"),
        )
    return InMemorySecretStore()


def get_secret_store() -> SecretStore:
    global _secret_store_singleton
    if _secret_store_singleton is None:
        _secret_store_singleton = build_secret_store()
    return _secret_store_singleton
