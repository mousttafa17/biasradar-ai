"""Supabase access helpers for topics and raw news items."""

from dataclasses import dataclass
from typing import Any

from postgrest.exceptions import APIError
from supabase import Client, create_client

from biasradar.analyzer import ArticleAnalysis
from biasradar.config import Settings, get_settings
from biasradar.news_fetcher import NewsArticle


@dataclass(slots=True)
class InsertSummary:
    """Counters produced while storing fetched articles."""

    inserted: int = 0
    skipped_duplicates: int = 0
    failed: int = 0


@dataclass(slots=True)
class StoredArticle:
    """An inserted article and the generated database identifier."""

    article: NewsArticle
    raw_item_id: str


def get_supabase(settings: Settings | None = None) -> Client:
    """Create a Supabase client from application settings."""

    config = settings or get_settings()
    return create_client(config.supabase_url, config.supabase_service_key)


def find_topic_id(client: Client, topic_name: str) -> str | None:
    """Find a topic by exact name, returning ``None`` when absent."""

    response = (
        client.table("topics").select("id").eq("name", topic_name).limit(1).execute()
    )
    if not response.data:
        return None
    return str(response.data[0]["id"])


def article_row(article: NewsArticle, topic_id: str | None) -> dict[str, Any]:
    """Convert a NewsAPI article into the existing ``raw_items`` shape."""

    return {
        "topic_id": topic_id,
        "source_name": article.source_name,
        "source_type": "news",
        "title": article.title,
        "url": str(article.url),
        "author": article.author,
        "published_at": article.published_at.isoformat()
        if article.published_at
        else None,
        "raw_text": article.raw_text,
        "language": "en",
        "status": "new",
    }


def is_duplicate_error(error: APIError) -> bool:
    """Return whether Postgres rejected a row for a unique constraint."""

    return error.code == "23505"


def insert_articles(
    client: Client, articles: list[NewsArticle], topic_id: str | None
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
                    .select("id,status")
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
) -> str:
    """Persist an article analysis and its extracted claims."""

    analysis_response = (
        client.table("analysis")
        .insert(
            {
                "raw_item_id": raw_item_id,
                "stance": analysis.stance.value,
                "stance_confidence": analysis.stance_confidence,
                "bias_direction": analysis.bias_direction,
                "bias_score": analysis.bias_score,
                "loaded_language_score": analysis.loaded_language_score,
                "one_sidedness_score": analysis.one_sidedness_score,
                "evidence_quality_score": analysis.evidence_quality_score,
                "emotionality_score": analysis.emotionality_score,
                "missing_counterarguments": analysis.missing_counterarguments,
                "loaded_terms": analysis.loaded_terms,
                "summary": analysis.short_summary,
                "reasoning": analysis.reasoning,
            }
        )
        .execute()
    )
    if not analysis_response.data or "id" not in analysis_response.data[0]:
        raise ValueError("Supabase insert did not return an analysis id")

    analysis_id = str(analysis_response.data[0]["id"])
    if analysis.claims:
        client.table("claims").insert(
            [
                {
                    "raw_item_id": raw_item_id,
                    "claim_text": claim.claim_text,
                    "claim_type": claim.claim_type.value,
                    "checkability": claim.checkability.value,
                    "importance_score": claim.importance_score,
                }
                for claim in analysis.claims
            ]
        ).execute()

    client.table("raw_items").update(
        {"cleaned_text": cleaned_text, "status": "analyzed"}
    ).eq("id", raw_item_id).execute()
    return analysis_id
