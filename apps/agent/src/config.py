import json
from pathlib import Path

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings

_APP_DIR = Path(__file__).resolve().parents[1]


def _find_repo_root(start: Path) -> Path:
    for path in (start, *start.parents):
        if (path / "docker-compose.yml").exists() or (path / "AGENTS.md").exists():
            return path
    return start


_REPO_ROOT = _find_repo_root(_APP_DIR)


def _registry_manifest_path() -> Path:
    direct = _REPO_ROOT / "packages" / "n8n-registry" / "data" / "registry_manifest.json"
    if direct.exists():
        return direct
    return _APP_DIR.parent / "data" / "registry_manifest.json"


class Settings(BaseSettings):
    environment: str = "development"
    log_level: str = "INFO"
    log_file_enabled: bool = True
    log_dir: str = "logs/agent"
    log_max_bytes: int = 10 * 1024 * 1024
    log_backup_count: int = 5
    log_payload_preview_chars: int = 1000
    run_log_enabled: bool = True
    run_log_retention_days: int = 30
    run_log_preview_chars: int = 300

    # LLM — Conduut-managed models (no per-user provider connection).
    # CONDUUT_MODEL_PROFILE selects the tier→model mapping (see agent/model_registry.py).
    # NOTE: defaults to "deepseek" on the feature/deepseek-tier-bakeoff branch so the
    # branch runs the DeepSeek bake-off out of the box (see model-cost-research-2026-06).
    model_profile: str = "deepseek"  # "default" | "gpt" | "deepseek"
    enable_tier_escalation: bool = True
    # Buffer+retry DeepSeek runs to absorb the #1244 plain-text-tool-call failure.
    enable_reliability_guard: bool = True
    # Workflow assurance rollout: observe logs findings, hybrid enforces only
    # deterministic rules, enforce also blocks incomplete contract coverage.
    workflow_assurance_mode: str = "hybrid"
    # Card retrieval readiness: auto=enforce in production, observe elsewhere.
    workflow_card_retrieval_mode: str = "auto"
    # Fixed, cheap Gemini model used for decoupled web-search research
    # (API auth discovery). Provider-independent of the conversational tier.
    research_model: str = "gemini-2.5-flash"
    anthropic_api_key: str = ""
    google_api_key: str = ""
    openai_api_key: str = ""
    openrouter_api_key: str = ""
    deepseek_api_key: str = ""

    # n8n
    n8n_url: str = "http://localhost:6180"
    n8n_api_key: str = Field(
        default="",
        validation_alias=AliasChoices(
            "CONDUUT_DEV_SHARED_N8N_API_KEY",
            "CONDUUT_N8N_API_KEY",
        ),
    )
    n8n_version: str = ""
    n8n_provider_mode: str = "shared_dev"
    n8n_registry_url: str = ""
    n8n_secret_manager_backend: str = "memory"
    n8n_secret_manager_project_id: str = ""
    n8n_secret_manager_secret_prefix: str = "conduut-n8n"
    n8n_migration_mode: str = "off"
    n8n_migration_manifest_path: str = ""
    # User-facing schedule times are stored in this workflow timezone. Keeping
    # it explicit prevents n8n's America/New_York default from silently shifting
    # schedules when the model writes the user's local clock time.
    workflow_timezone: str = "Europe/Istanbul"

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
    "deepseek": "deepseek_api_key",
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


def canonical_n8n_version() -> str:
    configured = str(settings.n8n_version or "").strip()
    if configured:
        return configured

    manifest_path = _registry_manifest_path()
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return ""

    version = payload.get("n8nVersion")
    return str(version).strip() if version else ""


def registry_n8n_url() -> str:
    configured = str(settings.n8n_registry_url or "").strip()
    if configured:
        return configured
    return str(settings.n8n_url or "").strip()


def validate_n8n_provider_settings() -> None:
    environment = str(settings.environment or "").strip().lower()
    provider_mode = str(settings.n8n_provider_mode or "").strip().lower()
    secret_backend = str(settings.n8n_secret_manager_backend or "").strip().lower()

    if environment == "production":
        if provider_mode != "customer_owned":
            raise ValueError("Production requires CONDUUT_N8N_PROVIDER_MODE=customer_owned.")
        if secret_backend != "google_secret_manager":
            raise ValueError(
                "Production requires CONDUUT_N8N_SECRET_MANAGER_BACKEND=google_secret_manager."
            )
    elif provider_mode not in {"shared_dev", "customer_owned"}:
        raise ValueError("Unsupported CONDUUT_N8N_PROVIDER_MODE.")
