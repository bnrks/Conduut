from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    environment: str = "development"
    log_level: str = "INFO"

    # LLM defaults (kullanıcı kendi key'ini gönderir, bunlar fallback)
    default_model: str = "gpt-4o-mini"

    # n8n
    n8n_url: str = "http://localhost:5678"
    n8n_api_key: str = ""

    model_config = {"env_prefix": "CONDUUT_", "env_file": ".env"}


settings = Settings()
