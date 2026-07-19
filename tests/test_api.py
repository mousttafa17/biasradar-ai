from uuid import UUID

from fastapi.testclient import TestClient

from biasradar.api import create_app, get_repository
from biasradar.config import APISettings

TOPIC_ID = "11111111-1111-4111-8111-111111111111"
REPORT_ID = "22222222-2222-4222-8222-222222222222"
SUBMISSION_ID = "33333333-3333-4333-8333-333333333333"
CLAIM_ID = "44444444-4444-4444-8444-444444444444"
CANDIDATE_ID = "55555555-5555-4555-8555-555555555555"
REVIEW_ID = "66666666-6666-4666-8666-666666666666"


class FakeRepository:
    def __init__(self) -> None:
        self.healthy = True
        self.rate_allowed = True
        self.submission_status = "submitted"

    def health(self) -> None:
        if not self.healthy:
            raise RuntimeError("secret database details")

    def list_topics(self, limit: int, offset: int):
        return [self.get_topic(TOPIC_ID)]

    def get_topic(self, topic_id: str):
        if topic_id != TOPIC_ID:
            return None
        return {
            "id": TOPIC_ID,
            "name": "Example topic",
            "status": "active",
            "keywords": ["example"],
            "internal_notes": "must not leak",
        }

    def get_latest_report(self, topic_id: str, period_start: str):
        if topic_id != TOPIC_ID:
            return None
        return {
            "id": REPORT_ID,
            "period_start": "2026-07-01T00:00:00Z",
            "period_end": "2026-07-18T00:00:00Z",
            "total_items": 12,
            "source_count": 7,
            "independent_content_groups": 10,
            "syndicated_items": 2,
            "pro_percent": 60,
            "anti_percent": 30,
            "neutral_percent": 5,
            "mixed_percent": 5,
            "unclear_percent": 0,
            "directional_pro_percent": 66.7,
            "directional_anti_percent": 33.3,
            "overall_bias_score": 18.2,
            "confidence_score": 0.72,
            "report_text": "Public summary.",
            "model_reasoning": "must not leak",
            "report_data": {
                "domain_profile": "football-v1",
                "channel_counts": {"news": 8, "rss": 4},
                "confidence_level": "moderate",
                "repeated_claim_clusters": [{"cluster_key": "one"}],
                "fact_check_summary": {"supported": 1},
                "verified_findings": ["Evidence supports: Example finding"],
                "football_summary": {
                    "analyzed_items": 12,
                    "stance_distribution": {"criticizes_referee": 60.0},
                    "controversy_type_counts": {"VAR_decision": 8},
                    "content_mode_counts": {"neutral_match_reporting": 4},
                    "framing_tag_counts": {"fan_emotion": 3},
                    "teams": {"Argentina": 10},
                    "referees": {"Example Referee": 6},
                    "federations": {"FIFA": 4},
                    "attributed_expert_opinions": 5,
                },
                "methodology": "Channel-balanced aggregation.",
                "limitations": ["Sample limitation."],
            },
        }

    def list_reports(self, topic_id: str, period_start: str, limit: int, offset: int):
        report = self.get_latest_report(topic_id, period_start)
        return [report] if report else []

    def get_report(self, topic_id: str, report_id: str):
        report = self.get_latest_report(topic_id, "")
        return report if report and report_id == REPORT_ID else None

    def authenticate(self, token: str):
        return "user-1" if token == "valid-token" else None

    def authenticate_reviewer(self, token: str):
        return "reviewer-1" if token == "reviewer-token" else None

    def consume_intake_rate(self, identity_hash: str, limit: int):
        return self.rate_allowed

    def _submission(self):
        return {
            "id": SUBMISSION_ID,
            "status": self.submission_status,
            "normalized_query": "Is media coverage unfairly portraying nuclear energy?",
            "topic_id": None,
            "attempt_count": 0,
            "created_at": "2026-07-19T10:00:00Z",
            "updated_at": "2026-07-19T10:00:00Z",
            "assessed_at": None,
            "topic_viability_assessments": [],
        }

    def enqueue_topic_submission(self, user_id: str, query: str, idempotency_key: str):
        return self._submission()

    def get_topic_submission(self, user_id: str, submission_id: str):
        return self._submission() if submission_id == SUBMISSION_ID else None

    def retry_topic_submission(self, user_id: str, submission_id: str):
        if submission_id != SUBMISSION_ID or self.submission_status != "failed":
            return None
        self.submission_status = "submitted"
        return self._submission()

    def _evidence(self, review_status="pending"):
        return {
            "id": CANDIDATE_ID,
            "claim_id": CLAIM_ID,
            "url": "https://official.example/record",
            "title": "Official record",
            "publisher": "Official Example",
            "published_at": "2026-07-18T00:00:00Z",
            "source_domain": "official.example",
            "review_status": review_status,
            "retrieved_at": "2026-07-19T00:00:00Z",
            "evidence_automated_assessments": [
                {
                    "relation": "supports",
                    "source_role": "primary_record",
                    "relevance_score": 0.9,
                    "excerpt": "Relevant official excerpt.",
                    "method_version": "official-domain-v1",
                    "model_id": "test-model",
                }
            ],
        }

    def list_claim_evidence(self, claim_id: str, limit: int, offset: int):
        return [self._evidence("approved")] if claim_id == CLAIM_ID else []

    def list_review_evidence(self, review_status: str, limit: int, offset: int):
        return [self._evidence()]

    def submit_evidence_review(
        self, candidate_id: str, reviewer_user_id: str, decision
    ):
        return REVIEW_ID


