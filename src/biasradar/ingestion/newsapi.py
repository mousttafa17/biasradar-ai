"""Fetch recent English-language articles from NewsAPI."""

import re

import httpx
from pydantic import BaseModel, Field
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from biasradar.ingestion.models import IngestedItem

NEWSAPI_EVERYTHING_URL = "https://newsapi.org/v2/everything"
MAX_QUERY_CHARACTERS = 300
DOMAIN_PATTERN = re.compile(r"^[a-z0-9.-]+$")


class NewsAPIError(RuntimeError):
    """A sanitized NewsAPI failure that never contains the API key or request URL."""


NewsArticle = IngestedItem


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
    def fetch(
        self,
        query: str,
        limit: int = 5,
        domains: list[str] | None = None,
    ) -> list[NewsArticle]:
        """Fetch at most ``limit`` recent articles for ``query``."""

        if not 1 <= limit <= 100:
            raise ValueError("limit must be between 1 and 100")
        query = query.strip()
        if not query or len(query) > MAX_QUERY_CHARACTERS:
            raise ValueError(
                f"query must contain 1 to {MAX_QUERY_CHARACTERS} characters"
            )
        normalized_domains = [
            domain.casefold().removeprefix("www.") for domain in domains or []
        ]
        if len(normalized_domains) > 20 or any(
            not DOMAIN_PATTERN.fullmatch(domain) for domain in normalized_domains
        ):
            raise ValueError("domains must contain at most 20 valid hostnames")

        params = {
            "q": query,
            "language": "en",
            "sortBy": "publishedAt",
            "pageSize": limit,
        }
        if normalized_domains:
            params["domains"] = ",".join(normalized_domains)
        response = httpx.get(
            NEWSAPI_EVERYTHING_URL,
            params=params,
            headers={"X-Api-Key": self.api_key},
            timeout=self.timeout,
        )
        if response.is_error:
            try:
                provider_message = str(
                    response.json().get("message", "request rejected")
                )
            except (ValueError, AttributeError):
                provider_message = "request rejected"
            provider_message = provider_message.replace(self.api_key, "[redacted]")
            raise NewsAPIError(
                f"NewsAPI returned HTTP {response.status_code}: "
                f"{provider_message[:300]}"
            )
        payload = NewsAPIResponse.model_validate(response.json())

        articles: list[NewsArticle] = []
        for item in payload.articles:
            source = item.get("source")
            source_name = source.get("name") if isinstance(source, dict) else None
            normalized = {
                **item,
                "source_name": source_name or "Unknown",
                "source_type": "news",
                "provider": "newsapi",
            }
            try:
                articles.append(NewsArticle.model_validate(normalized))
            except ValueError:
                # A malformed result should not prevent valid articles being used.
                continue
        return articles
