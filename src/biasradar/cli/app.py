"""Command-line interface for BiasRadar AI."""

import socket
import time
from datetime import UTC, datetime, timedelta
from typing import Annotated
from uuid import uuid4

import typer
from openai import APIConnectionError, APIStatusError, RateLimitError
from pydantic import ValidationError
from rich.console import Console
from rich.table import Table

from biasradar.analysis.analyzer import CURRENT_PROMPT_VERSION, ArticleAnalyzer
from biasradar.analysis.topic_viability import (
    normalize_topic_query,
)
from biasradar.config import get_settings
from biasradar.domains.profiles import get_domain_profile
from biasradar.evidence.fact_checker import (
    FactCheckVerdict,
    GoogleFactChecker,
    GoogleFactCheckError,
)
from biasradar.evidence.primary_sources import discover_primary_evidence
from biasradar.evidence.verifier import (
    EVIDENCE_METHOD_VERSION,
    EvidenceDocument,
    EvidenceVerifier,
    combine_atomic_verdicts,
    decide_atomic_verdict,
)
from biasradar.ingestion.cleaner import ArticleCleaner
from biasradar.ingestion.deduplication import deduplicate_items
from biasradar.ingestion.newsapi import NewsFetcher
from biasradar.ingestion.rss import RSSFetcher, RSSFetchError
from biasradar.persistence.repository import (
    ClaimedTopicSchedule,
    begin_pipeline_run,
    check_database_schema,
    claim_topic_submissions,
    create_topic_submission,
    fail_topic_submission,
    find_topic,
    find_topic_id,
    finish_pipeline_run,
    get_supabase,
    heartbeat_pipeline_run,
    insert_articles,
    list_topic_schedules,
    load_analyzed_items,
    load_checked_claim_ids,
    load_claim_checks,
    load_claims_for_items,
    load_deduplication_items,
    load_reanalysis_candidates,
    retry_or_fail_topic_submission,
    save_analysis,
    save_claim_check,
    save_deduplication,
    save_primary_evidence_candidate,
    save_topic_report,
    upsert_topic_schedule,
    worker_is_healthy,
)
from biasradar.reporting.generator import aggregate_topic, cluster_repeated_claims
from biasradar.workflows.content_ingestion import (
    collect_topic_content,
    configured_content_providers,
)
from biasradar.workflows.pipeline import daily_run_key
from biasradar.workflows.topic_intake import assess_topic_submission
from biasradar.workflows.worker import process_worker_cycle

app = typer.Typer(help="BiasRadar AI — media discourse and fact-checking monitor")
console = Console()


def _configuration_error(error: ValidationError) -> None:
    missing = ", ".join(str(item["loc"][0]).upper() for item in error.errors())
    console.print(f"[red]Configuration error:[/red] set {missing} in .env")
    raise typer.Exit(code=2)


def _safe_analysis_error(error: Exception) -> str:
    """Return a useful failure message without provider request details."""

    if isinstance(error, RateLimitError):
        return "model rate limit reached"
    if isinstance(error, APIConnectionError):
        return "could not connect to the configured model provider"
    if isinstance(error, APIStatusError):
        return f"model provider returned HTTP {error.status_code}"
    if isinstance(error, ValidationError):
        return "model output failed structured validation"
    if isinstance(error, ValueError):
        return str(error)[:300]
    return f"{type(error).__name__} while processing the article"


@app.command()
def topics() -> None:
    """List active monitored topics from Supabase."""

    try:
        supabase = get_supabase()
        response = (
            supabase.table("topics")
            .select("id,name,status,keywords")
            .eq("status", "active")
            .execute()
        )
    except ValidationError as error:
        _configuration_error(error)
    except Exception as error:
        console.print(f"[red]Could not load topics:[/red] {error}")
        raise typer.Exit(code=1) from error

    if not response.data:
        console.print("[yellow]No active topics found.[/yellow]")
        return

    for topic in response.data:
        console.print(f"[bold]{topic['name']}[/bold] — {topic['status']}")
        console.print(topic.get("keywords", []))


@app.command()
def analyze(
    topic: str = typer.Argument(..., help="Topic or search phrase to fetch."),
    limit: int = typer.Option(
        5, min=1, max=100, help="Maximum results per configured provider."
    ),
) -> None:
    """Fetch, store, clean, and analyze recent articles."""

    try:
        settings = get_settings()
    except ValidationError as error:
        _configuration_error(error)

    console.print(f"[bold green]Fetching articles for:[/bold green] {topic}")
    try:
        ingestion = collect_topic_content(settings, topic, limit)
        articles = ingestion.items
    except ValueError as error:
        console.print(f"[red]Invalid ingestion request:[/red] {error}")
        raise typer.Exit(code=2) from error
    except Exception as error:
        console.print("[red]Content ingestion failed:[/red] no provider was available")
        raise typer.Exit(code=1) from error

    for provider_error in ingestion.provider_errors:
        console.print(f"[yellow]{provider_error}[/yellow]")

    table = Table("#", "Title", "URL", show_lines=True)
    for index, article in enumerate(articles, start=1):
        table.add_row(str(index), article.title, str(article.url))
    if articles:
        console.print(table)
    else:
        console.print(
            "[yellow]Configured providers returned no matching items.[/yellow]"
        )

    try:
        supabase = get_supabase(settings)
        topic_id = find_topic_id(supabase, topic)
        summary, stored_articles = insert_articles(supabase, articles, topic_id)
    except Exception as error:
        console.print(f"[red]Supabase operation failed:[/red] {error}")
        raise typer.Exit(code=1) from error

    console.print("\n[bold]Summary[/bold]")
    console.print(f"Fetched: {len(articles)}")
    console.print(f"Inserted: [green]{summary.inserted}[/green]")
    console.print(f"Skipped duplicates: [yellow]{summary.skipped_duplicates}[/yellow]")
    console.print(f"Failed: [red]{summary.failed}[/red]")

    if not stored_articles:
        return
    if not settings.openai_api_key:
        console.print(
            "[yellow]Analysis skipped:[/yellow] OPENAI_API_KEY is not configured."
        )
        return

    cleaner = ArticleCleaner()
    analyzer = ArticleAnalyzer(
        api_key=settings.openai_api_key,
        base_url=settings.openai_base_url,
        model=settings.openai_model,
        domain_profile=settings.domain_profile,
    )
    analyzed = 0
    analysis_failed = 0
    claims_extracted = 0
    console.print("\n[bold]Article analysis[/bold]")
    for stored in stored_articles:
        article = stored.article
        try:
            text = cleaner.clean(str(article.url), article.raw_text)
            if not text:
                raise ValueError("no article text could be extracted")
            result = analyzer.analyze(
                topic,
                article.title,
                text,
                source_name=article.source_name,
                source_type=article.source_type,
                author=article.author,
            )
            save_analysis(
                supabase,
                raw_item_id=stored.raw_item_id,
                analysis=result,
                cleaned_text=text,
                model_id=settings.openai_model,
                prompt_version=analyzer.prompt_version,
            )
            analyzed += 1
            claims_extracted += len(result.claims)
            console.print(
                f"[green]Analyzed[/green] {article.title} "
                f"([bold]{result.stance.value}[/bold], "
                f"confidence {result.stance_confidence:.0%})"
            )
        except Exception as error:
            analysis_failed += 1
            console.print(
                f"[red]Analysis failed[/red] {article.title}: "
                f"{_safe_analysis_error(error)}"
            )

    console.print("\n[bold]Analysis summary[/bold]")
    console.print(f"Analyzed: [green]{analyzed}[/green]")
    console.print(f"Claims extracted: {claims_extracted}")
    console.print(f"Analysis failed: [red]{analysis_failed}[/red]")


