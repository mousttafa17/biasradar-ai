"""Fetch recent English-language articles from NewsAPI."""

from datetime import datetime

import httpx
from pydantic import BaseModel, ConfigDict, Field, HttpUrl
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

NEWSAPI_EVERYTHING_URL = "https://newsapi.org/v2/everything"


class NewsArticle(BaseModel):
    """Normalized article returned by NewsAPI."""

    model_config = ConfigDict(str_strip_whitespace=True)

    source_name: str = "Unknown"
    title: str
    url: HttpUrl
    author: str | None = None
    published_at: datetime | None = Field(default=None, validation_alias="publishedAt")
    description: str | None = None
    content: str | None = None

    @property
    def raw_text(self) -> str | None:
        """Return the best text snippet currently available."""

        return self.description or self.content


class NewsAPIResponse(BaseModel):
    """Relevant fields from a successful NewsAPI response."""

    status: str
    articles: list[dict[str, object]] = Field(default_factory=list)


class NewsFetcher:
    """Small NewsAPI client with bounded retries for transient failures."""

    def __init__(self, api_key: str, timeout: float = 20.0) -> None:
        self.api_key = api_key
        self.timeout = timeout

    @retry(
        retry=retry_if_exception_type((httpx.TimeoutException, httpx.NetworkError)),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=0.5, min=0.5, max=2),
        reraise=True,
    )
    def fetch(self, query: str, limit: int = 5) -> list[NewsArticle]:
        """Fetch at most ``limit`` recent articles for ``query``."""

        if not 1 <= limit <= 100:
            raise ValueError("limit must be between 1 and 100")

        response = httpx.get(
            NEWSAPI_EVERYTHING_URL,
            params={
                "q": query,
                "language": "en",
                "sortBy": "publishedAt",
                "pageSize": limit,
                "apiKey": self.api_key,
            },
            timeout=self.timeout,
        )
        response.raise_for_status()
        payload = NewsAPIResponse.model_validate(response.json())

        articles: list[NewsArticle] = []
        for item in payload.articles:
            source = item.get("source")
            source_name = source.get("name") if isinstance(source, dict) else None
            normalized = {**item, "source_name": source_name or "Unknown"}
            try:
                articles.append(NewsArticle.model_validate(normalized))
            except ValueError:
                # A malformed result should not prevent valid articles being used.
                continue
        return articles
