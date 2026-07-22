"""Application configuration loaded from environment variables."""

import json
from functools import lru_cache
from urllib.parse import urlsplit

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from biasradar.domains.profiles import get_domain_profile

ENV_CONFIG = SettingsConfigDict(
    env_file=".env",
    env_file_encoding="utf-8",
    extra="ignore",
)


class APISettings(BaseSettings):
    """Minimal server-only configuration for the read API."""

    supabase_url: str
    supabase_service_key: str
    api_cors_origins: str = "http://localhost:3000"
    api_topic_rate_limit: int = Field(default=10, ge=1, le=100)

    model_config = ENV_CONFIG

    @field_validator("supabase_url")
    @classmethod
    def validate_supabase_url(cls, value: str) -> str:
        return Settings.validate_service_url(value)

    @field_validator("supabase_service_key")
    @classmethod
    def validate_supabase_key(cls, value: str) -> str:
        return Settings.reject_placeholder_secret(value)

    @property
    def cors_origins(self) -> list[str]:
        """Return explicitly configured HTTP(S) frontend origins."""

        origins = [
            value.strip().rstrip("/") for value in self.api_cors_origins.split(",")
        ]
        validated: list[str] = []
        for origin in origins:
            parsed = urlsplit(origin)
            is_local = parsed.hostname in {"localhost", "127.0.0.1", "::1"}
            if (
                origin == "*"
                or not parsed.hostname
                or parsed.path not in {"", "/"}
                or parsed.query
                or parsed.fragment
                or (
                    parsed.scheme != "https"
                    and not (is_local and parsed.scheme == "http")
                )
            ):
                raise ValueError("API_CORS_ORIGINS contains an unsafe origin")
            validated.append(origin)
        return validated


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
    domain_profile: str = "football-v1"
    google_fact_check_api_key: str | None = None
    rss_feed_urls: str | None = None
    football_feeds_json: str | None = None
    football_pages_json: str | None = None
    primary_source_domains: str | None = None
    reddit_client_id: str | None = None
    reddit_client_secret: str | None = None
    reddit_user_agent: str | None = None
    reddit_subreddits: str | None = None
    reddit_ingestion_enabled: bool = False
    telegram_bot_token: str | None = None
    telegram_chat_id: str | None = None

    model_config = ENV_CONFIG

    @field_validator("supabase_url", "openai_base_url")
    @classmethod
    def validate_service_url(cls, value: str) -> str:
        """Require HTTPS service roots without credentials or query strings."""

        parsed = urlsplit(value)
        is_local = parsed.hostname in {"localhost", "127.0.0.1", "::1"}
        if parsed.scheme != "https" and not (is_local and parsed.scheme == "http"):
            raise ValueError("must use HTTPS (HTTP is allowed only for localhost)")
        if not parsed.hostname or parsed.username or parsed.password or parsed.query:
            raise ValueError(
                "must be a service root URL without credentials or a query"
            )
        return value.rstrip("/")

    @field_validator("supabase_service_key", "newsapi_key")
    @classmethod
    def reject_placeholder_secret(cls, value: str) -> str:
        """Reject empty and example credentials before making a request."""

        normalized = value.strip().lower()
        if not normalized or any(
            marker in normalized
            for marker in ("your-", "your_", "example", "replace-me", "changeme")
        ):
            raise ValueError("contains an empty or placeholder credential")
        return value.strip()

    @field_validator(
        "openai_api_key",
        "google_fact_check_api_key",
        "reddit_client_id",
        "reddit_client_secret",
    )
    @classmethod
    def reject_optional_placeholder(cls, value: str | None) -> str | None:
        if not value:
            return None
        return cls.reject_placeholder_secret(value)

    @field_validator("domain_profile")
    @classmethod
    def validate_domain_profile(cls, value: str) -> str:
        get_domain_profile(value)
        return value

    @property
    def configured_rss_feeds(self) -> list[str]:
        """Return comma/newline-separated feed URLs from the environment."""

        if not self.rss_feed_urls:
            return []
        return [
            value.strip()
            for value in self.rss_feed_urls.replace("\n", ",").split(",")
            if value.strip()
        ]

    @property
    def configured_primary_domains(self) -> list[str]:
        if not self.primary_source_domains:
            return []
        return [
            value.strip().casefold().removeprefix("www.")
            for value in self.primary_source_domains.replace("\n", ",").split(",")
            if value.strip()
        ]

    @property
    def configured_football_feeds(self):
        """Return validated categorized football feed definitions."""

        from biasradar.ingestion.rss import FeedSource

        if not self.football_feeds_json:
            return []
        payload = json.loads(self.football_feeds_json)
        if not isinstance(payload, list):
            raise ValueError("FOOTBALL_FEEDS_JSON must contain a JSON array")
        return [FeedSource.model_validate(value) for value in payload]

    @property
    def configured_football_pages(self):
        """Return validated opt-in official, transcript, and interview pages."""

        from biasradar.ingestion.curated_pages import CuratedPageSource

        if not self.football_pages_json:
            return []
        payload = json.loads(self.football_pages_json)
        if not isinstance(payload, list):
            raise ValueError("FOOTBALL_PAGES_JSON must contain a JSON array")
        return [CuratedPageSource.model_validate(value) for value in payload]

    @property
    def configured_reddit_subreddits(self) -> list[str]:
        if not self.reddit_subreddits:
            return []
        return [
            value.strip().removeprefix("r/")
            for value in self.reddit_subreddits.replace("\n", ",").split(",")
            if value.strip()
        ]

    @property
    def reddit_is_configured(self) -> bool:
        if not self.reddit_ingestion_enabled:
            return False
        values = (
            self.reddit_client_id,
            self.reddit_client_secret,
            self.reddit_user_agent,
        )
        if any(values) and not all(values):
            raise ValueError(
                "REDDIT_CLIENT_ID, REDDIT_CLIENT_SECRET, and REDDIT_USER_AGENT "
                "must be configured together"
            )
        return all(values)


@lru_cache
def get_settings() -> Settings:
    """Return the validated application settings."""

    return Settings()  # type: ignore[call-arg]


@lru_cache
def get_api_settings() -> APISettings:
    """Return validated read-API settings."""

    return APISettings()  # type: ignore[call-arg]
