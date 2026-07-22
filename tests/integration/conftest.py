"""Fixtures for the opt-in Supabase staging contract suite."""

import os
from collections.abc import Iterator
from dataclasses import dataclass, field
from uuid import uuid4

import pytest

from supabase import Client, create_client


@dataclass
class StagingDatabase:
    """Isolated clients and IDs registered for cleanup after each test."""

    url: str
    service_key: str
    anon_key: str
    client: Client
    topic_ids: list[str] = field(default_factory=list)
    submission_ids: list[str] = field(default_factory=list)
    worker_ids: list[str] = field(default_factory=list)

    def new_client(self, *, anonymous: bool = False) -> Client:
        return create_client(self.url, self.anon_key if anonymous else self.service_key)

    def create_topic(self) -> dict[str, object]:
        suffix = uuid4().hex
        response = (
            self.client.table("topics")
            .insert(
                {
                    "name": f"BiasRadar staging controversy {suffix}",
                    "subject": "Staging FC",
                    "supporting_frame": "The decision was correct",
                    "opposing_frame": "The decision was incorrect",
                    "keywords": ["staging", suffix],
                    "status": "active",
                }
            )
            .execute()
        )
        row = response.data[0]
        self.topic_ids.append(str(row["id"]))
        return row

    def cleanup(self) -> None:
        # Delete non-cascading audit rows first; topic-owned rows then cascade.
        for submission_id in self.submission_ids:
            self.client.table("topic_viability_assessments").delete().eq(
                "submission_id", submission_id
            ).execute()
            self.client.table("topic_submissions").delete().eq(
                "id", submission_id
            ).execute()
        for topic_id in self.topic_ids:
            self.client.table("topic_reports").delete().eq(
                "topic_id", topic_id
            ).execute()
            self.client.table("pipeline_runs").delete().eq(
                "topic_id", topic_id
            ).execute()
            self.client.table("raw_items").delete().eq("topic_id", topic_id).execute()
            self.client.table("topics").delete().eq("id", topic_id).execute()
        for worker_id in self.worker_ids:
            self.client.table("worker_instances").delete().eq(
                "worker_id", worker_id
            ).execute()


@pytest.fixture
def staging_db() -> Iterator[StagingDatabase]:
    required = {
        name: os.getenv(name, "").strip()
        for name in (
            "BIASRADAR_STAGING_URL",
            "BIASRADAR_STAGING_SERVICE_KEY",
            "BIASRADAR_STAGING_ANON_KEY",
        )
    }
    if os.getenv("BIASRADAR_STAGING_ALLOW_WRITES", "").lower() not in {
        "1",
        "true",
        "yes",
    }:
        pytest.skip("set BIASRADAR_STAGING_ALLOW_WRITES=true for staging tests")
    missing = [name for name, value in required.items() if not value]
    if missing:
        pytest.skip(f"missing staging configuration: {', '.join(missing)}")
    database = StagingDatabase(
        url=required["BIASRADAR_STAGING_URL"],
        service_key=required["BIASRADAR_STAGING_SERVICE_KEY"],
        anon_key=required["BIASRADAR_STAGING_ANON_KEY"],
        client=create_client(
            required["BIASRADAR_STAGING_URL"],
            required["BIASRADAR_STAGING_SERVICE_KEY"],
        ),
    )
    try:
        yield database
    finally:
        database.cleanup()
