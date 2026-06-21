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

    # LLM — Conduut-managed models (no per-user provider connection).
    # CONDUUT_MODEL_PROFILE selects the tier→model mapping (see agent/model_registry.py).
    model_profile: str = "default"  # "default" | "gpt"
    enable_tier_escalation: bool = True
    # Fixed, cheap Gemini model used for decoupled web-search research
    # (API auth discovery). Provider-independent of the conversational tier.
    research_model: str = "gemini-2.5-flash"
    anthropic_api_key: str = ""
    google_api_key: str = ""
    openai_api_key: str = ""
    openrouter_api_key: str = ""

    # n8n
    n8n_url: str = "http://localhost:6180"
    n8n_api_key: str = ""

    # OAuth broker
    public_web_url: str = "http://localhost:3000"
    google_oauth_client_id: str = ""
    google_oauth_client_secret: str = ""
    oauth_state_ttl_seconds: int = 600
    connection_encryption_key: str = ""

    model_config = {
        "env_prefix": "CONDUUT_",
        "env_file": (
            _REPO_ROOT / ".env",
            _APP_DIR / ".env",
        ),
        # model_profile would otherwise trip pydantic's protected "model_" namespace
        "protected_namespaces": (),
    }


settings = Settings()


# provider key -> Settings attribute holding the Conduut-managed API key.
_PROVIDER_KEY_ATTR: dict[str, str] = {
    "anthropic": "anthropic_api_key",
    "google": "google_api_key",
    "openai": "openai_api_key",
    "openrouter": "openrouter_api_key",
}


def key_for_provider(provider: str) -> str:
    """Return Conduut's API key for a provider, or raise if unknown/unset."""

    provider_key = provider.strip().lower()
    attr = _PROVIDER_KEY_ATTR.get(provider_key)
    if attr is None:
        raise ValueError(f"No Conduut-managed key mapping for provider '{provider}'")
    value = getattr(settings, attr, "")
    if not value:
        raise ValueError(
            f"Missing Conduut API key for provider '{provider_key}' (set CONDUUT_{attr.upper()})"
        )
    return value
