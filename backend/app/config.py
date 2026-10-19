from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "sqlite:///./updater.db"
    updater_token: str = ""
    updater_api_url: str = "http://127.0.0.1:8000"
    mcp_allowed_hosts: str = ""
    cors_origins: str = "http://localhost:5173"
    openrouter_api_key: str = ""
    allow_open_registration: bool = True
    github_webhook_secret: str = ""
    llm_model: str = "google/gemini-3.5-flash-lite"
    # Affinebot link (per-workspace credentials live in AffinebotLink; these are global knobs)
    affinebot_timeout_s: float = 10.0
    updater_secret_key: str = ""  # optional; encrypts link secrets at rest (Fernet)


@lru_cache
def get_settings() -> Settings:
    return Settings()
