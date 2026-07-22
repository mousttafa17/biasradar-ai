"""End-to-end database, worker, security, and frontend API contracts."""

import hashlib
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from postgrest.exceptions import APIError

from biasradar.api import create_app, get_repository
from biasradar.api.repository import SupabaseReadRepository
from biasradar.config import APISettings, Settings
from biasradar.persistence.repository import (
    begin_pipeline_run,
    check_database_schema,
    finish_pipeline_run,
    worker_is_healthy,
)

pytestmark = pytest.mark.staging


def _analysis_payload() -> dict[str, object]:
    return {
        "stance": "anti_subject",
        "framing_tags": ["evidence_based_criticism"],
        "stance_confidence": 0.86,
        "bias_direction": "against",
        "bias_score": 0.35,
        "loaded_language_score": 0.1,
        "one_sidedness_score": 0.3,
        "evidence_quality_score": 0.8,
        "emotionality_score": 0.1,
        "missing_counterarguments": [],
        "loaded_terms": [],
        "summary": "Two reports dispute the penalty decision.",
        "reasoning": "Private model rationale that must not reach the API.",
        "domain_profile": "football-v1",
        "domain_analysis": {
            "controversy_types": ["penalty_claim"],
            "primary_stance": "criticizes_referee",
            "secondary_stances": [],
            "content_modes": ["neutral_match_reporting"],
            "framing_tags": ["evidence_based_criticism"],
            "subject_team": "Staging FC",
            "opposing_team": "Fixture United",
            "player": None,
            "competition": "Integration Cup",
            "match": "Staging FC v Fixture United",
            "referee": "Test Referee",
            "federation": None,
            "incidents": [
                {
                    "controversy_type": "penalty_claim",
                    "description": "The 72nd-minute penalty decision",
                    "match_minute": 72,
                    "on_field_decision": "Penalty awarded",
                    "review_outcome": "VAR upheld the decision",
                }
            ],
            "attributed_expert_opinions": [],
        },
    }


def _create_raw_item(staging_db, topic_id: str) -> str:
    token = uuid4().hex
    response = (
        staging_db.client.table("raw_items")
        .insert(
            {
                "topic_id": topic_id,
                "source_name": "Staging Referee Journal",
                "source_type": "interview",
                "title": f"Staging decision report {token}",
                "url": f"https://example.com/staging/{token}",
                "raw_text": "A bounded integration fixture.",
                "status": "new",
            }
        )
        .execute()
    )
    return str(response.data[0]["id"])


def _save_analysis(staging_db, raw_item_id: str) -> str:
    response = staging_db.client.rpc(
        "save_article_analysis",
        {
            "p_raw_item_id": raw_item_id,
            "p_analysis": _analysis_payload(),
            "p_claims": [
                {
                    "claim_text": "VAR upheld the penalty.",
                    "claim_type": "verifiable_fact",
                    "checkability": "checkable",
                    "importance_score": 0.8,
                }
            ],
            "p_cleaned_text": "The cleaned staging fixture.",
            "p_model_id": "integration-model",
            "p_prompt_version": "football-v1-integration",
        },
    ).execute()
    return str(response.data)


def test_schema_contract_service_role_and_browser_boundary(staging_db):
    settings = Settings(
        supabase_url=staging_db.url,
        supabase_service_key=staging_db.service_key,
        newsapi_key="integration-only-key",
    )
    assert check_database_schema(settings) == []

    topic = staging_db.create_topic()
    assert (
        staging_db.client.table("topics")
        .select("id")
        .eq("id", topic["id"])
        .execute()
        .data
    )

    anon = staging_db.new_client(anonymous=True)
    try:
        rows = anon.table("topics").select("id").eq("id", topic["id"]).execute().data
    except Exception:
        rows = []
    assert rows == []
    with pytest.raises(APIError):
        anon.rpc("claim_due_topic_schedules", {"p_limit": 1}).execute()


def test_atomic_domain_analysis_persistence(staging_db):
    topic = staging_db.create_topic()
    raw_item_id = _create_raw_item(staging_db, str(topic["id"]))
    analysis_id = _save_analysis(staging_db, raw_item_id)

    analysis = (
        staging_db.client.table("analysis")
        .select("id,domain_profile,domain_analysis,is_current,analysis_version")
        .eq("id", analysis_id)
        .single()
        .execute()
        .data
    )
    raw_item = (
        staging_db.client.table("raw_items")
        .select("status,cleaned_text")
        .eq("id", raw_item_id)
        .single()
        .execute()
        .data
    )
    claims = (
        staging_db.client.table("claims")
        .select("analysis_id")
        .eq("raw_item_id", raw_item_id)
        .execute()
        .data
    )
    assert analysis["domain_profile"] == "football-v1"
    assert analysis["domain_analysis"]["primary_stance"] == "criticizes_referee"
    assert analysis["is_current"] is True and analysis["analysis_version"] == 1
    assert raw_item == {
        "status": "analyzed",
        "cleaned_text": "The cleaned staging fixture.",
    }
    assert claims == [{"analysis_id": analysis_id}]


