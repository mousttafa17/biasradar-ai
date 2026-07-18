# BiasRadar AI

BiasRadar AI is a Python CLI for monitoring media discourse around a topic. It
collects recent coverage, extracts readable article text, evaluates observable stance
and framing, and identifies claims for later fact-checking.

The project is designed to describe what published material says and how it says it.
It must not infer hidden intent or present unsupported conclusions about a person,
team, journalist, or institution.

Appropriate conclusions include:

- “The discourse currently leans against the subject.”
- “This claim is unverified based on the available evidence.”
- “This article uses loaded language or one-sided framing.”

BiasRadar must not claim that coverage proves corruption, intentional favoritism, or
that a writer is inherently biased.

## Current status

The first analysis vertical slice is working end to end:

1. Search NewsAPI for recent English-language articles.
2. Match the query to an existing Supabase topic by exact name when possible.
3. Insert article metadata into `raw_items`.
4. Skip duplicate URLs without stopping the run.
5. Download each new or incomplete article and extract its main text with
   Trafilatura.
6. Fall back to the NewsAPI description or content when page extraction fails.
7. Analyze the text with GitHub Models through its OpenAI-compatible API.
8. Validate the model’s JSON response with Pydantic.
9. Store article-level results in `analysis` and extracted claims in `claims`.
10. Save the extracted text and mark the raw item as `analyzed`.
11. Normalize publisher identities and group exact or near-syndicated content while
    preserving every raw record.
12. Aggregate independent content groups into deterministic topic-level percentages
    and save a frontend-ready result in `topic_reports`.

Processing is isolated per article. A blocked page, malformed model response, API
failure, or database error is reported without terminating the remaining articles.
An interrupted article remains eligible for analysis on the next run.

The migrations in `supabase/migrations` must be applied in filename order before
analysis and reporting use the atomic persistence function and extended report
schema. The `health` command reports missing tables, columns, or functions.

## Analysis output

Each analyzed article currently produces:

- A stance label:
  - `anti_subject`
  - `pro_subject`
  - `neutral`
  - `mixed`
  - `unclear`
- Zero or more framing tags:
  - `institutional_defense`
  - `conspiracy_claim`
  - `evidence_based_criticism`
  - `fan_emotion`
- Stance confidence.
- Bias direction and bias score.
- Loaded-language, one-sidedness, evidence-quality, and emotionality scores.
- Missing counterarguments and loaded terms.
- A short summary and evidence-grounded reasoning.
- Structured claims with:
  - claim text;
  - claim type;
  - checkability;
  - importance score.

Claim types are `verifiable_fact`, `interpretation`, `opinion`, `allegation`,
`prediction`, and `quote`. Checkability is classified as `checkable`,
`partly_checkable`, or `not_checkable`.

The current model prompt explicitly treats statements about secret plans, rigging,
desired winners, or intentional favoritism as allegations unless the supplied article
contains strong direct evidence. This stage extracts claims; it does not yet verify
them against external evidence.

## Requirements

