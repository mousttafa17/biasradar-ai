"""Command-line interface for BiasRadar AI."""

import httpx
import typer
from pydantic import ValidationError
from rich.console import Console
from rich.table import Table

from biasradar.analyzer import ArticleAnalyzer
from biasradar.article_cleaner import ArticleCleaner
from biasradar.config import get_settings
from biasradar.db import find_topic_id, get_supabase, insert_articles, save_analysis
from biasradar.news_fetcher import NewsFetcher

app = typer.Typer(help="BiasRadar AI — media discourse and fact-checking monitor")
console = Console()


def _configuration_error(error: ValidationError) -> None:
    missing = ", ".join(str(item["loc"][0]).upper() for item in error.errors())
    console.print(f"[red]Configuration error:[/red] set {missing} in .env")
    raise typer.Exit(code=2)


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
    limit: int = typer.Option(5, min=1, max=100, help="Maximum articles to fetch."),
) -> None:
    """Fetch, store, clean, and analyze recent articles."""

    try:
        settings = get_settings()
    except ValidationError as error:
        _configuration_error(error)

    console.print(f"[bold green]Fetching articles for:[/bold green] {topic}")
    try:
        articles = NewsFetcher(settings.newsapi_key).fetch(topic, limit)
    except (httpx.HTTPError, ValueError) as error:
        console.print(f"[red]NewsAPI request failed:[/red] {error}")
        raise typer.Exit(code=1) from error

    table = Table("#", "Title", "URL", show_lines=True)
    for index, article in enumerate(articles, start=1):
        table.add_row(str(index), article.title, str(article.url))
    if articles:
        console.print(table)
    else:
        console.print("[yellow]NewsAPI returned no articles.[/yellow]")

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
            result = analyzer.analyze(topic, article.title, text)
            save_analysis(
                supabase,
                raw_item_id=stored.raw_item_id,
                analysis=result,
                cleaned_text=text,
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
            console.print(f"[red]Analysis failed[/red] {article.title}: {error}")

    console.print("\n[bold]Analysis summary[/bold]")
    console.print(f"Analyzed: [green]{analyzed}[/green]")
    console.print(f"Claims extracted: {claims_extracted}")
    console.print(f"Analysis failed: [red]{analysis_failed}[/red]")


@app.command()
def health() -> None:
    """Validate required settings and check Supabase connectivity."""

    try:
        settings = get_settings()
    except ValidationError as error:
        _configuration_error(error)

    console.print("[green]Required ingestion variables are configured.[/green]")
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
    except Exception as error:
        console.print(f"[red]Supabase connectivity check failed:[/red] {error}")
        raise typer.Exit(code=1) from error
    console.print("[green]Supabase connection is healthy.[/green]")


if __name__ == "__main__":
    app()
