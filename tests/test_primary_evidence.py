from datetime import UTC, datetime

from biasradar.evidence.primary_sources import discover_primary_evidence
from biasradar.evidence.verifier import (
    EvidenceAssessment,
    EvidenceRelation,
    SourceRole,
    decide_atomic_verdict,
)
from biasradar.ingestion import IngestedItem


class FakeSearcher:
    def fetch(self, query, limit, domains=None):
        assert domains == ["official.example"]
        return [
            IngestedItem(
                source_name="Official Example",
                source_type="news",
                provider="test",
                title="Official decision",
                url="https://official.example/decision?utm_source=test",
                published_at=datetime(2026, 7, 19, tzinfo=UTC),
                description="Official decision text.",
            )
        ]


class FakeCleaner:
    def clean(self, url, fallback=None):
        return "The official record directly confirms the decision."


class FakeVerifier:
    def assess(self, claim, documents):
        return decide_atomic_verdict(
            claim,
            [
                EvidenceAssessment(
                    document_index=0,
                    relation=EvidenceRelation.SUPPORTS,
                    source_role=SourceRole.PRIMARY_RECORD,
                    relevance_score=0.95,
                    excerpt="The official record confirms the decision.",
                    reasoning="The record directly addresses the claim.",
                )
            ],
        )


def test_primary_discovery_builds_auditable_candidate() -> None:
    candidates = discover_primary_evidence(
        claim_text="The authority issued a decision.",
        domains=["official.example"],
        searcher=FakeSearcher(),
        cleaner=FakeCleaner(),
        verifier=FakeVerifier(),
    )

    assert len(candidates) == 1
    assert candidates[0].canonical_url == "https://official.example/decision"
    assert candidates[0].source_domain == "official.example"
    assert len(candidates[0].content_hash) == 64
    assert candidates[0].assessment.source_role is SourceRole.PRIMARY_RECORD


def test_primary_discovery_requires_an_explicit_domain_allow_list() -> None:
    try:
        discover_primary_evidence(
            claim_text="Claim",
            domains=[],
            searcher=FakeSearcher(),
            cleaner=FakeCleaner(),
            verifier=FakeVerifier(),
        )
    except ValueError as error:
        assert "official source domain" in str(error)
    else:
        raise AssertionError("expected a domain validation error")
