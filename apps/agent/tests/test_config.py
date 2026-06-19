import pytest

from src.config import _find_repo_root, key_for_provider, settings


def test_find_repo_root_uses_marker_directory(tmp_path):
    repo_root = tmp_path / "repo"
    app_dir = repo_root / "apps" / "agent"
    app_dir.mkdir(parents=True)
    (repo_root / "AGENTS.md").write_text("# test\n", encoding="utf-8")

    assert _find_repo_root(app_dir) == repo_root


def test_find_repo_root_falls_back_to_start_without_marker(tmp_path):
    app_dir = tmp_path / "app"
    app_dir.mkdir()

    assert _find_repo_root(app_dir) == app_dir


def test_key_for_provider_returns_configured_key(monkeypatch):
    monkeypatch.setattr(settings, "anthropic_api_key", "sk-ant-xyz")
    assert key_for_provider("anthropic") == "sk-ant-xyz"


def test_key_for_provider_normalizes_and_reads_google(monkeypatch):
    monkeypatch.setattr(settings, "google_api_key", "g-key")
    assert key_for_provider("Google") == "g-key"


def test_key_for_provider_raises_when_unset(monkeypatch):
    monkeypatch.setattr(settings, "google_api_key", "")
    with pytest.raises(ValueError, match="CONDUUT_GOOGLE_API_KEY"):
        key_for_provider("google")


def test_key_for_provider_rejects_unknown_provider():
    with pytest.raises(ValueError):
        key_for_provider("cohere")
