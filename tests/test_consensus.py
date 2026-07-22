from biasradar.analysis.consensus import (
    ConsensusGroup,
    ConsensusOpinion,
    ConsensusStatus,
    OpinionPosition,
    SourceRole,
    build_consensus,
    source_quality,
)


def _opinion(
    speaker: str,
    position: OpinionPosition,
    *,
    role: SourceRole = SourceRole.FORMER_REFEREE,
    direct: bool = True,
    article_id: str | None = None,
) -> ConsensusOpinion:
    return ConsensusOpinion(
        speaker=speaker,
        role=role,
        stated_credential="Former international referee",
        affiliation="Independent",
        is_direct_source=direct,
        opinion_summary="The decision was incorrect.",
        direct_quote="That was not a penalty.",
        incident_ref="72nd-minute penalty decision",
        position=position,
        position_confidence=0.9,
        article_id=article_id or speaker,
        source_name="Example Sports",
    )


def test_consensus_deduplicates_a_speaker_repeated_by_multiple_outlets() -> None:
    opinions = [
        _opinion("Referee One", OpinionPosition.DISAGREES_WITH_DECISION),
        _opinion("Referee Two", OpinionPosition.DISAGREES_WITH_DECISION),
        _opinion("Referee Three", OpinionPosition.DISAGREES_WITH_DECISION),
        _opinion("Referee Four", OpinionPosition.AGREES_WITH_DECISION),
        _opinion(
            "Referee One",
            OpinionPosition.DISAGREES_WITH_DECISION,
            direct=False,
            article_id="syndicated-copy",
        ),
    ]

    result = build_consensus(opinions)[0]

    assert result.source_group is ConsensusGroup.OFFICIATING_EXPERT
    assert result.status is ConsensusStatus.MODERATE
    assert result.leading_position is OpinionPosition.DISAGREES_WITH_DECISION
    assert result.leading_percent == 75.0
    assert result.extracted_opinions == 5
    assert result.independent_opinions == 4
    assert result.duplicate_mentions == 1


def test_consensus_refuses_to_publish_below_group_threshold() -> None:
    result = build_consensus(
        [
            _opinion("Referee One", OpinionPosition.DISAGREES_WITH_DECISION),
            _opinion("Referee Two", OpinionPosition.DISAGREES_WITH_DECISION),
        ]
    )[0]

    assert result.status is ConsensusStatus.INSUFFICIENT
    assert "Not enough independent" in result.summary


def test_source_quality_uses_only_observable_provenance_fields() -> None:
    expert = _opinion("Referee One", OpinionPosition.AGREES_WITH_DECISION)
    fan = _opinion(
        "Fan One",
        OpinionPosition.AGREES_WITH_DECISION,
        role=SourceRole.FAN,
        direct=False,
    )
    fan.stated_credential = None
    fan.direct_quote = None

    assert source_quality(expert) == 1.0
    assert source_quality(fan) == 0.2


def test_similar_incident_wording_is_clustered_before_consensus() -> None:
    opinions = [
        _opinion("Referee One", OpinionPosition.DISAGREES_WITH_DECISION),
        _opinion("Referee Two", OpinionPosition.DISAGREES_WITH_DECISION),
        _opinion("Referee Three", OpinionPosition.DISAGREES_WITH_DECISION),
    ]
    opinions[1].incident_ref = "penalty decision in the 72nd minute"

    results = build_consensus(opinions)

    assert len(results) == 1
    assert results[0].independent_opinions == 3
