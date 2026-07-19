import httpx

from biasradar.ingestion.newsapi import NewsAPIError, NewsFetcher


def test_fetch_normalizes_newsapi_articles(monkeypatch) -> None:
    request = httpx.Request("GET", "https://newsapi.org/v2/everything")
    response = httpx.Response(
        200,
        request=request,
        json={
            "status": "ok",
            "articles": [
                {
                    "source": {"name": "Example News"},
                    "author": "Reporter",
                    "title": "A recent story",
                    "description": "Story summary",
                    "url": "https://example.com/story",
                    "publishedAt": "2026-07-18T10:00:00Z",
                    "content": "Story content",
                }
            ],
        },
    )
    request_arguments = {}

    def fake_get(*args, **kwargs):
        request_arguments.update(kwargs)
        return response

    monkeypatch.setattr(httpx, "get", fake_get)

    articles = NewsFetcher("test-key").fetch("test query", limit=1)

    assert len(articles) == 1
    assert articles[0].source_name == "Example News"
    assert articles[0].raw_text == "Story summary"
    assert articles[0].published_at is not None
    assert articles[0].published_at.isoformat() == "2026-07-18T10:00:00+00:00"
    assert "apiKey" not in request_arguments["params"]
    assert request_arguments["headers"] == {"X-Api-Key": "test-key"}


def test_newsapi_error_never_contains_key_or_url(monkeypatch) -> None:
    response = httpx.Response(
        401,
        request=httpx.Request("GET", "https://newsapi.org/v2/everything"),
        json={"status": "error", "message": "API key super-secret rejected"},
    )
    monkeypatch.setattr(httpx, "get", lambda *args, **kwargs: response)

    try:
        NewsFetcher("super-secret").fetch("topic")
    except NewsAPIError as error:
        message = str(error)
    else:
        raise AssertionError("expected NewsAPIError")

    assert "super-secret" not in message
    assert "https://" not in message
    assert message == "NewsAPI returned HTTP 401: API key [redacted] rejected"
