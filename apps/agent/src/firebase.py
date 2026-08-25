from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import firebase_admin
from firebase_admin import credentials, firestore
from google.auth.credentials import AnonymousCredentials

from src.config import settings


@dataclass(frozen=True)
class FirebaseInitConfig:
    mode: Literal["certificate", "adc", "emulator"]
    project_id: str
    service_account_path: str | None = None


def _default_service_account_paths() -> tuple[Path, ...]:
    return (
        Path("/app/serviceAccount.json"),
        Path(__file__).resolve().parent.parent / "serviceAccount.json",
    )


def _resolve_service_account_path() -> Path | None:
    configured = str(settings.firebase_service_account_path or "").strip()
    if configured:
        candidate = Path(configured).expanduser().resolve()
        if not candidate.exists():
            raise FileNotFoundError(f"Firebase service account file not found: {candidate}")
        return candidate

    for candidate in _default_service_account_paths():
        if candidate.exists():
            return candidate.resolve()
    return None


def resolve_firebase_init_config() -> FirebaseInitConfig:
    mode = str(settings.firebase_credentials_mode or "auto").strip().lower()
    project_id = str(settings.firebase_project_id or "").strip()

    if mode == "certificate":
        service_account_path = _resolve_service_account_path()
        if service_account_path is None:
            raise FileNotFoundError(
                "CONDUUT_FIREBASE_CREDENTIALS_MODE=certificate requires a serviceAccount.json "
                "file or CONDUUT_FIREBASE_SERVICE_ACCOUNT_PATH."
            )
        return FirebaseInitConfig(
            mode="certificate",
            project_id=project_id,
            service_account_path=str(service_account_path),
        )

    if mode == "adc":
        return FirebaseInitConfig(mode="adc", project_id=project_id)

    if mode == "emulator":
        if not os.environ.get("FIRESTORE_EMULATOR_HOST"):
            raise ValueError(
                "CONDUUT_FIREBASE_CREDENTIALS_MODE=emulator requires FIRESTORE_EMULATOR_HOST."
            )
        return FirebaseInitConfig(mode="emulator", project_id=project_id)

    if mode != "auto":
        raise ValueError(f"Unsupported Firebase credentials mode '{mode}'.")

    service_account_path = _resolve_service_account_path()
    if service_account_path is not None:
        return FirebaseInitConfig(
            mode="certificate",
            project_id=project_id,
            service_account_path=str(service_account_path),
        )
    return FirebaseInitConfig(mode="adc", project_id=project_id)


def initialize_firebase_app():
    if firebase_admin._apps:
        return firebase_admin.get_app()

    init_config = resolve_firebase_init_config()
    options = {"projectId": init_config.project_id} if init_config.project_id else None
    if init_config.mode == "certificate":
        credential = credentials.Certificate(init_config.service_account_path)
    elif init_config.mode == "emulator":
        credential = _EmulatorCredentials()
    else:
        credential = credentials.ApplicationDefault()
    return firebase_admin.initialize_app(credential=credential, options=options)


class _EmulatorCredentials(credentials.Base):
    """Anonymous credentials allowed only for the explicit local test emulator mode."""

    def get_credential(self):
        return AnonymousCredentials()


_app = initialize_firebase_app()
db = firestore.client(_app)
