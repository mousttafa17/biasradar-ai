import pytest
from pydantic import ValidationError

from biasradar.config import APISettings, Settings


def test_placeholder_credentials_are_rejected() -> None:
    with pytest.raises(ValidationError):
        Settings(
            supabase_url="https://project.supabase.co",
            supabase_service_key="your-service-key",
            newsapi_key="your-newsapi-key",
        )


def test_non_https_remote_service_is_rejected() -> None:
    with pytest.raises(ValidationError):
        Settings(
            supabase_url="http://project.supabase.co",
            supabase_service_key="real-secret",
            newsapi_key="real-news-key",
        )


def test_rss_feed_configuration_accepts_commas_and_newlines() -> None:
    settings = Settings(
        supabase_url="https://project.supabase.co",
        supabase_service_key="real-secret",
        newsapi_key="real-news-key",
        rss_feed_urls="https://a.example/feed,\nhttps://b.example/atom",
    )

    assert settings.configured_rss_feeds == [
        "https://a.example/feed",
        "https://b.example/atom",
    ]


def test_api_cors_rejects_wildcards() -> None:
    settings = APISettings(
        supabase_url="https://project.supabase.co",
        supabase_service_key="real-secret",
        api_cors_origins="*",
    )

    with pytest.raises(ValueError, match="unsafe origin"):
        _ = settings.cors_origins
