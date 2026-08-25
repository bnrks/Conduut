import json
import shutil
import tempfile
from pathlib import Path

import pytest

from src.config import (
    _DEFAULT_LOCAL_SECRET_STORE_PATH,
    Settings,
    _find_repo_root,
    canonical_n8n_version,
    key_for_provider,
    registry_n8n_url,
    settings,
    shared_dev_n8n_api_key,
    validate_n8n_provider_settings,
)


def test_find_repo_root_uses_marker_directory(tmp_path):
    repo_root = tmp_path / "repo"
    app_dir = repo_root / "apps" / "agent"
    app_dir.mkdir(parents=True)
    (repo_root / "AGENTS.md").write_text("# test\n", encoding="utf-8")

    assert _find_repo_root(app_dir) == repo_root


def test_find_repo_root_falls_back_to_start_without_marker():
    temp_dir = tempfile.mkdtemp(prefix="conduut-find-root-")
    try:
        app_dir = Path(temp_dir) / "app"
        app_dir.mkdir()
        original_exists = Path.exists

        def fake_exists(path: Path) -> bool:
            if path.name in {"AGENTS.md", "docker-compose.yml"}:
                return False
            return original_exists(path)

        Path.exists = fake_exists  # type: ignore[method-assign]
        try:
            assert _find_repo_root(app_dir) == app_dir
        finally:
            Path.exists = original_exists  # type: ignore[method-assign]
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def test_key_for_provider_returns_configured_key(monkeypatch):
    monkeypatch.setattr(settings, "anthropic_api_key", "sk-ant-xyz")
    assert key_for_provider("anthropic") == "sk-ant-xyz"


def test_key_for_provider_normalizes_and_reads_google(monkeypatch):
    monkeypatch.setattr(settings, "google_api_key", "g-key")
    assert key_for_provider("Google") == "g-key"


def test_key_for_provider_returns_deepseek_key(monkeypatch):
    monkeypatch.setattr(settings, "deepseek_api_key", "sk-ds-xyz")
    assert key_for_provider("deepseek") == "sk-ds-xyz"


def test_key_for_provider_raises_when_unset(monkeypatch):
    monkeypatch.setattr(settings, "google_api_key", "")
    with pytest.raises(ValueError, match="CONDUUT_GOOGLE_API_KEY"):
        key_for_provider("google")


def test_key_for_provider_rejects_unknown_provider():
    with pytest.raises(ValueError):
        key_for_provider("cohere")


def test_workflow_timezone_defaults_to_istanbul():
    assert settings.workflow_timezone == "Europe/Istanbul"


def test_registry_n8n_url_falls_back_to_n8n_url(monkeypatch):
    monkeypatch.setattr(settings, "n8n_registry_url", "")
    monkeypatch.setattr(settings, "n8n_url", "http://localhost:6180")
    assert registry_n8n_url() == "http://localhost:6180"


def test_settings_accepts_both_shared_dev_n8n_api_key_names(monkeypatch):
    monkeypatch.setenv("CONDUUT_DEV_SHARED_N8N_API_KEY", "dev-key")
    monkeypatch.setenv("CONDUUT_N8N_API_KEY", "legacy-key")

    loaded = Settings(_env_file=None)

    assert loaded.dev_shared_n8n_api_key == "dev-key"
    assert loaded.n8n_api_key == "legacy-key"


def test_shared_dev_n8n_api_key_prefers_scoped_name(monkeypatch):
    monkeypatch.setattr(settings, "dev_shared_n8n_api_key", "dev-key")
    monkeypatch.setattr(settings, "n8n_api_key", "legacy-key")

    assert shared_dev_n8n_api_key() == "dev-key"


def test_canonical_n8n_version_reads_registry_manifest(tmp_path, monkeypatch):
    manifest = tmp_path / "registry_manifest.json"
    manifest.write_text(json.dumps({"n8nVersion": "1.121.3"}), encoding="utf-8")

    monkeypatch.setattr(settings, "n8n_version", "")
    monkeypatch.setattr("src.config._registry_manifest_path", lambda: manifest)

    assert canonical_n8n_version() == "1.121.3"


def test_local_secret_store_path_defaults_to_stable_absolute_path():
    assert Path(settings.n8n_local_secret_store_path).is_absolute()
    assert Path(settings.n8n_local_secret_store_path) == _DEFAULT_LOCAL_SECRET_STORE_PATH


def test_validate_n8n_provider_settings_rejects_non_google_secret_backend_in_production(
    monkeypatch,
):
    monkeypatch.setattr(settings, "environment", "production")
    monkeypatch.setattr(settings, "n8n_provider_mode", "customer_owned")
    monkeypatch.setattr(settings, "n8n_secret_manager_backend", "encrypted_file")
    monkeypatch.setattr(settings, "firebase_credentials_mode", "adc")
    monkeypatch.setattr(settings, "firebase_project_id", "firebase-prod")
    monkeypatch.setattr(settings, "n8n_secret_manager_project_id", "gsm-prod")
    monkeypatch.setattr(settings, "n8n_secret_manager_location", "europe-west3")

    with pytest.raises(ValueError, match="google_secret_manager"):
        validate_n8n_provider_settings()


