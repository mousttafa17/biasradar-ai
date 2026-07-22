"""Transparent source-quality scoring and independent-opinion consensus."""

import re
from collections import Counter
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

TOKEN_PATTERN = re.compile(r"[a-z0-9]+")


class SourceRole(StrEnum):
    REFEREE = "referee"
    FORMER_REFEREE = "former_referee"
    GOVERNING_BODY = "governing_body"
    CLUB = "club"
    PLAYER = "player"
    COACH = "coach"
    JOURNALIST = "journalist"
    ANALYST = "analyst"
    FAN = "fan"
    UNKNOWN = "unknown"


class OpinionPosition(StrEnum):
    AGREES_WITH_DECISION = "agrees_with_decision"
    DISAGREES_WITH_DECISION = "disagrees_with_decision"
    SUPPORTS_CLAIM = "supports_claim"
    REJECTS_CLAIM = "rejects_claim"
    MIXED = "mixed"
    UNCLEAR = "unclear"


class ConsensusGroup(StrEnum):
    OFFICIATING_EXPERT = "officiating_expert"
    OFFICIAL = "official"
    JOURNALISM = "journalism"
    PARTICIPANT = "participant"
    FAN = "fan"


class ConsensusStatus(StrEnum):
    STRONG = "strong_consensus"
    MODERATE = "moderate_consensus"
    SPLIT = "split"
    INSUFFICIENT = "insufficient_evidence"


class ConsensusOpinion(BaseModel):
    """One attributed judgment with provenance needed for independence checks."""

    model_config = ConfigDict(extra="forbid")

    speaker: str = Field(min_length=1, max_length=200)
    role: SourceRole = SourceRole.UNKNOWN
    stated_credential: str | None = Field(default=None, max_length=300)
    affiliation: str | None = Field(default=None, max_length=300)
    is_direct_source: bool = False
    opinion_summary: str = Field(min_length=1, max_length=1_000)
    direct_quote: str | None = Field(default=None, max_length=1_000)
    incident_ref: str = Field(min_length=1, max_length=500)
    position: OpinionPosition
    position_confidence: float = Field(default=0.5, ge=0, le=1)
    article_id: str
    source_name: str
    content_group_id: str | None = None


class ConsensusResult(BaseModel):
    incident_ref: str
    source_group: ConsensusGroup
    status: ConsensusStatus
    leading_position: OpinionPosition | None = None
    leading_percent: float | None = Field(default=None, ge=0, le=100)
    position_distribution: dict[str, float]
    extracted_opinions: int
    independent_opinions: int
    duplicate_mentions: int
    average_source_quality: float = Field(ge=0, le=1)
    confidence: float = Field(ge=0, le=1)
    source_roles: dict[str, int]
    summary: str
    limitations: list[str]


ROLE_QUALITY = {
    SourceRole.REFEREE: 0.95,
    SourceRole.FORMER_REFEREE: 0.90,
    SourceRole.GOVERNING_BODY: 0.85,
    SourceRole.ANALYST: 0.72,
    SourceRole.JOURNALIST: 0.65,
    SourceRole.COACH: 0.55,
    SourceRole.PLAYER: 0.50,
    SourceRole.CLUB: 0.45,
    SourceRole.FAN: 0.20,
    SourceRole.UNKNOWN: 0.20,
}

ROLE_GROUP = {
    SourceRole.REFEREE: ConsensusGroup.OFFICIATING_EXPERT,
    SourceRole.FORMER_REFEREE: ConsensusGroup.OFFICIATING_EXPERT,
    SourceRole.GOVERNING_BODY: ConsensusGroup.OFFICIAL,
    SourceRole.JOURNALIST: ConsensusGroup.JOURNALISM,
    SourceRole.ANALYST: ConsensusGroup.JOURNALISM,
    SourceRole.CLUB: ConsensusGroup.PARTICIPANT,
    SourceRole.PLAYER: ConsensusGroup.PARTICIPANT,
    SourceRole.COACH: ConsensusGroup.PARTICIPANT,
    SourceRole.FAN: ConsensusGroup.FAN,
}

MINIMUM_INDEPENDENT = {
    ConsensusGroup.OFFICIATING_EXPERT: 3,
    ConsensusGroup.OFFICIAL: 2,
    ConsensusGroup.JOURNALISM: 4,
    ConsensusGroup.PARTICIPANT: 3,
    ConsensusGroup.FAN: 5,
}


def normalized_identity(value: str) -> str:
    return " ".join(TOKEN_PATTERN.findall(value.casefold()))


def _incident_tokens(value: str) -> set[str]:
    return set(TOKEN_PATTERN.findall(value.casefold()))


def _incident_keys(opinions: list[ConsensusOpinion]) -> list[str]:
    """Cluster close incident descriptions without model-generated merging."""

    parents = list(range(len(opinions)))
    tokens = [_incident_tokens(opinion.incident_ref) for opinion in opinions]

    def find(index: int) -> int:
        while parents[index] != index:
            parents[index] = parents[parents[index]]
            index = parents[index]
        return index

    def union(left: int, right: int) -> None:
        left_root, right_root = find(left), find(right)
        if left_root != right_root:
            parents[right_root] = left_root

    for left in range(len(opinions)):
        for right in range(left + 1, len(opinions)):
            union_size = len(tokens[left] | tokens[right])
            similarity = (
                len(tokens[left] & tokens[right]) / union_size if union_size else 0
            )
            if similarity >= 0.55:
                union(left, right)

    labels: dict[int, str] = {}
    for index, opinion in enumerate(opinions):
        root = find(index)
        candidate = normalized_identity(opinion.incident_ref)
        current = labels.get(root)
        if current is None or (len(candidate), candidate) > (len(current), current):
            labels[root] = candidate
    return [labels[find(index)] for index in range(len(opinions))]


