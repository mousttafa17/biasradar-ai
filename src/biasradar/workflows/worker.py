"""Durable background worker cycles for intake and scheduled topic pipelines."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from biasradar.config import Settings
from biasradar.persistence.repository import (
    ClaimedTopicSchedule,
    claim_due_topic_schedules,
    claim_topic_submissions,
    find_topic_by_id,
    finish_topic_schedule,
    heartbeat_worker,
    retry_or_fail_topic_submission,
)
from biasradar.workflows.topic_intake import assess_topic_submission

TopicRunner = Callable[[ClaimedTopicSchedule, str], None]


@dataclass(slots=True)
class WorkerCycleResult:
    submissions_completed: int = 0
    submissions_failed: int = 0
    schedules_completed: int = 0
    schedules_failed: int = 0


def process_worker_cycle(
    client: Any,
    settings: Settings,
    *,
    worker_id: str,
    topic_runner: TopicRunner,
    submission_limit: int = 10,
    schedule_limit: int = 2,
    probe_limit: int = 20,
) -> WorkerCycleResult:
    """Claim bounded work units and finalize every claim deterministically."""

    result = WorkerCycleResult()
    heartbeat_worker(client, worker_id, {"status": "polling"})
    for submission in claim_topic_submissions(client, submission_limit):
        try:
            assess_topic_submission(
                client,
                settings,
                submission_id=submission.submission_id,
                query=submission.query,
                probe_limit=probe_limit,
            )
            result.submissions_completed += 1
        except Exception:
            result.submissions_failed += 1
            try:
                retry_or_fail_topic_submission(
                    client, submission.submission_id, submission.attempt_count
                )
            except Exception:
                pass

    for schedule in claim_due_topic_schedules(client, schedule_limit):
        try:
            topic = find_topic_by_id(client, schedule.topic_id)
            if not topic or topic.get("status") != "active":
                raise ValueError("scheduled topic is missing or inactive")
            topic_runner(schedule, str(topic["name"]))
            finish_topic_schedule(client, schedule.schedule_id, True)
            result.schedules_completed += 1
        except Exception as error:
            finish_topic_schedule(
                client,
                schedule.schedule_id,
                False,
                f"{type(error).__name__}: scheduled pipeline failed",
            )
            result.schedules_failed += 1
    heartbeat_worker(
        client,
        worker_id,
        {
            "status": "idle",
            "submissions_completed": result.submissions_completed,
            "submissions_failed": result.submissions_failed,
            "schedules_completed": result.schedules_completed,
            "schedules_failed": result.schedules_failed,
        },
    )
    return result
