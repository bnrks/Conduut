"""Encryption helpers for connection secrets stored in Firestore."""

from __future__ import annotations

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken

from src.config import settings


class ConnectionSecretError(RuntimeError):
    """Raised when connection secret encryption is unavailable or invalid."""


def _fernet() -> Fernet:
    key = settings.connection_encryption_key.strip()
    if not key:
        raise ConnectionSecretError("CONDUUT_CONNECTION_ENCRYPTION_KEY is not configured.")
    try:
        return Fernet(key.encode("utf-8"))
    except ValueError:
        digest = hashlib.sha256(key.encode("utf-8")).digest()
        return Fernet(base64.urlsafe_b64encode(digest))


def can_encrypt_connection_secrets() -> bool:
    return bool(settings.connection_encryption_key.strip())


def encrypt_connection_secret(value: str) -> str:
    if not value:
        return ""
    return _fernet().encrypt(value.encode("utf-8")).decode("utf-8")


def decrypt_connection_secret(value: str) -> str:
    if not value:
        return ""
    try:
        return _fernet().decrypt(value.encode("utf-8")).decode("utf-8")
    except InvalidToken as exc:
        raise ConnectionSecretError("Connection secret could not be decrypted.") from exc
