"""FastAPI application exposing safe, frontend-ready BiasRadar reads."""

from datetime import UTC, datetime, timedelta
from functools import lru_cache
from typing import Annotated
from uuid import UUID

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from biasradar.api_models import (
    HealthResponse,
    TopicListResponse,
    TopicOverviewResponse,
    TopicSummary,
)
from biasradar.api_repository import ReadRepository, SupabaseReadRepository
from biasradar.config import APISettings, get_api_settings


@lru_cache
def get_repository() -> ReadRepository:
    """Create the server-side read repository lazily."""

    return SupabaseReadRepository(get_api_settings())


def _topic(row: dict[str, object]) -> TopicSummary:
    return TopicSummary.model_validate(
        {
            "id": row["id"],
            "name": row["name"],
            "status": row["status"],
            "keywords": row.get("keywords") or [],
        }
    )


def create_app(settings: APISettings | None = None) -> FastAPI:
    """Create the API without connecting to external services at import time."""

    config = settings or get_api_settings()
    application = FastAPI(
        title="BiasRadar AI Read API",
        version="0.1.0",
        description="Read-only, allow-listed topic analytics for the BiasRadar UI.",
    )
    application.add_middleware(
        CORSMiddleware,
        allow_origins=config.cors_origins,
        allow_credentials=False,
        allow_methods=["GET"],
        allow_headers=["Accept", "Content-Type"],
    )

    @application.get("/health", response_model=HealthResponse, tags=["system"])
    def health(
        repository: Annotated[ReadRepository, Depends(get_repository)],
    ) -> HealthResponse:
        try:
            repository.health()
        except Exception as error:
            raise HTTPException(
                status_code=503, detail="database unavailable"
            ) from error
        return HealthResponse()

    @application.get("/topics", response_model=TopicListResponse, tags=["topics"])
    def topics(
        repository: Annotated[ReadRepository, Depends(get_repository)],
        limit: int = Query(20, ge=1, le=100),
        offset: int = Query(0, ge=0, le=10_000),
    ) -> TopicListResponse:
        try:
            rows = repository.list_topics(limit, offset)
        except Exception as error:
            raise HTTPException(
                status_code=503, detail="database unavailable"
            ) from error
        return TopicListResponse(
            items=[_topic(row) for row in rows], limit=limit, offset=offset
        )

    @application.get(
        "/topics/{topic_id}/overview",
        response_model=TopicOverviewResponse,
        tags=["topics"],
    )
    def topic_overview(
        topic_id: UUID,
        repository: Annotated[ReadRepository, Depends(get_repository)],
        days: int = Query(30, ge=1, le=3650),
    ) -> TopicOverviewResponse:
        try:
            topic_row = repository.get_topic(str(topic_id))
            if not topic_row:
                raise HTTPException(status_code=404, detail="topic not found")
            cutoff = datetime.now(UTC) - timedelta(days=days)
            report = repository.get_latest_report(str(topic_id), cutoff.isoformat())
        except HTTPException:
            raise
        except Exception as error:
            raise HTTPException(
                status_code=503, detail="database unavailable"
            ) from error
        if not report:
            raise HTTPException(
                status_code=404, detail="no report found in the requested period"
            )

        report_data = report.get("report_data") or {}
        stance = {
            "pro_subject": report["pro_percent"],
            "anti_subject": report["anti_percent"],
            "neutral": report["neutral_percent"],
            "mixed": report["mixed_percent"],
            "unclear": report["unclear_percent"],
        }
        return TopicOverviewResponse.model_validate(
            {
                "topic": _topic(topic_row),
                "report_id": report["id"],
                "period_start": report["period_start"],
                "period_end": report["period_end"],
                "total_items": report["total_items"],
                "source_count": report["source_count"],
                "independent_content_groups": report["independent_content_groups"],
                "syndicated_items": report["syndicated_items"],
                "channel_counts": report_data.get("channel_counts", {}),
                "stance_distribution": stance,
                "directional_pro_percent": report["directional_pro_percent"],
                "directional_anti_percent": report["directional_anti_percent"],
                "overall_bias_score": report["overall_bias_score"],
                "confidence_score": report["confidence_score"],
                "confidence_level": report_data.get("confidence_level", "low"),
                "repeated_claim_count": len(
                    report_data.get("repeated_claim_clusters", [])
                ),
                "fact_check_summary": report_data.get("fact_check_summary", {}),
                "methodology": report_data.get("methodology", "Not recorded."),
                "limitations": report_data.get("limitations", []),
                "summary": report["report_text"],
            }
        )

    return application


app = create_app()
