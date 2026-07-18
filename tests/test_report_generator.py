from datetime import UTC, datetime

import pytest

from biasradar.report_generator import (
    AnalyzedItem,
    ClaimCheckItem,
    ClaimItem,
    aggregate_topic,
    cluster_repeated_claims,
)


def _item(
    item_id: str,
    source: str,
    stance: str,
    confidence: float = 1.0,
    loaded: float = 0.5,
    one_sided: float = 0.5,
    evidence: float = 0.5,
    emotionality: float = 0.5,
    content_group_id: str | None = None,
) -> AnalyzedItem:
    return AnalyzedItem(
        raw_item_id=item_id,
        analysis_id=f"analysis-{item_id}",
        url=f"https://example.com/{item_id}",
        content_group_id=content_group_id,
        source_name=source,
        stance=stance,
        stance_confidence=confidence,
        loaded_language_score=loaded,
        one_sidedness_score=one_sided,
        evidence_quality_score=evidence,
        emotionality_score=emotionality,
    )


def test_aggregation_calculates_direction_and_bias_deterministically() -> None:
    now = datetime.now(UTC)
    report = aggregate_topic(
        topic_id="topic-1",
        topic_name="Example",
        period_start=now,
        period_end=now,
        items=[
            _item("1", "Source A", "pro_subject", 0.8, 0.4, 0.4, 0.8, 0.2),
            _item("2", "Source A", "pro_subject", 0.6, 0.4, 0.4, 0.8, 0.2),
            _item("3", "Source B", "anti_subject", 0.9, 0.8, 0.8, 0.2, 0.6),
        ],
    )

    assert report.directional_pro_percent == 60.9
    assert report.directional_anti_percent == 39.1
    assert report.overall_bias_score == -9.0
    assert report.source_count == 2
    assert report.confidence_level == "low"
    assert sum(report.stance_distribution.values()) == pytest.approx(100.0)


def test_each_content_group_has_equal_total_stance_influence() -> None:
    now = datetime.now(UTC)
    items = [
        _item(
            str(index),
            f"Syndicator {index}",
            "pro_subject",
            content_group_id="group-pro",
        )
        for index in range(10)
    ]
    items.append(
        _item(
            "anti",
            "Independent Source",
            "anti_subject",
            content_group_id="group-anti",
        )
    )

    report = aggregate_topic(
        topic_id="topic-1",
        topic_name="Example",
        period_start=now,
        period_end=now,
        items=items,
    )

    assert report.directional_pro_percent == 50.0
    assert report.directional_anti_percent == 50.0
    assert report.independent_content_groups == 2
    assert report.syndicated_items == 9


def test_each_channel_has_equal_total_stance_influence() -> None:
    now = datetime.now(UTC)
    news_items = [
        _item(str(index), f"News {index}", "pro_subject") for index in range(10)
    ]
    rss_item = _item("rss", "RSS Source", "anti_subject")
    rss_item.source_type = "rss"

    report = aggregate_topic(
        topic_id="topic-1",
        topic_name="Example",
        period_start=now,
        period_end=now,
        items=[*news_items, rss_item],
    )

    assert report.directional_pro_percent == 50.0
    assert report.directional_anti_percent == 50.0


def test_empty_sample_does_not_produce_a_report() -> None:
    now = datetime.now(UTC)

    with pytest.raises(ValueError, match="no analyzed items"):
        aggregate_topic(
            topic_id="topic-1",
            topic_name="Example",
            period_start=now,
            period_end=now,
            items=[],
        )


def test_non_directional_sample_does_not_claim_a_bias_direction() -> None:
    now = datetime.now(UTC)
    report = aggregate_topic(
        topic_id="topic-1",
        topic_name="Example",
        period_start=now,
        period_end=now,
        items=[_item("1", "Source A", "mixed")],
    )

    assert report.directional_pro_percent is None
    assert "not available" in report.report_text
    assert "0.0/100 toward" not in report.report_text


def test_repeated_claims_cluster_across_distinct_articles() -> None:
    claims = [
        ClaimItem(
            claim_id="claim-1",
            analysis_id="analysis-1",
            raw_item_id="item-1",
            source_name="Source A",
            claim_text="Argentina received a penalty after VAR review",
            claim_type="verifiable_fact",
            checkability="checkable",
            importance_score=0.8,
        ),
        ClaimItem(
            claim_id="claim-2",
            analysis_id="analysis-2",
            raw_item_id="item-2",
            source_name="Source B",
            claim_text="VAR review gave Argentina a penalty",
            claim_type="verifiable_fact",
            checkability="checkable",
            importance_score=0.9,
        ),
    ]

    clusters = cluster_repeated_claims(
        claims,
        checks=[
            ClaimCheckItem(
                claim_id="claim-2",
                verdict="contradicted",
                confidence=0.9,
                evidence_summary="Publisher: False",
                evidence_urls=["https://factcheck.example/review"],
            )
        ],
    )

    assert len(clusters) == 1
    assert clusters[0].item_count == 2
    assert clusters[0].source_count == 2
    assert clusters[0].representative_claim == claims[1].claim_text
    assert clusters[0].fact_check_verdict == "contradicted"
    assert clusters[0].evidence_urls == ["https://factcheck.example/review"]


def test_claims_repeated_only_within_one_article_do_not_cluster() -> None:
    claims = [
        ClaimItem(
            claim_id=f"claim-{index}",
            analysis_id="analysis-1",
            raw_item_id="item-1",
            source_name="Source A",
            claim_text="Argentina received a penalty after VAR review",
            claim_type="verifiable_fact",
            checkability="checkable",
            importance_score=0.8,
        )
        for index in range(2)
    ]

    assert cluster_repeated_claims(claims) == []


def test_syndicated_claim_copies_do_not_form_a_repeated_claim_cluster() -> None:
    claims = [
        ClaimItem(
            claim_id=f"claim-{index}",
            analysis_id=f"analysis-{index}",
            raw_item_id=f"item-{index}",
            source_name=f"Source {index}",
            content_group_id="same-syndicated-story",
            claim_text="Argentina received a penalty after VAR review",
            claim_type="verifiable_fact",
            checkability="checkable",
            importance_score=0.8,
        )
        for index in range(2)
    ]

    assert cluster_repeated_claims(claims) == []
