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


def test_broader_football_sources_are_validated_from_json() -> None:
    settings = Settings(
        supabase_url="https://project.supabase.co",
        supabase_service_key="real-secret",
        newsapi_key="real-news-key",
        football_feeds_json=(
            '[{"url":"https://fifa.example/feed","source_type":"official",'
            '"provider":"fifa_feed"}]'
        ),
        football_pages_json=(
            '[{"url":"https://club.example/interview","title":"Interview",'
            '"source_name":"Example FC","source_type":"interview"}]'
        ),
        reddit_client_id="client-id",
        reddit_client_secret="client-secret",
        reddit_user_agent="BiasRadar/0.1 by u/example",
        reddit_subreddits="soccer, r/football",
        reddit_ingestion_enabled=True,
    )

    assert settings.configured_football_feeds[0].source_type == "official"
    assert settings.configured_football_pages[0].source_type == "interview"
    assert settings.configured_reddit_subreddits == ["soccer", "football"]
    assert settings.reddit_is_configured is True
