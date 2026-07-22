"""FastAPI application exposing safe, frontend-ready BiasRadar reads."""

import hashlib
import re
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from typing import Annotated
from uuid import UUID

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, status
from fastapi.middleware.cors import CORSMiddleware

from biasradar.api.models import (
    EvidenceCandidateResponse,
    EvidenceListResponse,
    EvidenceReviewRequest,
    EvidenceReviewResponse,
    HealthResponse,
    IncidentListResponse,
    IncidentView,
    NarrativeHistoryPoint,
    NarrativeResponse,
    ReportListResponse,
    ReportSummary,
    TimelinePoint,
    TimelineResponse,
    TopicListResponse,
    TopicOverviewResponse,
    TopicSubmissionRequest,
    TopicSubmissionResponse,
    TopicSummary,
    VisualizationMetric,
)
from biasradar.api.repository import ReadRepository, SupabaseReadRepository
from biasradar.config import APISettings, get_api_settings

IDEMPOTENCY_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{8,200}$")
TOKEN_PATTERN = re.compile(r"[a-z0-9]+")


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


def _overview(topic_row: dict[str, object], report: dict[str, object]):
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
            "domain_profile": report_data.get("domain_profile", "generic-v1"),
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
            "repeated_claim_count": len(report_data.get("repeated_claim_clusters", [])),
            "fact_check_summary": report_data.get("fact_check_summary", {}),
            "verified_findings": report_data.get("verified_findings", []),
            "football_summary": report_data.get("football_summary"),
            "methodology": report_data.get("methodology", "Not recorded."),
            "limitations": report_data.get("limitations", []),
            "summary": report["report_text"],
        }
    )


def _tokens(value: str) -> set[str]:
    return set(TOKEN_PATTERN.findall(value.casefold()))


def _similar(left: str, right: str) -> float:
    left_tokens, right_tokens = _tokens(left), _tokens(right)
    union = left_tokens | right_tokens
    return len(left_tokens & right_tokens) / len(union) if union else 0.0


def _narrative_metrics(
    summary: dict[str, object],
    confidence: float,
    previous: dict[str, object] | None = None,
) -> list[VisualizationMetric]:
    distribution = summary.get("stance_distribution") or {}
    counts = summary.get("stance_counts") or {}
    previous_distribution = (previous or {}).get("stance_distribution") or {}
    analyzed = int(summary.get("analyzed_items") or 0)
    return [
        VisualizationMetric(
            label=str(label),
            percentage=float(percentage),
            item_count=int(
                counts.get(label, round(analyzed * float(percentage) / 100))
            ),
            confidence=confidence,
            trend=(
                round(float(percentage) - float(previous_distribution.get(label, 0)), 1)
                if previous
                else None
            ),
        )
        for label, percentage in distribution.items()
    ]


def _submission(row: dict[str, object]) -> TopicSubmissionResponse:
    assessments = row.get("topic_viability_assessments") or []
    assessment = (
        assessments
        if isinstance(assessments, dict)
        else assessments[0]
        if assessments
        else None
    )
    return TopicSubmissionResponse.model_validate(
        {
            "id": row["id"],
            "status": row["status"],
            "query": row["normalized_query"],
            "topic_id": row.get("topic_id"),
            "attempt_count": row.get("attempt_count", 0),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "assessed_at": row.get("assessed_at"),
            "assessment": assessment,
        }
    )


def _user_id(authorization: str | None, repository: ReadRepository) -> str:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="authentication required")
    token = authorization.removeprefix("Bearer ").strip()
    if not token:
        raise HTTPException(status_code=401, detail="authentication required")
    try:
        user_id = repository.authenticate(token)
    except Exception as error:
        raise HTTPException(status_code=401, detail="invalid authentication") from error
    if not user_id:
        raise HTTPException(status_code=401, detail="invalid authentication")
    return user_id


def _reviewer_id(authorization: str | None, repository: ReadRepository) -> str:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="reviewer authentication required")
    try:
        reviewer_id = repository.authenticate_reviewer(
            authorization.removeprefix("Bearer ").strip()
        )
    except Exception as error:
        raise HTTPException(
            status_code=401, detail="invalid reviewer authentication"
        ) from error
    if not reviewer_id:
        raise HTTPException(status_code=403, detail="evidence reviewer role required")
    return reviewer_id


