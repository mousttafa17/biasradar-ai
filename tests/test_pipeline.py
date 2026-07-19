from datetime import date

from biasradar.workflows.pipeline import daily_run_key


def test_daily_run_key_is_stable_and_version_sensitive() -> None:
    arguments = {
        "topic_id": "topic-1",
        "run_date": date(2026, 7, 18),
        "days": 30,
        "prompt_version": "stance-v2",
        "model_id": "openai/gpt-4.1-mini",
    }

    first = daily_run_key(**arguments)
    second = daily_run_key(**arguments)
    changed = daily_run_key(**{**arguments, "prompt_version": "stance-v3"})

    assert first == second
    assert first != changed
    assert len(first) == 64
