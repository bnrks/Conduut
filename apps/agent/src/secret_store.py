from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import re
import tempfile
from collections.abc import MutableMapping
from pathlib import Path
from typing import Protocol

import firebase_admin
from cryptography.fernet import Fernet
from google.api_core.exceptions import AlreadyExists, NotFound
from google.protobuf import duration_pb2

from src.config import settings

logger = logging.getLogger(__name__)


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


class EncryptedFileSecretStore:
    def __init__(self, store_path: str | Path):
        self._store_path = Path(store_path).expanduser().resolve()
        self._key_path = self._store_path.with_suffix(".key")
        self._lock = asyncio.Lock()

    async def put_secret(self, secret_ref: str, secret_value: str) -> str:
        async with self._lock:
            payload = await asyncio.to_thread(self._read_payload)
            payload[secret_ref] = self._encrypt(secret_value)
            await asyncio.to_thread(self._write_payload, payload)
        return secret_ref

    async def get_secret(self, secret_ref: str) -> str | None:
        async with self._lock:
            payload = await asyncio.to_thread(self._read_payload)
            encrypted = payload.get(secret_ref)
            if encrypted is None:
                return None
            return self._decrypt(encrypted)

    async def delete_secret(self, secret_ref: str) -> None:
        async with self._lock:
            payload = await asyncio.to_thread(self._read_payload)
            payload.pop(secret_ref, None)
            await asyncio.to_thread(self._write_payload, payload)

    async def put_secret_version(self, secret_ref: str, secret_value: str) -> str:
        return await self.put_secret(secret_ref, secret_value)

    def _fernet(self) -> Fernet:
        return Fernet(self._ensure_key())

    def _encrypt(self, value: str) -> str:
        return self._fernet().encrypt(value.encode("utf-8")).decode("utf-8")

    def _decrypt(self, value: str) -> str:
        return self._fernet().decrypt(value.encode("utf-8")).decode("utf-8")

    def _ensure_key(self) -> bytes:
        self._ensure_parent_dir()
        if self._key_path.exists():
            return self._key_path.read_bytes().strip()

        key = Fernet.generate_key()
        if self._write_new_file(self._key_path, key + b"\n"):
            return key
        return self._key_path.read_bytes().strip()

    def _read_payload(self) -> dict[str, str]:
        if not self._store_path.exists():
            return {}
        try:
            payload = json.loads(self._store_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise RuntimeError(
                f"Encrypted secret store at '{self._store_path}' is not valid JSON."
            ) from exc
        if not isinstance(payload, dict):
            raise RuntimeError(
                f"Encrypted secret store at '{self._store_path}' must contain a JSON object."
            )
        secrets: dict[str, str] = {}
        for key, value in payload.items():
            if isinstance(key, str) and isinstance(value, str):
                secrets[key] = value
        return secrets

    def _write_payload(self, payload: dict[str, str]) -> None:
        self._ensure_parent_dir()
        encoded = json.dumps(payload, indent=2, sort_keys=True).encode("utf-8")
        fd, temp_name = tempfile.mkstemp(
            prefix=f"{self._store_path.name}.",
            suffix=".tmp",
            dir=self._store_path.parent,
            text=False,
        )
        temp_path = Path(temp_name)
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(encoded)
            self._set_owner_only_permissions(temp_path)
            os.replace(temp_path, self._store_path)
            self._set_owner_only_permissions(self._store_path)
        finally:
            if temp_path.exists():
                try:
                    temp_path.unlink()
                except OSError:
                    pass

    def _write_new_file(self, path: Path, data: bytes, *, replace_existing: bool = False) -> bool:
        flags = os.O_WRONLY | os.O_CREAT
        if replace_existing:
            flags |= os.O_TRUNC
        else:
            flags |= os.O_EXCL
        try:
            fd = os.open(path, flags, 0o600)
        except FileExistsError:
            if not replace_existing:
                return False
            raise
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(data)
        finally:
            self._set_owner_only_permissions(path)
        return True

    def _ensure_parent_dir(self) -> None:
        self._store_path.parent.mkdir(parents=True, exist_ok=True)
        self._set_owner_only_permissions(self._store_path.parent)

    def _set_owner_only_permissions(self, path: Path) -> None:
        try:
            os.chmod(path, 0o600 if path.is_file() else 0o700)
        except OSError:
            return


class GoogleSecretManagerSecretStore:
    _VERSION_DESTROY_TTL_SECONDS = 7 * 24 * 60 * 60

    def __init__(self, *, project_id: str, secret_prefix: str, location: str = ""):
        self._project_id = project_id
        self._secret_prefix = secret_prefix.strip("-/")
        self._location = location.strip()
        if not self._project_id.strip():
            raise ValueError("Google Secret Manager project id is required.")
        if not re.fullmatch(r"[A-Za-z0-9_-]+", self._secret_prefix):
            raise ValueError(
                "Google Secret Manager secret prefix must use only letters, numbers, hyphens, "
                "or underscores."
            )

    def _client(self):
        from google.cloud import secretmanager

        return secretmanager.SecretManagerServiceClient()

    def _secret_name(self, secret_ref: str) -> str:
        normalized = secret_ref.strip()
        if not normalized:
            raise ValueError("Secret reference cannot be empty.")
        digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:40]
        name = f"{self._secret_prefix}-tenant-{digest}".strip("-")
        if not name:
            raise ValueError("Secret reference cannot be converted to a valid GSM secret id.")
        return name[:255]

    def _secret_path(self, secret_ref: str) -> str:
        name = self._secret_name(secret_ref)
        return f"projects/{self._project_id}/secrets/{name}"

    @staticmethod
    def _parse_version_number(version_name: str) -> int:
        try:
            return int(version_name.rsplit("/", 1)[-1])
        except (TypeError, ValueError):
            return -1

    async def _ensure_secret(self, client, secret_ref: str) -> str:
        secret_path = self._secret_path(secret_ref)
        parent = f"projects/{self._project_id}"
        secret_id = self._secret_name(secret_ref)

        try:
            await asyncio.to_thread(
                client.create_secret,
                request={
                    "parent": parent,
                    "secret_id": secret_id,
                    "secret": {
                        "replication": (
                            {"user_managed": {"replicas": [{"location": self._location}]}}
                            if self._location
                            else {"automatic": {}}
                        ),
                        "version_destroy_ttl": duration_pb2.Duration(
                            seconds=self._VERSION_DESTROY_TTL_SECONDS
                        ),
                    },
                },
            )
        except AlreadyExists:
            pass
        return secret_path

    async def _access_secret_version(self, client, version_name: str) -> str:
        response = await asyncio.to_thread(
            client.access_secret_version,
            request={"name": version_name},
        )
        return response.payload.data.decode("utf-8")

    async def _enabled_version_names(self, client, secret_path: str) -> list[str]:
        try:
            versions = await asyncio.to_thread(
                lambda: list(
                    client.list_secret_versions(
                        request={"parent": secret_path, "filter": "state:ENABLED"}
                    )
                )
            )
        except NotFound:
            return []
        names = [str(getattr(version, "name", "") or "") for version in versions]
        names = [name for name in names if name]
        names.sort(key=self._parse_version_number)
        return names

    async def _latest_enabled_version_name(self, client, secret_path: str) -> str | None:
        versions = await self._enabled_version_names(client, secret_path)
        if not versions:
            return None
        return versions[-1]

    async def put_secret(self, secret_ref: str, secret_value: str) -> str:
        client = self._client()
        secret_path = await self._ensure_secret(client, secret_ref)
        created = await asyncio.to_thread(
            client.add_secret_version,
            request={
                "parent": secret_path,
                "payload": {"data": secret_value.encode("utf-8")},
            },
        )
        created_name = str(getattr(created, "name", "") or "")
        try:
            if not created_name:
                raise RuntimeError("Secret Manager did not return the new version name.")
            roundtrip = await self._access_secret_version(client, created_name)
            if roundtrip != secret_value:
                raise RuntimeError("Secret Manager verification mismatch.")
        except Exception as exc:
            if created_name:
                try:
                    await asyncio.to_thread(
                        client.destroy_secret_version,
                        request={"name": created_name},
                    )
                except Exception:
                    pass
            raise RuntimeError("Unable to verify tenant secret in Google Secret Manager.") from exc
        return secret_ref

    async def get_secret(self, secret_ref: str) -> str | None:
        client = self._client()
        secret_path = self._secret_path(secret_ref)
        try:
            version_name = await self._latest_enabled_version_name(client, secret_path)
            if version_name is None:
                return None
            return await self._access_secret_version(client, version_name)
        except NotFound:
            return None
        except Exception as exc:
            raise RuntimeError("Unable to read tenant secret from Google Secret Manager.") from exc

    async def delete_secret(self, secret_ref: str) -> None:
        client = self._client()
        try:
            await asyncio.to_thread(
                client.delete_secret,
                request={"name": self._secret_path(secret_ref)},
            )
        except NotFound:
            return

    async def put_secret_version(self, secret_ref: str, secret_value: str) -> str:
        client = self._client()
        secret_path = await self._ensure_secret(client, secret_ref)
        previous = await self._enabled_version_names(client, secret_path)
        added = await asyncio.to_thread(
            client.add_secret_version,
            request={
                "parent": secret_path,
                "payload": {"data": secret_value.encode("utf-8")},
            },
        )
        added_name = str(getattr(added, "name", "") or "")
        try:
            if not added_name:
                raise RuntimeError("Secret Manager did not return the new version name.")
            roundtrip = await self._access_secret_version(client, added_name)
            if roundtrip != secret_value:
                raise RuntimeError("Secret Manager verification mismatch.")
        except Exception as exc:
            if added_name:
                try:
                    await asyncio.to_thread(
                        client.destroy_secret_version,
                        request={"name": added_name},
                    )
                except Exception:
                    pass
            raise RuntimeError(
                "Unable to verify rotated tenant secret in Google Secret Manager."
            ) from exc

        for version_name in previous:
            if version_name == added_name:
                continue
            try:
                await asyncio.to_thread(
                    client.destroy_secret_version,
                    request={"name": version_name},
                )
            except Exception as exc:
                logger.warning(
                    "tenant_secret_previous_version_cleanup_failed",
                    extra={"error_type": type(exc).__name__},
                )
        return secret_ref


_secret_store_singleton: SecretStore | None = None


def build_secret_store() -> SecretStore:
    backend = str(settings.n8n_secret_manager_backend or "memory").strip().lower()
    if backend == "encrypted_file":
        return EncryptedFileSecretStore(settings.n8n_local_secret_store_path)
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
            location=str(settings.n8n_secret_manager_location or ""),
        )
    if backend == "memory":
        return InMemorySecretStore()
    raise ValueError(f"Unsupported CONDUUT_N8N_SECRET_MANAGER_BACKEND '{backend}'.")


def get_secret_store() -> SecretStore:
    global _secret_store_singleton
    if _secret_store_singleton is None:
        _secret_store_singleton = build_secret_store()
    return _secret_store_singleton
