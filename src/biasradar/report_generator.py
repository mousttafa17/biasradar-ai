"""Deterministic topic-level aggregation for analyzed discourse items."""

import re
from collections import Counter
from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from biasradar.analyzer import FramingTag, StanceLabel


class ConfidenceLevel(StrEnum):
    LOW = "low"
    MODERATE = "moderate"
    HIGH = "high"


class AnalyzedItem(BaseModel):
    """The fields required to aggregate one analyzed item."""

    model_config = ConfigDict(extra="ignore")

    raw_item_id: str
    analysis_id: str
    url: str
    content_group_id: str | None = None
    is_group_origin: bool | None = None
    source_name: str
    source_type: str = "news"
    stance: StanceLabel
    framing_tags: list[FramingTag] = Field(default_factory=list)
    stance_confidence: float = Field(ge=0, le=1)
    loaded_language_score: float = Field(ge=0, le=1)
    one_sidedness_score: float = Field(ge=0, le=1)
    evidence_quality_score: float = Field(ge=0, le=1)
    emotionality_score: float = Field(ge=0, le=1)


class ClaimItem(BaseModel):
    """A version-linked claim used for cross-article clustering."""

    claim_id: str
    analysis_id: str
    raw_item_id: str
    source_name: str
    content_group_id: str | None = None
    claim_text: str
    claim_type: str
    checkability: str
    importance_score: float = Field(ge=0, le=1)


class ClaimCheckItem(BaseModel):
    """Stored evidence result linked to a versioned claim."""

    claim_id: str
    verdict: str
    confidence: float = Field(ge=0, le=1)
    evidence_summary: str
    evidence_urls: list[str] = Field(default_factory=list)
    provider: str | None = None
    method_version: str | None = None
    match_score: float | None = None
    evidence_data: dict[str, object] = Field(default_factory=dict)


class ClaimCluster(BaseModel):
    """A repeated claim supported by at least two distinct analyzed items."""

    cluster_key: str
    representative_claim: str
    item_count: int
    source_count: int
    independent_content_groups: int
    syndicated_items: int
    average_importance: float
    claim_types: dict[str, int]
    checkability: dict[str, int]
    claim_ids: list[str]
    fact_check_verdict: str | None = None
    fact_check_confidence: float | None = None
    evidence_urls: list[str] = Field(default_factory=list)


class TopicReport(BaseModel):
    """Frontend-ready deterministic report for one topic and period."""

    topic_id: str
    topic_name: str
    period_start: datetime
    period_end: datetime
    total_items: int
    classified_items: int
    source_count: int
    independent_content_groups: int
    syndicated_items: int
    deduplicated_items: int
    channel_counts: dict[str, int]
    stance_distribution: dict[str, float]
    directional_pro_percent: float | None
    directional_anti_percent: float | None
    overall_bias_score: float = Field(ge=-100, le=100)
    average_framing_intensity: float = Field(ge=0, le=100)
    average_evidence_quality: float = Field(ge=0, le=100)
    framing_tag_counts: dict[str, int]
    repeated_claim_clusters: list[ClaimCluster]
    fact_check_summary: dict[str, int]
    confidence_score: float = Field(ge=0, le=1)
    confidence_level: ConfidenceLevel
    methodology: str
    limitations: list[str]

    @property
    def report_text(self) -> str:
        """Render a concise, appropriately qualified human summary."""

        if self.directional_pro_percent is None:
            direction = (
                "There was not enough directional coverage for a pro/anti split."
            )
            bias_sentence = (
                "A directional framing-bias index was not available because no "
                "items had pro or anti stance."
            )
        else:
            direction = (
                "Among directional collected coverage, "
                f"{self.directional_pro_percent:.1f}% leaned toward/supporting and "
                f"{self.directional_anti_percent:.1f}% leaned against/critical."
            )
            bias_direction = (
                "toward/supporting"
                if self.overall_bias_score >= 0
                else "against/critical"
            )
            bias_sentence = (
                "The deterministic framing-bias index was "
                f"{abs(self.overall_bias_score):.1f}/100 {bias_direction}."
            )
        return (
            f"Based on {self.total_items} collected items from {self.source_count} "
            f"sources representing {self.independent_content_groups} independent "
            f"content groups, {direction} {bias_sentence} "
            f"Confidence is {self.confidence_level.value}. "
            f"The sample contained {len(self.repeated_claim_clusters)} repeated "
            f"claim clusters and {sum(self.fact_check_summary.values())} stored "
            "fact-check results."
        )


STANCE_KEYS = tuple(label.value for label in StanceLabel)
TOKEN_PATTERN = re.compile(r"[a-z0-9]+")
STOP_WORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "by",
    "for",
    "from",
    "has",
    "have",
    "in",
    "is",
    "it",
    "of",
    "on",
    "that",
    "the",
    "their",
    "this",
    "to",
    "was",
    "were",
    "will",
    "with",
}


def _round_percent(value: float) -> float:
    return round(value * 100 + 1e-9, 1)


