"""Safe RSS and Atom feed ingestion adapter."""

import re
from datetime import UTC, datetime
from time import struct_time

import feedparser
import httpx

from biasradar.common.security import validate_public_url, validated_redirect
from biasradar.ingestion.models import IngestedItem

MAX_FEED_BYTES = 5_000_000
TOKEN_PATTERN = re.compile(r"[a-z0-9]+")


class RSSFetchError(RuntimeError):
    """A sanitized RSS failure."""


def _parsed_datetime(value: struct_time | None) -> datetime | None:
    if not value:
        return None
    return datetime(*value[:6], tzinfo=UTC)


class RSSFetcher:
    """Fetch configured feeds and normalize matching entries."""

    def __init__(self, feed_urls: list[str], timeout: float = 20.0) -> None:
        self.feed_urls = feed_urls
        self.timeout = timeout

    def _download(self, feed_url: str) -> bytes:
        current_url = validate_public_url(feed_url)
        headers = {"User-Agent": "BiasRadarAI/0.1 RSS reader"}
        with httpx.Client(
            timeout=self.timeout,
            follow_redirects=False,
            trust_env=False,
        ) as client:
            for _ in range(6):
                with client.stream("GET", current_url, headers=headers) as response:
                    if response.is_redirect:
                        location = response.headers.get("location")
                        if not location:
                            raise RSSFetchError("feed redirect had no destination")
                        current_url = validated_redirect(current_url, location)
                        continue
                    response.raise_for_status()
                    content_length = response.headers.get("content-length")
                    if content_length and int(content_length) > MAX_FEED_BYTES:
                        raise RSSFetchError("feed exceeded the download limit")
                    body = bytearray()
                    for chunk in response.iter_bytes():
                        body.extend(chunk)
                        if len(body) > MAX_FEED_BYTES:
                            raise RSSFetchError("feed exceeded the download limit")
                    return bytes(body)
        raise RSSFetchError("feed exceeded the redirect limit")

    def fetch(self, query: str, limit: int = 20) -> list[IngestedItem]:
        if not 1 <= limit <= 100:
            raise ValueError("limit must be between 1 and 100")
        terms = {
            term for term in TOKEN_PATTERN.findall(query.casefold()) if len(term) > 2
        }
        items: list[IngestedItem] = []
        successful_feeds = 0
        for feed_url in self.feed_urls:
            try:
                parsed = feedparser.parse(self._download(feed_url))
                successful_feeds += 1
            except Exception:
                continue

            source_name = str(parsed.feed.get("title") or "Unknown RSS source")
            language = str(parsed.feed.get("language") or "en")[:2].casefold()
            for entry in parsed.entries:
                title = str(entry.get("title") or "").strip()
                link = str(entry.get("link") or "").strip()
                summary = str(entry.get("summary") or "").strip() or None
                searchable = f"{title} {summary or ''}".casefold()
                entry_terms = set(TOKEN_PATTERN.findall(searchable))
                if not title or not link or (terms and not terms & entry_terms):
                    continue
                try:
                    validate_public_url(link)
                    items.append(
                        IngestedItem(
                            source_name=source_name,
                            source_type="rss",
                            provider="rss",
                            language=language,
                            title=title,
                            url=link,
                            author=entry.get("author"),
                            published_at=_parsed_datetime(
                                entry.get("published_parsed")
                                or entry.get("updated_parsed")
                            ),
                            description=summary,
                        )
                    )
                except ValueError:
                    continue
                if len(items) >= limit:
                    return items
        if not successful_feeds:
            raise RSSFetchError("could not retrieve any configured feeds")
        return items
