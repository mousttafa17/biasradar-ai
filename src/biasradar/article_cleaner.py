"""Download untrusted article pages safely and extract their readable text."""

import httpx
import trafilatura
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from biasradar.security import UnsafeURLError, validate_public_url, validated_redirect

MAX_ARTICLE_CHARACTERS = 40_000
MAX_DOWNLOAD_BYTES = 2_000_000
MAX_REDIRECTS = 5
ALLOWED_CONTENT_TYPES = ("text/html", "application/xhtml+xml", "text/plain")


class ArticleCleaner:
    """SSRF-aware HTTP downloader backed by Trafilatura extraction."""

    def __init__(self, timeout: float = 20.0) -> None:
        self.timeout = timeout

    @retry(
        retry=retry_if_exception_type((httpx.TimeoutException, httpx.NetworkError)),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=0.5, min=0.5, max=2),
        reraise=True,
    )
    def _download(self, url: str) -> str:
        current_url = validate_public_url(url)
        headers = {"User-Agent": "BiasRadarAI/0.1 (+article analysis)"}
        with httpx.Client(
            timeout=self.timeout,
            follow_redirects=False,
            trust_env=False,
        ) as client:
            for _ in range(MAX_REDIRECTS + 1):
                with client.stream("GET", current_url, headers=headers) as response:
                    if response.is_redirect:
                        location = response.headers.get("location")
                        if not location:
                            raise httpx.HTTPError("article redirect omitted its target")
                        current_url = validated_redirect(current_url, location)
                        continue
                    response.raise_for_status()
                    content_type = response.headers.get("content-type", "").lower()
                    if content_type and not content_type.startswith(
                        ALLOWED_CONTENT_TYPES
                    ):
                        raise httpx.HTTPError("article response is not readable text")
                    content_length = response.headers.get("content-length")
                    if content_length and int(content_length) > MAX_DOWNLOAD_BYTES:
                        raise httpx.HTTPError("article response is too large")

                    body = bytearray()
                    for chunk in response.iter_bytes():
                        body.extend(chunk)
                        if len(body) > MAX_DOWNLOAD_BYTES:
                            raise httpx.HTTPError("article response is too large")
                    return bytes(body).decode(
                        response.encoding or "utf-8", errors="replace"
                    )
        raise httpx.TooManyRedirects("article exceeded the redirect limit")

    def clean(self, url: str, fallback: str | None = None) -> str:
        """Extract main text, falling back safely when downloading is blocked."""

        try:
            html = self._download(url)
            extracted = trafilatura.extract(
                html,
                include_comments=False,
                include_tables=False,
                favor_precision=True,
            )
        except (httpx.HTTPError, UnsafeURLError, ValueError):
            extracted = None

        text = extracted or fallback or ""
        lines: list[str] = []
        for line in text.splitlines():
            clean_line = line.strip()
            if clean_line and (not lines or clean_line != lines[-1]):
                lines.append(clean_line)
        return "\n".join(lines)[:MAX_ARTICLE_CHARACTERS]
