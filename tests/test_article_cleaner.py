import httpx

from biasradar.article_cleaner import ArticleCleaner


def test_cleaner_extracts_main_text(monkeypatch) -> None:
    response = httpx.Response(
        200,
        request=httpx.Request("GET", "https://example.com/story"),
        text="<html><body><article><p>Main article text.</p></article></body></html>",
    )
    monkeypatch.setattr(httpx, "get", lambda *args, **kwargs: response)

    result = ArticleCleaner().clean("https://example.com/story", "Fallback")

    assert result == "Main article text."


def test_cleaner_uses_fallback_on_http_error(monkeypatch) -> None:
    def fail(*args, **kwargs):
        raise httpx.HTTPStatusError(
            "blocked",
            request=httpx.Request("GET", "https://example.com/story"),
            response=httpx.Response(403),
        )

    monkeypatch.setattr(httpx, "get", fail)

    assert ArticleCleaner().clean("https://example.com/story", "Fallback") == "Fallback"
