"""Download article pages and extract their main readable text."""

import httpx
import trafilatura
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

MAX_ARTICLE_CHARACTERS = 40_000


class ArticleCleaner:
    """HTTP downloader backed by Trafilatura content extraction."""

    def __init__(self, timeout: float = 20.0) -> None:
        self.timeout = timeout

    @retry(
        retry=retry_if_exception_type((httpx.TimeoutException, httpx.NetworkError)),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=0.5, min=0.5, max=2),
        reraise=True,
    )
    def clean(self, url: str, fallback: str | None = None) -> str:
        """Extract main text, falling back to the NewsAPI snippet on failure."""

        try:
            response = httpx.get(
                url,
                follow_redirects=True,
                timeout=self.timeout,
                headers={"User-Agent": "BiasRadarAI/0.1 (+article analysis)"},
            )
            response.raise_for_status()
            extracted = trafilatura.extract(
                response.text,
                include_comments=False,
                include_tables=False,
                favor_precision=True,
            )
        except httpx.HTTPError:
            extracted = None

        text = extracted or fallback or ""
        lines: list[str] = []
        for line in text.splitlines():
            clean_line = line.strip()
            if clean_line and (not lines or clean_line != lines[-1]):
                lines.append(clean_line)
        return "\n".join(lines)[:MAX_ARTICLE_CHARACTERS]
