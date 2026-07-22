from biasradar.config import Settings
from biasradar.ingestion.models import IngestedItem
from biasradar.workflows import content_ingestion


class Provider:
    def __init__(self, url: str, failing: bool = False) -> None:
        self.url = url
        self.failing = failing

    def fetch(self, query: str, limit: int = 5):
        if self.failing:
            raise RuntimeError("provider unavailable")
        return [
            IngestedItem(
                title=query,
                url=self.url,
                source_name="Source",
                provider="test",
            )
        ]


def test_collection_keeps_partial_results_and_deduplicates_urls(monkeypatch) -> None:
    settings = Settings(
        supabase_url="https://project.supabase.co",
        supabase_service_key="real-secret",
        newsapi_key="real-news-key",
    )
    monkeypatch.setattr(
        content_ingestion,
        "configured_content_providers",
        lambda settings: [
            ("First", Provider("https://example.com/story")),
            ("Duplicate", Provider("https://example.com/story")),
            ("Broken", Provider("https://example.com/broken", failing=True)),
        ],
    )

    batch = content_ingestion.collect_topic_content(settings, "VAR", 5)

    assert len(batch.items) == 1
    assert batch.successful_providers == 2
    assert batch.provider_errors == ["Broken ingestion failed"]
