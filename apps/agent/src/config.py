from pathlib import Path

from pydantic_settings import BaseSettings

_APP_DIR = Path(__file__).resolve().parents[1]


def _find_repo_root(start: Path) -> Path:
    for path in (start, *start.parents):
        if (path / "docker-compose.yml").exists() or (path / "AGENTS.md").exists():
            return path
    return start


_REPO_ROOT = _find_repo_root(_APP_DIR)


class Settings(BaseSettings):
    environment: str = "development"
    log_level: str = "INFO"
    log_file_enabled: bool = True
    log_dir: str = "logs/agent"
    log_max_bytes: int = 10 * 1024 * 1024
    log_backup_count: int = 5
    log_payload_preview_chars: int = 1000

    # LLM defaults (kullanıcı kendi key'ini gönderir, bunlar fallback)
    default_model: str = "gpt-4o-mini"

    # n8n
    n8n_url: str = "http://localhost:5980"
    n8n_api_key: str = ""

    # OAuth broker
    public_web_url: str = "http://localhost:3000"
    google_oauth_client_id: str = ""
    google_oauth_client_secret: str = ""
    oauth_state_ttl_seconds: int = 600

    model_config = {
        "env_prefix": "CONDUUT_",
        "env_file": (
            _REPO_ROOT / ".env",
            _APP_DIR / ".env",
        ),
    }


settings = Settings()
