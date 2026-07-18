"""Evidence retrieval, constrained comparison, and deterministic verdict rules."""

import json
from enum import StrEnum
from pathlib import Path

from openai import APIConnectionError, APIStatusError, OpenAI, RateLimitError
from pydantic import BaseModel, ConfigDict, Field
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from biasradar.fact_checker import FactCheckVerdict

PROMPT_PATH = Path(__file__).parents[2] / "prompts" / "evidence_verifier.txt"
EVIDENCE_METHOD_VERSION = "news-evidence-v1"
MAX_ATOMIC_CLAIMS = 5
MAX_EVIDENCE_DOCUMENTS = 5


class AtomicClaim(BaseModel):
    text: str = Field(min_length=1, max_length=1_000)


class AtomicClaimSet(BaseModel):
    model_config = ConfigDict(extra="forbid")
    atomic_claims: list[AtomicClaim] = Field(min_length=1, max_length=MAX_ATOMIC_CLAIMS)


class EvidenceDocument(BaseModel):
    url: str
    title: str
    publisher: str
    published_at: str | None = None
    text: str = Field(min_length=1, max_length=20_000)


class EvidenceRelation(StrEnum):
    SUPPORTS = "supports"
    CONTRADICTS = "contradicts"
    PARTIALLY_SUPPORTS = "partially_supports"
    PROVIDES_CONTEXT = "provides_context"
    IRRELEVANT = "irrelevant"
    INSUFFICIENT = "insufficient"


class SourceRole(StrEnum):
    PRIMARY_RECORD = "primary_record"
    OFFICIAL_STATEMENT = "official_statement"
    DIRECT_TRANSCRIPT = "direct_transcript"
    INDEPENDENT_SECONDARY = "independent_secondary"
    REPETITION = "repetition"
    UNKNOWN = "unknown"


class EvidenceAssessment(BaseModel):
    model_config = ConfigDict(extra="forbid")
    document_index: int = Field(ge=0)
    relation: EvidenceRelation
    source_role: SourceRole
    relevance_score: float = Field(ge=0, le=1)
    excerpt: str = Field(max_length=2_000)
    reasoning: str = Field(min_length=1, max_length=2_000)


class EvidenceAssessmentSet(BaseModel):
    model_config = ConfigDict(extra="forbid")
    assessments: list[EvidenceAssessment] = Field(max_length=MAX_EVIDENCE_DOCUMENTS)


class AtomicVerification(BaseModel):
    claim: str
    verdict: FactCheckVerdict
    confidence: float = Field(ge=0, le=1)
    assessments: list[EvidenceAssessment]


class EvidenceVerificationResult(BaseModel):
    verdict: FactCheckVerdict
    confidence: float = Field(ge=0, le=1)
    evidence_summary: str
    evidence_urls: list[str] = Field(default_factory=list)
    notes: str
    matched_claim_text: str | None = None
    match_score: float = Field(ge=0, le=1)
    atomic_results: list[AtomicVerification]
    documents: list[EvidenceDocument]
    prior_check: dict[str, object] | None = None


ROLE_WEIGHT = {
    SourceRole.PRIMARY_RECORD: 1.0,
    SourceRole.OFFICIAL_STATEMENT: 0.8,
    SourceRole.DIRECT_TRANSCRIPT: 0.9,
    SourceRole.INDEPENDENT_SECONDARY: 0.55,
    SourceRole.REPETITION: 0.1,
    SourceRole.UNKNOWN: 0.2,
}


def decide_atomic_verdict(
    claim: str, assessments: list[EvidenceAssessment]
) -> AtomicVerification:
    """Convert evidence relationships into a deterministic atomic verdict."""

    useful = [item for item in assessments if item.relevance_score >= 0.55]
    support = sum(
        ROLE_WEIGHT[item.source_role] * item.relevance_score
        for item in useful
        if item.relation is EvidenceRelation.SUPPORTS
    )
    contradiction = sum(
        ROLE_WEIGHT[item.source_role] * item.relevance_score
        for item in useful
        if item.relation is EvidenceRelation.CONTRADICTS
    )
    context = any(
        item.relation
        in {EvidenceRelation.PARTIALLY_SUPPORTS, EvidenceRelation.PROVIDES_CONTEXT}
        for item in useful
    )
    threshold = 0.75
    if support >= threshold and contradiction >= threshold:
        verdict = FactCheckVerdict.NEEDS_HUMAN_REVIEW
        confidence = min(0.8, (support + contradiction) / 4)
    elif contradiction >= threshold:
        verdict = FactCheckVerdict.CONTRADICTED
        confidence = min(0.95, 0.5 + contradiction / 3)
    elif support >= threshold:
        verdict = FactCheckVerdict.SUPPORTED
        confidence = min(0.95, 0.5 + support / 3)
    elif context:
        verdict = FactCheckVerdict.MISLEADING
        confidence = 0.55
    else:
        verdict = FactCheckVerdict.UNVERIFIED
        confidence = 0.3 if useful else 0.2
    return AtomicVerification(
        claim=claim,
        verdict=verdict,
        confidence=round(confidence, 3),
        assessments=assessments,
    )