@app.command("ingest-rss")
def ingest_rss(
    topic: str = typer.Argument(..., help="Stored topic used to filter feed entries."),
    feed: Annotated[
        list[str] | None,
        typer.Option(
            "--feed",
            help="RSS/Atom URL; repeat for multiple feeds. Defaults to RSS_FEED_URLS.",
        ),
    ] = None,
    limit: int = typer.Option(20, min=1, max=100, help="Maximum matching entries."),
) -> None:
    """Fetch, store, clean, and analyze matching RSS or Atom entries."""

    try:
        settings = get_settings()
    except ValidationError as error:
        _configuration_error(error)
    feed_urls = feed or settings.configured_rss_feeds
    if not feed_urls:
        console.print(
            "[red]No feeds configured.[/red] Set RSS_FEED_URLS or pass --feed."
        )
        raise typer.Exit(code=2)

    try:
        articles = RSSFetcher(feed_urls).fetch(topic, limit)
    except (RSSFetchError, ValueError) as error:
        console.print(f"[red]RSS ingestion failed:[/red] {error}")
        raise typer.Exit(code=1) from error

    try:
        supabase = get_supabase(settings)
        topic_id = find_topic_id(supabase, topic)
        summary, stored_articles = insert_articles(supabase, articles, topic_id)
    except Exception as error:
        console.print("[red]RSS persistence failed due to a database error.[/red]")
        raise typer.Exit(code=1) from error

    console.print(f"[bold]RSS matches for {topic}[/bold]")
    console.print(f"Matched: {len(articles)}")
    console.print(f"Inserted: [green]{summary.inserted}[/green]")
    console.print(f"Skipped duplicates: [yellow]{summary.skipped_duplicates}[/yellow]")
    console.print(f"Failed: [red]{summary.failed}[/red]")
    if not stored_articles or not settings.openai_api_key:
        if stored_articles and not settings.openai_api_key:
            console.print(
                "[yellow]Analysis skipped:[/yellow] OPENAI_API_KEY is not configured."
            )
        return

    cleaner = ArticleCleaner()
    analyzer = ArticleAnalyzer(
        api_key=settings.openai_api_key,
        base_url=settings.openai_base_url,
        model=settings.openai_model,
        domain_profile=settings.domain_profile,
    )
    analyzed = 0
    failed = 0
    for stored in stored_articles:
        try:
            text = cleaner.clean(str(stored.article.url), stored.article.raw_text)
            if not text:
                raise ValueError("no article text could be extracted")
            result = analyzer.analyze(
                topic,
                stored.article.title,
                text,
                source_name=stored.article.source_name,
                source_type=stored.article.source_type,
                author=stored.article.author,
            )
            save_analysis(
                supabase,
                raw_item_id=stored.raw_item_id,
                analysis=result,
                cleaned_text=text,
                model_id=settings.openai_model,
                prompt_version=analyzer.prompt_version,
            )
            analyzed += 1
        except Exception as error:
            failed += 1
            console.print(
                f"[red]Analysis failed[/red] {stored.article.title}: "
                f"{_safe_analysis_error(error)}"
            )
    console.print(f"Analyzed: [green]{analyzed}[/green]")
    console.print(f"Analysis failed: [red]{failed}[/red]")


