from types import SimpleNamespace

from biasradar.config import Settings
from biasradar.persistence.repository import ClaimedTopicSchedule
from biasradar.workflows import worker


def _settings() -> Settings:
    return Settings(
        supabase_url="https://project.supabase.co",
        supabase_service_key="real-secret",
        newsapi_key="real-news-key",
        openai_api_key="model-key",
    )


def test_worker_cycle_processes_intake_and_due_schedule(monkeypatch) -> None:
    heartbeats = []
    finished = []
    submission = SimpleNamespace(
        submission_id="submission-1",
        query="A sufficiently long controversy topic",
        attempt_count=1,
    )
    schedule = ClaimedTopicSchedule(
        schedule_id="schedule-1",
        topic_id="topic-1",
        interval_minutes=1440,
        lookback_days=30,
        news_limit=10,
        rss_limit=10,
    )
    monkeypatch.setattr(
        worker, "heartbeat_worker", lambda *args: heartbeats.append(args)
    )
    monkeypatch.setattr(
        worker, "claim_topic_submissions", lambda client, limit: [submission]
    )
    monkeypatch.setattr(worker, "assess_topic_submission", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        worker, "claim_due_topic_schedules", lambda client, limit: [schedule]
    )
    monkeypatch.setattr(
        worker,
        "find_topic_by_id",
        lambda client, topic_id: {
            "id": topic_id,
            "name": "VAR topic",
            "status": "active",
        },
    )
    monkeypatch.setattr(
        worker,
        "finish_topic_schedule",
        lambda client, schedule_id, succeeded, error=None: finished.append(
            (schedule_id, succeeded, error)
        ),
    )
    called = []

    result = worker.process_worker_cycle(
        object(),
        _settings(),
        worker_id="worker-1",
        topic_runner=lambda claimed, name: called.append((claimed, name)),
    )

    assert result.submissions_completed == 1
    assert result.schedules_completed == 1
    assert called[0][1] == "VAR topic"
    assert finished == [("schedule-1", True, None)]
    assert len(heartbeats) == 2


def test_worker_can_claim_schedule_created_by_viability_in_same_cycle(
    monkeypatch,
) -> None:
    due_schedules = []
    submission = SimpleNamespace(
        submission_id="submission-1",
        query="A sufficiently long football controversy",
        attempt_count=1,
    )
    schedule = ClaimedTopicSchedule(
        schedule_id="schedule-1",
        topic_id="topic-1",
        interval_minutes=1440,
        lookback_days=30,
        news_limit=20,
        rss_limit=20,
    )
    monkeypatch.setattr(worker, "heartbeat_worker", lambda *args: None)
    monkeypatch.setattr(
        worker, "claim_topic_submissions", lambda client, limit: [submission]
    )
    monkeypatch.setattr(
        worker,
        "assess_topic_submission",
        lambda *args, **kwargs: due_schedules.append(schedule),
    )
    monkeypatch.setattr(
        worker,
        "claim_due_topic_schedules",
        lambda client, limit: list(due_schedules),
    )
    monkeypatch.setattr(
        worker,
        "find_topic_by_id",
        lambda client, topic_id: {
            "id": topic_id,
            "name": "New penalty controversy",
            "status": "active",
        },
    )
    finished = []
    monkeypatch.setattr(
        worker,
        "finish_topic_schedule",
        lambda client, schedule_id, succeeded, error=None: finished.append(
            (schedule_id, succeeded)
        ),
    )

    result = worker.process_worker_cycle(
        object(),
        _settings(),
        worker_id="worker-1",
        topic_runner=lambda claimed, name: None,
    )

    assert result.submissions_completed == 1
    assert result.schedules_completed == 1
    assert finished == [("schedule-1", True)]


def test_worker_cycle_finalizes_failed_schedule(monkeypatch) -> None:
    schedule = ClaimedTopicSchedule(
        schedule_id="schedule-1",
        topic_id="topic-1",
        interval_minutes=1440,
        lookback_days=30,
        news_limit=10,
        rss_limit=10,
    )
    finished = []
    monkeypatch.setattr(worker, "heartbeat_worker", lambda *args: None)
    monkeypatch.setattr(worker, "claim_topic_submissions", lambda client, limit: [])
    monkeypatch.setattr(
        worker, "claim_due_topic_schedules", lambda client, limit: [schedule]
    )
    monkeypatch.setattr(
        worker,
        "find_topic_by_id",
        lambda client, topic_id: {
            "id": topic_id,
            "name": "VAR topic",
            "status": "active",
        },
    )
    monkeypatch.setattr(
        worker,
        "finish_topic_schedule",
        lambda client, schedule_id, succeeded, error=None: finished.append(
            (succeeded, error)
        ),
    )

    result = worker.process_worker_cycle(
        object(),
        _settings(),
        worker_id="worker-1",
        topic_runner=lambda schedule, name: (_ for _ in ()).throw(RuntimeError()),
    )

    assert result.schedules_failed == 1
    assert finished[0][0] is False
    assert "scheduled pipeline failed" in finished[0][1]
