from src.config import _find_repo_root


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
