"""Read-only Supabase repository used by the public API."""

from typing import Any, Protocol

from postgrest.exceptions import APIError

from biasradar.analysis.topic_viability import normalize_topic_query, topic_query_hash
from biasradar.config import APISettings
from supabase import Client, create_client


class ReadRepository(Protocol):
    """Data operations exposed to API route handlers."""

    def health(self) -> None: ...

    def list_topics(self, limit: int, offset: int) -> list[dict[str, Any]]: ...

    def get_topic(self, topic_id: str) -> dict[str, Any] | None: ...

    def get_latest_report(
        self, topic_id: str, period_start: str
    ) -> dict[str, Any] | None: ...

    def list_reports(
        self, topic_id: str, period_start: str, limit: int, offset: int
    ) -> list[dict[str, Any]]: ...

    def get_report(self, topic_id: str, report_id: str) -> dict[str, Any] | None: ...

    def list_topic_domain_analyses(
        self, topic_id: str, period_start: str, limit: int
    ) -> list[dict[str, Any]]: ...

    def authenticate(self, token: str) -> str | None: ...

    def authenticate_reviewer(self, token: str) -> str | None: ...

    def consume_intake_rate(self, identity_hash: str, limit: int) -> bool: ...

    def enqueue_topic_submission(
        self, user_id: str, query: str, idempotency_key: str
    ) -> dict[str, Any]: ...

    def get_topic_submission(
        self, user_id: str, submission_id: str
    ) -> dict[str, Any] | None: ...

    def retry_topic_submission(
        self, user_id: str, submission_id: str
    ) -> dict[str, Any] | None: ...

    def list_claim_evidence(
        self, claim_id: str, limit: int, offset: int
    ) -> list[dict[str, Any]]: ...

    def list_review_evidence(
        self, review_status: str, limit: int, offset: int
    ) -> list[dict[str, Any]]: ...

    def submit_evidence_review(
        self, candidate_id: str, reviewer_user_id: str, decision: dict[str, Any]
    ) -> str: ...