def _confidence_level(score: float) -> ConfidenceLevel:
    if score >= 0.75:
        return ConfidenceLevel.HIGH
    if score >= 0.45:
        return ConfidenceLevel.MODERATE
    return ConfidenceLevel.LOW


def _claim_tokens(text: str) -> set[str]:
    return {
        token
        for token in TOKEN_PATTERN.findall(text.casefold())
        if token not in STOP_WORDS and len(token) > 1
    }


def _claim_similarity(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def cluster_repeated_claims(
    claims: list[ClaimItem],
    checks: list[ClaimCheckItem] | None = None,
    similarity_threshold: float = 0.55,
) -> list[ClaimCluster]:
    """Group lexically similar claims repeated across distinct articles."""

    if not 0 <= similarity_threshold <= 1:
        raise ValueError("similarity threshold must be between 0 and 1")
    parents = list(range(len(claims)))
    tokens = [_claim_tokens(claim.claim_text) for claim in claims]

    def find(index: int) -> int:
        while parents[index] != index:
            parents[index] = parents[parents[index]]
            index = parents[index]
        return index

    def union(left: int, right: int) -> None:
        left_root, right_root = find(left), find(right)
        if left_root != right_root:
            parents[right_root] = left_root

    for left in range(len(claims)):
        for right in range(left + 1, len(claims)):
            left_group = claims[left].content_group_id or claims[left].raw_item_id
            right_group = claims[right].content_group_id or claims[right].raw_item_id
            if left_group == right_group:
                continue
            if _claim_similarity(tokens[left], tokens[right]) >= similarity_threshold:
                union(left, right)

    groups: dict[int, list[ClaimItem]] = {}
    for index, claim in enumerate(claims):
        groups.setdefault(find(index), []).append(claim)

    clusters: list[ClaimCluster] = []
    checks_by_claim = {check.claim_id: check for check in checks or []}
    for members in groups.values():
        item_ids = {member.raw_item_id for member in members}
        content_groups = {
            member.content_group_id or member.raw_item_id for member in members
        }
        if len(content_groups) < 2:
            continue
        representative = max(
            members,
            key=lambda member: (member.importance_score, len(member.claim_text)),
        )
        cluster_tokens = sorted(_claim_tokens(representative.claim_text))
        member_checks = [
            checks_by_claim[member.claim_id]
            for member in members
            if member.claim_id in checks_by_claim
        ]
        verdicts = {check.verdict for check in member_checks}
        cluster_verdict = (
            next(iter(verdicts))
            if len(verdicts) == 1
            else "needs_human_review"
            if verdicts
            else None
        )
        clusters.append(
            ClaimCluster(
                cluster_key="-".join(cluster_tokens[:8]),
                representative_claim=representative.claim_text,
                item_count=len(item_ids),
                source_count=len({member.source_name.casefold() for member in members}),
                independent_content_groups=len(content_groups),
                syndicated_items=len(item_ids) - len(content_groups),
                average_importance=round(
                    sum(member.importance_score for member in members) / len(members),
                    3,
                ),
                claim_types=dict(Counter(member.claim_type for member in members)),
                checkability=dict(Counter(member.checkability for member in members)),
                claim_ids=[member.claim_id for member in members],
                fact_check_verdict=cluster_verdict,
                fact_check_confidence=(
                    round(
                        sum(check.confidence for check in member_checks)
                        / len(member_checks),
                        3,
                    )
                    if member_checks
                    else None
                ),
                evidence_urls=list(
                    dict.fromkeys(
                        url for check in member_checks for url in check.evidence_urls
                    )
                ),
            )
        )
    return sorted(
        clusters,
        key=lambda cluster: (
            cluster.item_count,
            cluster.source_count,
            cluster.average_importance,
        ),
        reverse=True,
    )


def aggregate_topic(
    *,
    topic_id: str,
    topic_name: str,
    period_start: datetime,
    period_end: datetime,
    items: list[AnalyzedItem],
    claims: list[ClaimItem] | None = None,
    claim_checks: list[ClaimCheckItem] | None = None,
) -> TopicReport:
    """Aggregate item metrics using transparent, deterministic arithmetic."""

    if not items:
        raise ValueError("no analyzed items were found for this topic and period")

    source_keys = [
        item.source_name.strip().casefold() or f"unknown:{item.raw_item_id}"
        for item in items
    ]
    group_keys = [
        item.content_group_id or f"unprocessed:{item.raw_item_id}" for item in items
    ]
    group_frequency = Counter(group_keys)
    channel_groups: dict[str, set[str]] = {}
    channel_group_frequency: Counter[tuple[str, str]] = Counter()
    for item, group_key in zip(items, group_keys, strict=True):
        channel_groups.setdefault(item.source_type, set()).add(group_key)
        channel_group_frequency[(item.source_type, group_key)] += 1
    channel_count = len(channel_groups)
    stance_weights = dict.fromkeys(STANCE_KEYS, 0.0)
    directional_bias_total = 0.0
    directional_weight = 0.0
    framing_total = 0.0
    evidence_total = 0.0
    metric_weight = 0.0

    for item, group_key in zip(items, group_keys, strict=True):
        # Channels receive equal total influence. Within a channel, independent
        # content groups receive equal influence divided among syndicated copies.
        base_weight = 1 / (
            channel_count
            * len(channel_groups[item.source_type])
            * channel_group_frequency[(item.source_type, group_key)]
        )
        weight = item.stance_confidence * base_weight
        stance_weights[item.stance.value] += weight

        framing_intensity = (
            0.35 * item.loaded_language_score
            + 0.35 * item.one_sidedness_score
            + 0.20 * item.emotionality_score
            + 0.10 * (1 - item.evidence_quality_score)
        )
        framing_total += framing_intensity * base_weight
        evidence_total += item.evidence_quality_score * base_weight
        metric_weight += base_weight
        direction = {
            StanceLabel.PRO_SUBJECT: 1,
            StanceLabel.ANTI_SUBJECT: -1,
        }.get(item.stance)
        if direction is not None:
            directional_bias_total += direction * framing_intensity * weight
            directional_weight += weight

    total_weight = sum(stance_weights.values())
    if total_weight:
        distribution = {
            key: _round_percent(value / total_weight)
            for key, value in stance_weights.items()
        }
        # Independent rounding can total 99.9 or 100.1. Assign that residual to
        # the largest category so frontend segments always close at exactly 100%.
        largest_key = max(stance_weights, key=lambda key: stance_weights[key])
        distribution[largest_key] = round(
            distribution[largest_key] + 100 - sum(distribution.values()), 1
        )
    else:
        distribution = dict.fromkeys(STANCE_KEYS, 0.0)

    pro_weight = stance_weights[StanceLabel.PRO_SUBJECT]
    anti_weight = stance_weights[StanceLabel.ANTI_SUBJECT]
    pro_anti_weight = pro_weight + anti_weight
    directional_pro = (
        _round_percent(pro_weight / pro_anti_weight) if pro_anti_weight else None
    )
    directional_anti = (
        round(100 - directional_pro, 1) if directional_pro is not None else None
    )
    overall_bias = (
        round(100 * directional_bias_total / directional_weight, 1)
        if directional_weight
        else 0.0
    )

    unique_sources = len(set(source_keys))
    independent_groups = len(set(group_keys))
    deduplicated_items = sum(item.content_group_id is not None for item in items)
    syndicated_items = sum(size - 1 for size in group_frequency.values())
    average_confidence = sum(item.stance_confidence for item in items) / len(items)
    confidence_score = round(
        0.35 * average_confidence
        + 0.30 * min(independent_groups / 20, 1)
        + 0.20 * min(unique_sources / 10, 1)
        + 0.15 * min(channel_count / 3, 1),
        3,
    )
    limitations = [
        "Percentages describe collected coverage, not all media or public opinion.",
        "Stance and framing metrics are model classifications, not verified intent.",
        "Repeated items are content-group-balanced, but syndicated-text detection "
        "is not perfect and strict similarity can miss heavily edited republications.",
        "Repeated claims use lexical similarity and may miss paraphrases or group "
        "claims that require human distinction.",
    ]
    if len(items) < 10:
        limitations.append("The sample contains fewer than 10 analyzed items.")
    if unique_sources < 5:
        limitations.append("The sample contains fewer than 5 independent source names.")
    if channel_count < 2:
        limitations.append("The sample contains only one media channel.")
    if deduplicated_items < len(items):
        limitations.append(
            f"{len(items) - deduplicated_items} items have not been "
            "content-deduplicated."
        )

    return TopicReport(
        topic_id=topic_id,
        topic_name=topic_name,
        period_start=period_start,
        period_end=period_end,
        total_items=len(items),
        classified_items=sum(item.stance is not StanceLabel.UNCLEAR for item in items),
        source_count=unique_sources,
        independent_content_groups=independent_groups,
        syndicated_items=syndicated_items,
        deduplicated_items=deduplicated_items,
        channel_counts=dict(Counter(item.source_type for item in items)),
        stance_distribution=distribution,
        directional_pro_percent=directional_pro,
        directional_anti_percent=directional_anti,
        overall_bias_score=overall_bias,
        average_framing_intensity=round(100 * framing_total / metric_weight, 1),
        average_evidence_quality=round(100 * evidence_total / metric_weight, 1),
        framing_tag_counts=dict(
            Counter(tag.value for item in items for tag in item.framing_tags)
        ),
        repeated_claim_clusters=cluster_repeated_claims(
            claims or [], checks=claim_checks
        ),
        fact_check_summary=dict(Counter(check.verdict for check in claim_checks or [])),
        confidence_score=confidence_score,
        confidence_level=_confidence_level(confidence_score),
        methodology=(
            "Confidence-weighted stance with equal total influence per channel, then "
            "per independent content group within each channel. "
            "Bias index = signed weighted mean of 35% loaded language, 35% "
            "one-sidedness, 20% emotionality, and 10% inverse evidence quality."
        ),
        limitations=limitations,
    )
