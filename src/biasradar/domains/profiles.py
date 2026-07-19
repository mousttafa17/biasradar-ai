"""Generic domain-profile registry for specialized BiasRadar products."""

from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel

from biasradar.domains.football import FootballAnalysis

PROMPT_ROOT = Path(__file__).parents[3] / "prompts"


@dataclass(frozen=True, slots=True)
class DomainProfile[DomainAnalysis: BaseModel]:
    profile_id: str
    prompt_version: str
    analysis_model: type[DomainAnalysis] | None
    prompt_path: Path | None

    @property
    def prompt(self) -> str:
        return self.prompt_path.read_text(encoding="utf-8") if self.prompt_path else ""

    def validate_analysis(self, payload: dict[str, object]) -> dict[str, object]:
        if self.analysis_model is None:
            if payload:
                raise ValueError("generic profile does not accept domain analysis")
            return {}
        return self.analysis_model.model_validate(payload).model_dump(mode="json")


GENERIC_V1 = DomainProfile(
    profile_id="generic-v1",
    prompt_version="generic-v1",
    analysis_model=None,
    prompt_path=None,
)

FOOTBALL_V1 = DomainProfile(
    profile_id="football-v1",
    prompt_version="football-v1",
    analysis_model=FootballAnalysis,
    prompt_path=PROMPT_ROOT / "football_controversy.txt",
)

DOMAIN_PROFILES: dict[str, DomainProfile] = {
    profile.profile_id: profile for profile in (GENERIC_V1, FOOTBALL_V1)
}


def get_domain_profile(profile_id: str) -> DomainProfile:
    try:
        return DOMAIN_PROFILES[profile_id]
    except KeyError as error:
        supported = ", ".join(sorted(DOMAIN_PROFILES))
        raise ValueError(
            f"unsupported domain profile {profile_id!r}; choose {supported}"
        ) from error
