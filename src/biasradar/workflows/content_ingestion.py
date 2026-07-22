"""Coordinate configured content providers through one normalized boundary."""

from dataclasses import dataclass, field

from biasradar.config import Settings
from biasradar.ingestion.curated_pages import CuratedPageFetcher
from biasradar.ingestion.models import ContentProvider, IngestedItem
from biasradar.ingestion.newsapi import NewsFetcher
from biasradar.ingestion.reddit import RedditFetcher
from biasradar.ingestion.rss import RSSFetcher


@dataclass(slots=True)
class IngestionBatch:
    items: list[IngestedItem] = field(default_factory=list)
    provider_errors: list[str] = field(default_factory=list)
    successful_providers: int = 0


def configured_content_providers(
    settings: Settings,
) -> list[tuple[str, ContentProvider]]:
    """Build only providers explicitly enabled by validated configuration."""

    providers: list[tuple[str, ContentProvider]] = [
        ("NewsAPI", NewsFetcher(settings.newsapi_key))
    ]
    feeds = [*settings.configured_rss_feeds, *settings.configured_football_feeds]
    if feeds:
        providers.append(("RSS/Atom", RSSFetcher(feeds)))
    pages = settings.configured_football_pages
    if pages:
        providers.append(("Curated football pages", CuratedPageFetcher(pages)))
    if settings.reddit_is_configured:
        providers.append(
            (
                "Reddit API",
                RedditFetcher(
                    client_id=settings.reddit_client_id or "",
                    client_secret=settings.reddit_client_secret or "",
                    user_agent=settings.reddit_user_agent or "",
                    subreddits=settings.configured_reddit_subreddits,
                ),
            )
        )
    return providers


def collect_topic_content(
    settings: Settings,
    query: str,
    limit_per_provider: int,
    provider_limits: dict[str, int] | None = None,
) -> IngestionBatch:
    """Fetch all configured providers without one outage hiding other coverage."""

    if not 1 <= limit_per_provider <= 100:
        raise ValueError("limit per provider must be between 1 and 100")
    batch = IngestionBatch()
    seen_urls: set[str] = set()
    for name, provider in configured_content_providers(settings):
        try:
            provider_limit = (provider_limits or {}).get(name, limit_per_provider)
            if not 1 <= provider_limit <= 100:
                raise ValueError("provider limit must be between 1 and 100")
            fetched = provider.fetch(query, provider_limit)
            batch.successful_providers += 1
            for item in fetched:
                url = str(item.url)
                if url not in seen_urls:
                    seen_urls.add(url)
                    batch.items.append(item)
        except Exception:
            batch.provider_errors.append(f"{name} ingestion failed")
    if not batch.successful_providers:
        raise RuntimeError("no configured ingestion provider was available")
    return batch