@app.command("run-topic")
def run_topic(
    topic: str = typer.Argument(..., help="Stored topic to process end to end."),
    days: int = typer.Option(30, min=1, max=3650, help="Report lookback window."),
    news_limit: int = typer.Option(20, min=1, max=100),
    rss_limit: int = typer.Option(20, min=1, max=100),
) -> None:
    """Run an idempotent daily ingestion, analysis, deduplication, and report job."""

    run = None
    counters: dict[str, int] = {
        "fetched": 0,
        "inserted": 0,
        "duplicates": 0,
        "analyzed": 0,
        "analysis_failed": 0,
        "claims": 0,
    }
    provider_errors: list[str] = []
    try:
        settings = get_settings()
        if not settings.openai_api_key:
            console.print("[red]OPENAI_API_KEY is required for pipeline runs.[/red]")
            raise typer.Exit(code=2)
        supabase = get_supabase(settings)
        missing_schema = check_database_schema(settings)
        if missing_schema:
            console.print(
                "[red]Database schema is not ready.[/red] Run `biasradar health` "
                "for details."
            )
            raise typer.Exit(code=1)
        topic_row = find_topic(supabase, topic)
        if not topic_row:
            console.print(f"[red]Topic not found:[/red] {topic}")
            raise typer.Exit(code=1)

        requested_end = datetime.now(UTC)
        requested_start = requested_end - timedelta(days=days)
        idempotency_key = daily_run_key(
            topic_id=str(topic_row["id"]),
            run_date=requested_end.date(),
            days=days,
            prompt_version=(
                f"{CURRENT_PROMPT_VERSION}+"
                f"{get_domain_profile(settings.domain_profile).prompt_version}"
            ),
            model_id=settings.openai_model,
        )
        run = begin_pipeline_run(
            supabase,
            topic_id=str(topic_row["id"]),
            idempotency_key=idempotency_key,
            period_start=requested_start.isoformat(),
            period_end=requested_end.isoformat(),
            prompt_version=(
                f"{CURRENT_PROMPT_VERSION}+"
                f"{get_domain_profile(settings.domain_profile).prompt_version}"
            ),
            model_id=settings.openai_model,
        )
        if run.status == "completed":
            console.print(
                f"[green]Daily run already completed.[/green] Report: {run.report_id}"
            )
            return

        ingestion = collect_topic_content(
            settings,
            topic,
            rss_limit,
            provider_limits={"NewsAPI": news_limit, "RSS/Atom": rss_limit},
        )
        articles = ingestion.items
        provider_errors.extend(ingestion.provider_errors)
        counters["fetched"] = len(articles)
        insert_summary, stored = insert_articles(
            supabase, articles, str(topic_row["id"])
        )
        counters["inserted"] = insert_summary.inserted
        counters["duplicates"] = insert_summary.skipped_duplicates
        heartbeat_pipeline_run(supabase, run.run_id)

        cleaner = ArticleCleaner()
        analyzer = ArticleAnalyzer(
            api_key=settings.openai_api_key,
            base_url=settings.openai_base_url,
            model=settings.openai_model,
            domain_profile=settings.domain_profile,
        )
        for candidate in stored:
            try:
                text = cleaner.clean(
                    str(candidate.article.url), candidate.article.raw_text
                )
                if not text:
                    raise ValueError("no article text could be extracted")
                result = analyzer.analyze(
                    topic,
                    candidate.article.title,
                    text,
                    source_name=candidate.article.source_name,
                    source_type=candidate.article.source_type,
                    author=candidate.article.author,
                )
                save_analysis(
                    supabase,
                    raw_item_id=candidate.raw_item_id,
                    analysis=result,
                    cleaned_text=text,
                    model_id=settings.openai_model,
                    prompt_version=analyzer.prompt_version,
                )
                counters["analyzed"] += 1
                counters["claims"] += len(result.claims)
            except Exception:
                counters["analysis_failed"] += 1
            heartbeat_pipeline_run(supabase, run.run_id)

        deduplication = deduplicate_items(
            load_deduplication_items(
                supabase,
                str(topic_row["id"]),
                run.period_start,
                run.period_end,
            )
        )
        save_deduplication(supabase, deduplication)
        heartbeat_pipeline_run(supabase, run.run_id)
        items = load_analyzed_items(
            supabase, str(topic_row["id"]), run.period_start, run.period_end
        )
        claims = load_claims_for_items(supabase, items)
        checks = load_claim_checks(supabase, [claim.claim_id for claim in claims])
        topic_report = aggregate_topic(
            topic_id=str(topic_row["id"]),
            topic_name=str(topic_row["name"]),
            period_start=datetime.fromisoformat(run.period_start),
            period_end=datetime.fromisoformat(run.period_end),
            items=items,
            claims=claims,
            claim_checks=checks,
        )
        report_id = save_topic_report(
            supabase, topic_report, pipeline_run_id=run.run_id
        )
        counters["independent_content_groups"] = topic_report.independent_content_groups
        finish_pipeline_run(
            supabase,
            run.run_id,
            status="completed",
            counters=counters,
            provider_errors=provider_errors,
            report_id=report_id,
        )
    except typer.Exit:
        raise
    except Exception as error:
        if run:
            try:
                finish_pipeline_run(
                    supabase,
                    run.run_id,
                    status="failed",
                    counters=counters,
                    provider_errors=provider_errors,
                    error_summary=_safe_analysis_error(error),
                )
            except Exception:
                pass
        console.print(f"[red]Pipeline run failed:[/red] {_safe_analysis_error(error)}")
        raise typer.Exit(code=1) from error

    console.print(f"[green]Pipeline run completed:[/green] {run.run_id}")
    console.print(f"Report: {report_id}")
    for key, value in counters.items():
        console.print(f"{key.replace('_', ' ').title()}: {value}")
    for message in provider_errors:
        console.print(f"[yellow]{message}[/yellow]")


@app.command("assess-topic")
def assess_topic(
    query: str = typer.Argument(..., help="Proposed controversial media topic."),
    probe_limit: int = typer.Option(
        20, min=5, max=100, help="Maximum results per configured provider."
    ),
) -> None:
    """Assess topic viability before creating an active monitored topic."""

    submission = None
    try:
        normalized_query = normalize_topic_query(query)
        settings = get_settings()
        if not settings.openai_api_key:
            console.print("[red]OPENAI_API_KEY is required for topic intake.[/red]")
            raise typer.Exit(code=2)
        supabase = get_supabase(settings)
        missing_schema = check_database_schema(settings)
        if missing_schema:
            console.print(
                "[red]Database schema is not ready.[/red] Run `biasradar health` "
                "for details."
            )
            raise typer.Exit(code=1)
        submission = create_topic_submission(supabase, normalized_query)
        if submission.status not in {"submitted", "assessing", "failed"}:
            console.print(
                f"[green]Submission already assessed:[/green] {submission.status}"
            )
            if submission.topic_id:
                console.print(f"Topic: {submission.topic_id}")
            return

        assessment, signals, topic_id = assess_topic_submission(
            supabase,
            settings,
            submission_id=submission.submission_id,
            query=normalized_query,
            probe_limit=probe_limit,
        )
    except typer.Exit:
        raise
    except ValueError as error:
        console.print(f"[red]Invalid topic submission:[/red] {error}")
        raise typer.Exit(code=2) from error
    except Exception as error:
        if submission:
            try:
                fail_topic_submission(supabase, submission.submission_id)
            except Exception:
                pass
        console.print(
            f"[red]Topic assessment failed:[/red] {_safe_analysis_error(error)}"
        )
        raise typer.Exit(code=1) from error

    table = Table("Signal", "Result", show_header=False)
    table.add_row("Status", assessment.status.value)
    table.add_row("Confidence", f"{assessment.confidence:.0%}")
    table.add_row("Coverage items", str(signals.item_count))
    table.add_row("Independent sources", str(signals.independent_source_count))
    table.add_row("Canonical topic", assessment.definition.canonical_name)
    console.print(table)
    for reason in assessment.reasons:
        console.print(f"- {reason}")
    for question in assessment.clarification_questions:
        console.print(f"[yellow]Clarification:[/yellow] {question}")
    if topic_id:
        console.print(f"[green]Monitored topic created:[/green] {topic_id}")


