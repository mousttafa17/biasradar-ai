import pytest

from biasradar.ingestion.reddit import RedditAPIError, RedditFetcher


class Response:
    def __init__(self, payload, failing: bool = False) -> None:
        self.payload = payload
        self.failing = failing

    def raise_for_status(self) -> None:
        if self.failing:
            raise RuntimeError("request failed with secret URL")

    def json(self):
        return self.payload


def test_reddit_fetcher_uses_oauth_and_normalizes_posts(monkeypatch) -> None:
    monkeypatch.setattr(
        "httpx.post",
        lambda *args, **kwargs: Response(
            {"access_token": "access-token", "expires_in": 3600}
        ),
    )
    monkeypatch.setattr(
        "httpx.get",
        lambda *args, **kwargs: Response(
            {
                "data": {
                    "children": [
                        {
                            "data": {
                                "name": "t3_abc",
                                "title": "Argentina VAR controversy",
                                "permalink": "/r/soccer/comments/abc/story/",
                                "subreddit_name_prefixed": "r/soccer",
                                "author": "fan-account",
                                "created_utc": 1_700_000_000,
                                "selftext": "The decision divided supporters.",
                                "score": 120,
                                "num_comments": 42,
                                "upvote_ratio": 0.8,
                            }
                        }
                    ]
                }
            }
        ),
    )

    item = RedditFetcher(
        "client-id",
        "client-secret",
        "BiasRadar/0.1 by u/example",
        ["soccer"],
    ).fetch("Argentina VAR")[0]

    assert item.source_type == "social"
    assert item.provider == "reddit_api"
    assert item.external_id == "t3_abc"
    assert item.engagement_data["comments"] == 42
    assert str(item.url).startswith("https://www.reddit.com/r/soccer/")


def test_reddit_errors_do_not_expose_credentials(monkeypatch) -> None:
    monkeypatch.setattr(
        "httpx.post", lambda *args, **kwargs: Response({}, failing=True)
    )
    fetcher = RedditFetcher(
        "client-id",
        "super-secret",
        "BiasRadar/0.1 by u/example",
    )

    with pytest.raises(RedditAPIError) as captured:
        fetcher.fetch("Argentina")

    assert "super-secret" not in str(captured.value)