class SupabaseReadRepository:
    """Service repository with allow-listed reads and guarded workflow writes."""

    def __init__(self, settings: APISettings) -> None:
        self.client: Client = create_client(
            settings.supabase_url, settings.supabase_service_key
        )

    def health(self) -> None:
        self.client.table("topics").select("id").limit(1).execute()

    def list_topics(self, limit: int, offset: int) -> list[dict[str, Any]]:
        response = (
            self.client.table("topics")
            .select("id,name,status,keywords")
            .eq("status", "active")
            .order("name")
            .range(offset, offset + limit - 1)
            .execute()
        )
        return list(response.data)

    def get_topic(self, topic_id: str) -> dict[str, Any] | None:
        response = (
            self.client.table("topics")
            .select("id,name,status,keywords")
            .eq("id", topic_id)
            .limit(1)
            .execute()
        )
        return response.data[0] if response.data else None

    def get_latest_report(
        self, topic_id: str, period_start: str
    ) -> dict[str, Any] | None:
        columns = (
            "id,period_start,period_end,total_items,source_count,"
            "independent_content_groups,syndicated_items,pro_percent,anti_percent,"
            "neutral_percent,mixed_percent,unclear_percent,"
            "directional_pro_percent,directional_anti_percent,overall_bias_score,"
            "confidence_score,report_text,report_data"
        )
        response = (
            self.client.table("topic_reports")
            .select(columns)
            .eq("topic_id", topic_id)
            .gte("period_end", period_start)
            .order("period_end", desc=True)
            .limit(1)
            .execute()
        )
        return response.data[0] if response.data else None

    def list_reports(
        self, topic_id: str, period_start: str, limit: int, offset: int
    ) -> list[dict[str, Any]]:
        columns = (
            "id,period_start,period_end,total_items,source_count,"
            "independent_content_groups,syndicated_items,pro_percent,anti_percent,"
            "neutral_percent,mixed_percent,unclear_percent,"
            "directional_pro_percent,directional_anti_percent,overall_bias_score,"
            "confidence_score,report_text,report_data"
        )
        response = (
            self.client.table("topic_reports")
            .select(columns)
            .eq("topic_id", topic_id)
            .gte("period_end", period_start)
            .order("period_end", desc=True)
            .range(offset, offset + limit - 1)
            .execute()
        )
        return list(response.data)

    def get_report(self, topic_id: str, report_id: str) -> dict[str, Any] | None:
        response = (
            self.client.table("topic_reports")
            .select(
                "id,period_start,period_end,total_items,source_count,"
                "independent_content_groups,syndicated_items,pro_percent,anti_percent,"
                "neutral_percent,mixed_percent,unclear_percent,"
                "directional_pro_percent,directional_anti_percent,overall_bias_score,"
                "confidence_score,report_text,report_data"
            )
            .eq("topic_id", topic_id)
            .eq("id", report_id)
            .limit(1)
            .execute()
        )
        return response.data[0] if response.data else None

    def list_topic_domain_analyses(
        self, topic_id: str, period_start: str, limit: int
    ) -> list[dict[str, Any]]:
        raw_response = (
            self.client.table("raw_items")
            .select("id,source_name,source_type,content_group_id")
            .eq("topic_id", topic_id)
            .gte("fetched_at", period_start)
            .order("fetched_at", desc=True)
            .limit(limit)
            .execute()
        )
        raw_by_id = {str(row["id"]): row for row in raw_response.data}
        if not raw_by_id:
            return []
        response = (
            self.client.table("analysis")
            .select("raw_item_id,domain_profile,domain_analysis")
            .in_("raw_item_id", list(raw_by_id))
            .eq("is_current", True)
            .eq("domain_profile", "football-v1")
            .execute()
        )
        return [
            {**row, **raw_by_id[str(row["raw_item_id"])]}
            for row in response.data
            if str(row["raw_item_id"]) in raw_by_id
        ]

    def authenticate(self, token: str) -> str | None:
        response = self.client.auth.get_user(token)
        return str(response.user.id) if response.user else None

    def authenticate_reviewer(self, token: str) -> str | None:
        response = self.client.auth.get_user(token)
        user = response.user
        if not user:
            return None
        return (
            str(user.id)
            if (user.app_metadata or {}).get("role") == "evidence_reviewer"
            else None
        )

    def consume_intake_rate(self, identity_hash: str, limit: int) -> bool:
        response = self.client.rpc(
            "consume_topic_intake_rate_limit",
            {"p_identity_hash": identity_hash, "p_limit": limit},
        ).execute()
        return response.data is True

    @staticmethod
    def _submission_columns() -> str:
        return (
            "id,status,normalized_query,topic_id,attempt_count,created_at,updated_at,"
            "assessed_at,topic_viability_assessments(status,confidence,"
            "coverage_signals,topic_definition,reasons,clarification_questions,"
            "prompt_version,model_id)"
        )

    def enqueue_topic_submission(
        self, user_id: str, query: str, idempotency_key: str
    ) -> dict[str, Any]:
        normalized = normalize_topic_query(query)
        query_hash = topic_query_hash(normalized)
        existing = (
            self.client.table("topic_submissions")
            .select(self._submission_columns())
            .eq("user_id", user_id)
            .eq("idempotency_key", idempotency_key)
            .limit(1)
            .execute()
        )
        if not existing.data:
            existing = (
                self.client.table("topic_submissions")
                .select(self._submission_columns())
                .eq("user_id", user_id)
                .eq("query_hash", query_hash)
                .limit(1)
                .execute()
            )
        if existing.data:
            return existing.data[0]
        try:
            response = (
                self.client.table("topic_submissions")
                .insert(
                    {
                        "user_id": user_id,
                        "raw_query": query,
                        "normalized_query": normalized,
                        "query_hash": query_hash,
                        "idempotency_key": idempotency_key,
                        "status": "submitted",
                    }
                )
                .execute()
            )
        except APIError as error:
            if error.code != "23505":
                raise
            response = (
                self.client.table("topic_submissions")
                .select(self._submission_columns())
                .eq("user_id", user_id)
                .eq("query_hash", query_hash)
                .limit(1)
                .execute()
            )
            return response.data[0]
        return self.get_topic_submission(user_id, str(response.data[0]["id"])) or {}

    def get_topic_submission(
        self, user_id: str, submission_id: str
    ) -> dict[str, Any] | None:
        response = (
            self.client.table("topic_submissions")
            .select(self._submission_columns())
            .eq("user_id", user_id)
            .eq("id", submission_id)
            .limit(1)
            .execute()
        )
        return response.data[0] if response.data else None

    def retry_topic_submission(
        self, user_id: str, submission_id: str
    ) -> dict[str, Any] | None:
        response = (
            self.client.table("topic_submissions")
            .update(
                {
                    "status": "submitted",
                    "attempt_count": 0,
                    "next_attempt_at": None,
                    "lease_expires_at": None,
                }
            )
            .eq("user_id", user_id)
            .eq("id", submission_id)
            .eq("status", "failed")
            .execute()
        )
        if not response.data:
            return None
        return self.get_topic_submission(user_id, submission_id)

    @staticmethod
    def _evidence_columns() -> str:
        return (
            "id,claim_id,url,title,publisher,published_at,source_domain,review_status,"
            "retrieved_at,evidence_automated_assessments(relation,source_role,"
            "relevance_score,excerpt,method_version,model_id)"
        )

    def list_claim_evidence(
        self, claim_id: str, limit: int, offset: int
    ) -> list[dict[str, Any]]:
        response = (
            self.client.table("evidence_candidates")
            .select(self._evidence_columns())
            .eq("claim_id", claim_id)
            .eq("review_status", "approved")
            .order("retrieved_at", desc=True)
            .range(offset, offset + limit - 1)
            .execute()
        )
        return list(response.data)

    def list_review_evidence(
        self, review_status: str, limit: int, offset: int
    ) -> list[dict[str, Any]]:
        response = (
            self.client.table("evidence_candidates")
            .select(self._evidence_columns())
            .eq("review_status", review_status)
            .order("retrieved_at")
            .range(offset, offset + limit - 1)
            .execute()
        )
        return list(response.data)

    def submit_evidence_review(
        self, candidate_id: str, reviewer_user_id: str, decision: dict[str, Any]
    ) -> str:
        response = self.client.rpc(
            "submit_evidence_review",
            {
                "p_candidate_id": candidate_id,
                "p_reviewer_user_id": reviewer_user_id,
                "p_decision": decision["decision"],
                "p_corrected_relation": decision.get("corrected_relation"),
                "p_corrected_source_role": decision.get("corrected_source_role"),
                "p_corrected_excerpt": decision.get("corrected_excerpt"),
                "p_final_verdict": decision.get("final_verdict"),
                "p_confidence": decision.get("confidence"),
                "p_notes": decision.get("notes", ""),
            },
        ).execute()
        if not response.data:
            raise ValueError("review transaction did not return an id")
        return str(response.data)
