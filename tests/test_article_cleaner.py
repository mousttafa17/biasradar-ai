from biasradar.article_cleaner import ArticleCleaner
from biasradar.security import UnsafeURLError


def test_cleaner_extracts_main_text(monkeypatch) -> None:
    cleaner = ArticleCleaner()
    monkeypatch.setattr(
        cleaner,
        "_download",
        lambda url: (
            "<html><body><article><p>Main article text.</p></article></body></html>"
        ),
    )

    result = cleaner.clean("https://example.com/story", "Fallback")

    assert result == "Main article text."


def test_cleaner_uses_fallback_on_http_error(monkeypatch) -> None:
    def fail(url: str) -> str:
        raise UnsafeURLError("blocked")

    cleaner = ArticleCleaner()
    monkeypatch.setattr(cleaner, "_download", fail)

    assert cleaner.clean("https://example.com/story", "Fallback") == "Fallback"