def test_validate_n8n_provider_settings_accepts_customer_owned_google_backend_in_production(
    monkeypatch,
):
    monkeypatch.setattr(settings, "environment", "production")
    monkeypatch.setattr(settings, "n8n_provider_mode", "customer_owned")
    monkeypatch.setattr(settings, "n8n_secret_manager_backend", "google_secret_manager")
    monkeypatch.setattr(settings, "firebase_credentials_mode", "adc")
    monkeypatch.setattr(settings, "firebase_project_id", "firebase-prod")
    monkeypatch.setattr(settings, "n8n_secret_manager_project_id", "gsm-prod")
    monkeypatch.setattr(settings, "n8n_secret_manager_location", "europe-west3")

    validate_n8n_provider_settings()


def test_validate_n8n_provider_settings_rejects_memory_for_local_customer_owned(
    monkeypatch,
):
    monkeypatch.setattr(settings, "environment", "development")
    monkeypatch.setattr(settings, "n8n_provider_mode", "customer_owned")
    monkeypatch.setattr(settings, "n8n_secret_manager_backend", "memory")

    with pytest.raises(ValueError, match="encrypted_file"):
        validate_n8n_provider_settings()


def test_validate_n8n_provider_settings_accepts_encrypted_file_for_local_customer_owned(
    monkeypatch,
):
    monkeypatch.setattr(settings, "environment", "development")
    monkeypatch.setattr(settings, "n8n_provider_mode", "customer_owned")
    monkeypatch.setattr(settings, "n8n_secret_manager_backend", "encrypted_file")

    validate_n8n_provider_settings()


def test_validate_n8n_provider_settings_rejects_non_adc_firebase_mode_in_staging(monkeypatch):
    monkeypatch.setattr(settings, "environment", "staging")
    monkeypatch.setattr(settings, "n8n_provider_mode", "customer_owned")
    monkeypatch.setattr(settings, "n8n_secret_manager_backend", "google_secret_manager")
    monkeypatch.setattr(settings, "n8n_secret_manager_project_id", "gsm-staging")
    monkeypatch.setattr(settings, "n8n_secret_manager_location", "europe-west3")
    monkeypatch.setattr(settings, "firebase_credentials_mode", "certificate")
    monkeypatch.setattr(settings, "firebase_project_id", "firebase-staging")

    with pytest.raises(ValueError, match="CONDUUT_FIREBASE_CREDENTIALS_MODE=adc"):
        validate_n8n_provider_settings()


def test_validate_n8n_provider_settings_rejects_missing_firebase_project_id_in_staging(
    monkeypatch,
):
    monkeypatch.setattr(settings, "environment", "staging")
    monkeypatch.setattr(settings, "n8n_provider_mode", "customer_owned")
    monkeypatch.setattr(settings, "n8n_secret_manager_backend", "google_secret_manager")
    monkeypatch.setattr(settings, "n8n_secret_manager_project_id", "gsm-staging")
    monkeypatch.setattr(settings, "n8n_secret_manager_location", "europe-west3")
    monkeypatch.setattr(settings, "firebase_credentials_mode", "adc")
    monkeypatch.setattr(settings, "firebase_project_id", "")

    with pytest.raises(ValueError, match="CONDUUT_FIREBASE_PROJECT_ID"):
        validate_n8n_provider_settings()


def test_validate_n8n_provider_settings_rejects_unknown_firebase_credentials_mode(monkeypatch):
    monkeypatch.setattr(settings, "environment", "development")
    monkeypatch.setattr(settings, "firebase_credentials_mode", "bogus")

    with pytest.raises(ValueError, match="CONDUUT_FIREBASE_CREDENTIALS_MODE"):
        validate_n8n_provider_settings()


def test_validate_n8n_provider_settings_rejects_emulator_credentials_in_production(
    monkeypatch,
):
    monkeypatch.setattr(settings, "environment", "production")
    monkeypatch.setattr(settings, "firebase_credentials_mode", "emulator")

    with pytest.raises(ValueError, match="limited to development and test"):
        validate_n8n_provider_settings()


def test_validate_n8n_provider_settings_rejects_missing_gsm_location_in_staging(monkeypatch):
    monkeypatch.setattr(settings, "environment", "staging")
    monkeypatch.setattr(settings, "n8n_provider_mode", "customer_owned")
    monkeypatch.setattr(settings, "n8n_secret_manager_backend", "google_secret_manager")
    monkeypatch.setattr(settings, "n8n_secret_manager_project_id", "gsm-staging")
    monkeypatch.setattr(settings, "n8n_secret_manager_location", "")
    monkeypatch.setattr(settings, "firebase_credentials_mode", "adc")
    monkeypatch.setattr(settings, "firebase_project_id", "firebase-staging")

    with pytest.raises(ValueError, match="CONDUUT_N8N_SECRET_MANAGER_LOCATION"):
        validate_n8n_provider_settings()
