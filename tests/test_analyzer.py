import json
from types import SimpleNamespace

from biasradar.analysis.analyzer import ArticleAnalyzer, StanceLabel


def test_analyzer_validates_structured_json(monkeypatch) -> None:
    payload = {
        "stance": "anti_subject",
        "framing_tags": ["evidence_based_criticism"],
        "stance_confidence": 0.8,
        "bias_direction": "critical of the subject",
        "bias_score": 0.4,
        "loaded_language_score": 0.2,
        "one_sidedness_score": 0.3,
        "evidence_quality_score": 0.7,
        "emotionality_score": 0.1,
        "missing_counterarguments": [],
        "loaded_terms": [],
        "short_summary": "The article criticizes a documented decision.",
        "reasoning": "It cites a public decision and avoids claims about intent.",
        "claims": [
            {
                "claim_text": "The organization published a decision.",
                "claim_type": "verifiable_fact",
                "checkability": "checkable",
                "importance_score": 0.7,
            }
        ],
    }
    analyzer = ArticleAnalyzer("token", "https://example.com", "test-model")
    response = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(payload)))]
    )
    monkeypatch.setattr(
        analyzer.client.chat.completions,
        "create",
        lambda **kwargs: response,
    )

    result = analyzer.analyze("topic", "title", "article text")

    assert result.stance is StanceLabel.ANTI_SUBJECT
    assert result.framing_tags[0].value == "evidence_based_criticism"
    assert result.claims[0].claim_type.value == "verifiable_fact"