def test_topic_submission_claimed_once_across_workers(staging_db):
    token = uuid4().hex
    query = f"Was the referee unfair to Staging FC in match {token}?"
    submission = (
        staging_db.client.table("topic_submissions")
        .insert(
            {
                "raw_query": query,
                "normalized_query": query.casefold(),
                "query_hash": hashlib.sha256(query.casefold().encode()).hexdigest(),
                "status": "submitted",
            }
        )
        .execute()
        .data[0]
    )
    staging_db.submission_ids.append(str(submission["id"]))

    def claim() -> list[dict[str, object]]:
        return (
            staging_db.new_client()
            .rpc("claim_topic_submissions", {"p_limit": 1})
            .execute()
            .data
        )

    with ThreadPoolExecutor(max_workers=6) as executor:
        results = executor.map(lambda _: claim(), range(6))
        rows = [row for result in results for row in result]
    assert [str(row["id"]) for row in rows].count(str(submission["id"])) == 1


def test_accepted_submission_runs_through_initial_analysis_lifecycle(staging_db):
    token = uuid4().hex
    query = f"Was the penalty decision unfair to Lifecycle FC {token}?"
    submission = (
        staging_db.client.table("topic_submissions")
        .insert(
            {
                "raw_query": query,
                "normalized_query": query.casefold(),
                "query_hash": hashlib.sha256(query.casefold().encode()).hexdigest(),
                "status": "assessing_viability",
            }
        )
        .execute()
        .data[0]
    )
    staging_db.submission_ids.append(str(submission["id"]))

    topic_id = (
        staging_db.client.rpc(
            "save_topic_viability",
            {
                "p_submission_id": submission["id"],
                "p_status": "accepted",
                "p_confidence": 0.9,
                "p_coverage_signals": {
                    "item_count": 12,
                    "independent_source_count": 7,
                    "channel_counts": {"news": 9, "interview": 3},
                    "sufficient": True,
                },
                "p_topic_definition": {
                    "canonical_name": f"Lifecycle football controversy {token}",
                    "subject": "Lifecycle FC",
                    "supporting_frame": "The penalty was correct",
                    "opposing_frame": "The penalty was incorrect",
                    "keywords": ["Lifecycle FC", "penalty"],
                },
                "p_reasons": ["Sufficient independent football coverage."],
                "p_clarification_questions": [],
                "p_duplicate_topic_id": None,
                "p_prompt_version": "football-viability-integration",
                "p_model_id": "integration-model",
            },
        )
        .execute()
        .data
    )
    staging_db.topic_ids.append(str(topic_id))

    queued = (
        staging_db.client.table("topic_submissions")
        .select("status,topic_id")
        .eq("id", submission["id"])
        .single()
        .execute()
        .data
    )
    schedule = (
        staging_db.client.table("topic_schedules")
        .select("id,initial_submission_id,next_run_at")
        .eq("topic_id", topic_id)
        .single()
        .execute()
        .data
    )
    assert queued == {"status": "queued_for_analysis", "topic_id": topic_id}
    assert schedule["initial_submission_id"] == submission["id"]

    claimed = (
        staging_db.client.rpc("claim_due_topic_schedules", {"p_limit": 20})
        .execute()
        .data
    )
    assert str(schedule["id"]) in {str(row["id"]) for row in claimed}
    analyzing = (
        staging_db.client.table("topic_submissions")
        .select("status")
        .eq("id", submission["id"])
        .single()
        .execute()
        .data
    )
    assert analyzing["status"] == "analyzing"

    now = datetime.now(UTC)
    staging_db.client.table("topic_reports").insert(
        {
            "topic_id": topic_id,
            "period_start": (now - timedelta(days=1)).isoformat(),
            "period_end": now.isoformat(),
            "total_items": 0,
            "pro_percent": 0,
            "anti_percent": 0,
            "neutral_percent": 0,
            "mixed_percent": 0,
            "unclear_percent": 0,
            "directional_pro_percent": 0,
            "directional_anti_percent": 0,
            "overall_bias_score": 0,
            "confidence_score": 0,
            "source_count": 0,
            "independent_content_groups": 0,
            "syndicated_items": 0,
            "deduplicated_items": 0,
            "report_text": "Lifecycle integration report.",
            "report_data": {},
        }
    ).execute()

    staging_db.client.rpc(
        "finish_topic_schedule",
        {
            "p_schedule_id": schedule["id"],
            "p_succeeded": True,
            "p_error": None,
        },
    ).execute()
    ready = (
        staging_db.client.table("topic_submissions")
        .select("status")
        .eq("id", submission["id"])
        .single()
        .execute()
        .data
    )
    assert ready["status"] == "report_ready"


