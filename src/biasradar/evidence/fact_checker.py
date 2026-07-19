"""Conservative claim lookup through Google Fact Check Tools."""

import re
from enum import StrEnum
from typing import Any

import httpx
from pydantic import BaseModel, Field
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

GOOGLE_CLAIM_SEARCH_URL = "https://factchecktools.googleapis.com/v1alpha1/claims:search"
FACT_CHECK_METHOD_VERSION = "google-claim-search-v1"
MIN_MATCH_SCORE = 0.35
TOKEN_PATTERN = re.compile(r"[a-z0-9]+")
STOP_WORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "by",
    "for",
    "from",
    "has",
    "have",
    "in",
    "is",
    "it",
    "of",
    "on",
    "that",
    "the",
    "their",
    "this",
    "to",
    "was",
    "were",
    "will",
    "with",
}


class FactCheckVerdict(StrEnum):
    SUPPORTED = "supported"
    CONTRADICTED = "contradicted"
    UNVERIFIED = "unverified"
    MISLEADING = "misleading"
    OPINION = "opinion"
    NEEDS_HUMAN_REVIEW = "needs_human_review"


class FactCheckReview(BaseModel):
    publisher: str = "Unknown"
    url: str
    title: str | None = None
    review_date: str | None = None
    textual_rating: str


class FactCheckResult(BaseModel):
    verdict: FactCheckVerdict
    confidence: float = Field(ge=0, le=1)
    evidence_summary: str
    evidence_urls: list[str] = Field(default_factory=list, max_length=20)
    notes: str
    matched_claim_text: str | None = None
    match_score: float = Field(ge=0, le=1)
    reviews: list[FactCheckReview] = Field(default_factory=list, max_length=20)


class GoogleFactCheckError(RuntimeError):
    """A sanitized provider error that contains no API key or request URL."""


def _tokens(text: str) -> set[str]:
    return {
        token
        for token in TOKEN_PATTERN.findall(text.casefold())
        if token not in STOP_WORDS and len(token) > 1
    }


def claim_similarity(left: str, right: str) -> float:
    """Return deterministic normalized-token Jaccard similarity."""

    left_tokens, right_tokens = _tokens(left), _tokens(right)
    if not left_tokens or not right_tokens:
        return 0.0
    return len(left_tokens & right_tokens) / len(left_tokens | right_tokens)


def rating_verdict(rating: str) -> FactCheckVerdict:
    """Map common English publisher ratings conservatively."""

    normalized = rating.casefold().strip()
    misleading_terms = (
        "misleading",
        "mostly false",
        "partly false",
        "mostly true",
        "partly true",
        "half true",
        "half-true",
        "missing context",
        "mixture",
        "mixed",
    )
    false_terms = (
        "false",
        "incorrect",
        "inaccurate",
        "fake",
        "hoax",
        "pants on fire",
        "not true",
    )
    true_terms = ("true", "correct", "accurate")
    unverified_terms = ("unproven", "unverified", "no evidence", "unsupported")
    if any(term in normalized for term in misleading_terms):
        return FactCheckVerdict.MISLEADING
    if any(term in normalized for term in unverified_terms):
        return FactCheckVerdict.UNVERIFIED
    if any(term in normalized for term in false_terms):
        return FactCheckVerdict.CONTRADICTED
    if any(term in normalized for term in true_terms):
        return FactCheckVerdict.SUPPORTED
    return FactCheckVerdict.NEEDS_HUMAN_REVIEW


def _reviews(claim: dict[str, Any]) -> list[FactCheckReview]:
    reviews: list[FactCheckReview] = []
    for raw in claim.get("claimReview", [])[:20]:
        if not raw.get("url") or not raw.get("textualRating"):
            continue
        reviews.append(
            FactCheckReview(
                publisher=raw.get("publisher", {}).get("name") or "Unknown",
                url=str(raw["url"]),
                title=raw.get("title"),
                review_date=raw.get("reviewDate"),
                textual_rating=str(raw["textualRating"]),
            )
        )
    return reviews


def interpret_search_results(
    query: str, provider_claims: list[dict[str, Any]]
) -> FactCheckResult:
    """Choose the most relevant published review and derive a cautious verdict."""

    matches = sorted(
        (
            (claim_similarity(query, str(claim.get("text", ""))), claim)
            for claim in provider_claims
        ),
        key=lambda item: item[0],
        reverse=True,
    )
    if not matches or matches[0][0] < MIN_MATCH_SCORE:
        return FactCheckResult(
            verdict=FactCheckVerdict.UNVERIFIED,
            confidence=0.2,
            evidence_summary="No sufficiently similar published fact-check was found.",
            notes=(
                "Unverified means no relevant result was found in this provider; it "
                "does not mean the claim is false or true."
            ),
            match_score=matches[0][0] if matches else 0.0,
        )

    score, matched = matches[0]
    reviews = _reviews(matched)
    if not reviews:
        return FactCheckResult(
            verdict=FactCheckVerdict.UNVERIFIED,
            confidence=round(score * 0.5, 3),
            evidence_summary="A similar claim was found without usable review details.",
            notes="The result requires manual evidence review.",
            matched_claim_text=str(matched.get("text", "")),
            match_score=score,
        )

    mapped = [rating_verdict(review.textual_rating) for review in reviews]
    decisive = {
        verdict
        for verdict in mapped
        if verdict is not FactCheckVerdict.NEEDS_HUMAN_REVIEW
    }
    if len(decisive) == 1:
        verdict = decisive.pop()
        confidence = min(0.95, 0.55 + 0.30 * score + 0.05 * min(len(reviews), 2))
    else:
        verdict = FactCheckVerdict.NEEDS_HUMAN_REVIEW
        confidence = min(0.7, 0.35 + 0.25 * score)

    rating_summary = "; ".join(
        f"{review.publisher}: {review.textual_rating}" for review in reviews
    )
    return FactCheckResult(
        verdict=verdict,
        confidence=round(confidence, 3),
        evidence_summary=rating_summary[:2_000],
        evidence_urls=list(dict.fromkeys(review.url for review in reviews)),
        notes=(
            "Verdict normalized from published ClaimReview ratings. Read the linked "
            "reviews because rating systems and claim wording differ by publisher."
        ),
        matched_claim_text=str(matched.get("text", "")),
        match_score=round(score, 3),
        reviews=reviews,
    )


class GoogleFactChecker:
    """Search Google Fact Check Tools without exposing its API key in URLs."""

    def __init__(self, api_key: str, timeout: float = 20.0) -> None:
        self.api_key = api_key
        self.timeout = timeout

    @retry(
        retry=retry_if_exception_type((httpx.TimeoutException, httpx.NetworkError)),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=0.5, min=0.5, max=3),
        reraise=True,
    )
    def check(self, claim_text: str, max_age_days: int = 3650) -> FactCheckResult:
        """Search published English-language fact checks for one claim."""

        try:
            response = httpx.get(
                GOOGLE_CLAIM_SEARCH_URL,
                params={
                    "query": claim_text[:1_000],
                    "languageCode": "en",
                    "maxAgeDays": max_age_days,
                    "pageSize": 10,
                },
                headers={"X-Goog-Api-Key": self.api_key},
                timeout=self.timeout,
            )
        except httpx.HTTPError:
            raise
        if response.is_error:
            raise GoogleFactCheckError(
                f"Google Fact Check returned HTTP {response.status_code}"
            )
        payload = response.json()
        return interpret_search_results(claim_text, payload.get("claims", []))