@app.command("process-topic-submissions")
def process_topic_submissions(
    limit: int = typer.Option(10, min=1, max=50, help="Maximum queue claims."),
    probe_limit: int = typer.Option(20, min=5, max=100),
) -> None:
    """Claim and process queued topic submissions with bounded retries."""

    try:
        settings = get_settings()
        if not settings.openai_api_key:
            console.print("[red]OPENAI_API_KEY is required for intake workers.[/red]")
            raise typer.Exit(code=2)
        supabase = get_supabase(settings)
        missing_schema = check_database_schema(settings)
        if missing_schema:
            console.print(
                "[red]Database schema is not ready.[/red] Run `biasradar health`."
            )
            raise typer.Exit(code=1)
        submissions = claim_topic_submissions(supabase, limit)
    except typer.Exit:
        raise
    except Exception as error:
        console.print("[red]Could not claim topic submissions.[/red]")
        raise typer.Exit(code=1) from error

    if not submissions:
        console.print("[green]No topic submissions are ready.[/green]")
        return
    completed = 0
    failed = 0
    for submission in submissions:
        try:
            assessment, _, topic_id = assess_topic_submission(
                supabase,
                settings,
                submission_id=submission.submission_id,
                query=submission.query,
                probe_limit=probe_limit,
            )
            completed += 1
            console.print(
                f"[green]{assessment.status.value}[/green] — {submission.query}"
                + (f" ({topic_id})" if topic_id else "")
            )
        except Exception:
            failed += 1
            try:
                retry_or_fail_topic_submission(
                    supabase,
                    submission.submission_id,
                    submission.attempt_count,
                )
            except Exception:
                pass
            console.print(f"[red]Assessment failed[/red] — {submission.query}")
    console.print(f"Completed: [green]{completed}[/green]")
    console.print(f"Failed/retried: [red]{failed}[/red]")


@app.command("schedule-topic")
def schedule_topic(
    topic: str = typer.Argument(..., help="Stored active topic name."),
    every_minutes: int = typer.Option(1440, min=1440, max=10080),
    days: int = typer.Option(30, min=1, max=3650),
    news_limit: int = typer.Option(20, min=1, max=100),
    rss_limit: int = typer.Option(20, min=1, max=100),
) -> None:
    """Create or update a durable daily-or-slower topic schedule."""

    settings = get_settings()
    client = get_supabase(settings)
    topic_row = find_topic(client, topic)
    if not topic_row:
        console.print(f"[red]Topic not found:[/red] {topic}")
        raise typer.Exit(code=1)
    schedule_id = upsert_topic_schedule(
        client,
        topic_id=str(topic_row["id"]),
        interval_minutes=every_minutes,
        lookback_days=days,
        news_limit=news_limit,
        rss_limit=rss_limit,
    )
    console.print(f"[green]Schedule ready:[/green] {schedule_id}")


@app.command("list-schedules")
def schedules() -> None:
    """List durable topic schedules and their most recent outcomes."""

    rows = list_topic_schedules(get_supabase(get_settings()))
    table = Table("Topic ID", "Next run", "Interval", "Status", "Failures")
    for row in rows:
        table.add_row(
            str(row["topic_id"]),
            str(row["next_run_at"]),
            f"{row['interval_minutes']} min",
            str(row.get("last_status") or "never"),
            str(row["consecutive_failures"]),
        )
    console.print(table)


def _scheduled_topic_runner(schedule: ClaimedTopicSchedule, topic_name: str) -> None:
    try:
        run_topic(
            topic=topic_name,
            days=schedule.lookback_days,
            news_limit=schedule.news_limit,
            rss_limit=schedule.rss_limit,
        )
    except typer.Exit as error:
        if error.exit_code:
            raise RuntimeError("scheduled topic pipeline failed") from error


@app.command("worker")
def worker(
    poll_seconds: int = typer.Option(15, min=2, max=300),
    submission_limit: int = typer.Option(10, min=1, max=50),
    schedule_limit: int = typer.Option(2, min=1, max=20),
    probe_limit: int = typer.Option(20, min=5, max=100),
    once: bool = typer.Option(False, help="Process one cycle and exit."),
) -> None:
    """Run the durable intake and scheduled-topic background worker."""

    settings = get_settings()
    if not settings.openai_api_key:
        console.print("[red]OPENAI_API_KEY is required for workers.[/red]")
        raise typer.Exit(code=2)
    client = get_supabase(settings)
    missing = check_database_schema(settings)
    if missing:
        console.print("[red]Database schema is not ready.[/red]")
        raise typer.Exit(code=1)
    worker_id = f"{socket.gethostname()}:{uuid4()}"
    console.print(f"[green]Worker started:[/green] {worker_id}")
    try:
        while True:
            result = process_worker_cycle(
                client,
                settings,
                worker_id=worker_id,
                topic_runner=_scheduled_topic_runner,
                submission_limit=submission_limit,
                schedule_limit=schedule_limit,
                probe_limit=probe_limit,
            )
            completed = result.submissions_completed + result.schedules_completed
            failed = result.submissions_failed + result.schedules_failed
            if completed or failed:
                console.print(
                    f"Worker cycle: [green]{completed} completed[/green], "
                    f"[red]{failed} failed[/red]"
                )
            if once:
                return
            time.sleep(poll_seconds)
    except KeyboardInterrupt:
        console.print("[yellow]Worker stopped.[/yellow]")


@app.command("worker-health")
def worker_health(
    max_age_seconds: int = typer.Option(120, min=10, max=3600),
) -> None:
    """Exit successfully when at least one recent worker heartbeat exists."""

    healthy = worker_is_healthy(get_supabase(get_settings()), max_age_seconds)
    if not healthy:
        console.print("[red]No healthy worker heartbeat was found.[/red]")
        raise typer.Exit(code=1)
    console.print("[green]A background worker is healthy.[/green]")


