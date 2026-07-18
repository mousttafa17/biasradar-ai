from biasradar.evidence_verifier import (
    EvidenceAssessment,
    EvidenceDocument,
    EvidenceRelation,
    SourceRole,
    combine_atomic_verdicts,
    decide_atomic_verdict,
)
from biasradar.fact_checker import FactCheckVerdict


def _assessment(
    relation: EvidenceRelation,
    role: SourceRole,
    relevance: float = 0.9,
) -> EvidenceAssessment:
    return EvidenceAssessment(
        document_index=0,
        relation=relation,
        source_role=role,
        relevance_score=relevance,
        excerpt="Directly relevant evidence excerpt.",
        reasoning="The excerpt directly addresses the atomic claim.",
    )


def test_strong_primary_evidence_supports_atomic_claim() -> None:
    result = decide_atomic_verdict(
        "FIFA appointed the referee.",
        [
            _assessment(
                EvidenceRelation.SUPPORTS,
                SourceRole.PRIMARY_RECORD,
            )
        ],
    )

    assert result.verdict is FactCheckVerdict.SUPPORTED
    assert result.confidence > 0.7


def test_repeated_reporting_alone_does_not_verify_claim() -> None:
    result = decide_atomic_verdict(
        "FIFA appointed the referee.",
        [
            _assessment(EvidenceRelation.SUPPORTS, SourceRole.REPETITION)
            for _ in range(5)
        ],
    )

    assert result.verdict is FactCheckVerdict.UNVERIFIED


def test_conflicting_strong_evidence_requires_human_review() -> None:
    result = decide_atomic_verdict(
        "FIFA appointed the referee.",
        [
            _assessment(EvidenceRelation.SUPPORTS, SourceRole.PRIMARY_RECORD),
            _assessment(EvidenceRelation.CONTRADICTS, SourceRole.PRIMARY_RECORD),
        ],
    )

    assert result.verdict is FactCheckVerdict.NEEDS_HUMAN_REVIEW


def test_compound_claim_is_not_supported_when_one_atom_is_unverified() -> None:
    supported = decide_atomic_verdict(
        "FIFA appointed the referee.",
        [_assessment(EvidenceRelation.SUPPORTS, SourceRole.PRIMARY_RECORD)],
    )
    unverified = decide_atomic_verdict("The appointment was secret.", [])
    document = EvidenceDocument(
        url="https://example.com/evidence",
        title="Appointment announcement",
        publisher="Example",
        text="FIFA appointed the referee.",
    )

    result = combine_atomic_verdicts(
        "FIFA appointed the referee secretly.",
        [supported, unverified],
        [document],
    )

    assert result.verdict is FactCheckVerdict.UNVERIFIED
    assert result.evidence_urls == ["https://example.com/evidence"]
