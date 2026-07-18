"""Application configuration loaded from environment variables."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """BiasRadar settings.

    Required values are validated when a command first needs configuration,
    rather than at import time, so CLI help remains available without a .env.
    """

    supabase_url: str
    supabase_service_key: str
    newsapi_key: str

    openai_api_key: str | None = None
    openai_base_url: str = "https://models.github.ai/inference"
    openai_model: str = "openai/gpt-4.1-mini"
    google_fact_check_api_key: str | None = None
    telegram_bot_token: str | None = None
    telegram_chat_id: str | None = None

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    """Return the validated application settings."""

    return Settings()  # type: ignore[call-arg]