@app.command()
def health() -> None:
    """Validate required settings and check Supabase connectivity."""

    try:
        settings = get_settings()
    except ValidationError as error:
        _configuration_error(error)

    try:
        provider_names = [name for name, _ in configured_content_providers(settings)]
    except (ValueError, TypeError) as error:
        console.print(f"[red]Ingestion configuration error:[/red] {error}")
        raise typer.Exit(code=2) from error

    console.print("[green]Required ingestion variables are configured.[/green]")
    console.print("[green]Content providers:[/green] " + ", ".join(provider_names))
    if settings.openai_api_key:
        console.print(
            f"[green]Model configured:[/green] {settings.openai_model} via "
            f"{settings.openai_base_url}"
        )
    else:
        console.print(
            "[yellow]OPENAI_API_KEY is not set; analysis will be skipped.[/yellow]"
        )
    try:
        get_supabase(settings).table("topics").select("id").limit(1).execute()
        missing_schema = check_database_schema(settings)
    except Exception as error:
        console.print(
            "[red]Supabase connectivity check failed.[/red] "
            "Verify the project URL and secret key."
        )
        raise typer.Exit(code=1) from error
    console.print("[green]Supabase connection is healthy.[/green]")
    if missing_schema:
        console.print("[red]Database schema is not ready:[/red]")
        for item in missing_schema:
            console.print(f"  - {item}")
        console.print(
            "Apply the reviewed migration in supabase/migrations before analyzing."
        )
        raise typer.Exit(code=1)
    console.print("[green]Database schema contract is healthy.[/green]")


@app.command()
def report(
    topic: str = typer.Argument(..., help="Stored topic name to aggregate."),
    days: int = typer.Option(
        30, min=1, max=3650, help="Lookback period based on ingestion time."
    ),
) -> None:
    """Calculate and save a deterministic topic-level bias report."""

    try:
        settings = get_settings()
        supabase = get_supabase(settings)
        missing_schema = check_database_schema(settings)
        if missing_schema:
            console.print(
                "[red]Database schema is not ready.[/red] Run `biasradar health` "
                "for details."
            )
            raise typer.Exit(code=1)
        topic_row = find_topic(supabase, topic)
        if not topic_row:
            console.print(f"[red]Topic not found:[/red] {topic}")
            raise typer.Exit(code=1)

        period_end = datetime.now(UTC)
        period_start = period_end - timedelta(days=days)
        deduplication_items = load_deduplication_items(
            supabase,
            topic_id=str(topic_row["id"]),
            period_start=period_start.isoformat(),
            period_end=period_end.isoformat(),
        )
        save_deduplication(
            supabase,
            deduplicate_items(deduplication_items),
        )
        items = load_analyzed_items(
            supabase,
            topic_id=str(topic_row["id"]),
            period_start=period_start.isoformat(),
            period_end=period_end.isoformat(),
        )
        claims = load_claims_for_items(supabase, items)
        claim_checks = load_claim_checks(supabase, [claim.claim_id for claim in claims])
        topic_report = aggregate_topic(
            topic_id=str(topic_row["id"]),
            topic_name=str(topic_row["name"]),
            period_start=period_start,
            period_end=period_end,
            items=items,
            claims=claims,
            claim_checks=claim_checks,
        )
        report_id = save_topic_report(supabase, topic_report)
    except typer.Exit:
        raise
    except ValueError as error:
        console.print(f"[yellow]Report not generated:[/yellow] {error}")
        raise typer.Exit(code=1) from error
    except Exception as error:
        console.print("[red]Report generation failed due to a database error.[/red]")
        raise typer.Exit(code=1) from error

    distribution = topic_report.stance_distribution
    table = Table("Metric", "Result", show_header=False)
    table.add_row("Items", str(topic_report.total_items))
    table.add_row("Sources", str(topic_report.source_count))
    table.add_row(
        "Independent content groups",
        str(topic_report.independent_content_groups),
    )
    table.add_row("Syndicated copies", str(topic_report.syndicated_items))
    table.add_row("Toward/supporting", f"{distribution['pro_subject']:.1f}%")
    table.add_row("Against/critical", f"{distribution['anti_subject']:.1f}%")
    table.add_row("Neutral", f"{distribution['neutral']:.1f}%")
    table.add_row("Mixed", f"{distribution['mixed']:.1f}%")
    table.add_row("Unclear", f"{distribution['unclear']:.1f}%")
    if topic_report.directional_pro_percent is not None:
        table.add_row(
            "Directional split",
            f"{topic_report.directional_pro_percent:.1f}% toward / "
            f"{topic_report.directional_anti_percent:.1f}% against",
        )
    if topic_report.directional_pro_percent is None:
        table.add_row("Framing-bias index", "Not available (no directional items)")
    else:
        bias_direction = (
            "toward/supporting"
            if topic_report.overall_bias_score >= 0
            else "against/critical"
        )
        table.add_row(
            "Framing-bias index",
            f"{abs(topic_report.overall_bias_score):.1f}/100 {bias_direction}",
        )
    table.add_row(
        "Confidence",
        f"{topic_report.confidence_level.value} ({topic_report.confidence_score:.0%})",
    )
    console.print(f"\n[bold]{topic_report.topic_name}[/bold]")
    console.print(table)
    if topic_report.football_summary:
        football_table = Table("Football stance", "Weighted coverage")
        for stance, percent in sorted(
            topic_report.football_summary.stance_distribution.items(),
            key=lambda item: item[1],
            reverse=True,
        ):
            if percent > 0:
                football_table.add_row(stance, f"{percent:.1f}%")
        console.print("\n[bold]Football narrative[/bold]")
        console.print(football_table)
        controversy_types = topic_report.football_summary.controversy_type_counts
        if controversy_types:
            console.print(
                "Controversy types: "
                + ", ".join(
                    f"{name} ({count})"
                    for name, count in sorted(
                        controversy_types.items(),
                        key=lambda item: item[1],
                        reverse=True,
                    )
                )
            )
    console.print(f"\n{topic_report.report_text}")
    if topic_report.repeated_claim_clusters:
        claim_table = Table(
            "Repeated claim", "Items", "Sources", "Importance", "Fact check"
        )
        for cluster in topic_report.repeated_claim_clusters[:10]:
            claim_table.add_row(
                cluster.representative_claim,
                str(cluster.item_count),
                str(cluster.source_count),
                f"{cluster.average_importance:.0%}",
                cluster.fact_check_verdict or "not checked",
            )
        console.print("\n[bold]Repeated claims[/bold]")
        console.print(claim_table)
    console.print("\n[bold]Limitations[/bold]")
    for limitation in topic_report.limitations:
        console.print(f"- {limitation}")
    console.print(f"\n[green]Saved topic report:[/green] {report_id}")


