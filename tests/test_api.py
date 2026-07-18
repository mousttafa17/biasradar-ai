from uuid import UUID

from fastapi.testclient import TestClient

from biasradar.api import create_app, get_repository
from biasradar.config import APISettings

TOPIC_ID = "11111111-1111-4111-8111-111111111111"
REPORT_ID = "22222222-2222-4222-8222-222222222222"


class FakeRepository:
    def __init__(self) -> None:
        self.healthy = True

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
                "channel_counts": {"news": 8, "rss": 4},
                "confidence_level": "moderate",
                "repeated_claim_clusters": [{"cluster_key": "one"}],
                "fact_check_summary": {"supported": 1},
                "methodology": "Channel-balanced aggregation.",
                "limitations": ["Sample limitation."],
            },
        }


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
    assert "model_reasoning" not in response.text


def test_invalid_topic_id_and_query_bounds_are_rejected() -> None:
    client, _ = _client()

    assert client.get("/topics/not-a-uuid/overview").status_code == 422
    assert client.get("/topics?limit=101").status_code == 422


def test_openapi_documents_initial_public_contract() -> None:
    client, _ = _client()

    schema = client.get("/openapi.json").json()

    assert set(schema["paths"]) == {
        "/health",
        "/topics",
        "/topics/{topic_id}/overview",
    }
    assert UUID(TOPIC_ID).version == 4
