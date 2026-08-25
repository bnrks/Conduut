import importlib
import re
import sys
from pathlib import Path

import firebase_admin
import pytest
from firebase_admin import firestore as firebase_firestore


def _load_firebase_module(monkeypatch):
    sys.modules.pop("src.firebase", None)
    monkeypatch.setattr(firebase_admin, "_apps", {"existing": object()})
    monkeypatch.setattr(firebase_admin, "get_app", lambda: object())
    monkeypatch.setattr(firebase_firestore, "client", lambda app=None: object())
    return importlib.import_module("src.firebase")


def test_resolve_firebase_init_config_prefers_configured_certificate(monkeypatch, tmp_path):
    firebase = _load_firebase_module(monkeypatch)
    service_account = tmp_path / "service-account.json"
    service_account.write_text("{}", encoding="utf-8")

    monkeypatch.setattr(firebase.settings, "firebase_credentials_mode", "certificate")
    monkeypatch.setattr(firebase.settings, "firebase_project_id", "firebase-local")
    monkeypatch.setattr(
        firebase.settings,
        "firebase_service_account_path",
        str(service_account),
    )

    config = firebase.resolve_firebase_init_config()

    assert config.mode == "certificate"
    assert config.project_id == "firebase-local"
    assert config.service_account_path == str(service_account.resolve())


def test_resolve_firebase_init_config_auto_falls_back_to_adc(monkeypatch):
    firebase = _load_firebase_module(monkeypatch)
    monkeypatch.setattr(firebase.settings, "firebase_credentials_mode", "auto")
    monkeypatch.setattr(firebase.settings, "firebase_project_id", "firebase-cloud")
    monkeypatch.setattr(firebase.settings, "firebase_service_account_path", "")
    monkeypatch.setattr(firebase, "_default_service_account_paths", lambda: ())

    config = firebase.resolve_firebase_init_config()

    assert config.mode == "adc"
    assert config.project_id == "firebase-cloud"
    assert config.service_account_path is None


def test_resolve_firebase_init_config_certificate_requires_existing_file(monkeypatch, tmp_path):
    firebase = _load_firebase_module(monkeypatch)
    missing_path = tmp_path / "missing.json"

    monkeypatch.setattr(firebase.settings, "firebase_credentials_mode", "certificate")
    monkeypatch.setattr(firebase.settings, "firebase_service_account_path", str(missing_path))

    with pytest.raises(FileNotFoundError, match=re.escape(str(Path(missing_path).resolve()))):
        firebase.resolve_firebase_init_config()


def test_resolve_firebase_init_config_emulator_requires_host(monkeypatch):
    firebase = _load_firebase_module(monkeypatch)
    monkeypatch.setattr(firebase.settings, "firebase_credentials_mode", "emulator")
    monkeypatch.delenv("FIRESTORE_EMULATOR_HOST", raising=False)

    with pytest.raises(ValueError, match="FIRESTORE_EMULATOR_HOST"):
        firebase.resolve_firebase_init_config()


def test_resolve_firebase_init_config_accepts_explicit_emulator(monkeypatch):
    firebase = _load_firebase_module(monkeypatch)
    monkeypatch.setattr(firebase.settings, "firebase_credentials_mode", "emulator")
    monkeypatch.setattr(firebase.settings, "firebase_project_id", "firebase-test")
    monkeypatch.setenv("FIRESTORE_EMULATOR_HOST", "127.0.0.1:8080")

    config = firebase.resolve_firebase_init_config()

    assert config.mode == "emulator"
    assert config.project_id == "firebase-test"
