"""Read-only Supabase repository used by the public API."""

from typing import Any, Protocol

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


class SupabaseReadRepository:
    """Narrow service-role repository; no write methods are available."""

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
