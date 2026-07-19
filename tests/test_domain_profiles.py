import json
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from biasradar.analysis.analyzer import ArticleAnalyzer
from biasradar.domains.football import FootballAnalysis, FootballStance
from biasradar.domains.profiles import FOOTBALL_V1, get_domain_profile


def _football_payload():
    return {
        "controversy_types": ["VAR_decision", "penalty_claim"],
        "primary_stance": "criticizes_referee",
        "secondary_stances": ["supports_team"],
        "content_modes": ["neutral_match_reporting"],
        "framing_tags": ["evidence_based_criticism"],
        "subject_team": "Argentina",
        "opposing_team": "England",
        "player": None,
        "competition": "World Cup",
        "match": "Argentina v England",
        "referee": "Example Referee",
        "federation": "FIFA",
        "incidents": [
            {
                "controversy_type": "penalty_claim",
                "description": "The article disputes a penalty decision.",
                "match_minute": 72,
                "on_field_decision": "Penalty awarded",
                "review_outcome": "VAR upheld the decision",
            }
        ],
        "attributed_expert_opinions": [],
    }


def test_football_profile_registry_validates_the_domain_schema() -> None:
    result = FOOTBALL_V1.validate_analysis(_football_payload())

    assert result["primary_stance"] == "criticizes_referee"
    assert get_domain_profile("football-v1") is FOOTBALL_V1
    with pytest.raises(ValueError, match="unsupported domain profile"):
        get_domain_profile("medical-v1")


def test_football_dimensions_reject_flat_or_duplicate_stances() -> None:
    payload = _football_payload()
    payload["secondary_stances"] = ["criticizes_referee"]

    with pytest.raises(ValidationError, match="primary stance"):
        FootballAnalysis.model_validate(payload)


def test_article_analyzer_applies_football_prompt_and_validation(monkeypatch) -> None:
    domain_analysis = _football_payload()
    payload = {
        "domain_profile": "football-v1",
        "domain_analysis": domain_analysis,
        "stance": "anti_subject",
        "framing_tags": ["evidence_based_criticism"],
        "stance_confidence": 0.8,
        "bias_direction": "Critical of the officiating decision",
        "bias_score": 0.4,
        "loaded_language_score": 0.2,
        "one_sidedness_score": 0.3,
        "evidence_quality_score": 0.7,
        "emotionality_score": 0.1,
        "missing_counterarguments": [],
        "loaded_terms": [],
        "short_summary": "The article disputes a penalty decision.",
        "reasoning": "The criticism is explicit in the supplied article.",
        "claims": [],
    }
    analyzer = ArticleAnalyzer(
        "token",
        "https://example.com",
        "test-model",
        domain_profile="football-v1",
    )
    response = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(payload)))]
    )
    monkeypatch.setattr(
        analyzer.client.chat.completions, "create", lambda **kwargs: response
    )

    result = analyzer.analyze("topic", "title", "article")

    assert result.domain_profile == "football-v1"
    assert result.domain_analysis["primary_stance"] == FootballStance.CRITICIZES_REFEREE
    assert "DOMAIN PROFILE: football-v1" in analyzer.system_prompt
    assert analyzer.prompt_version.endswith("football-v1")