def test_schedule_lease_backoff_and_worker_heartbeat(staging_db):
    topic = staging_db.create_topic()
    schedule = (
        staging_db.client.table("topic_schedules")
        .insert({"topic_id": topic["id"], "next_run_at": datetime.now(UTC).isoformat()})
        .execute()
        .data[0]
    )

    def claim() -> list[dict[str, object]]:
        return (
            staging_db.new_client()
            .rpc("claim_due_topic_schedules", {"p_limit": 1})
            .execute()
            .data
        )

    with ThreadPoolExecutor(max_workers=6) as executor:
        results = executor.map(lambda _: claim(), range(6))
        rows = [row for result in results for row in result]
    assert [str(row["id"]) for row in rows].count(str(schedule["id"])) == 1

    before_failure = datetime.now(UTC)
    staging_db.client.rpc(
        "finish_topic_schedule",
        {
            "p_schedule_id": schedule["id"],
            "p_succeeded": False,
            "p_error": "fixture failure",
        },
    ).execute()
    updated = (
        staging_db.client.table("topic_schedules")
        .select(
            "last_status,last_error,consecutive_failures,next_run_at,lease_expires_at"
        )
        .eq("id", schedule["id"])
        .single()
        .execute()
        .data
    )
    assert updated["last_status"] == "failed"
    assert updated["last_error"] == "fixture failure"
    assert updated["consecutive_failures"] == 1
    assert updated["lease_expires_at"] is None
    assert datetime.fromisoformat(updated["next_run_at"]) >= (
        before_failure + timedelta(minutes=4)
    )

    worker_id = f"staging-worker-{uuid4().hex}"
    staging_db.worker_ids.append(worker_id)
    staging_db.client.rpc(
        "heartbeat_worker", {"p_worker_id": worker_id, "p_metadata": {"test": True}}
    ).execute()
    assert worker_is_healthy(staging_db.client, max_age_seconds=30)


def test_pipeline_run_is_idempotent_after_completion(staging_db):
    topic = staging_db.create_topic()
    now = datetime.now(UTC)
    values = {
        "topic_id": str(topic["id"]),
        "idempotency_key": f"staging:{uuid4().hex}",
        "period_start": (now - timedelta(days=1)).isoformat(),
        "period_end": now.isoformat(),
        "prompt_version": "football-v1-integration",
        "model_id": "integration-model",
    }
    first = begin_pipeline_run(staging_db.client, **values)
    finish_pipeline_run(
        staging_db.client,
        first.run_id,
        status="completed",
        counters={"analyzed": 1},
        provider_errors=[],
    )
    second = begin_pipeline_run(staging_db.client, **values)
    assert second.run_id == first.run_id
    assert second.status == "completed"


def test_incident_and_narrative_apis_use_stored_sanitized_data(staging_db):
    topic = staging_db.create_topic()
    raw_item_id = _create_raw_item(staging_db, str(topic["id"]))
    _save_analysis(staging_db, raw_item_id)
    now = datetime.now(UTC)
    report_data = {
        "domain_profile": "football-v1",
        "football_summary": {
            "analyzed_items": 1,
            "stance_distribution": {"criticizes_referee": 100.0},
            "stance_counts": {"criticizes_referee": 1},
            "controversy_type_counts": {"penalty_claim": 1},
            "content_mode_counts": {"neutral_match_reporting": 1},
            "framing_tag_counts": {"evidence_based_criticism": 1},
            "teams": {"Staging FC": 1},
            "referees": {"Test Referee": 1},
            "federations": {},
            "attributed_expert_opinions": 0,
            "consensus_results": [],
        },
    }
    staging_db.client.table("topic_reports").insert(
        {
            "topic_id": topic["id"],
            "period_start": (now - timedelta(days=1)).isoformat(),
            "period_end": now.isoformat(),
            "total_items": 1,
            "pro_percent": 0,
            "anti_percent": 100,
            "neutral_percent": 0,
            "mixed_percent": 0,
            "unclear_percent": 0,
            "directional_pro_percent": 0,
            "directional_anti_percent": 100,
            "overall_bias_score": -35,
            "confidence_score": 0.8,
            "source_count": 1,
            "independent_content_groups": 1,
            "syndicated_items": 0,
            "deduplicated_items": 0,
            "report_text": "Stored public staging summary.",
            "report_data": report_data,
        }
    ).execute()

    api_settings = APISettings(
        supabase_url=staging_db.url,
        supabase_service_key=staging_db.service_key,
    )
    app = create_app(api_settings)
    app.dependency_overrides[get_repository] = lambda: SupabaseReadRepository(
        api_settings
    )
    client = TestClient(app)
    incidents = client.get(f"/topics/{topic['id']}/incidents?days=30")
    narratives = client.get(f"/topics/{topic['id']}/narratives?days=30")
    assert incidents.status_code == 200
    assert incidents.json()["items"][0]["controversy_type"] == "penalty_claim"
    assert narratives.status_code == 200
    assert narratives.json()["metrics"][0]["label"] == "criticizes_referee"
    serialized = incidents.text + narratives.text
    assert staging_db.service_key not in serialized
    assert "Private model rationale" not in serialized
