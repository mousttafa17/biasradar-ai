from biasradar.ingestion.curated_pages import CuratedPageFetcher, CuratedPageSource


class Cleaner:
    def clean(self, url: str) -> str:
        return "Argentina penalty interview with the match referee"


def test_curated_page_fetcher_normalizes_configured_transcript() -> None:
    fetcher = CuratedPageFetcher(
        [
            CuratedPageSource(
                url="https://official.example/transcript",
                title="Post-match referee transcript",
                source_name="Competition organizer",
                source_type="transcript",
                content_license="Official publication",
                attribution="Competition organizer",
            )
        ],
        cleaner=Cleaner(),  # type: ignore[arg-type]
    )

    item = fetcher.fetch("Argentina penalty")[0]

    assert item.source_type == "transcript"
    assert item.provider == "curated_web"
    assert item.content_license == "Official publication"
    assert item.raw_text == "Argentina penalty interview with the match referee"


def test_curated_page_fetcher_filters_unrelated_pages() -> None:
    fetcher = CuratedPageFetcher(
        [
            CuratedPageSource(
                url="https://official.example/transcript",
                title="Post-match transcript",
                source_name="Competition organizer",
                source_type="transcript",
            )
        ],
        cleaner=Cleaner(),  # type: ignore[arg-type]
    )

    assert fetcher.fetch("basketball transfer") == []
