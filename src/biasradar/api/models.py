"""Allow-listed public response models for the BiasRadar read API."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class PublicModel(BaseModel):
    """Base model that rejects accidental internal fields."""

    model_config = ConfigDict(extra="forbid")


class HealthResponse(PublicModel):
    status: Literal["ok"] = "ok"
    database: Literal["healthy"] = "healthy"


class TopicSummary(PublicModel):
    id: UUID
    name: str
    status: str
    keywords: list[str] = Field(default_factory=list)


class TopicListResponse(PublicModel):
    items: list[TopicSummary]
    limit: int
    offset: int


class StanceDistribution(PublicModel):
    pro_subject: float = Field(ge=0, le=100)
    anti_subject: float = Field(ge=0, le=100)
    neutral: float = Field(ge=0, le=100)
    mixed: float = Field(ge=0, le=100)
    unclear: float = Field(ge=0, le=100)


class ConsensusResultResponse(PublicModel):
    incident_ref: str
    source_group: str
    status: str
    leading_position: str | None = None
    leading_percent: float | None = Field(default=None, ge=0, le=100)
    position_distribution: dict[str, float]
    extracted_opinions: int = Field(ge=0)
    independent_opinions: int = Field(ge=0)
    duplicate_mentions: int = Field(ge=0)
    average_source_quality: float = Field(ge=0, le=1)
    confidence: float = Field(ge=0, le=1)
    source_roles: dict[str, int]
    summary: str
    limitations: list[str]


class FootballReportSummaryResponse(PublicModel):
    analyzed_items: int = Field(ge=0)
    stance_distribution: dict[str, float]
    stance_counts: dict[str, int] = Field(default_factory=dict)
    controversy_type_counts: dict[str, int]
    content_mode_counts: dict[str, int]
    framing_tag_counts: dict[str, int]
    teams: dict[str, int]
    referees: dict[str, int]
    federations: dict[str, int]
    attributed_expert_opinions: int = Field(ge=0)
    consensus_results: list[ConsensusResultResponse] = Field(default_factory=list)


class VisualizationMetric(PublicModel):
    label: str
    percentage: float = Field(ge=0, le=100)
    item_count: int = Field(ge=0)
    confidence: float = Field(ge=0, le=1)
    trend: float | None = None


class IncidentView(PublicModel):
    incident_id: str
    controversy_type: str
    description: str
    match_minute: int | None = Field(default=None, ge=0, le=130)
    on_field_decision: str | None = None
    review_outcome: str | None = None
    item_count: int = Field(ge=1)
    source_count: int = Field(ge=1)
    independent_content_groups: int = Field(ge=1)
    syndicated_items: int = Field(ge=0)
    channel_counts: dict[str, int]
    consensus: list[ConsensusResultResponse] = Field(default_factory=list)


class IncidentListResponse(PublicModel):
    topic_id: UUID
    period_start: datetime
    period_end: datetime
    items: list[IncidentView]
    limitations: list[str]


class NarrativeHistoryPoint(PublicModel):
    report_id: UUID
    timestamp: datetime
    metrics: list[VisualizationMetric]


class NarrativeResponse(PublicModel):
    topic_id: UUID
    period_start: datetime
    period_end: datetime
    metrics: list[VisualizationMetric]
    controversy_type_counts: dict[str, int]
    content_mode_counts: dict[str, int]
    framing_tag_counts: dict[str, int]
    consensus: list[ConsensusResultResponse]
    history: list[NarrativeHistoryPoint]


class TopicOverviewResponse(PublicModel):
    topic: TopicSummary
    domain_profile: str = "generic-v1"
    report_id: UUID
    period_start: datetime
    period_end: datetime
    total_items: int = Field(ge=0)
    source_count: int = Field(ge=0)
    independent_content_groups: int = Field(ge=0)
    syndicated_items: int = Field(ge=0)
    channel_counts: dict[str, int]
    stance_distribution: StanceDistribution
    directional_pro_percent: float | None = Field(default=None, ge=0, le=100)
    directional_anti_percent: float | None = Field(default=None, ge=0, le=100)
    overall_bias_score: float = Field(ge=-100, le=100)
    confidence_score: float = Field(ge=0, le=1)
    confidence_level: Literal["low", "moderate", "high"]
    repeated_claim_count: int = Field(ge=0)
    fact_check_summary: dict[str, int]
    verified_findings: list[str] = Field(default_factory=list)
    football_summary: FootballReportSummaryResponse | None = None
    methodology: str
    limitations: list[str]
    summary: str


class ReportSummary(PublicModel):
    id: UUID
    period_start: datetime
    period_end: datetime
    total_items: int = Field(ge=0)
    independent_content_groups: int = Field(ge=0)
    overall_bias_score: float = Field(ge=-100, le=100)
    confidence_score: float = Field(ge=0, le=1)


class ReportListResponse(PublicModel):
    items: list[ReportSummary]
    limit: int
    offset: int


class TimelinePoint(PublicModel):
    report_id: UUID
    timestamp: datetime
    toward_percent: float | None = Field(default=None, ge=0, le=100)
    against_percent: float | None = Field(default=None, ge=0, le=100)
    bias_score: float = Field(ge=-100, le=100)
    confidence: float = Field(ge=0, le=1)
    independent_content_groups: int = Field(ge=0)
    channel_counts: dict[str, int]


class TimelineResponse(PublicModel):
    topic_id: UUID
    points: list[TimelinePoint]


class TopicSubmissionRequest(PublicModel):
    query: str = Field(min_length=10, max_length=500)


class ViabilityResult(PublicModel):
    status: str
    confidence: float = Field(ge=0, le=1)
    coverage_signals: dict[str, object]
    topic_definition: dict[str, object]
    reasons: list[str]
    clarification_questions: list[str]
    prompt_version: str
    model_id: str


class TopicSubmissionResponse(PublicModel):
    id: UUID
    status: str
    query: str
    topic_id: UUID | None = None
    attempt_count: int = Field(ge=0, le=3)
    created_at: datetime
    updated_at: datetime
    assessed_at: datetime | None = None
    assessment: ViabilityResult | None = None


class AutomatedEvidence(PublicModel):
    relation: str
    source_role: str
    relevance_score: float = Field(ge=0, le=1)
    excerpt: str
    method_version: str
    model_id: str


class EvidenceCandidateResponse(PublicModel):
    id: UUID
    claim_id: UUID
    url: str
    title: str
    publisher: str
    published_at: datetime | None = None
    source_domain: str
    review_status: str
    retrieved_at: datetime
    automated_assessments: list[AutomatedEvidence]


class EvidenceListResponse(PublicModel):
    items: list[EvidenceCandidateResponse]
    limit: int
    offset: int


class EvidenceReviewRequest(PublicModel):
    decision: Literal["approved", "rejected", "needs_more_evidence"]
    corrected_relation: (
        Literal[
            "supports",
            "contradicts",
            "partially_supports",
            "provides_context",
            "irrelevant",
            "insufficient",
        ]
        | None
    ) = None
    corrected_source_role: (
        Literal[
            "primary_record",
            "official_statement",
            "direct_transcript",
            "independent_secondary",
            "repetition",
            "unknown",
        ]
        | None
    ) = None
    corrected_excerpt: str | None = Field(default=None, max_length=2_000)
    final_verdict: (
        Literal[
            "supported",
            "contradicted",
            "unverified",
            "misleading",
            "opinion",
            "needs_human_review",
        ]
        | None
    ) = None
    confidence: float | None = Field(default=None, ge=0, le=1)
    notes: str = Field(default="", max_length=4_000)


class EvidenceReviewResponse(PublicModel):
    review_id: UUID
    candidate_id: UUID
    decision: str
