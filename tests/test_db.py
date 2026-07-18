from postgrest.exceptions import APIError

from biasradar.db import article_row, is_duplicate_error
from biasradar.news_fetcher import NewsArticle


def test_article_row_matches_raw_items_shape() -> None:
    article = NewsArticle(
        source_name="Example News",
        title="Example title",
        url="https://example.com/story",
        description="Example description",
    )

    row = article_row(article, "topic-123")

    assert row == {
        "topic_id": "topic-123",
        "source_name": "Example News",
        "source_type": "news",
        "ingestion_provider": "unknown",
        "title": "Example title",
        "url": "https://example.com/story",
        "author": None,
        "published_at": None,
        "raw_text": "Example description",
        "engagement_data": {},
        "language": "en",
        "status": "new",
    }


def test_postgres_unique_violation_is_duplicate() -> None:
    error = APIError(
        {"code": "23505", "message": "duplicate", "hint": None, "details": None}
    )

    assert is_duplicate_error(error) is True