@app.command()
def deduplicate(
    topic: str = typer.Argument(..., help="Stored topic to normalize and group."),
    days: int = typer.Option(
        30, min=1, max=3650, help="Lookback period based on ingestion time."
    ),
) -> None:
    """Normalize sources and group syndicated content without deleting items."""

    try:
        settings = get_settings()
        supabase = get_supabase(settings)
        missing_schema = check_database_schema(settings)
        if missing_schema:
            console.print(
                "[red]Database schema is not ready.[/red] Run `biasradar health` "
                "for details."
            )
            raise typer.Exit(code=1)
        topic_row = find_topic(supabase, topic)
        if not topic_row:
            console.print(f"[red]Topic not found:[/red] {topic}")
            raise typer.Exit(code=1)

        period_end = datetime.now(UTC)
        period_start = period_end - timedelta(days=days)
        items = load_deduplication_items(
            supabase,
            topic_id=str(topic_row["id"]),
            period_start=period_start.isoformat(),
            period_end=period_end.isoformat(),
        )
        result = deduplicate_items(items)
        saved = save_deduplication(supabase, result)
    except typer.Exit:
        raise
    except Exception as error:
        console.print(f"[red]Deduplication failed:[/red] {error}")
        raise typer.Exit(code=1) from error

    console.print(f"[bold]{topic_row['name']} content normalization[/bold]")
    console.print(f"Processed: [green]{saved}[/green]")
    console.print(f"Independent content groups: {result.independent_content_groups}")
    console.print(f"Syndicated copies: [yellow]{result.syndicated_items}[/yellow]")
    console.print(f"Exact duplicate groups: {result.exact_duplicate_groups}")
    console.print(f"Near-duplicate groups: {result.near_duplicate_groups}")


@app.command()
def reanalyze(
    topic: str = typer.Argument(..., help="Stored topic name to reanalyze."),
    days: int = typer.Option(
        30, min=1, max=3650, help="Lookback period based on ingestion time."
    ),
    force: bool = typer.Option(
        False, "--force", help="Reanalyze current items even when versions match."
    ),
) -> None:
    """Create new analysis versions while preserving historical results."""

    try:
        settings = get_settings()
        if not settings.openai_api_key:
            console.print("[red]OPENAI_API_KEY is required for reanalysis.[/red]")
            raise typer.Exit(code=2)
        supabase = get_supabase(settings)
        missing_schema = check_database_schema(settings)
        if missing_schema:
            console.print(
                "[red]Database schema is not ready.[/red] Run `biasradar health` "
                "for details."
            )
            raise typer.Exit(code=1)
        topic_row = find_topic(supabase, topic)
        if not topic_row:
            console.print(f"[red]Topic not found:[/red] {topic}")
            raise typer.Exit(code=1)

        period_end = datetime.now(UTC)
        period_start = period_end - timedelta(days=days)
        candidates = load_reanalysis_candidates(
            supabase,
            topic_id=str(topic_row["id"]),
            period_start=period_start.isoformat(),
            period_end=period_end.isoformat(),
            model_id=settings.openai_model,
            prompt_version=(
                f"{CURRENT_PROMPT_VERSION}+"
                f"{get_domain_profile(settings.domain_profile).prompt_version}"
            ),
            only_stale=not force,
        )
    except typer.Exit:
        raise
    except Exception as error:
        console.print("[red]Could not load reanalysis candidates.[/red]")
        raise typer.Exit(code=1) from error

    if not candidates:
        console.print("[green]All analyses already use the current versions.[/green]")
        return

    analyzer = ArticleAnalyzer(
        api_key=settings.openai_api_key,
        base_url=settings.openai_base_url,
        model=settings.openai_model,
        domain_profile=settings.domain_profile,
    )
    cleaner = ArticleCleaner()
    updated = 0
    failed = 0
    claims_extracted = 0
    console.print(
        f"[bold]Reanalyzing {len(candidates)} items[/bold] with "
        f"{CURRENT_PROMPT_VERSION} / {settings.openai_model}"
    )
    for candidate in candidates:
        try:
            text = candidate.cleaned_text or cleaner.clean(
                candidate.url, candidate.fallback_text
            )
            if not text:
                raise ValueError("no stored or extractable article text")
            result = analyzer.analyze(
                topic_row["name"],
                candidate.title,
                text,
                source_name=candidate.source_name,
                source_type=candidate.source_type,
                author=candidate.author,
            )
            save_analysis(
                supabase,
                raw_item_id=candidate.raw_item_id,
                analysis=result,
                cleaned_text=text,
                model_id=settings.openai_model,
                prompt_version=analyzer.prompt_version,
            )
            updated += 1
            claims_extracted += len(result.claims)
            next_version = (candidate.current_version or 0) + 1
            console.print(
                f"[green]Version {next_version}[/green] {candidate.title} "
                f"({result.stance.value}, {result.stance_confidence:.0%})"
            )
        except Exception as error:
            failed += 1
            console.print(
                f"[red]Reanalysis failed[/red] {candidate.title}: "
                f"{_safe_analysis_error(error)}"
            )

    console.print("\n[bold]Reanalysis summary[/bold]")
    console.print(f"Updated: [green]{updated}[/green]")
    console.print(f"Claims extracted: {claims_extracted}")
    console.print(f"Failed: [red]{failed}[/red]")


