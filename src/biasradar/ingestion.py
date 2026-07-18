"""Provider-neutral models and interfaces for content ingestion."""

from datetime import datetime
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field, HttpUrl


class IngestedItem(BaseModel):
    """A normalized item emitted by any ingestion provider."""

    model_config = ConfigDict(str_strip_whitespace=True, populate_by_name=True)

    source_name: str = "Unknown"
    source_type: str = "news"
    provider: str = "unknown"
    language: str = "en"
    title: str
    url: HttpUrl
    author: str | None = None
    published_at: datetime | None = Field(default=None, validation_alias="publishedAt")
    description: str | None = None
    content: str | None = None
    engagement_data: dict[str, int | float | str] = Field(default_factory=dict)

    @property
    def raw_text(self) -> str | None:
        """Return the best text snippet currently available."""

        return self.description or self.content


class ContentProvider(Protocol):
    """Interface implemented by ingestion provider adapters."""

    def fetch(self, query: str, limit: int = 5) -> list[IngestedItem]:
        """Return normalized items relevant to a topic query."""
