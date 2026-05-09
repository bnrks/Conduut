from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    environment: str = "development"
    log_level: str = "INFO"

    # LLM defaults (kullanıcı kendi key'ini gönderir, bunlar fallback)
    default_model: str = "gpt-4o-mini"

    # n8n
    n8n_url: str = "http://localhost:5678"
    n8n_api_key: str = ""

    # OAuth broker
    public_web_url: str = "http://localhost:3000"
    google_oauth_client_id: str = ""
    google_oauth_client_secret: str = ""
    oauth_state_ttl_seconds: int = 600

    model_config = {"env_prefix": "CONDUUT_", "env_file": ".env"}


settings = Settings()
