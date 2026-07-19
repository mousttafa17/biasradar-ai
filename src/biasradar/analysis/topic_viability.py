"""Topic-agnostic intake, coverage signals, and structured viability assessment."""

import hashlib
import json
import re
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

from biasradar.ingestion.models import IngestedItem

PROMPT_PATH = Path(__file__).parents[3] / "prompts" / "topic_viability.txt"
TOPIC_VIABILITY_PROMPT_VERSION = "topic-viability-v1"
TOKEN_PATTERN = re.compile(r"[a-z0-9]+")


class ViabilityStatus(StrEnum):
    ACCEPTED = "accepted"
    NEEDS_CLARIFICATION = "needs_clarification"
    INSUFFICIENT_COVERAGE = "insufficient_coverage"
    TOO_BROAD = "too_broad"
    TOO_NARROW = "too_narrow"
    UNSAFE = "unsafe"
    DUPLICATE_TOPIC = "duplicate_topic"


class CoverageSignals(BaseModel):
    model_config = ConfigDict(extra="forbid")

    item_count: int = Field(ge=0)
    independent_source_count: int = Field(ge=0)
    channel_counts: dict[str, int]
    sample_titles: list[str] = Field(default_factory=list, max_length=20)

    @property
    def sufficient(self) -> bool:
        return self.item_count >= 5 and self.independent_source_count >= 3


class TopicDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    canonical_name: str = Field(min_length=3, max_length=200)
    subject: str = Field(min_length=2, max_length=300)
    supporting_frame: str = Field(min_length=3, max_length=500)
    opposing_frame: str = Field(min_length=3, max_length=500)
    keywords: list[str] = Field(min_length=1, max_length=20)
    exclusions: list[str] = Field(default_factory=list, max_length=20)
    language: str = Field(min_length=2, max_length=20)
    geographic_scope: str = Field(min_length=2, max_length=100)
    timeframe_days: int = Field(ge=7, le=3650)


class TopicViabilityAssessment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: ViabilityStatus
    confidence: float = Field(ge=0, le=1)
    definition: TopicDefinition
    reasons: list[str] = Field(min_length=1, max_length=10)
    clarification_questions: list[str] = Field(default_factory=list, max_length=5)


def normalize_topic_query(query: str) -> str:
    """Normalize a submission for idempotency without changing its meaning."""

    normalized = " ".join(query.split()).strip()
    if not 10 <= len(normalized) <= 500:
        raise ValueError("topic query must contain 10 to 500 characters")
    return normalized


def topic_query_hash(query: str) -> str:
    return hashlib.sha256(normalize_topic_query(query).casefold().encode()).hexdigest()


def coverage_signals(items: list[IngestedItem]) -> CoverageSignals:
    """Calculate provider-independent viability signals from a bounded sample."""

    sources = {
        (item.source_name.strip().casefold(), item.source_type) for item in items
    }
    channels: dict[str, int] = {}
    for item in items:
        channels[item.source_type] = channels.get(item.source_type, 0) + 1
    return CoverageSignals(
        item_count=len(items),
        independent_source_count=len(sources),
        channel_counts=channels,
        sample_titles=[item.title for item in items[:20]],
    )


def topic_similarity(left: str, right: str) -> float:
    left_tokens = set(TOKEN_PATTERN.findall(left.casefold()))
    right_tokens = set(TOKEN_PATTERN.findall(right.casefold()))
    if not left_tokens or not right_tokens:
        return 0
    return len(left_tokens & right_tokens) / len(left_tokens | right_tokens)


def enforce_measurable_gates(
    assessment: TopicViabilityAssessment,
    signals: CoverageSignals,
    duplicate_topic_id: str | None = None,
) -> TopicViabilityAssessment:
    """Ensure model output cannot override measurable coverage or duplication."""

    if duplicate_topic_id:
        return assessment.model_copy(
            update={
                "status": ViabilityStatus.DUPLICATE_TOPIC,
                "reasons": ["A substantially similar monitored topic already exists."],
            }
        )
    if assessment.status is ViabilityStatus.ACCEPTED and not signals.sufficient:
        return assessment.model_copy(
            update={
                "status": ViabilityStatus.INSUFFICIENT_COVERAGE,
                "reasons": [
                    "The coverage probe found fewer than 5 items or 3 independent "
                    "sources."
                ],
            }
        )
    return assessment


class TopicViabilityAssessor:
    """Create a constrained topic definition using coverage evidence."""

    def __init__(self, api_key: str, base_url: str, model: str) -> None:
        self.client = OpenAI(api_key=api_key, base_url=base_url)
        self.model = model
        self.prompt = PROMPT_PATH.read_text(encoding="utf-8")

    @retry(
        retry=retry_if_exception_type(
            (APIConnectionError, RateLimitError, APIStatusError)
        ),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=8),
        reraise=True,
    )
    def assess(self, query: str, signals: CoverageSignals) -> TopicViabilityAssessment:
        response = self.client.chat.completions.create(
            model=self.model,
            temperature=0,
            max_tokens=2_500,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": self.prompt},
                {
                    "role": "user",
                    "content": "Untrusted intake data:\n"
                    + json.dumps(
                        {
                            "submitted_query": query,
                            "coverage_signals": signals.model_dump(mode="json"),
                        },
                        ensure_ascii=False,
                    ),
                },
            ],
        )
        content = response.choices[0].message.content
        if not content:
            raise ValueError("model returned an empty viability assessment")
        return TopicViabilityAssessment.model_validate(json.loads(content))
