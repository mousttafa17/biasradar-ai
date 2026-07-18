import httpx

from biasradar.fact_checker import (
    FactCheckVerdict,
    GoogleFactChecker,
    interpret_search_results,
    rating_verdict,
)


def test_no_relevant_match_is_unverified_not_false() -> None:
    result = interpret_search_results(
        "Argentina received a penalty after VAR review",
        [{"text": "An unrelated claim about the economy", "claimReview": []}],
    )

    assert result.verdict is FactCheckVerdict.UNVERIFIED
    assert result.evidence_urls == []
    assert "does not mean" in result.notes


def test_relevant_false_review_is_contradicted() -> None:
    result = interpret_search_results(
        "Argentina received a penalty after VAR review",
        [
            {
                "text": "Argentina received a penalty following a VAR review",
                "claimReview": [
                    {
                        "publisher": {"name": "Example Fact Check"},
                        "url": "https://factcheck.example/review",
                        "textualRating": "False",
                    }
                ],
            }
        ],
    )

    assert result.verdict is FactCheckVerdict.CONTRADICTED
    assert result.evidence_urls == ["https://factcheck.example/review"]


def test_conflicting_reviews_require_human_review() -> None:
    reviews = [
        {
            "publisher": {"name": "Publisher A"},
            "url": "https://a.example/review",
            "textualRating": "True",
        },
        {
            "publisher": {"name": "Publisher B"},
            "url": "https://b.example/review",
            "textualRating": "False",
        },
    ]
    result = interpret_search_results(
        "Argentina received a penalty after VAR review",
        [
            {
                "text": "Argentina received a penalty following a VAR review",
                "claimReview": reviews,
            }
        ],
    )

    assert result.verdict is FactCheckVerdict.NEEDS_HUMAN_REVIEW


def test_mostly_false_maps_to_misleading_before_false() -> None:
    assert rating_verdict("Mostly false") is FactCheckVerdict.MISLEADING


def test_google_key_is_sent_in_header_not_query(monkeypatch) -> None:
    response = httpx.Response(
        200,
        request=httpx.Request("GET", "https://factchecktools.googleapis.com"),
        json={"claims": []},
    )
    captured = {}

    def fake_get(*args, **kwargs):
        captured.update(kwargs)
        return response

    monkeypatch.setattr(httpx, "get", fake_get)

    result = GoogleFactChecker("secret-key").check("Example checkable claim")

    assert result.verdict is FactCheckVerdict.UNVERIFIED
    assert "key" not in captured["params"]
    assert captured["headers"] == {"X-Goog-Api-Key": "secret-key"}
