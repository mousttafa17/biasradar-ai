"""Authenticated Reddit post search with explicit API provenance."""

import re
from datetime import UTC, datetime
from time import monotonic
from typing import Any

import httpx

from biasradar.ingestion.models import IngestedItem

TOKEN_URL = "https://www.reddit.com/api/v1/access_token"
API_ROOT = "https://oauth.reddit.com"
SUBREDDIT_PATTERN = re.compile(r"^[A-Za-z0-9_]{2,21}$")


class RedditAPIError(RuntimeError):
    """Sanitized Reddit API error that does not expose credentials or query URLs."""


class RedditFetcher:
    """Read Reddit posts through application-only OAuth."""

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        user_agent: str,
        subreddits: list[str] | None = None,
        timeout: float = 20.0,
    ) -> None:
        if not client_id.strip() or not client_secret.strip():
            raise ValueError("Reddit client credentials are required")
        if not user_agent.strip() or "BiasRadar" not in user_agent:
            raise ValueError("Reddit user agent must identify BiasRadar")
        self.client_id = client_id
        self.client_secret = client_secret
        self.user_agent = user_agent
        self.subreddits = [
            value.strip().removeprefix("r/") for value in subreddits or []
        ]
        if any(not SUBREDDIT_PATTERN.fullmatch(value) for value in self.subreddits):
            raise ValueError("subreddit names contain unsupported characters")
        self.timeout = timeout
        self._access_token: str | None = None
        self._expires_at = 0.0

    def _token(self) -> str:
        if self._access_token and monotonic() < self._expires_at:
            return self._access_token
        try:
            response = httpx.post(
                TOKEN_URL,
                auth=(self.client_id, self.client_secret),
                data={"grant_type": "client_credentials"},
                headers={"User-Agent": self.user_agent},
                timeout=self.timeout,
            )
            response.raise_for_status()
            payload = response.json()
            token = str(payload.get("access_token") or "")
            if not token:
                raise RedditAPIError("Reddit OAuth returned no access token")
            self._access_token = token
            self._expires_at = monotonic() + max(
                int(payload.get("expires_in") or 3600) - 60, 60
            )
            return token
        except RedditAPIError:
            raise
        except Exception as error:
            raise RedditAPIError("Reddit authentication failed") from error

    def _search(
        self, query: str, limit: int, subreddit: str | None
    ) -> list[dict[str, Any]]:
        path = f"/r/{subreddit}/search" if subreddit else "/search"
        parameters: dict[str, str | int] = {
            "q": query,
            "limit": limit,
            "sort": "relevance",
            "t": "month",
            "type": "link",
            "raw_json": 1,
        }
        if subreddit:
            parameters["restrict_sr"] = "on"
        try:
            response = httpx.get(
                API_ROOT + path,
                params=parameters,
                headers={
                    "Authorization": f"Bearer {self._token()}",
                    "User-Agent": self.user_agent,
                },
                timeout=self.timeout,
            )
            response.raise_for_status()
            children = response.json().get("data", {}).get("children", [])
            return [value.get("data", {}) for value in children]
        except Exception as error:
            raise RedditAPIError("Reddit search failed") from error

    def fetch(self, query: str, limit: int = 20) -> list[IngestedItem]:
        if not query.strip() or len(query) > 300:
            raise ValueError("query must contain between 1 and 300 characters")
        if not 1 <= limit <= 100:
            raise ValueError("limit must be between 1 and 100")
        scopes = self.subreddits or [None]
        posts: dict[str, dict[str, Any]] = {}
        per_scope = min(limit, 100)
        for subreddit in scopes:
            for post in self._search(query, per_scope, subreddit):
                external_id = str(post.get("name") or post.get("id") or "")
                if external_id:
                    posts.setdefault(external_id, post)

        items: list[IngestedItem] = []
        for external_id, post in posts.items():
            title = str(post.get("title") or "").strip()
            permalink = str(post.get("permalink") or "").strip()
            if not title or not permalink.startswith("/"):
                continue
            subreddit = str(post.get("subreddit_name_prefixed") or "Reddit")
            items.append(
                IngestedItem(
                    source_name=subreddit,
                    source_type="social",
                    provider="reddit_api",
                    external_id=external_id,
                    content_license="Reddit User Content; API terms apply",
                    attribution="Reddit post; retain author and canonical link",
                    title=title,
                    url="https://www.reddit.com" + permalink,
                    author=str(post.get("author") or "") or None,
                    published_at=datetime.fromtimestamp(
                        float(post.get("created_utc") or 0), tz=UTC
                    ),
                    content=str(post.get("selftext") or "") or None,
                    engagement_data={
                        "score": int(post.get("score") or 0),
                        "comments": int(post.get("num_comments") or 0),
                        "upvote_ratio": float(post.get("upvote_ratio") or 0),
                        "subreddit": subreddit,
                    },
                )
            )
            if len(items) >= limit:
                break
        return items
