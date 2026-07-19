"""Deterministic source normalization and syndicated-content grouping."""

import hashlib
import re
from collections import Counter
from datetime import UTC, datetime
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from pydantic import BaseModel, Field

TOKEN_PATTERN = re.compile(r"[a-z0-9]+")
WHITESPACE = re.compile(r"\s+")
TRACKING_PARAMETERS = {
    "fbclid",
    "gclid",
    "mc_cid",
    "mc_eid",
    "ref",
    "referrer",
}
TRACKING_PREFIXES = ("utm_",)
NEAR_DUPLICATE_JACCARD = 0.82
NEAR_DUPLICATE_HAMMING = 3


class DeduplicationItem(BaseModel):
    raw_item_id: str
    url: str
    source_name: str
    source_type: str = "news"
    title: str
    cleaned_text: str | None = None
    raw_text: str | None = None
    published_at: datetime | None = None
    fetched_at: datetime | None = None


class DeduplicatedItem(BaseModel):
    raw_item_id: str
    canonical_url: str
    normalized_domain: str
    normalized_source_name: str
    source_type: str
    content_hash: str
    content_simhash: str
    content_group_id: str
    is_group_origin: bool
    group_size: int = Field(ge=1)


class DeduplicationResult(BaseModel):
    items: list[DeduplicatedItem]
    total_items: int
    independent_content_groups: int
    syndicated_items: int
    exact_duplicate_groups: int
    near_duplicate_groups: int


def canonicalize_url(url: str) -> str:
    """Remove fragments and common tracking parameters from a URL."""

    parsed = urlsplit(url)
    scheme = parsed.scheme.casefold()
    hostname = (parsed.hostname or "").casefold().rstrip(".")
    port = parsed.port
    netloc = hostname
    is_default_port = (scheme == "https" and port == 443) or (
        scheme == "http" and port == 80
    )
    if port and not is_default_port:
        netloc = f"{hostname}:{port}"
    filtered_query = [
        (key, value)
        for key, value in parse_qsl(parsed.query, keep_blank_values=True)
        if key.casefold() not in TRACKING_PARAMETERS
        and not key.casefold().startswith(TRACKING_PREFIXES)
    ]
    path = parsed.path or "/"
    if path != "/":
        path = path.rstrip("/")
    return urlunsplit((scheme, netloc, path, urlencode(sorted(filtered_query)), ""))


def normalized_domain(url: str) -> str:
    """Return a stable lower-case hostname for source normalization."""

    hostname = (urlsplit(url).hostname or "unknown").casefold().rstrip(".")
    return hostname.removeprefix("www.")


def normalize_source_name(name: str, domain: str) -> str:
    """Normalize whitespace while preserving the publisher's display name."""

    clean = WHITESPACE.sub(" ", name).strip(" -|\t\n")
    return clean or domain


def _normalized_text(item: DeduplicationItem) -> str:
    text = item.cleaned_text or item.raw_text or item.title
    return " ".join(TOKEN_PATTERN.findall(text.casefold()))


def _shingles(text: str, size: int = 5) -> set[str]:
    tokens = text.split()
    if len(tokens) < size:
        return {" ".join(tokens)} if tokens else set()
    return {
        " ".join(tokens[index : index + size])
        for index in range(len(tokens) - size + 1)
    }


def _simhash(shingles: set[str]) -> int:
    if not shingles:
        return 0
    vector = [0] * 64
    for shingle in shingles:
        value = int.from_bytes(
            hashlib.blake2b(shingle.encode(), digest_size=8).digest(), "big"
        )
        for bit in range(64):
            vector[bit] += 1 if value & (1 << bit) else -1
    result = 0
    for bit, score in enumerate(vector):
        if score >= 0:
            result |= 1 << bit
    return result


def _is_near_duplicate(
    left_shingles: set[str],
    right_shingles: set[str],
    left_simhash: int,
    right_simhash: int,
) -> bool:
    if not left_shingles or not right_shingles:
        return False
    intersection = len(left_shingles & right_shingles)
    union = len(left_shingles | right_shingles)
    jaccard = intersection / union if union else 0
    hamming = (left_simhash ^ right_simhash).bit_count()
    return jaccard >= NEAR_DUPLICATE_JACCARD or hamming <= NEAR_DUPLICATE_HAMMING


def _origin_sort_key(item: DeduplicationItem) -> tuple[datetime, str]:
    timestamp = item.published_at or item.fetched_at or datetime.max.replace(tzinfo=UTC)
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=UTC)
    return timestamp, item.raw_item_id


def deduplicate_items(items: list[DeduplicationItem]) -> DeduplicationResult:
    """Group exact and strict near-duplicate content without deleting any rows."""

    if not items:
        return DeduplicationResult(
            items=[],
            total_items=0,
            independent_content_groups=0,
            syndicated_items=0,
            exact_duplicate_groups=0,
            near_duplicate_groups=0,
        )

    texts = [_normalized_text(item) for item in items]
    hashes = [hashlib.sha256(text.encode()).hexdigest() for text in texts]
    shingles = [_shingles(text) for text in texts]
    simhashes = [_simhash(value) for value in shingles]
    parents = list(range(len(items)))

    def find(index: int) -> int:
        while parents[index] != index:
            parents[index] = parents[parents[index]]
            index = parents[index]
        return index

    def union(left: int, right: int) -> None:
        left_root, right_root = find(left), find(right)
        if left_root != right_root:
            parents[right_root] = left_root

    hash_owner: dict[str, int] = {}
    for index, content_hash in enumerate(hashes):
        if content_hash in hash_owner:
            union(hash_owner[content_hash], index)
        else:
            hash_owner[content_hash] = index

    for left in range(len(items)):
        for right in range(left + 1, len(items)):
            if hashes[left] == hashes[right]:
                continue
            if _is_near_duplicate(
                shingles[left], shingles[right], simhashes[left], simhashes[right]
            ):
                union(left, right)

    groups: dict[int, list[int]] = {}
    for index in range(len(items)):
        groups.setdefault(find(index), []).append(index)

    output: list[DeduplicatedItem] = []
    exact_groups = 0
    near_groups = 0
    for members in groups.values():
        origin = min(members, key=lambda index: _origin_sort_key(items[index]))
        group_hashes = {hashes[index] for index in members}
        if len(members) > 1 and len(group_hashes) == 1:
            exact_groups += 1
        if len(group_hashes) > 1:
            near_groups += 1
        group_id = hashes[origin][:32]
        for index in members:
            item = items[index]
            canonical = canonicalize_url(item.url)
            domain = normalized_domain(canonical)
            output.append(
                DeduplicatedItem(
                    raw_item_id=item.raw_item_id,
                    canonical_url=canonical,
                    normalized_domain=domain,
                    normalized_source_name=normalize_source_name(
                        item.source_name, domain
                    ),
                    source_type=item.source_type,
                    content_hash=hashes[index],
                    content_simhash=f"{simhashes[index]:016x}",
                    content_group_id=group_id,
                    is_group_origin=index == origin,
                    group_size=len(members),
                )
            )

    group_sizes = Counter(item.content_group_id for item in output)
    return DeduplicationResult(
        items=output,
        total_items=len(items),
        independent_content_groups=len(groups),
        syndicated_items=sum(size - 1 for size in group_sizes.values()),
        exact_duplicate_groups=exact_groups,
        near_duplicate_groups=near_groups,
    )
