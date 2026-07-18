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


class TopicOverviewResponse(PublicModel):
    topic: TopicSummary
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
    methodology: str
    limitations: list[str]
    summary: str