def _client(
    repository: FakeRepository | None = None,
) -> tuple[TestClient, FakeRepository]:
    fake = repository or FakeRepository()
    settings = APISettings(
        supabase_url="https://project.supabase.co",
        supabase_service_key="real-secret",
        api_cors_origins="http://localhost:3000",
    )
    app = create_app(settings)
    app.dependency_overrides[get_repository] = lambda: fake
    return TestClient(app), fake


def test_health_sanitizes_database_failures() -> None:
    client, repository = _client()
    repository.healthy = False

    response = client.get("/health")

    assert response.status_code == 503
    assert response.json() == {"detail": "database unavailable"}
    assert "secret" not in response.text


def test_topics_is_paginated_and_allow_listed() -> None:
    client, _ = _client()

    response = client.get("/topics?limit=10&offset=0")

    assert response.status_code == 200
    assert response.json()["limit"] == 10
    assert response.json()["items"][0]["name"] == "Example topic"
    assert "internal_notes" not in response.text


def test_overview_returns_frontend_ready_summary_without_internal_data() -> None:
    client, _ = _client()

    response = client.get(f"/topics/{TOPIC_ID}/overview?days=30")

    assert response.status_code == 200
    payload = response.json()
    assert payload["report_id"] == REPORT_ID
    assert payload["stance_distribution"]["pro_subject"] == 60
    assert payload["channel_counts"] == {"news": 8, "rss": 4}
    assert payload["repeated_claim_count"] == 1
    assert payload["domain_profile"] == "football-v1"
    assert payload["football_summary"]["controversy_type_counts"] == {"VAR_decision": 8}
    assert payload["verified_findings"] == ["Evidence supports: Example finding"]
    assert "model_reasoning" not in response.text


def test_invalid_topic_id_and_query_bounds_are_rejected() -> None:
    client, _ = _client()

    assert client.get("/topics/not-a-uuid/overview").status_code == 422
    assert client.get("/topics?limit=101").status_code == 422