def combine_atomic_verdicts(
    original_claim: str,
    atomic_results: list[AtomicVerification],
    documents: list[EvidenceDocument],
    prior_check: dict[str, object] | None = None,
) -> EvidenceVerificationResult:
    """Combine atomic decisions without overstating partially verified claims."""

    verdicts = {item.verdict for item in atomic_results}
    if FactCheckVerdict.NEEDS_HUMAN_REVIEW in verdicts or (
        FactCheckVerdict.SUPPORTED in verdicts
        and FactCheckVerdict.CONTRADICTED in verdicts
    ):
        verdict = FactCheckVerdict.NEEDS_HUMAN_REVIEW
    elif FactCheckVerdict.CONTRADICTED in verdicts:
        verdict = FactCheckVerdict.CONTRADICTED
    elif verdicts == {FactCheckVerdict.SUPPORTED}:
        verdict = FactCheckVerdict.SUPPORTED
    elif FactCheckVerdict.MISLEADING in verdicts:
        verdict = FactCheckVerdict.MISLEADING
    else:
        verdict = FactCheckVerdict.UNVERIFIED

    confidence = round(
        sum(item.confidence for item in atomic_results) / len(atomic_results), 3
    )
    supported = sum(
        item.verdict is FactCheckVerdict.SUPPORTED for item in atomic_results
    )
    contradicted = sum(
        item.verdict is FactCheckVerdict.CONTRADICTED for item in atomic_results
    )
    return EvidenceVerificationResult(
        verdict=verdict,
        confidence=confidence,
        evidence_summary=(
            f"Evaluated {len(atomic_results)} atomic assertions against "
            f"{len(documents)} retrieved documents: {supported} supported, "
            f"{contradicted} contradicted."
        ),
        evidence_urls=list(dict.fromkeys(document.url for document in documents)),
        notes=(
            "Automated evidence comparison using retrieved NewsAPI coverage. "
            "Repeated reporting is not equivalent to independent primary evidence; "
            "review excerpts and source roles before consequential use."
        ),
        matched_claim_text=original_claim,
        match_score=max(
            (
                assessment.relevance_score
                for item in atomic_results
                for assessment in item.assessments
            ),
            default=0.0,
        ),
        atomic_results=atomic_results,
        documents=documents,
        prior_check=prior_check,
    )


class EvidenceVerifier:
    """Constrained model client for decomposition and evidence comparison."""

    def __init__(self, api_key: str, base_url: str, model: str) -> None:
        self.client = OpenAI(api_key=api_key, base_url=base_url)
        self.model = model
        self.prompt = PROMPT_PATH.read_text(encoding="utf-8")

    def _completion(self, instruction: str, payload: dict[str, object]) -> dict:
        response = self.client.chat.completions.create(
            model=self.model,
            temperature=0,
            max_tokens=4_000,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": self.prompt},
                {
                    "role": "user",
                    "content": instruction
                    + "\n"
                    + json.dumps(payload, ensure_ascii=False),
                },
            ],
        )
        content = response.choices[0].message.content
        if not content:
            raise ValueError("model returned an empty evidence response")
        return json.loads(content)

    @retry(
        retry=retry_if_exception_type(
            (APIConnectionError, RateLimitError, APIStatusError)
        ),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=8),
        reraise=True,
    )
    def decompose(self, claim_text: str) -> list[AtomicClaim]:
        result = self._completion(
            "Decompose this claim into atomic assertions.", {"claim": claim_text}
        )
        return AtomicClaimSet.model_validate(result).atomic_claims

    @retry(
        retry=retry_if_exception_type(
            (APIConnectionError, RateLimitError, APIStatusError)
        ),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=8),
        reraise=True,
    )
    def assess(
        self, atomic_claim: str, documents: list[EvidenceDocument]
    ) -> AtomicVerification:
        result = self._completion(
            "Assess every supplied document against the atomic claim.",
            {
                "atomic_claim": atomic_claim,
                "documents": [
                    document.model_dump(mode="json") for document in documents
                ],
            },
        )
        validated = EvidenceAssessmentSet.model_validate(result)
        assessments = [
            item
            for item in validated.assessments
            if item.document_index < len(documents)
        ]
        return decide_atomic_verdict(atomic_claim, assessments)