@app.command("discover-primary-evidence")
def discover_primary_evidence_command(
    topic: str = typer.Argument(..., help="Stored topic whose claims need evidence."),
    domain: Annotated[
        list[str] | None,
        typer.Option(
            "--domain",
            help="Official hostname; repeat it or configure PRIMARY_SOURCE_DOMAINS.",
        ),
    ] = None,
    days: int = typer.Option(30, min=1, max=3650),
    claim_limit: int = typer.Option(10, min=1, max=50),
    evidence_limit: int = typer.Option(5, min=1, max=10),
    min_importance: float = typer.Option(0.7, min=0, max=1),
) -> None:
    """Discover official-domain evidence candidates for current claims."""

    try:
        settings = get_settings()
        if not settings.openai_api_key:
            console.print("[red]OPENAI_API_KEY is required.[/red]")
            raise typer.Exit(code=2)
        domains = domain or settings.configured_primary_domains
        if not domains:
            console.print(
                "[red]At least one official domain is required.[/red] Use --domain "
                "or PRIMARY_SOURCE_DOMAINS."
            )
            raise typer.Exit(code=2)
        supabase = get_supabase(settings)
        if check_database_schema(settings):
            console.print("[red]Database schema is not ready.[/red]")
            raise typer.Exit(code=1)
        topic_row = find_topic(supabase, topic)
        if not topic_row:
            console.print(f"[red]Topic not found:[/red] {topic}")
            raise typer.Exit(code=1)
        period_end = datetime.now(UTC)
        period_start = period_end - timedelta(days=days)
        items = load_analyzed_items(
            supabase,
            str(topic_row["id"]),
            period_start.isoformat(),
            period_end.isoformat(),
        )
        claims = sorted(
            (
                claim
                for claim in load_claims_for_items(supabase, items)
                if claim.checkability in {"checkable", "partly_checkable"}
                and claim.importance_score >= min_importance
            ),
            key=lambda claim: claim.importance_score,
            reverse=True,
        )[:claim_limit]
    except typer.Exit:
        raise
    except Exception as error:
        console.print("[red]Could not load evidence discovery candidates.[/red]")
        raise typer.Exit(code=1) from error

    searcher = NewsFetcher(settings.newsapi_key)
    cleaner = ArticleCleaner()
    verifier = EvidenceVerifier(
        api_key=settings.openai_api_key,
        base_url=settings.openai_base_url,
        model=settings.openai_model,
    )
    item_by_id = {item.raw_item_id: item for item in items}
    saved = 0
    failed = 0
    for claim in claims:
        try:
            candidates = discover_primary_evidence(
                claim_text=claim.claim_text,
                domains=domains,
                searcher=searcher,
                cleaner=cleaner,
                verifier=verifier,
                limit=evidence_limit,
                excluded_urls={item_by_id[claim.raw_item_id].url},
            )
            for candidate in candidates:
                save_primary_evidence_candidate(
                    supabase,
                    claim_id=claim.claim_id,
                    candidate=candidate,
                    model_id=settings.openai_model,
                )
                saved += 1
            console.print(
                f"[green]{len(candidates)} candidates[/green] — {claim.claim_text}"
            )
        except Exception as error:
            failed += 1
            console.print(
                f"[red]Discovery failed[/red] — {claim.claim_text[:160]}: "
                f"{_safe_analysis_error(error)}"
            )
    console.print(f"Saved candidates: [green]{saved}[/green]")
    console.print(f"Failed claims: [red]{failed}[/red]")


@app.command("fact-check")
def fact_check(
    topic: str = typer.Argument(
        ..., help="Stored topic whose claims should be checked."
    ),
    days: int = typer.Option(
        30, min=1, max=3650, help="Lookback period based on ingestion time."
    ),
    min_importance: float = typer.Option(
        0.7, min=0, max=1, help="Minimum importance for non-repeated claims."
    ),
    limit: int = typer.Option(20, min=1, max=100, help="Maximum claims to check."),
    force: bool = typer.Option(False, "--force", help="Refresh existing checks."),
) -> None:
    """Check prioritized current claims against published ClaimReview evidence."""

    try:
        settings = get_settings()
        if not settings.google_fact_check_api_key:
            console.print(
                "[red]GOOGLE_FACT_CHECK_API_KEY is required for fact-checking.[/red]"
            )
            raise typer.Exit(code=2)
        supabase = get_supabase(settings)
        missing_schema = check_database_schema(settings)
        if missing_schema:
            console.print(
                "[red]Database schema is not ready.[/red] Run `biasradar health` "
                "for details."
            )
            raise typer.Exit(code=1)
        topic_row = find_topic(supabase, topic)
        if not topic_row:
            console.print(f"[red]Topic not found:[/red] {topic}")
            raise typer.Exit(code=1)

        period_end = datetime.now(UTC)
        period_start = period_end - timedelta(days=days)
        items = load_analyzed_items(
            supabase,
            topic_id=str(topic_row["id"]),
            period_start=period_start.isoformat(),
            period_end=period_end.isoformat(),
        )
        claims = load_claims_for_items(supabase, items)
    except typer.Exit:
        raise
    except Exception as error:
        console.print("[red]Could not load claims for fact-checking.[/red]")
        raise typer.Exit(code=1) from error

    eligible = [
        claim
        for claim in claims
        if claim.checkability in {"checkable", "partly_checkable"}
        and claim.claim_type != "opinion"
    ]
    by_id = {claim.claim_id: claim for claim in eligible}
    prioritized = []
    clustered_ids: set[str] = set()
    for cluster in cluster_repeated_claims(eligible):
        clustered_ids.update(cluster.claim_ids)
        cluster_claims = [
            by_id[claim_id] for claim_id in cluster.claim_ids if claim_id in by_id
        ]
        representative = max(
            cluster_claims,
            key=lambda claim: (claim.importance_score, len(claim.claim_text)),
            default=None,
        )
        if representative:
            prioritized.append(representative)
    prioritized.extend(
        sorted(
            (
                claim
                for claim in eligible
                if claim.claim_id not in clustered_ids
                and claim.importance_score >= min_importance
            ),
            key=lambda claim: claim.importance_score,
            reverse=True,
        )
    )
    candidates = list(dict.fromkeys(claim.claim_id for claim in prioritized))[:limit]
    candidate_claims = [by_id[claim_id] for claim_id in candidates]
    already_checked = (
        set()
        if force
        else load_checked_claim_ids(
            supabase, [claim.claim_id for claim in candidate_claims]
        )
    )
    candidate_claims = [
        claim for claim in candidate_claims if claim.claim_id not in already_checked
    ]
    if not candidate_claims:
        console.print(
            "[green]No new eligible claims require checking.[/green] "
            "Use --force to refresh existing checks."
        )
        return

    checker = GoogleFactChecker(settings.google_fact_check_api_key)
    counts = {verdict.value: 0 for verdict in FactCheckVerdict}
    matched = 0
    failed = 0
    console.print(f"[bold]Checking {len(candidate_claims)} prioritized claims[/bold]")
    for claim in candidate_claims:
        try:
            result = checker.check(claim.claim_text)
            save_claim_check(supabase, claim.claim_id, result)
            counts[result.verdict.value] += 1
            if result.evidence_urls:
                matched += 1
            console.print(
                f"[green]{result.verdict.value}[/green] "
                f"({result.confidence:.0%}) — {claim.claim_text}"
            )
        except GoogleFactCheckError as error:
            failed += 1
            console.print(f"[red]Provider rejected claim check:[/red] {error}")
        except Exception:
            failed += 1
            console.print(f"[red]Claim check failed[/red] — {claim.claim_text[:160]}")

    console.print("\n[bold]Fact-check summary[/bold]")
    console.print(f"Checked: {sum(counts.values())}")
    console.print(f"Published matches: {matched}")
    for verdict, count in counts.items():
        if count:
            console.print(f"{verdict}: {count}")
    console.print(f"Skipped existing: {len(already_checked)}")
    console.print(f"Failed: [red]{failed}[/red]")