def _evidence(row: dict[str, object]) -> EvidenceCandidateResponse:
    automated = row.get("evidence_automated_assessments") or []
    return EvidenceCandidateResponse.model_validate(
        {
            "id": row["id"],
            "claim_id": row["claim_id"],
            "url": row["url"],
            "title": row["title"],
            "publisher": row["publisher"],
            "published_at": row.get("published_at"),
            "source_domain": row["source_domain"],
            "review_status": row["review_status"],
            "retrieved_at": row["retrieved_at"],
            "automated_assessments": automated
            if isinstance(automated, list)
            else [automated],
        }
    )


def _consume_intake_rate(
    repository: ReadRepository,
    user_id: str,
    request: Request,
    limit: int,
) -> None:
    client_ip = request.client.host if request.client else "unknown"
    identities = (f"user:{user_id}", f"ip:{client_ip}")
    try:
        allowed = all(
            repository.consume_intake_rate(
                hashlib.sha256(identity.encode()).hexdigest(), limit
            )
            for identity in identities
        )
    except Exception as error:
        raise HTTPException(status_code=503, detail="intake unavailable") from error
    if not allowed:
        raise HTTPException(status_code=429, detail="topic intake rate limit exceeded")


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
        allow_methods=["GET", "POST"],
        allow_headers=["Accept", "Authorization", "Content-Type", "Idempotency-Key"],
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

        return _overview(topic_row, report)

    @application.get(
        "/topics/{topic_id}/incidents",
        response_model=IncidentListResponse,
        tags=["football"],
    )
    def topic_incidents(
        topic_id: UUID,
        repository: Annotated[ReadRepository, Depends(get_repository)],
        days: int = Query(30, ge=1, le=3650),
        limit: int = Query(500, ge=1, le=1000),
    ) -> IncidentListResponse:
        period_end = datetime.now(UTC)
        period_start = period_end - timedelta(days=days)
        try:
            if not repository.get_topic(str(topic_id)):
                raise HTTPException(status_code=404, detail="topic not found")
            rows = repository.list_topic_domain_analyses(
                str(topic_id), period_start.isoformat(), limit
            )
            report = repository.get_latest_report(
                str(topic_id), period_start.isoformat()
            )
        except HTTPException:
            raise
        except Exception as error:
            raise HTTPException(
                status_code=503, detail="database unavailable"
            ) from error

        clusters: list[dict[str, object]] = []
        for row in rows:
            analysis = row.get("domain_analysis") or {}
            for incident in analysis.get("incidents", []):
                description = str(incident.get("description") or "").strip()
                if not description:
                    continue
                cluster = next(
                    (
                        value
                        for value in clusters
                        if value["type"] == incident.get("controversy_type")
                        and _similar(str(value["description"]), description) >= 0.55
                    ),
                    None,
                )
                if cluster is None:
                    cluster = {
                        "type": incident.get("controversy_type") or "other_football",
                        "description": description,
                        "minute": incident.get("match_minute"),
                        "decision": incident.get("on_field_decision"),
                        "review": incident.get("review_outcome"),
                        "items": set(),
                        "sources": set(),
                        "groups": set(),
                        "channels": {},
                    }
                    clusters.append(cluster)
                cluster["items"].add(str(row["raw_item_id"]))
                cluster["sources"].add(str(row.get("source_name") or "Unknown"))
                cluster["groups"].add(
                    str(row.get("content_group_id") or row["raw_item_id"])
                )
                channel = str(row.get("source_type") or "news")
                cluster["channels"][channel] = cluster["channels"].get(channel, 0) + 1

        football_summary = ((report or {}).get("report_data") or {}).get(
            "football_summary"
        ) or {}
        consensus = football_summary.get("consensus_results", [])
        items = []
        for cluster in clusters:
            matching_consensus = [
                value
                for value in consensus
                if _similar(
                    str(value.get("incident_ref") or ""),
                    str(cluster["description"]),
                )
                >= 0.4
            ]
            identity_description = (
                " ".join(sorted(_tokens(str(cluster["description"]))))
                if cluster["minute"] is None and not cluster["decision"]
                else ""
            )
            key = (
                f"{cluster['type']}:{cluster['minute']}:{cluster['decision']}:"
                f"{cluster['review']}:{identity_description}"
            )
            item_count = len(cluster["items"])
            independent_groups = len(cluster["groups"])
            items.append(
                IncidentView(
                    incident_id=hashlib.sha256(key.encode()).hexdigest()[:16],
                    controversy_type=str(cluster["type"]),
                    description=str(cluster["description"]),
                    match_minute=cluster["minute"],
                    on_field_decision=cluster["decision"],
                    review_outcome=cluster["review"],
                    item_count=item_count,
                    source_count=len(cluster["sources"]),
                    independent_content_groups=independent_groups,
                    syndicated_items=item_count - independent_groups,
                    channel_counts=cluster["channels"],
                    consensus=matching_consensus,
                )
            )
        items.sort(key=lambda item: (item.item_count, item.source_count), reverse=True)
        return IncidentListResponse(
            topic_id=topic_id,
            period_start=period_start,
            period_end=period_end,
            items=items,
            limitations=[
                "Incidents are model-extracted and lexically clustered.",
                "Consensus describes attributed judgments, not verified match facts.",
            ],
        )

    @application.get(
        "/topics/{topic_id}/narratives",
        response_model=NarrativeResponse,
        tags=["football"],
    )
    def topic_narratives(
        topic_id: UUID,
        repository: Annotated[ReadRepository, Depends(get_repository)],
        days: int = Query(365, ge=1, le=3650),
        limit: int = Query(100, ge=1, le=365),
    ) -> NarrativeResponse:
        cutoff = datetime.now(UTC) - timedelta(days=days)
        try:
            if not repository.get_topic(str(topic_id)):
                raise HTTPException(status_code=404, detail="topic not found")
            rows = repository.list_reports(str(topic_id), cutoff.isoformat(), limit, 0)
        except HTTPException:
            raise
        except Exception as error:
            raise HTTPException(
                status_code=503, detail="database unavailable"
            ) from error
        if not rows:
            raise HTTPException(status_code=404, detail="no narrative reports found")
        chronological = list(reversed(rows))
        history = []
        previous_summary = None
        for row in chronological:
            summary = (row.get("report_data") or {}).get("football_summary") or {}
            history.append(
                NarrativeHistoryPoint(
                    report_id=row["id"],
                    timestamp=row["period_end"],
                    metrics=_narrative_metrics(
                        summary, float(row["confidence_score"]), previous_summary
                    ),
                )
            )
            previous_summary = summary
        latest = rows[0]
        latest_summary = (latest.get("report_data") or {}).get("football_summary") or {}
        previous = (
            (rows[1].get("report_data") or {}).get("football_summary") or {}
            if len(rows) > 1
            else None
        )
        return NarrativeResponse(
            topic_id=topic_id,
            period_start=latest["period_start"],
            period_end=latest["period_end"],
            metrics=_narrative_metrics(
                latest_summary, float(latest["confidence_score"]), previous
            ),
            controversy_type_counts=latest_summary.get("controversy_type_counts", {}),
            content_mode_counts=latest_summary.get("content_mode_counts", {}),
            framing_tag_counts=latest_summary.get("framing_tag_counts", {}),
            consensus=latest_summary.get("consensus_results", []),
            history=history,
        )

    @application.get(
        "/topics/{topic_id}/reports",
        response_model=ReportListResponse,
        tags=["reports"],
    )
    def report_history(
        topic_id: UUID,
        repository: Annotated[ReadRepository, Depends(get_repository)],
        days: int = Query(365, ge=1, le=3650),
        limit: int = Query(50, ge=1, le=100),
        offset: int = Query(0, ge=0, le=10_000),
    ) -> ReportListResponse:
        cutoff = datetime.now(UTC) - timedelta(days=days)
        try:
            if not repository.get_topic(str(topic_id)):
                raise HTTPException(status_code=404, detail="topic not found")
            rows = repository.list_reports(
                str(topic_id), cutoff.isoformat(), limit, offset
            )
        except HTTPException:
            raise
        except Exception as error:
            raise HTTPException(
                status_code=503, detail="database unavailable"
            ) from error
        return ReportListResponse(
            items=[
                ReportSummary.model_validate(
                    {
                        "id": row["id"],
                        "period_start": row["period_start"],
                        "period_end": row["period_end"],
                        "total_items": row["total_items"],
                        "independent_content_groups": row["independent_content_groups"],
                        "overall_bias_score": row["overall_bias_score"],
                        "confidence_score": row["confidence_score"],
                    }
                )
                for row in rows
            ],
            limit=limit,
            offset=offset,
        )

    @application.get(
        "/topics/{topic_id}/reports/{report_id}",
        response_model=TopicOverviewResponse,
        tags=["reports"],
    )
    def report_detail(
        topic_id: UUID,
        report_id: UUID,
        repository: Annotated[ReadRepository, Depends(get_repository)],
    ) -> TopicOverviewResponse:
        try:
            topic_row = repository.get_topic(str(topic_id))
            report = repository.get_report(str(topic_id), str(report_id))
        except Exception as error:
            raise HTTPException(
                status_code=503, detail="database unavailable"
            ) from error
        if not topic_row:
            raise HTTPException(status_code=404, detail="topic not found")
        if not report:
            raise HTTPException(status_code=404, detail="report not found")
        return _overview(topic_row, report)

    @application.get(
        "/topics/{topic_id}/timeline",
        response_model=TimelineResponse,
        tags=["reports"],
    )
    def timeline(
        topic_id: UUID,
        repository: Annotated[ReadRepository, Depends(get_repository)],
        days: int = Query(365, ge=1, le=3650),
        limit: int = Query(365, ge=1, le=1000),
    ) -> TimelineResponse:
        cutoff = datetime.now(UTC) - timedelta(days=days)
        try:
            if not repository.get_topic(str(topic_id)):
                raise HTTPException(status_code=404, detail="topic not found")
            rows = repository.list_reports(str(topic_id), cutoff.isoformat(), limit, 0)
        except HTTPException:
            raise
        except Exception as error:
            raise HTTPException(
                status_code=503, detail="database unavailable"
            ) from error
        points = []
        for row in reversed(rows):
            report_data = row.get("report_data") or {}
            points.append(
                TimelinePoint(
                    report_id=row["id"],
                    timestamp=row["period_end"],
                    toward_percent=row["directional_pro_percent"],
                    against_percent=row["directional_anti_percent"],
                    bias_score=row["overall_bias_score"],
                    confidence=row["confidence_score"],
                    independent_content_groups=row["independent_content_groups"],
                    channel_counts=report_data.get("channel_counts", {}),
                )
            )
        return TimelineResponse(topic_id=topic_id, points=points)

    @application.post(
        "/topic-submissions",
        response_model=TopicSubmissionResponse,
        status_code=status.HTTP_202_ACCEPTED,
        tags=["intake"],
    )
    def submit_topic(
        payload: TopicSubmissionRequest,
        request: Request,
        repository: Annotated[ReadRepository, Depends(get_repository)],
        authorization: Annotated[str | None, Header()] = None,
        idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
    ) -> TopicSubmissionResponse:
        content_length = request.headers.get("content-length", "0")
        if not content_length.isdigit() or int(content_length) > 4096:
            raise HTTPException(status_code=413, detail="request body too large")
        user_id = _user_id(authorization, repository)
        if not idempotency_key or not IDEMPOTENCY_PATTERN.fullmatch(idempotency_key):
            raise HTTPException(status_code=400, detail="invalid idempotency key")
        _consume_intake_rate(repository, user_id, request, config.api_topic_rate_limit)
        try:
            row = repository.enqueue_topic_submission(
                user_id, payload.query, idempotency_key
            )
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        except Exception as error:
            raise HTTPException(status_code=503, detail="intake unavailable") from error
        return _submission(row)

    @application.get(
        "/topic-submissions/{submission_id}",
        response_model=TopicSubmissionResponse,
        tags=["intake"],
    )
    def topic_submission_status(
        submission_id: UUID,
        repository: Annotated[ReadRepository, Depends(get_repository)],
        authorization: Annotated[str | None, Header()] = None,
    ) -> TopicSubmissionResponse:
        user_id = _user_id(authorization, repository)
        try:
            row = repository.get_topic_submission(user_id, str(submission_id))
        except Exception as error:
            raise HTTPException(status_code=503, detail="intake unavailable") from error
        if not row:
            raise HTTPException(status_code=404, detail="submission not found")
        return _submission(row)

    @application.post(
        "/topic-submissions/{submission_id}/retry",
        response_model=TopicSubmissionResponse,
        status_code=status.HTTP_202_ACCEPTED,
        tags=["intake"],
    )
    def retry_topic_submission_route(
        submission_id: UUID,
        request: Request,
        repository: Annotated[ReadRepository, Depends(get_repository)],
        authorization: Annotated[str | None, Header()] = None,
    ) -> TopicSubmissionResponse:
        user_id = _user_id(authorization, repository)
        _consume_intake_rate(repository, user_id, request, config.api_topic_rate_limit)
        try:
            row = repository.retry_topic_submission(user_id, str(submission_id))
        except Exception as error:
            raise HTTPException(status_code=503, detail="intake unavailable") from error
        if not row:
            raise HTTPException(
                status_code=409, detail="only an owned failed submission can retry"
            )
        return _submission(row)

    @application.get(
        "/claims/{claim_id}/evidence",
        response_model=EvidenceListResponse,
        tags=["evidence"],
    )
    def claim_evidence(
        claim_id: UUID,
        repository: Annotated[ReadRepository, Depends(get_repository)],
        limit: int = Query(20, ge=1, le=100),
        offset: int = Query(0, ge=0, le=10_000),
    ) -> EvidenceListResponse:
        try:
            rows = repository.list_claim_evidence(str(claim_id), limit, offset)
        except Exception as error:
            raise HTTPException(
                status_code=503, detail="evidence unavailable"
            ) from error
        return EvidenceListResponse(
            items=[_evidence(row) for row in rows], limit=limit, offset=offset
        )

    @application.get(
        "/review/evidence",
        response_model=EvidenceListResponse,
        tags=["review"],
    )
    def review_evidence_queue(
        repository: Annotated[ReadRepository, Depends(get_repository)],
        authorization: Annotated[str | None, Header()] = None,
        review_status: str = Query(
            "pending",
            alias="status",
            pattern="^(pending|approved|rejected|needs_more_evidence)$",
        ),
        limit: int = Query(20, ge=1, le=100),
        offset: int = Query(0, ge=0, le=10_000),
    ) -> EvidenceListResponse:
        _reviewer_id(authorization, repository)
        try:
            rows = repository.list_review_evidence(review_status, limit, offset)
        except Exception as error:
            raise HTTPException(
                status_code=503, detail="evidence unavailable"
            ) from error
        return EvidenceListResponse(
            items=[_evidence(row) for row in rows], limit=limit, offset=offset
        )

    @application.post(
        "/review/evidence/{candidate_id}/decision",
        response_model=EvidenceReviewResponse,
        tags=["review"],
    )
    def review_evidence_decision(
        candidate_id: UUID,
        payload: EvidenceReviewRequest,
        repository: Annotated[ReadRepository, Depends(get_repository)],
        authorization: Annotated[str | None, Header()] = None,
    ) -> EvidenceReviewResponse:
        reviewer_id = _reviewer_id(authorization, repository)
        try:
            review_id = repository.submit_evidence_review(
                str(candidate_id), reviewer_id, payload.model_dump(mode="json")
            )
        except Exception as error:
            raise HTTPException(status_code=503, detail="review unavailable") from error
        return EvidenceReviewResponse(
            review_id=review_id,
            candidate_id=candidate_id,
            decision=payload.decision,
        )

    return application


app = create_app()