def source_quality(opinion: ConsensusOpinion) -> float:
    """Score observable role/provenance attributes without inferring authority."""

    score = ROLE_QUALITY[opinion.role]
    if opinion.stated_credential:
        score += 0.04
    if opinion.is_direct_source:
        score += 0.04
    if opinion.direct_quote:
        score += 0.02
    return round(min(score, 1.0), 3)


def _closed_percent(weights: dict[str, float]) -> dict[str, float]:
    total = sum(weights.values())
    if not total:
        return {}
    result = {key: round(100 * value / total, 1) for key, value in weights.items()}
    largest = max(weights, key=weights.get)  # type: ignore[arg-type]
    result[largest] = round(result[largest] + 100 - sum(result.values()), 1)
    return result


def _summary(
    group: ConsensusGroup,
    status: ConsensusStatus,
    count: int,
    position: OpinionPosition | None,
    percent: float | None,
) -> str:
    label = group.value.replace("_", " ")
    if status is ConsensusStatus.INSUFFICIENT:
        return f"Not enough independent {label} opinions to determine consensus."
    if status is ConsensusStatus.SPLIT:
        return f"The {label} opinions were split across {count} independent sources."
    strength = "Strong" if status is ConsensusStatus.STRONG else "Moderate"
    position_text = (position or OpinionPosition.UNCLEAR).value.replace("_", " ")
    return (
        f"{strength} {label} consensus: {percent:.1f}% of weighted opinions "
        f"{position_text} across {count} independent sources."
    )


def build_consensus(opinions: list[ConsensusOpinion]) -> list[ConsensusResult]:
    """Deduplicate attributed judgments and calculate incident/group consensus."""

    buckets: dict[tuple[str, ConsensusGroup], list[ConsensusOpinion]] = {}
    incident_keys = _incident_keys(opinions)
    for opinion, incident in zip(opinions, incident_keys, strict=True):
        group = ROLE_GROUP.get(opinion.role)
        if group and opinion.position is not OpinionPosition.UNCLEAR:
            buckets.setdefault((incident, group), []).append(opinion)

    results: list[ConsensusResult] = []
    for (incident, group), extracted in buckets.items():
        # A named person/organization is one independent opinion even if quoted by
        # many outlets. Keep the most directly sourced, highest-quality occurrence.
        independent: dict[str, ConsensusOpinion] = {}
        for opinion in extracted:
            identity = normalized_identity(opinion.speaker)
            existing = independent.get(identity)
            ranking = (
                opinion.is_direct_source,
                source_quality(opinion),
                opinion.position_confidence,
            )
            if existing is None or ranking > (
                existing.is_direct_source,
                source_quality(existing),
                existing.position_confidence,
            ):
                independent[identity] = opinion

        unique = list(independent.values())
        weights: dict[str, float] = {}
        for opinion in unique:
            weight = source_quality(opinion) * opinion.position_confidence
            weights[opinion.position.value] = (
                weights.get(opinion.position.value, 0.0) + weight
            )
        distribution = _closed_percent(weights)
        leading = max(distribution, key=distribution.get) if distribution else None
        leading_percent = distribution.get(leading) if leading else None
        runner_up = sorted(distribution.values(), reverse=True)[1:2] or [0.0]
        minimum = MINIMUM_INDEPENDENT[group]
        if len(unique) < minimum:
            status = ConsensusStatus.INSUFFICIENT
        elif leading_percent is not None and leading_percent >= 80:
            status = ConsensusStatus.STRONG
        elif (
            leading_percent is not None
            and leading_percent >= 67
            and leading_percent - runner_up[0] >= 20
        ):
            status = ConsensusStatus.MODERATE
        else:
            status = ConsensusStatus.SPLIT
        average_quality = (
            sum(source_quality(opinion) for opinion in unique) / len(unique)
            if unique
            else 0.0
        )
        confidence = round(
            min(len(unique) / (minimum * 2), 1)
            * average_quality
            * ((leading_percent or 0) / 100),
            3,
        )
        limitations = [
            "Consensus covers attributed opinions found in the collected sample, "
            "not every qualified person.",
            "Roles and credentials are limited to information explicit in sources.",
        ]
        results.append(
            ConsensusResult(
                incident_ref=incident,
                source_group=group,
                status=status,
                leading_position=OpinionPosition(leading) if leading else None,
                leading_percent=leading_percent,
                position_distribution=distribution,
                extracted_opinions=len(extracted),
                independent_opinions=len(unique),
                duplicate_mentions=len(extracted) - len(unique),
                average_source_quality=round(average_quality, 3),
                confidence=confidence,
                source_roles=dict(Counter(opinion.role.value for opinion in unique)),
                summary=_summary(
                    group,
                    status,
                    len(unique),
                    OpinionPosition(leading) if leading else None,
                    leading_percent,
                ),
                limitations=limitations,
            )
        )
    return sorted(
        results,
        key=lambda result: (
            result.status is not ConsensusStatus.INSUFFICIENT,
            result.confidence,
            result.independent_opinions,
        ),
        reverse=True,
    )
