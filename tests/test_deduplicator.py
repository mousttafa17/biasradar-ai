from datetime import UTC, datetime, timedelta

from biasradar.deduplicator import (
    DeduplicationItem,
    canonicalize_url,
    deduplicate_items,
    normalized_domain,
)


def _item(
    item_id: str,
    text: str,
    *,
    hours: int = 0,
    url: str | None = None,
) -> DeduplicationItem:
    return DeduplicationItem(
        raw_item_id=item_id,
        url=url or f"https://www.example.com/{item_id}",
        source_name=" Example   News ",
        title=f"Title {item_id}",
        cleaned_text=text,
        published_at=datetime(2026, 1, 1, tzinfo=UTC) + timedelta(hours=hours),
    )


def test_url_canonicalization_removes_tracking_and_normalizes_host() -> None:
    url = "HTTPS://WWW.Example.COM:443/story/?utm_source=x&b=2&a=1#section"

    assert canonicalize_url(url) == "https://www.example.com/story?a=1&b=2"
    assert normalized_domain(url) == "example.com"


def test_exact_duplicates_are_grouped_and_earliest_item_is_origin() -> None:
    text = "one two three four five six seven eight nine ten"
    result = deduplicate_items(
        [_item("later", text, hours=2), _item("first", text, hours=1)]
    )
    by_id = {item.raw_item_id: item for item in result.items}

    assert result.total_items == 2
    assert result.independent_content_groups == 1
    assert result.syndicated_items == 1
    assert result.exact_duplicate_groups == 1
    assert by_id["first"].is_group_origin is True
    assert by_id["later"].is_group_origin is False
    assert by_id["first"].content_group_id == by_id["later"].content_group_id


def test_near_duplicates_group_but_unrelated_content_remains_independent() -> None:
    base = "alpha beta gamma delta epsilon zeta eta theta iota kappa lambda mu"
    near = f"{base} changed"
    unrelated = "football referee stadium crowd whistle tournament final result"
    result = deduplicate_items(
        [_item("base", base), _item("near", near), _item("other", unrelated)]
    )
    by_id = {item.raw_item_id: item for item in result.items}

    assert result.independent_content_groups == 2
    assert result.near_duplicate_groups == 1
    assert by_id["base"].content_group_id == by_id["near"].content_group_id
    assert by_id["other"].content_group_id != by_id["base"].content_group_id
    assert len(result.items) == 3
