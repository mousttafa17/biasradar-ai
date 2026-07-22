"""Opt-in ingestion for official records, transcripts, and interview pages."""

import re

from pydantic import BaseModel, ConfigDict, Field, HttpUrl

from biasradar.ingestion.cleaner import ArticleCleaner
from biasradar.ingestion.models import IngestedItem

TOKEN_PATTERN = re.compile(r"[a-z0-9]+")
ALLOWED_SOURCE_TYPES = {"official", "transcript", "interview"}


class CuratedPageSource(BaseModel):
    model_config = ConfigDict(extra="forbid")

    url: HttpUrl
    title: str = Field(min_length=1, max_length=500)
    source_name: str = Field(min_length=1, max_length=200)
    source_type: str = "official"
    language: str = Field(default="en", min_length=2, max_length=10)
    content_license: str | None = Field(default=None, max_length=500)
    attribution: str | None = Field(default=None, max_length=500)

    def model_post_init(self, _context: object) -> None:
        if self.source_type not in ALLOWED_SOURCE_TYPES:
            supported = ", ".join(sorted(ALLOWED_SOURCE_TYPES))
            raise ValueError(f"source_type must be one of: {supported}")


class CuratedPageFetcher:
    """Fetch only operator-configured public pages through the SSRF-safe cleaner."""

    def __init__(
        self,
        sources: list[CuratedPageSource],
        cleaner: ArticleCleaner | None = None,
    ) -> None:
        self.sources = sources
        self.cleaner = cleaner or ArticleCleaner()

    def fetch(self, query: str, limit: int = 20) -> list[IngestedItem]:
        if not 1 <= limit <= 100:
            raise ValueError("limit must be between 1 and 100")
        query_terms = {
            token for token in TOKEN_PATTERN.findall(query.casefold()) if len(token) > 2
        }
        items: list[IngestedItem] = []
        for source in self.sources:
            try:
                text = self.cleaner.clean(str(source.url))
            except Exception:
                continue
            page_terms = set(TOKEN_PATTERN.findall(f"{source.title} {text}".casefold()))
            if query_terms and not query_terms & page_terms:
                continue
            items.append(
                IngestedItem(
                    source_name=source.source_name,
                    source_type=source.source_type,
                    provider="curated_web",
                    external_id=str(source.url),
                    content_license=source.content_license,
                    attribution=source.attribution,
                    language=source.language,
                    title=source.title,
                    url=source.url,
                    content=text,
                )
            )
            if len(items) >= limit:
                break
        return items