def test_report_history_detail_and_timeline_are_frontend_ready() -> None:
    client, _ = _client()

    history = client.get(f"/topics/{TOPIC_ID}/reports").json()
    detail = client.get(f"/topics/{TOPIC_ID}/reports/{REPORT_ID}").json()
    timeline = client.get(f"/topics/{TOPIC_ID}/timeline").json()

    assert history["items"][0]["id"] == REPORT_ID
    assert detail["summary"] == "Public summary."
    assert timeline["points"][0] == {
        "report_id": REPORT_ID,
        "timestamp": "2026-07-18T00:00:00Z",
        "toward_percent": 66.7,
        "against_percent": 33.3,
        "bias_score": 18.2,
        "confidence": 0.72,
        "independent_content_groups": 10,
        "channel_counts": {"news": 8, "rss": 4},
    }


def test_authenticated_topic_submission_is_queued_without_running_assessment() -> None:
    client, _ = _client()

    response = client.post(
        "/topic-submissions",
        headers={
            "Authorization": "Bearer valid-token",
            "Idempotency-Key": "topic-request-001",
        },
        json={"query": "Is media coverage unfairly portraying nuclear energy?"},
    )

    assert response.status_code == 202
    assert response.json()["id"] == SUBMISSION_ID
    assert response.json()["status"] == "submitted"
    assert response.json()["assessment"] is None


def test_topic_submission_requires_auth_and_obeys_persistent_rate_limit() -> None:
    client, repository = _client()
    payload = {"query": "Is media coverage unfairly portraying nuclear energy?"}

    assert client.post("/topic-submissions", json=payload).status_code == 401
    repository.rate_allowed = False
    response = client.post(
        "/topic-submissions",
        headers={
            "Authorization": "Bearer valid-token",
            "Idempotency-Key": "topic-request-002",
        },
        json=payload,
    )
    assert response.status_code == 429


def test_submission_status_is_owner_scoped_and_only_failed_items_retry() -> None:
    client, repository = _client()
    headers = {"Authorization": "Bearer valid-token"}

    assert client.get(f"/topic-submissions/{SUBMISSION_ID}").status_code == 401
    assert (
        client.post(
            f"/topic-submissions/{SUBMISSION_ID}/retry", headers=headers
        ).status_code
        == 409
    )
    repository.submission_status = "failed"
    retry = client.post(f"/topic-submissions/{SUBMISSION_ID}/retry", headers=headers)
    assert retry.status_code == 202
    assert retry.json()["status"] == "submitted"


def test_claim_evidence_is_public_but_review_queue_requires_reviewer_role() -> None:
    client, _ = _client()

    evidence = client.get(f"/claims/{CLAIM_ID}/evidence")
    forbidden = client.get(
        "/review/evidence", headers={"Authorization": "Bearer valid-token"}
    )
    review_queue = client.get(
        "/review/evidence", headers={"Authorization": "Bearer reviewer-token"}
    )

    assert evidence.status_code == 200
    assert evidence.json()["items"][0]["source_domain"] == "official.example"
    assert forbidden.status_code == 403
    assert review_queue.status_code == 200


def test_reviewer_decision_is_authenticated_and_append_only() -> None:
    client, _ = _client()

    response = client.post(
        f"/review/evidence/{CANDIDATE_ID}/decision",
        headers={"Authorization": "Bearer reviewer-token"},
        json={
            "decision": "approved",
            "corrected_source_role": "primary_record",
            "final_verdict": "supported",
            "confidence": 0.9,
            "notes": "The official record directly supports the claim.",
        },
    )

    assert response.status_code == 200
    assert response.json()["review_id"] == REVIEW_ID


def test_openapi_documents_initial_public_contract() -> None:
    client, _ = _client()

    schema = client.get("/openapi.json").json()

    assert set(schema["paths"]) == {
        "/health",
        "/topics",
        "/topics/{topic_id}/overview",
        "/topics/{topic_id}/reports",
        "/topics/{topic_id}/reports/{report_id}",
        "/topics/{topic_id}/timeline",
        "/topic-submissions",
        "/topic-submissions/{submission_id}",
        "/topic-submissions/{submission_id}/retry",
        "/claims/{claim_id}/evidence",
        "/review/evidence",
        "/review/evidence/{candidate_id}/decision",
    }
    assert UUID(TOPIC_ID).version == 4
