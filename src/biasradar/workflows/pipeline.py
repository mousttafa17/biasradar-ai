"""Deterministic helpers for scheduled topic orchestration."""

import hashlib
from datetime import date


def daily_run_key(
    *,
    topic_id: str,
    run_date: date,
    days: int,
    prompt_version: str,
    model_id: str,
) -> str:
    """Build a stable, non-identifying idempotency key for one daily run."""

    source = (
        f"daily:{topic_id}:{run_date.isoformat()}:{days}:{prompt_version}:{model_id}"
    )
    return hashlib.sha256(source.encode()).hexdigest()
