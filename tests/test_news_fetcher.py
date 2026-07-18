import httpx

from biasradar.news_fetcher import NewsFetcher


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
    monkeypatch.setattr(httpx, "get", lambda *args, **kwargs: response)

    articles = NewsFetcher("test-key").fetch("test query", limit=1)

    assert len(articles) == 1
    assert articles[0].source_name == "Example News"
    assert articles[0].raw_text == "Story summary"
    assert articles[0].published_at is not None
    assert articles[0].published_at.isoformat() == "2026-07-18T10:00:00+00:00"
