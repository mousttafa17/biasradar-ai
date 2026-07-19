import pytest

from biasradar.analysis.topic_viability import (
    CoverageSignals,
    TopicViabilityAssessment,
    ViabilityStatus,
    coverage_signals,
    enforce_measurable_gates,
    normalize_topic_query,
    topic_query_hash,
    topic_similarity,
)
from biasradar.ingestion import IngestedItem


def _assessment(status: str = "accepted") -> TopicViabilityAssessment:
    return TopicViabilityAssessment.model_validate(
        {
            "status": status,
            "confidence": 0.8,
            "definition": {
                "canonical_name": "Media framing of nuclear energy policy",
                "subject": "nuclear energy policy",
                "supporting_frame": "Nuclear energy is a useful low-carbon option",
                "opposing_frame": "Nuclear energy creates unacceptable risks",
                "keywords": ["nuclear energy", "policy", "safety"],
                "exclusions": ["nuclear weapons"],
                "language": "en",
                "geographic_scope": "international",
                "timeframe_days": 90,
            },
            "reasons": ["The subject and competing frames are identifiable."],
            "clarification_questions": [],
        }
    )


def test_topic_query_normalization_and_hash_are_stable() -> None:
    first = normalize_topic_query("  Media   framing of nuclear energy  ")
    second = normalize_topic_query("Media framing of nuclear energy")

    assert first == second
    assert topic_query_hash(first) == topic_query_hash(second)
    with pytest.raises(ValueError, match="10 to 500"):
        normalize_topic_query("short")


def test_coverage_signals_count_independent_sources_and_channels() -> None:
    items = [
        IngestedItem(
            source_name=f"Source {index}",
            source_type="news" if index < 3 else "rss",
            provider="test",
            title=f"Story {index}",
            url=f"https://example.com/{index}",
        )
        for index in range(5)
    ]

    signals = coverage_signals(items)

    assert signals.item_count == 5
    assert signals.independent_source_count == 5
    assert signals.channel_counts == {"news": 3, "rss": 2}
    assert signals.sufficient is True


def test_measurable_coverage_can_block_model_acceptance() -> None:
    signals = CoverageSignals(
        item_count=4,
        independent_source_count=2,
        channel_counts={"news": 4},
    )

    result = enforce_measurable_gates(_assessment(), signals)

    assert result.status is ViabilityStatus.INSUFFICIENT_COVERAGE


def test_duplicate_detection_overrides_model_acceptance() -> None:
    signals = CoverageSignals(
        item_count=10,
        independent_source_count=5,
        channel_counts={"news": 10},
    )

    result = enforce_measurable_gates(
        _assessment(), signals, duplicate_topic_id="existing-topic"
    )

    assert result.status is ViabilityStatus.DUPLICATE_TOPIC
    assert (
        topic_similarity(
            "Media framing of nuclear energy policy",
            "Nuclear energy policy media framing",
        )
        > 0.8
    )
