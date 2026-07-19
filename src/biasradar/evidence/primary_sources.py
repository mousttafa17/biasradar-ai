"""Domain-constrained primary-source discovery for arbitrary claims."""

import hashlib

from pydantic import BaseModel

from biasradar.evidence.verifier import (
    EVIDENCE_METHOD_VERSION,
    EvidenceAssessment,
    EvidenceDocument,
    EvidenceVerifier,
)
from biasradar.ingestion.cleaner import ArticleCleaner
from biasradar.ingestion.deduplication import canonicalize_url, normalized_domain
from biasradar.ingestion.newsapi import NewsFetcher

PRIMARY_DISCOVERY_METHOD = f"official-domain-{EVIDENCE_METHOD_VERSION}"


class PrimaryEvidenceCandidate(BaseModel):
    url: str
    canonical_url: str
    title: str
    publisher: str
    published_at: str | None
    source_domain: str
    content_hash: str
    discovery_method: str = PRIMARY_DISCOVERY_METHOD
    assessment: EvidenceAssessment


def discover_primary_evidence(
    *,
    claim_text: str,
    domains: list[str],
    searcher: NewsFetcher,
    cleaner: ArticleCleaner,
    verifier: EvidenceVerifier,
    limit: int = 5,
    excluded_urls: set[str] | None = None,
) -> list[PrimaryEvidenceCandidate]:
    """Discover and assess documents from an explicit official-domain allow-list."""

    if not domains:
        raise ValueError("at least one official source domain is required")
    articles = searcher.fetch(claim_text[:300], limit, domains=domains)
    documents: list[EvidenceDocument] = []
    article_rows = []
    for article in articles:
        url = str(article.url)
        if url in (excluded_urls or set()):
            continue
        text = cleaner.clean(url, article.raw_text)
        if not text:
            continue
        documents.append(
            EvidenceDocument(
                url=url,
                title=article.title,
                publisher=article.source_name,
                published_at=(
                    article.published_at.isoformat() if article.published_at else None
                ),
                text=text[:20_000],
            )
        )
        article_rows.append((article, text))
    if not documents:
        return []
    verification = verifier.assess(claim_text, documents)
    candidates = []
    for assessment in verification.assessments:
        if assessment.document_index >= len(article_rows):
            continue
        article, text = article_rows[assessment.document_index]
        canonical_url = canonicalize_url(str(article.url))
        candidates.append(
            PrimaryEvidenceCandidate(
                url=str(article.url),
                canonical_url=canonical_url,
                title=article.title,
                publisher=article.source_name,
                published_at=(
                    article.published_at.isoformat() if article.published_at else None
                ),
                source_domain=normalized_domain(canonical_url),
                content_hash=hashlib.sha256(text.encode()).hexdigest(),
                assessment=assessment,
            )
        )
    return candidates