@app.command("verify-evidence")
def verify_evidence(
    topic: str = typer.Argument(..., help="Stored topic whose claims need evidence."),
    days: int = typer.Option(
        30, min=1, max=3650, help="Lookback period based on ingestion time."
    ),
    min_importance: float = typer.Option(
        0.7, min=0, max=1, help="Minimum claim importance."
    ),
    limit: int = typer.Option(3, min=1, max=20, help="Maximum claims to verify."),
    evidence_limit: int = typer.Option(
        5, min=1, max=10, help="Maximum search results per atomic assertion."
    ),
    force: bool = typer.Option(
        False, "--force", help="Refresh claims already checked by this evidence method."
    ),
) -> None:
    """Retrieve and compare secondary evidence for unverified current claims."""

    try:
        settings = get_settings()
        if not settings.openai_api_key:
            console.print("[red]OPENAI_API_KEY is required.[/red]")
            raise typer.Exit(code=2)
        supabase = get_supabase(settings)
        missing_schema = check_database_schema(settings)
        if missing_schema:
            console.print(
                "[red]Database schema is not ready.[/red] Run `biasradar health` "
                "for details."
            )
            raise typer.Exit(code=1)
        topic_row = find_topic(supabase, topic)
        if not topic_row:
            console.print(f"[red]Topic not found:[/red] {topic}")
            raise typer.Exit(code=1)
        period_end = datetime.now(UTC)
        period_start = period_end - timedelta(days=days)
        items = load_analyzed_items(
            supabase,
            topic_id=str(topic_row["id"]),
            period_start=period_start.isoformat(),
            period_end=period_end.isoformat(),
        )
        claims = load_claims_for_items(supabase, items)
        checks = load_claim_checks(supabase, [claim.claim_id for claim in claims])
    except typer.Exit:
        raise
    except Exception as error:
        console.print("[red]Could not load evidence-verification candidates.[/red]")
        raise typer.Exit(code=1) from error

    checks_by_claim = {check.claim_id: check for check in checks}
    item_by_id = {item.raw_item_id: item for item in items}
    candidates = sorted(
        (
            claim
            for claim in claims
            if claim.importance_score >= min_importance
            and claim.checkability in {"checkable", "partly_checkable"}
            and claim.claim_id in checks_by_claim
            and (
                checks_by_claim[claim.claim_id].verdict == "unverified"
                or (
                    force
                    and checks_by_claim[claim.claim_id].provider
                    == "newsapi_evidence_pipeline"
                )
            )
            and (
                force
                or checks_by_claim[claim.claim_id].provider
                != "newsapi_evidence_pipeline"
            )
        ),
        key=lambda claim: claim.importance_score,
        reverse=True,
    )[:limit]
    if not candidates:
        console.print(
            "[green]No important current claims have an unverified provider "
            "check.[/green]"
        )
        return

    verifier = EvidenceVerifier(
        api_key=settings.openai_api_key,
        base_url=settings.openai_base_url,
        model=settings.openai_model,
    )
    searcher = NewsFetcher(settings.newsapi_key)
    cleaner = ArticleCleaner()
    counts = {verdict.value: 0 for verdict in FactCheckVerdict}
    failed = 0
    console.print(f"[bold]Deep-verifying {len(candidates)} claims[/bold]")
    for claim in candidates:
        try:
            atomic_claims = verifier.decompose(claim.claim_text)
            original_item = item_by_id[claim.raw_item_id]
            documents_by_url: dict[str, EvidenceDocument] = {}
            atomic_results = []
            for atomic_claim in atomic_claims:
                articles = searcher.fetch(atomic_claim.text[:300], evidence_limit)
                atomic_documents: list[EvidenceDocument] = []
                for article in articles:
                    url = str(article.url)
                    if url == original_item.url:
                        continue
                    document = documents_by_url.get(url)
                    if document is None:
                        text = cleaner.clean(url, article.raw_text)
                        if not text:
                            continue
                        document = EvidenceDocument(
                            url=url,
                            title=article.title,
                            publisher=article.source_name,
                            published_at=(
                                article.published_at.isoformat()
                                if article.published_at
                                else None
                            ),
                            text=text[:20_000],
                        )
                        documents_by_url[url] = document
                    atomic_documents.append(document)
                if atomic_documents:
                    atomic_results.append(
                        verifier.assess(atomic_claim.text, atomic_documents)
                    )
                else:
                    atomic_results.append(decide_atomic_verdict(atomic_claim.text, []))

            prior = checks_by_claim[claim.claim_id].model_dump(mode="json")
            result = combine_atomic_verdicts(
                claim.claim_text,
                atomic_results,
                list(documents_by_url.values()),
                prior_check=prior,
            )
            save_claim_check(
                supabase,
                claim.claim_id,
                result,
                provider="newsapi_evidence_pipeline",
                method_version=EVIDENCE_METHOD_VERSION,
            )
            counts[result.verdict.value] += 1
            console.print(
                f"[green]{result.verdict.value}[/green] "
                f"({result.confidence:.0%}, {len(result.documents)} documents) — "
                f"{claim.claim_text}"
            )
        except Exception as error:
            failed += 1
            console.print(
                f"[red]Evidence verification failed[/red] — {claim.claim_text[:160]}: "
                f"{_safe_analysis_error(error)}"
            )

    console.print("\n[bold]Evidence verification summary[/bold]")
    console.print(f"Verified: {sum(counts.values())}")
    for verdict, count in counts.items():
        if count:
            console.print(f"{verdict}: {count}")
    console.print(f"Failed: [red]{failed}[/red]")


if __name__ == "__main__":
    app()
