"""Reusable execution logic for claimed topic viability submissions."""

from typing import Any

from biasradar.analysis.topic_viability import (
    CoverageSignals,
    TopicViabilityAssessment,
    TopicViabilityAssessor,
    coverage_signals,
    enforce_measurable_gates,
)
from biasradar.config import Settings
from biasradar.persistence.repository import find_similar_topic, save_topic_viability
from biasradar.workflows.content_ingestion import collect_topic_content


def assess_topic_submission(
    client: Any,
    settings: Settings,
    *,
    submission_id: str,
    query: str,
    probe_limit: int = 20,
) -> tuple[TopicViabilityAssessment, CoverageSignals, str | None]:
    """Probe, assess, gate, and atomically finalize one claimed submission."""

    ingestion = collect_topic_content(settings, query, probe_limit)
    candidates = ingestion.items

    unique_candidates = list({str(item.url): item for item in candidates}.values())
    signals = coverage_signals(unique_candidates)
    duplicate = find_similar_topic(client, query)
    assessor = TopicViabilityAssessor(
        api_key=settings.openai_api_key or "",
        base_url=settings.openai_base_url,
        model=settings.openai_model,
    )
    assessment = enforce_measurable_gates(
        assessor.assess(query, signals),
        signals,
        duplicate_topic_id=str(duplicate["id"]) if duplicate else None,
    )
    topic_id = save_topic_viability(
        client,
        submission_id=submission_id,
        assessment=assessment,
        signals=signals,
        model_id=settings.openai_model,
        duplicate_topic_id=str(duplicate["id"]) if duplicate else None,
    )
    return assessment, signals, topic_id
