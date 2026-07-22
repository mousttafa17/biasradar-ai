"""Supabase access helpers for topics and raw news items."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from postgrest.exceptions import APIError

from biasradar.analysis.analyzer import CURRENT_PROMPT_VERSION, ArticleAnalysis
from biasradar.analysis.topic_viability import (
    TOPIC_VIABILITY_PROMPT_VERSION,
    CoverageSignals,
    TopicViabilityAssessment,
    normalize_topic_query,
    topic_query_hash,
    topic_similarity,
)
from biasradar.config import Settings, get_settings
from biasradar.evidence.fact_checker import FACT_CHECK_METHOD_VERSION, FactCheckResult
from biasradar.evidence.primary_sources import PrimaryEvidenceCandidate
from biasradar.evidence.verifier import EvidenceVerificationResult
from biasradar.ingestion.deduplication import (
    DeduplicationItem,
    DeduplicationResult,
)
from biasradar.ingestion.models import IngestedItem
from biasradar.reporting.generator import (
    AnalyzedItem,
    ClaimCheckItem,
    ClaimItem,
    TopicReport,
)
from supabase import Client, create_client

REQUIRED_COLUMNS = {
    "sources": {"id", "name", "domain", "source_type", "reliability_score"},
    "topics": {"id", "name", "status", "keywords"},
    "raw_items": {
        "id",
        "topic_id",
        "source_name",
        "source_type",
        "title",
        "url",
        "cleaned_text",
        "status",
        "source_id",
        "canonical_url",
        "normalized_domain",
        "content_hash",
        "content_simhash",
        "content_group_id",
        "is_group_origin",
        "deduplicated_at",
        "ingestion_provider",
        "engagement_data",
        "external_id",
        "content_license",
        "attribution",
    },
    "analysis": {
        "id",
        "raw_item_id",
        "analysis_version",
        "prompt_version",
        "model_id",
        "is_current",
        "domain_profile",
        "domain_analysis",
        "stance",
        "framing_tags",
        "stance_confidence",
        "bias_direction",
        "bias_score",
        "loaded_language_score",
        "one_sidedness_score",
        "evidence_quality_score",
        "emotionality_score",
        "missing_counterarguments",
        "loaded_terms",
        "summary",
        "reasoning",
    },
    "claims": {
        "id",
        "analysis_id",
        "raw_item_id",
        "claim_text",
        "claim_type",
        "checkability",
        "importance_score",
    },
    "topic_reports": {
        "id",
        "topic_id",
        "period_start",
        "period_end",
        "total_items",
        "pro_percent",
        "anti_percent",
        "neutral_percent",
        "mixed_percent",
        "unclear_percent",
        "directional_pro_percent",
        "directional_anti_percent",
        "overall_bias_score",
        "confidence_score",
        "source_count",
        "independent_content_groups",
        "syndicated_items",
        "deduplicated_items",
        "report_text",
        "report_data",
        "pipeline_run_id",
    },
    "pipeline_runs": {
        "id",
        "topic_id",
        "idempotency_key",
        "status",
        "period_start",
        "period_end",
        "prompt_version",
        "model_id",
        "counters",
        "provider_errors",
        "error_summary",
        "report_id",
        "started_at",
        "heartbeat_at",
        "finished_at",
    },
    "topic_schedules": {
        "id",
        "topic_id",
        "enabled",
        "interval_minutes",
        "lookback_days",
        "news_limit",
        "rss_limit",
        "next_run_at",
        "lease_expires_at",
        "last_status",
        "last_error",
        "consecutive_failures",
    },
    "worker_instances": {"worker_id", "started_at", "heartbeat_at", "metadata"},
    "topic_submissions": {
        "id",
        "raw_query",
        "normalized_query",
        "query_hash",
        "status",
        "topic_id",
        "created_at",
        "assessed_at",
        "user_id",
        "idempotency_key",
        "attempt_count",
        "lease_expires_at",
        "next_attempt_at",
        "updated_at",
    },
    "topic_intake_rate_limits": {
        "identity_hash",
        "window_start",
        "request_count",
    },
    "evidence_candidates": {
        "id",
        "claim_id",
        "url",
        "canonical_url",
        "title",
        "publisher",
        "published_at",
        "source_domain",
        "content_hash",
        "discovery_method",
        "retrieved_at",
        "review_status",
    },
    "evidence_automated_assessments": {
        "id",
        "evidence_candidate_id",
        "relation",
        "source_role",
        "relevance_score",
        "excerpt",
        "reasoning",
        "method_version",
        "model_id",
        "created_at",
    },
    "evidence_reviews": {
        "id",
        "evidence_candidate_id",
        "reviewer_user_id",
        "decision",
        "corrected_relation",
        "corrected_source_role",
        "corrected_excerpt",
        "final_verdict",
        "confidence",
        "notes",
        "created_at",
    },
    "topic_viability_assessments": {
        "id",
        "submission_id",
        "status",
        "confidence",
        "coverage_signals",
        "topic_definition",
        "reasons",
        "clarification_questions",
        "duplicate_topic_id",
        "prompt_version",
        "model_id",
    },
    "claim_checks": {
        "id",
        "claim_id",
        "verdict",
        "confidence",
        "evidence_summary",
        "evidence_urls",
        "notes",
        "provider",
        "method_version",
        "matched_claim_text",
        "match_score",
        "evidence_data",
        "checked_at",
    },
}
REQUIRED_RPC_PATHS = {
    "/rpc/save_article_analysis": "function save_article_analysis",
    "/rpc/begin_pipeline_run": "function begin_pipeline_run",
    "/rpc/save_topic_viability": "function save_topic_viability",
    "/rpc/consume_topic_intake_rate_limit": (
        "function consume_topic_intake_rate_limit"
    ),
    "/rpc/claim_topic_submissions": "function claim_topic_submissions",
    "/rpc/claim_due_topic_schedules": "function claim_due_topic_schedules",
    "/rpc/finish_topic_schedule": "function finish_topic_schedule",
    "/rpc/heartbeat_worker": "function heartbeat_worker",
    "/rpc/submit_evidence_review": "function submit_evidence_review",
}


@dataclass(slots=True)
class InsertSummary:
    """Counters produced while storing fetched articles."""

    inserted: int = 0
    skipped_duplicates: int = 0
    failed: int = 0


@dataclass(slots=True)
class StoredArticle:
    """An inserted article and the generated database identifier."""

    article: IngestedItem
    raw_item_id: str


@dataclass(slots=True)
class ReanalysisCandidate:
    """Stored article content whose current analysis may need refreshing."""

    raw_item_id: str
    title: str
    url: str
    source_name: str
    source_type: str
    author: str | None
    fallback_text: str | None
    cleaned_text: str | None
    current_version: int | None


@dataclass(slots=True)
class PipelineRun:
    """A claimed idempotent orchestration run."""

    run_id: str
    status: str
    report_id: str | None
    period_start: str
    period_end: str


@dataclass(slots=True)
class ClaimedTopicSchedule:
    schedule_id: str
    topic_id: str
    interval_minutes: int
    lookback_days: int
    news_limit: int
    rss_limit: int


@dataclass(slots=True)
class TopicSubmission:
    submission_id: str
    status: str
    topic_id: str | None


@dataclass(slots=True)
class ClaimedTopicSubmission:
    submission_id: str
    query: str
    attempt_count: int


def get_supabase(settings: Settings | None = None) -> Client:
    """Create a Supabase client from application settings."""

    config = settings or get_settings()
    return create_client(config.supabase_url, config.supabase_service_key)


def check_database_schema(settings: Settings) -> list[str]:
    """Return missing database objects without exposing credentials in errors."""

    try:
        response = httpx.get(
            f"{settings.supabase_url}/rest/v1/",
            headers={
                "apikey": settings.supabase_service_key,
                "Authorization": f"Bearer {settings.supabase_service_key}",
            },
            timeout=20,
        )
    except httpx.HTTPError as error:
        raise RuntimeError("could not reach the Supabase schema endpoint") from error
    if response.is_error:
        raise RuntimeError(
            f"Supabase schema endpoint returned HTTP {response.status_code}"
        )

    document = response.json()
    definitions = document.get("definitions", {})
    missing: list[str] = []
    for table, expected in REQUIRED_COLUMNS.items():
        actual = set(definitions.get(table, {}).get("properties", {}))
        if not actual:
            missing.append(f"table {table}")
            continue
        missing.extend(
            f"column {table}.{column}" for column in sorted(expected - actual)
        )
    paths = document.get("paths", {})
    for path, label in REQUIRED_RPC_PATHS.items():
        if path not in paths:
            missing.append(label)
    return missing


def find_topic_id(client: Client, topic_name: str) -> str | None:
    """Find a topic by exact name, returning ``None`` when absent."""

    response = (
        client.table("topics").select("id").eq("name", topic_name).limit(1).execute()
    )
    if not response.data:
        response = (
            client.table("topics")
            .select("id")
            .ilike("name", topic_name)
            .limit(1)
            .execute()
        )
    if not response.data:
        return None
    return str(response.data[0]["id"])


def find_topic(client: Client, topic_name: str) -> dict[str, Any] | None:
    """Return topic metadata using exact, then case-insensitive matching."""

    columns = "id,name,subject,opposing_frame,supporting_frame"
    response = (
        client.table("topics").select(columns).eq("name", topic_name).limit(1).execute()
    )
    if not response.data:
        response = (
            client.table("topics")
            .select(columns)
            .ilike("name", topic_name)
            .limit(1)
            .execute()
        )
    return response.data[0] if response.data else None


def find_topic_by_id(client: Client, topic_id: str) -> dict[str, Any] | None:
    response = (
        client.table("topics")
        .select("id,name,status,keywords")
        .eq("id", topic_id)
        .limit(1)
        .execute()
    )
    return response.data[0] if response.data else None


def upsert_topic_schedule(
    client: Client,
    *,
    topic_id: str,
    interval_minutes: int,
    lookback_days: int,
    news_limit: int,
    rss_limit: int,
    enabled: bool = True,
) -> str:
    row = {
        "topic_id": topic_id,
        "interval_minutes": interval_minutes,
        "lookback_days": lookback_days,
        "news_limit": news_limit,
        "rss_limit": rss_limit,
        "enabled": enabled,
        "next_run_at": datetime.now(UTC).isoformat(),
    }
    response = (
        client.table("topic_schedules").upsert(row, on_conflict="topic_id").execute()
    )
    if not response.data:
        raise ValueError("Supabase did not return a topic schedule")
    return str(response.data[0]["id"])


def list_topic_schedules(client: Client) -> list[dict[str, Any]]:
    response = (
        client.table("topic_schedules")
        .select(
            "id,topic_id,enabled,interval_minutes,lookback_days,news_limit,"
            "rss_limit,next_run_at,last_status,last_error,consecutive_failures"
        )
        .order("next_run_at")
        .execute()
    )
    return list(response.data)


def claim_due_topic_schedules(client: Client, limit: int) -> list[ClaimedTopicSchedule]:
    response = client.rpc("claim_due_topic_schedules", {"p_limit": limit}).execute()
    return [
        ClaimedTopicSchedule(
            schedule_id=str(row["id"]),
            topic_id=str(row["topic_id"]),
            interval_minutes=int(row["interval_minutes"]),
            lookback_days=int(row["lookback_days"]),
            news_limit=int(row["news_limit"]),
            rss_limit=int(row["rss_limit"]),
        )
        for row in response.data
    ]


def finish_topic_schedule(
    client: Client, schedule_id: str, succeeded: bool, error: str | None = None
) -> None:
    client.rpc(
        "finish_topic_schedule",
        {
            "p_schedule_id": schedule_id,
            "p_succeeded": succeeded,
            "p_error": error[:500] if error else None,
        },
    ).execute()


def heartbeat_worker(
    client: Client, worker_id: str, metadata: dict[str, object]
) -> None:
    client.rpc(
        "heartbeat_worker",
        {"p_worker_id": worker_id, "p_metadata": metadata},
    ).execute()


def worker_is_healthy(client: Client, max_age_seconds: int = 120) -> bool:
    cutoff = (datetime.now(UTC) - timedelta(seconds=max_age_seconds)).isoformat()
    response = (
        client.table("worker_instances")
        .select("worker_id")
        .gte("heartbeat_at", cutoff)
        .limit(1)
        .execute()
    )
    return bool(response.data)


def create_topic_submission(client: Client, query: str) -> TopicSubmission:
    """Create or reclaim an idempotent normalized topic submission."""

    normalized = normalize_topic_query(query)
    query_hash = topic_query_hash(normalized)
    existing = (
        client.table("topic_submissions")
        .select("id,status,topic_id")
        .eq("query_hash", query_hash)
        .limit(1)
        .execute()
    )
    if existing.data:
        row = existing.data[0]
        if row["status"] == "failed":
            client.table("topic_submissions").update(
                {"status": "assessing", "assessed_at": None}
            ).eq("id", row["id"]).execute()
            row["status"] = "assessing"
        return TopicSubmission(
            submission_id=str(row["id"]),
            status=str(row["status"]),
            topic_id=str(row["topic_id"]) if row.get("topic_id") else None,
        )
    response = (
        client.table("topic_submissions")
        .insert(
            {
                "raw_query": query,
                "normalized_query": normalized,
                "query_hash": query_hash,
                "status": "assessing",
            }
        )
        .execute()
    )
    if not response.data or "id" not in response.data[0]:
        raise ValueError("Supabase did not return a topic submission id")
    return TopicSubmission(
        submission_id=str(response.data[0]["id"]),
        status="assessing",
        topic_id=None,
    )


def find_similar_topic(
    client: Client, query: str, threshold: float = 0.72
) -> dict[str, Any] | None:
    """Find a strongly overlapping active topic using transparent token similarity."""

    response = (
        client.table("topics")
        .select("id,name")
        .eq("status", "active")
        .limit(500)
        .execute()
    )
    candidates = [
        (topic_similarity(query, str(row["name"])), row) for row in response.data
    ]
    score, row = max(candidates, default=(0.0, None), key=lambda item: item[0])
    return row if row and score >= threshold else None


def fail_topic_submission(client: Client, submission_id: str) -> None:
    """Mark an intake attempt failed without persisting sensitive diagnostics."""

    client.table("topic_submissions").update(
        {"status": "failed", "assessed_at": datetime.now(UTC).isoformat()}
    ).eq("id", submission_id).execute()


def retry_or_fail_topic_submission(
    client: Client, submission_id: str, attempt_count: int
) -> None:
    """Schedule a bounded retry, or mark a submission terminally failed."""

    terminal = attempt_count >= 3
    delay_minutes = min(2**attempt_count, 30)
    client.table("topic_submissions").update(
        {
            "status": "failed" if terminal else "submitted",
            "lease_expires_at": None,
            "next_attempt_at": (
                None
                if terminal
                else (datetime.now(UTC) + timedelta(minutes=delay_minutes)).isoformat()
            ),
            "assessed_at": datetime.now(UTC).isoformat() if terminal else None,
            "updated_at": datetime.now(UTC).isoformat(),
        }
    ).eq("id", submission_id).execute()


def claim_topic_submissions(client: Client, limit: int) -> list[ClaimedTopicSubmission]:
    """Atomically lease queued or abandoned submissions to one worker."""

    response = client.rpc("claim_topic_submissions", {"p_limit": limit}).execute()
    return [
        ClaimedTopicSubmission(
            submission_id=str(row["id"]),
            query=str(row["normalized_query"]),
            attempt_count=int(row["attempt_count"]),
        )
        for row in response.data or []
    ]


def save_topic_viability(
    client: Client,
    *,
    submission_id: str,
    assessment: TopicViabilityAssessment,
    signals: CoverageSignals,
    model_id: str,
    duplicate_topic_id: str | None = None,
) -> str | None:
    """Atomically save an assessment and create a topic only when accepted."""

    response = client.rpc(
        "save_topic_viability",
        {
            "p_submission_id": submission_id,
            "p_status": assessment.status.value,
            "p_confidence": assessment.confidence,
            "p_coverage_signals": signals.model_dump(mode="json"),
            "p_topic_definition": assessment.definition.model_dump(mode="json"),
            "p_reasons": assessment.reasons,
            "p_clarification_questions": assessment.clarification_questions,
            "p_duplicate_topic_id": duplicate_topic_id,
            "p_prompt_version": TOPIC_VIABILITY_PROMPT_VERSION,
            "p_model_id": model_id,
        },
    ).execute()
    return str(response.data) if response.data else None


def article_row(article: IngestedItem, topic_id: str | None) -> dict[str, Any]:
    """Convert a NewsAPI article into the existing ``raw_items`` shape."""

    return {
        "topic_id": topic_id,
        "source_name": article.source_name,
        "source_type": article.source_type,
        "ingestion_provider": article.provider,
        "title": article.title,
        "url": str(article.url),
        "author": article.author,
        "published_at": article.published_at.isoformat()
        if article.published_at
        else None,
        "raw_text": article.raw_text,
        "engagement_data": article.engagement_data,
        "external_id": article.external_id,
        "content_license": article.content_license,
        "attribution": article.attribution,
        "language": article.language,
        "status": "new",
    }


def is_duplicate_error(error: APIError) -> bool:
    """Return whether Postgres rejected a row for a unique constraint."""

    return error.code == "23505"


def insert_articles(
    client: Client, articles: list[IngestedItem], topic_id: str | None
) -> tuple[InsertSummary, list[StoredArticle]]:
    """Insert articles individually so one bad row cannot abort the batch."""

    summary = InsertSummary()
    stored: list[StoredArticle] = []
    for article in articles:
        try:
            response = (
                client.table("raw_items")
                .insert(article_row(article, topic_id))
                .execute()
            )
            if not response.data or "id" not in response.data[0]:
                raise ValueError("Supabase insert did not return a raw item id")
            summary.inserted += 1
            stored.append(
                StoredArticle(article=article, raw_item_id=str(response.data[0]["id"]))
            )
        except APIError as error:
            if is_duplicate_error(error):
                summary.skipped_duplicates += 1
                existing = (
                    client.table("raw_items")
                    .select("id,status,topic_id")
                    .eq("url", str(article.url))
                    .limit(1)
                    .execute()
                )
                if existing.data and existing.data[0].get("status") != "analyzed":
                    stored.append(
                        StoredArticle(
                            article=article,
                            raw_item_id=str(existing.data[0]["id"]),
                        )
                    )
                if (
                    topic_id
                    and existing.data
                    and existing.data[0].get("topic_id") is None
                ):
                    client.table("raw_items").update({"topic_id": topic_id}).eq(
                        "id", existing.data[0]["id"]
                    ).execute()
            else:
                summary.failed += 1
        except Exception:  # Supabase transport errors vary by client version.
            summary.failed += 1
    return summary, stored


def save_analysis(
    client: Client,
    raw_item_id: str,
    analysis: ArticleAnalysis,
    cleaned_text: str,
    model_id: str,
    prompt_version: str = CURRENT_PROMPT_VERSION,
) -> str:
    """Atomically persist analysis, claims, cleaned text, and final status."""

    payload = analysis.model_dump(mode="json", exclude={"claims", "short_summary"})
    payload["summary"] = analysis.short_summary
    response = client.rpc(
        "save_article_analysis",
        {
            "p_raw_item_id": raw_item_id,
            "p_analysis": payload,
            "p_claims": [claim.model_dump(mode="json") for claim in analysis.claims],
            "p_cleaned_text": cleaned_text,
            "p_model_id": model_id,
            "p_prompt_version": prompt_version,
        },
    ).execute()
    if not response.data:
        raise ValueError("Supabase transaction did not return an analysis id")
    return str(response.data)


def load_analyzed_items(
    client: Client,
    topic_id: str,
    period_start: str,
    period_end: str,
) -> list[AnalyzedItem]:
    """Load analyzed items for deterministic topic aggregation."""

    raw_response = (
        client.table("raw_items")
        .select("id,source_name,source_type,url,content_group_id,is_group_origin")
        .eq("topic_id", topic_id)
        .gte("fetched_at", period_start)
        .lte("fetched_at", period_end)
        .execute()
    )
    if not raw_response.data:
        return []
    raw_by_id = {str(row["id"]): row for row in raw_response.data}
    analysis_response = (
        client.table("analysis")
        .select(
            "id,raw_item_id,domain_profile,domain_analysis,stance,framing_tags,"
            "stance_confidence,"
            "loaded_language_score,one_sidedness_score,"
            "evidence_quality_score,emotionality_score"
        )
        .in_("raw_item_id", list(raw_by_id))
        .eq("is_current", True)
        .execute()
    )
    items: list[AnalyzedItem] = []
    for row in analysis_response.data:
        raw_item_id = str(row["raw_item_id"])
        raw = raw_by_id.get(raw_item_id)
        if raw:
            items.append(
                AnalyzedItem.model_validate(
                    {
                        **row,
                        "analysis_id": str(row["id"]),
                        "source_name": raw.get("source_name") or "Unknown",
                        "source_type": raw.get("source_type") or "news",
                        "url": str(raw["url"]),
                        "content_group_id": raw.get("content_group_id"),
                        "is_group_origin": raw.get("is_group_origin"),
                    }
                )
            )
    return items


def load_deduplication_items(
    client: Client,
    topic_id: str,
    period_start: str,
    period_end: str,
) -> list[DeduplicationItem]:
    """Load raw topic content required for source and content normalization."""

    response = (
        client.table("raw_items")
        .select(
            "id,url,source_name,source_type,title,cleaned_text,raw_text,"
            "published_at,fetched_at"
        )
        .eq("topic_id", topic_id)
        .gte("fetched_at", period_start)
        .lte("fetched_at", period_end)
        .execute()
    )
    return [
        DeduplicationItem.model_validate({**row, "raw_item_id": str(row["id"])})
        for row in response.data
    ]


def save_deduplication(client: Client, result: DeduplicationResult) -> int:
    """Persist normalized sources and group metadata without deleting raw items."""

    source_rows: dict[tuple[str, str], dict[str, str]] = {}
    for item in result.items:
        key = (item.normalized_domain, item.source_type)
        source_rows.setdefault(
            key,
            {
                "name": item.normalized_source_name,
                "domain": item.normalized_domain,
                "source_type": item.source_type,
            },
        )

    source_ids: dict[tuple[str, str], str] = {}
    for key, row in source_rows.items():
        response = (
            client.table("sources")
            .upsert(row, on_conflict="domain,source_type")
            .execute()
        )
        if not response.data or "id" not in response.data[0]:
            raise ValueError("Supabase upsert did not return a source id")
        source_ids[key] = str(response.data[0]["id"])

    deduplicated_at = datetime.now(UTC).isoformat()
    saved = 0
    for item in result.items:
        key = (item.normalized_domain, item.source_type)
        response = (
            client.table("raw_items")
            .update(
                {
                    "source_id": source_ids[key],
                    "canonical_url": item.canonical_url,
                    "normalized_domain": item.normalized_domain,
                    "content_hash": item.content_hash,
                    "content_simhash": item.content_simhash,
                    "content_group_id": item.content_group_id,
                    "is_group_origin": item.is_group_origin,
                    "deduplicated_at": deduplicated_at,
                }
            )
            .eq("id", item.raw_item_id)
            .execute()
        )
        if not response.data:
            raise ValueError(f"raw item {item.raw_item_id} was not updated")
        saved += 1
    return saved


def load_claims_for_items(client: Client, items: list[AnalyzedItem]) -> list[ClaimItem]:
    """Load claims linked to the current analysis versions in a report sample."""

    if not items:
        return []
    by_analysis = {item.analysis_id: item for item in items}
    response = (
        client.table("claims")
        .select(
            "id,analysis_id,raw_item_id,claim_text,claim_type,"
            "checkability,importance_score"
        )
        .in_("analysis_id", list(by_analysis))
        .execute()
    )
    claims: list[ClaimItem] = []
    for row in response.data:
        item = by_analysis.get(str(row["analysis_id"]))
        if item:
            claims.append(
                ClaimItem.model_validate(
                    {
                        **row,
                        "claim_id": str(row["id"]),
                        "analysis_id": str(row["analysis_id"]),
                        "raw_item_id": str(row["raw_item_id"]),
                        "source_name": item.source_name,
                        "content_group_id": item.content_group_id,
                    }
                )
            )
    return claims


def load_reanalysis_candidates(
    client: Client,
    topic_id: str,
    period_start: str,
    period_end: str,
    model_id: str,
    prompt_version: str = CURRENT_PROMPT_VERSION,
    only_stale: bool = True,
) -> list[ReanalysisCandidate]:
    """Load topic items whose current analysis is stale or explicitly requested."""

    raw_response = (
        client.table("raw_items")
        .select("id,title,url,source_name,source_type,author,raw_text,cleaned_text")
        .eq("topic_id", topic_id)
        .gte("fetched_at", period_start)
        .lte("fetched_at", period_end)
        .execute()
    )
    if not raw_response.data:
        return []
    raw_ids = [str(row["id"]) for row in raw_response.data]
    analysis_response = (
        client.table("analysis")
        .select("raw_item_id,analysis_version,prompt_version,model_id")
        .in_("raw_item_id", raw_ids)
        .eq("is_current", True)
        .execute()
    )
    current = {str(row["raw_item_id"]): row for row in analysis_response.data}
    candidates: list[ReanalysisCandidate] = []
    for row in raw_response.data:
        raw_item_id = str(row["id"])
        existing = current.get(raw_item_id)
        is_stale = not existing or (
            existing.get("prompt_version") != prompt_version
            or existing.get("model_id") != model_id
        )
        if only_stale and not is_stale:
            continue
        candidates.append(
            ReanalysisCandidate(
                raw_item_id=raw_item_id,
                title=str(row["title"]),
                url=str(row["url"]),
                source_name=str(row.get("source_name") or "Unknown"),
                source_type=str(row.get("source_type") or "news"),
                author=str(row["author"]) if row.get("author") else None,
                fallback_text=row.get("raw_text"),
                cleaned_text=row.get("cleaned_text"),
                current_version=(
                    int(existing["analysis_version"]) if existing else None
                ),
            )
        )
    return candidates


def save_topic_report(
    client: Client,
    report: TopicReport,
    pipeline_run_id: str | None = None,
) -> str:
    """Save a frontend-ready topic report and return its identifier."""

    distribution = report.stance_distribution
    row = {
        "topic_id": report.topic_id,
        "period_start": report.period_start.isoformat(),
        "period_end": report.period_end.isoformat(),
        "total_items": report.total_items,
        "pro_percent": distribution["pro_subject"],
        "anti_percent": distribution["anti_subject"],
        "neutral_percent": distribution["neutral"],
        "mixed_percent": distribution["mixed"],
        "unclear_percent": distribution["unclear"],
        "directional_pro_percent": report.directional_pro_percent,
        "directional_anti_percent": report.directional_anti_percent,
        "overall_bias_score": report.overall_bias_score,
        "confidence_score": report.confidence_score,
        "source_count": report.source_count,
        "independent_content_groups": report.independent_content_groups,
        "syndicated_items": report.syndicated_items,
        "deduplicated_items": report.deduplicated_items,
        "report_text": report.report_text,
        "report_data": report.model_dump(mode="json"),
        "pipeline_run_id": pipeline_run_id,
    }
    query = client.table("topic_reports")
    response = (
        query.upsert(row, on_conflict="pipeline_run_id").execute()
        if pipeline_run_id
        else query.insert(row).execute()
    )
    if not response.data or "id" not in response.data[0]:
        raise ValueError("Supabase insert did not return a topic report id")
    return str(response.data[0]["id"])


def begin_pipeline_run(
    client: Client,
    *,
    topic_id: str,
    idempotency_key: str,
    period_start: str,
    period_end: str,
    prompt_version: str,
    model_id: str,
) -> PipelineRun:
    """Atomically claim a run or return its already-completed result."""

    response = client.rpc(
        "begin_pipeline_run",
        {
            "p_topic_id": topic_id,
            "p_idempotency_key": idempotency_key,
            "p_period_start": period_start,
            "p_period_end": period_end,
            "p_prompt_version": prompt_version,
            "p_model_id": model_id,
        },
    ).execute()
    row = response.data[0] if isinstance(response.data, list) else response.data
    if not row or "id" not in row:
        raise ValueError("Supabase did not return a pipeline run")
    return PipelineRun(
        run_id=str(row["id"]),
        status=str(row["status"]),
        report_id=str(row["report_id"]) if row.get("report_id") else None,
        period_start=str(row["period_start"]),
        period_end=str(row["period_end"]),
    )


def finish_pipeline_run(
    client: Client,
    run_id: str,
    *,
    status: str,
    counters: dict[str, int],
    provider_errors: list[str],
    report_id: str | None = None,
    error_summary: str | None = None,
) -> None:
    """Finish a claimed run with bounded, sanitized audit information."""

    if status not in {"completed", "failed"}:
        raise ValueError("pipeline run can finish only as completed or failed")
    response = (
        client.table("pipeline_runs")
        .update(
            {
                "status": status,
                "counters": counters,
                "provider_errors": provider_errors[:20],
                "report_id": report_id,
                "error_summary": error_summary[:500] if error_summary else None,
                "finished_at": datetime.now(UTC).isoformat(),
            }
        )
        .eq("id", run_id)
        .eq("status", "running")
        .execute()
    )
    if not response.data:
        raise ValueError("pipeline run was not active when finishing")


def heartbeat_pipeline_run(client: Client, run_id: str) -> None:
    """Renew an active run lease so crashed jobs can later be reclaimed."""

    response = (
        client.table("pipeline_runs")
        .update({"heartbeat_at": datetime.now(UTC).isoformat()})
        .eq("id", run_id)
        .eq("status", "running")
        .execute()
    )
    if not response.data:
        raise ValueError("pipeline run lease is no longer active")


def load_checked_claim_ids(client: Client, claim_ids: list[str]) -> set[str]:
    """Return claim identifiers that already have a stored check."""

    if not claim_ids:
        return set()
    response = (
        client.table("claim_checks")
        .select("claim_id")
        .in_("claim_id", claim_ids)
        .execute()
    )
    return {str(row["claim_id"]) for row in response.data}


def load_claim_checks(client: Client, claim_ids: list[str]) -> list[ClaimCheckItem]:
    """Load stored fact checks for report enrichment."""

    if not claim_ids:
        return []
    response = (
        client.table("claim_checks")
        .select(
            "claim_id,verdict,confidence,evidence_summary,evidence_urls,"
            "provider,method_version,match_score,evidence_data"
        )
        .in_("claim_id", claim_ids)
        .execute()
    )
    return [ClaimCheckItem.model_validate(row) for row in response.data]


def save_claim_check(
    client: Client,
    claim_id: str,
    result: FactCheckResult | EvidenceVerificationResult,
    provider: str = "google_fact_check_tools",
    method_version: str = FACT_CHECK_METHOD_VERSION,
) -> str:
    """Insert or refresh the provider check for an immutable versioned claim."""

    response = (
        client.table("claim_checks")
        .upsert(
            {
                "claim_id": claim_id,
                "verdict": result.verdict.value,
                "confidence": result.confidence,
                "evidence_summary": result.evidence_summary,
                "evidence_urls": result.evidence_urls,
                "notes": result.notes,
                "provider": provider,
                "method_version": method_version,
                "matched_claim_text": result.matched_claim_text,
                "match_score": result.match_score,
                "evidence_data": result.model_dump(mode="json"),
                "checked_at": datetime.now(UTC).isoformat(),
            },
            on_conflict="claim_id",
        )
        .execute()
    )
    if not response.data or "id" not in response.data[0]:
        raise ValueError("Supabase upsert did not return a claim check id")
    return str(response.data[0]["id"])


def save_primary_evidence_candidate(
    client: Client,
    *,
    claim_id: str,
    candidate: PrimaryEvidenceCandidate,
    model_id: str,
) -> str:
    """Persist a candidate and an immutable versioned automated assessment."""

    response = (
        client.table("evidence_candidates")
        .upsert(
            {
                "claim_id": claim_id,
                "url": candidate.url,
                "canonical_url": candidate.canonical_url,
                "title": candidate.title,
                "publisher": candidate.publisher,
                "published_at": candidate.published_at,
                "source_domain": candidate.source_domain,
                "content_hash": candidate.content_hash,
                "discovery_method": candidate.discovery_method,
            },
            on_conflict="claim_id,canonical_url",
        )
        .execute()
    )
    if not response.data or "id" not in response.data[0]:
        raise ValueError("Supabase did not return an evidence candidate id")
    candidate_id = str(response.data[0]["id"])
    existing = (
        client.table("evidence_automated_assessments")
        .select("id")
        .eq("evidence_candidate_id", candidate_id)
        .eq("method_version", candidate.discovery_method)
        .eq("model_id", model_id)
        .limit(1)
        .execute()
    )
    if not existing.data:
        assessment = candidate.assessment
        client.table("evidence_automated_assessments").insert(
            {
                "evidence_candidate_id": candidate_id,
                "relation": assessment.relation.value,
                "source_role": assessment.source_role.value,
                "relevance_score": assessment.relevance_score,
                "excerpt": assessment.excerpt,
                "reasoning": assessment.reasoning,
                "method_version": candidate.discovery_method,
                "model_id": model_id,
            }
        ).execute()
    return candidate_id