- Python 3.13+
- [`uv`](https://docs.astral.sh/uv/)
- A Supabase project containing the existing BiasRadar tables
- A [NewsAPI](https://newsapi.org/) key
- A GitHub personal access token with `models: read` access for
  [GitHub Models](https://docs.github.com/en/github-models/quickstart)

## Installation

```bash
git clone <repository-url>
cd biasradar-ai
cp .env.example .env
uv sync --dev
```

Apply all migrations in order after reviewing them on a staging Supabase project:

```text
supabase/migrations/202607180001_secure_analysis_boundary.sql
supabase/migrations/202607180002_topic_aggregation.sql
supabase/migrations/202607180003_versioned_analysis.sql
supabase/migrations/202607180004_fact_checking.sql
supabase/migrations/202607180005_source_deduplication.sql
supabase/migrations/202607180006_multichannel_ingestion.sql
```

You can apply them with your normal Supabase migration workflow or paste them into the
Supabase SQL Editor. They enable RLS, remove direct `anon` and `authenticated` table
access, add data constraints, separate stance from framing tags, create the
`save_article_analysis` transaction function, preserve versioned analysis history,
link claims to exact analysis versions, store reproducible fact-check evidence, and
extend `topic_reports` with frontend-ready report data. Do not apply those access
revocations unchanged if another application already relies on direct Data API access
to these tables; define its RLS policies first.

Add your credentials to `.env`:

```dotenv
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_SERVICE_KEY=your-supabase-service-role-key
NEWSAPI_KEY=your-newsapi-key

# GitHub Models uses an OpenAI-compatible API.
OPENAI_API_KEY=github_pat_your-token
OPENAI_BASE_URL=https://models.github.ai/inference
OPENAI_MODEL=openai/gpt-4.1-mini

GOOGLE_FACT_CHECK_API_KEY=
RSS_FEED_URLS=https://example.com/feed.xml,https://example.org/atom.xml
API_CORS_ORIGINS=http://localhost:3000
# Reserved for later stages.
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=
```

`SUPABASE_URL` must be the project root URL. Do not append `/rest/v1` or use the
Supabase dashboard URL.

Never commit `.env`, expose the service-role key in browser code, or paste access
tokens into logs or issues. `.env` is excluded by `.gitignore`.

## CLI usage

Check configuration and Supabase connectivity:

```bash
uv run biasradar health
```

List active topics:

```bash
uv run biasradar topics
```

Fetch and analyze up to five articles:

```bash
uv run biasradar analyze "Argentina FIFA favoritism" --limit 5
```

Reanalyze only items with an old prompt or model version:

```bash
uv run biasradar reanalyze "Argentina FIFA Favoritism" --days 30
```

Force a new version even when versions already match:

```bash
uv run biasradar reanalyze "Argentina FIFA Favoritism" --days 30 --force
```

Check prioritized current claims against published fact checks:

```bash
uv run biasradar fact-check "Argentina FIFA Favoritism" --days 30
```

Refresh previously stored checks:

```bash
uv run biasradar fact-check "Argentina FIFA Favoritism" --days 30 --force
```

Retrieve and compare deeper secondary evidence for important unverified claims:

```bash
uv run biasradar verify-evidence \
  "Argentina FIFA Favoritism" \
  --days 30 \
  --limit 3 \
  --evidence-limit 5
```

Use `--force` only when intentionally refreshing evidence already processed by the
current evidence method.

Normalize sources and group syndicated copies explicitly (reporting also runs this
step automatically):

```bash
uv run biasradar deduplicate "Argentina FIFA Favoritism" --days 30
```

Fetch, store, and analyze matching entries from configured RSS/Atom feeds:

```bash
uv run biasradar ingest-rss "Argentina FIFA Favoritism" --limit 20
```

You can also repeat `--feed` to use URLs without adding them to `.env`.

Generate and save a 30-day topic report:

```bash
uv run biasradar report "Argentina FIFA Favoritism" --days 30
```

### Read API

Start the FastAPI read server locally:

```bash
uv run biasradar-api
```

The initial frontend contract exposes:

- `GET /health`
- `GET /topics?limit=20&offset=0`
- `GET /topics/{topic_id}/overview?days=30`
- `GET /docs` for interactive OpenAPI documentation
- `GET /openapi.json` for the machine-readable contract

The server binds to `127.0.0.1:8000` by default. `API_CORS_ORIGINS` is a
comma-separated allow-list of exact frontend origins; wildcards, paths, queries, and
insecure non-local origins are rejected. The repository offers read operations only,
response models allow-list public fields, query windows are bounded, and database
errors are sanitized. The service-role credential remains server-side and must never
be added to frontend environment variables.

The limit must be between 1 and 100. NewsAPI results are requested in English and
ordered by publication time.

### Topic matching and duplicate behavior

`analyze` searches `topics.name` exactly and then uses a case-insensitive exact match.
If no match exists, ingestion continues with `topic_id = null`.

Articles are uniquely identified by URL:

- A new URL is inserted and analyzed.
- A duplicate URL with a status other than `analyzed` is retried.
- A duplicate already marked `analyzed` is skipped.

The command prints ingestion and analysis summaries containing fetched, inserted,
duplicate, failed, analyzed, and extracted-claim counts.

When an existing duplicate article has no `topic_id`, rerunning `analyze` with a
matching topic repairs that association without analyzing completed content twice.

### Versioned reanalysis

Each analysis records its numeric version, prompt version, model ID, current status,
and superseded timestamp. Reanalysis preserves the old analysis and its claims for
auditing, marks it non-current, and creates a new current version atomically. Reports
read only current analysis versions and their linked claims.

By default, `reanalyze` processes only items whose prompt or model differs from the
current configuration. `--force` deliberately creates another version for every item
in the requested window.

## Topic-level aggregation

The report engine calculates percentages with deterministic arithmetic; it does not
ask the model to invent an overall conclusion. It produces:

- A full distribution across `pro_subject`, `anti_subject`, `neutral`, `mixed`, and
  `unclear` that always totals exactly 100%.
- A pro/anti split calculated only from directional coverage.
- A signed framing-bias index from -100 (against/critical) to +100
  (toward/supporting).
- Average framing intensity and evidence quality.
- Source, independent-content-group, channel, and framing-tag counts.
- Repeated claim clusters with item count, source count, importance, type, and
  checkability summaries.
- A deterministic confidence score and explicit limitations.
- A complete JSON payload in `topic_reports.report_data` for a future frontend.

Each represented channel receives equal total influence. Within a channel, each
independent content group receives equal influence, divided among syndicated copies
and adjusted by stance confidence. A high-volume provider or wire-service story
therefore does not dominate the result. The framing-bias index is
the signed, confidence-weighted mean of 35% loaded language, 35% one-sidedness, 20%
emotionality, and 10% inverse evidence quality.

The `deduplicate` command canonicalizes URLs, normalizes publisher domains into
`sources`, hashes normalized article text, and applies a strict shingle/SimHash near-
duplicate comparison. The earliest published copy is marked as the group origin. It
does not delete or merge records, so every outlet and provenance path remains visible.

The report describes only material collected during the requested ingestion-time
window. It does not claim to measure all media or public opinion.

Repeated claims are clustered deterministically with normalized-token Jaccard
similarity and must occur in at least two independent content groups. Syndicated
copies alone cannot create a repeated-claim cluster. This is transparent and
reproducible, but it can miss semantically equivalent paraphrases and may require
human review for claims with similar wording but different context.

## Fact-checking

The `fact-check` command prioritizes one representative from every repeated-claim
cluster, followed by important standalone claims. Only current-version claims marked
`checkable` or `partly_checkable` are eligible. Existing checks are skipped unless
`--force` is supplied.

Google Fact Check Tools returns published `ClaimReview` records rather than an
authoritative truth oracle. BiasRadar therefore:

- requires a minimum lexical match between the extracted and reviewed claim;
- preserves matched claim wording, publisher ratings, review URLs, dates, and titles;
- maps common English ratings conservatively;
- uses `needs_human_review` when publishers conflict or ratings are unfamiliar;
- uses `unverified` when no sufficiently relevant review is found;
- never interprets “no result” as evidence that a claim is true or false;
- stores method version, match score, normalized verdict, confidence, and complete
  evidence JSON in `claim_checks`.

Supported verdicts are `supported`, `contradicted`, `unverified`, `misleading`,
`opinion`, and `needs_human_review`. Reports attach stored evidence to repeated claim
clusters and include a verdict summary in `report_data`.

## Evidence verification

`verify-evidence` provides a deeper fallback for important current claims that remain
`unverified` after the Google lookup. It currently uses NewsAPI as a discovery layer,
then downloads candidate pages through the SSRF-safe article cleaner.

For each selected claim, the pipeline:

1. Decomposes compound wording into at most five atomic assertions.
2. Searches each atomic assertion independently.
3. Excludes the article from which the claim was originally extracted.
4. Deduplicates evidence URLs and bounds retrieved text.
5. Gives the model only the claim and retrieved documents.
6. Requires an excerpt, relevance score, relationship, and source role per document.
7. Applies deterministic support and contradiction thresholds.
8. Refuses to mark the compound claim supported unless every atomic assertion is
   supported.
9. Preserves the earlier Google check inside the new evidence audit payload.
10. Updates `claim_checks` with the method version, documents, excerpts, atomic
    results, confidence, and limitations.

Supported evidence relationships are `supports`, `contradicts`,
`partially_supports`, `provides_context`, `irrelevant`, and `insufficient`. Source
roles are `primary_record`, `official_statement`, `direct_transcript`,
`independent_secondary`, `repetition`, and `unknown`. Repeated reporting has very low
weight and cannot verify a claim by volume alone.

This first evidence layer is more rigorous than a ClaimReview-only lookup, but NewsAPI
primarily discovers news coverage. It is not a complete primary-source search engine.
The stored excerpts and URLs must still be reviewed for consequential conclusions.

## Security boundary

BiasRadar treats provider responses, article URLs, downloaded pages, and model output
as untrusted input.

Current controls include:

- Secrets are loaded from `.env`, which is excluded from Git.
- Placeholder credentials and unsafe service URLs fail configuration validation.
- The NewsAPI key is sent in a header, not a query string.
- Provider and model errors are sanitized before being printed.
- Article downloads accept only HTTP(S) URLs that resolve to public IP addresses.
- Redirect destinations are resolved and validated individually.
- Embedded URL credentials and private, loopback, link-local, multicast, and reserved
  destinations are rejected.
- Proxy environment variables are ignored for untrusted article downloads.
- Redirect count, download size, content type, timeouts, article size, model response
  size, claim count, and field lengths are bounded.
- Article content is JSON-encoded as untrusted model input, and structured output is
  strictly validated before persistence.
- Analysis, claims, cleaned text, and final status are saved in one database
  transaction.
- RLS and database constraints provide defense in depth against invalid data and
  unintended low-privilege access.

The Supabase secret/service-role key bypasses RLS and must only be used by this trusted
CLI or another controlled backend. Never distribute it in a browser, mobile app, or
desktop client. For a future public UI, route privileged operations through a backend
and use Supabase Auth plus narrowly scoped RLS policies for user-facing reads.

## Supabase integration

The project uses the existing database rather than defining a replacement schema.
The current slice reads or writes these tables:

- `topics`: exact topic lookup and active-topic listing.
- `sources`: normalized publisher identity by domain and channel type.
- `raw_items`: source metadata, cleaned text, processing status, and content-group
  provenance.
- `analysis`: versioned article stance, framing metrics, summary, and reasoning.
- `claims`: claims linked to both an article and an exact analysis version.
- `claim_checks`: normalized verdicts and complete published-review evidence.
- `topic_reports`: deterministic percentages and frontend-ready report JSON.

## Project structure

```text
biasradar-ai/
├── src/biasradar/
│   ├── config.py            # Environment-backed settings
│   ├── api.py               # FastAPI routes and response boundary
│   ├── api_models.py        # Strict public response models
│   ├── api_repository.py    # Narrow read-only Supabase access
│   ├── api_server.py        # Local Uvicorn entry point
│   ├── db.py                # Supabase reads, schema checks, and persistence
│   ├── security.py          # SSRF and untrusted-URL validation
│   ├── news_fetcher.py      # NewsAPI client and article models
│   ├── ingestion.py         # Provider-neutral content contract
│   ├── rss_fetcher.py       # Safe RSS/Atom provider adapter
│   ├── article_cleaner.py   # Page download and Trafilatura extraction
│   ├── analyzer.py          # GitHub Models client and validated AI output
│   ├── fact_checker.py      # Google ClaimReview search and verdict normalization
│   ├── evidence_verifier.py # Atomic claims and evidence comparison
│   ├── deduplicator.py      # Source normalization and content-chain grouping
│   ├── report_generator.py  # Deterministic aggregation and report models
│   ├── telegram_client.py   # Placeholder for Telegram delivery
│   └── cli.py               # Typer commands and workflow orchestration
├── prompts/
│   ├── stance_classifier.txt
│   ├── fact_checker.txt
│   ├── evidence_verifier.txt
│   └── report_generator.txt
├── tests/
├── supabase/migrations/     # Reviewed database constraints and RPC functions
├── scripts/
├── .env.example
└── pyproject.toml
```

## Development

Format, lint, and test the project with:

```bash
uv run ruff format .
uv run ruff check .
uv run pytest
```

The current test suite covers NewsAPI normalization and secret redaction, article
extraction and fallback, RSS normalization and filtering, SSRF blocking,
configuration validation, structured model-response validation, Supabase row
construction, duplicate-error detection,
content-group balancing, closed percentage distributions, directional splits, and
deterministic bias calculations. It also tests cross-article claim clustering and
prevents repetitions within one article from becoming a cluster. Fact-check tests
cover no-result semantics, conflicting reviews, rating normalization, evidence
propagation, and API-key handling. Evidence tests cover primary support, repeated
reporting, conflicting evidence, and compound-claim completeness. API tests cover
pagination, validation, sanitized failures, field allow-listing, overview construction,
and the OpenAPI contract. Live API credentials are not required for unit tests.

## Not yet implemented

The following capabilities remain on the roadmap:

- Additional evidence providers beyond Google Fact Check Tools.
- Dedicated primary-source discovery and human review workflows.
- More scalable/semantic syndicated detection for very large corpora and heavily
  rewritten republications.
- Semantic claim clustering for paraphrases beyond lexical similarity.
- Cluster-aware propagation rules for semantically equivalent paraphrases.
- Telegram report delivery.
- Full integration tests for NewsAPI, GitHub Models, and Supabase.
- Automated deployment and rollback tooling for database migrations.

Extracted claims, model scores, and normalized provider ratings should always be
treated as analysis leads—not established facts or final judgments. Read the linked
reviews and use human judgment for consequential conclusions.
