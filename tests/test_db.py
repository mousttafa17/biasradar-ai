from types import SimpleNamespace

from postgrest.exceptions import APIError

from biasradar.ingestion.newsapi import NewsArticle
from biasradar.persistence.repository import (
    article_row,
    is_duplicate_error,
    save_analysis,
)


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


def test_save_analysis_forwards_domain_payload_to_atomic_rpc() -> None:
    captured: dict[str, object] = {}

    class Query:
        def execute(self) -> SimpleNamespace:
            return SimpleNamespace(data="analysis-id")

    class Client:
        def rpc(self, name: str, payload: dict[str, object]) -> Query:
            captured["name"] = name
            captured["payload"] = payload
            return Query()

    class Analysis:
        short_summary = "Summary"
        claims: list[object] = []

        def model_dump(self, **_: object) -> dict[str, object]:
            return {
                "domain_profile": "football-v1",
                "domain_analysis": {"primary_stance": "criticizes_referee"},
                "stance": "anti_subject",
            }

    save_analysis(
        Client(),  # type: ignore[arg-type]
        raw_item_id="raw-id",
        analysis=Analysis(),  # type: ignore[arg-type]
        cleaned_text="Cleaned",
        model_id="model-id",
        prompt_version="prompt-v1",
    )

    rpc_payload = captured["payload"]
    assert isinstance(rpc_payload, dict)
    persisted = rpc_payload["p_analysis"]
    assert isinstance(persisted, dict)
    assert persisted["domain_profile"] == "football-v1"
    assert persisted["domain_analysis"] == {"primary_stance": "criticizes_referee"}
