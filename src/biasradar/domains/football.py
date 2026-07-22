"""Validated football controversy taxonomy for the first BiasRadar domain."""

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator

from biasradar.analysis.consensus import OpinionPosition, SourceRole


class FootballControversyType(StrEnum):
    VAR_DECISION = "VAR_decision"
    PENALTY_CLAIM = "penalty_claim"
    RED_CARD_CLAIM = "red_card_claim"
    OFFSIDE_CLAIM = "offside_claim"
    REFEREE_PERFORMANCE = "referee_performance"
    FEDERATION_BIAS = "federation_bias"
    CORRUPTION_ALLEGATION = "corruption_allegation"
    PLAYER_MEDIA_BIAS = "player_media_bias"
    TEAM_MEDIA_BIAS = "team_media_bias"
    FAN_NARRATIVE = "fan_narrative"
    OTHER_FOOTBALL = "other_football"


class FootballStance(StrEnum):
    SUPPORTS_TEAM = "supports_team"
    CRITICIZES_TEAM = "criticizes_team"
    DEFENDS_REFEREE = "defends_referee"
    CRITICIZES_REFEREE = "criticizes_referee"
    ACCUSES_FEDERATION = "accuses_federation"
    DEFENDS_FEDERATION = "defends_federation"
    UNCLEAR = "unclear"


class FootballContentMode(StrEnum):
    NEUTRAL_MATCH_REPORTING = "neutral_match_reporting"
    TACTICAL_ANALYSIS = "tactical_analysis"


class FootballFramingTag(StrEnum):
    FAN_EMOTION = "fan_emotion"
    CONSPIRACY_CLAIM = "conspiracy_claim"
    LOADED_LANGUAGE = "loaded_language"
    INSTITUTIONAL_DEFENSE = "institutional_defense"
    EVIDENCE_BASED_CRITICISM = "evidence_based_criticism"


class FootballIncident(BaseModel):
    model_config = ConfigDict(extra="forbid")

    controversy_type: FootballControversyType
    description: str = Field(min_length=1, max_length=1_000)
    match_minute: int | None = Field(default=None, ge=0, le=130)
    on_field_decision: str | None = Field(default=None, max_length=500)
    review_outcome: str | None = Field(default=None, max_length=500)


class AttributedFootballOpinion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    speaker: str = Field(min_length=1, max_length=200)
    source_role: SourceRole = SourceRole.UNKNOWN
    stated_credential: str | None = Field(default=None, max_length=300)
    affiliation: str | None = Field(default=None, max_length=300)
    is_direct_source: bool = False
    opinion_summary: str = Field(min_length=1, max_length=1_000)
    direct_quote: str | None = Field(default=None, max_length=1_000)
    incident_ref: str = Field(default="unspecified incident", max_length=500)
    position: OpinionPosition = OpinionPosition.UNCLEAR
    position_confidence: float = Field(default=0.5, ge=0, le=1)


class FootballAnalysis(BaseModel):
    """Football-specific dimensions embedded in generic article analysis."""

    model_config = ConfigDict(extra="forbid")

    controversy_types: list[FootballControversyType] = Field(min_length=1, max_length=5)
    primary_stance: FootballStance
    secondary_stances: list[FootballStance] = Field(default_factory=list, max_length=6)
    content_modes: list[FootballContentMode] = Field(default_factory=list, max_length=2)
    framing_tags: list[FootballFramingTag] = Field(default_factory=list, max_length=5)
    subject_team: str | None = Field(default=None, max_length=200)
    opposing_team: str | None = Field(default=None, max_length=200)
    player: str | None = Field(default=None, max_length=200)
    competition: str | None = Field(default=None, max_length=200)
    match: str | None = Field(default=None, max_length=300)
    referee: str | None = Field(default=None, max_length=200)
    federation: str | None = Field(default=None, max_length=200)
    incidents: list[FootballIncident] = Field(default_factory=list, max_length=10)
    attributed_expert_opinions: list[AttributedFootballOpinion] = Field(
        default_factory=list, max_length=20
    )

    @model_validator(mode="after")
    def validate_dimensions(self) -> "FootballAnalysis":
        if self.primary_stance in self.secondary_stances:
            raise ValueError("primary stance cannot also be a secondary stance")
        for values, label in (
            (self.controversy_types, "controversy types"),
            (self.secondary_stances, "secondary stances"),
            (self.content_modes, "content modes"),
            (self.framing_tags, "framing tags"),
        ):
            if len(values) != len(set(values)):
                raise ValueError(f"{label} must not contain duplicates")
        return self
