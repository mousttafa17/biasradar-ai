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

Processing is isolated per article. A blocked page, malformed model response, API
failure, or database error is reported without terminating the remaining articles.
An interrupted article remains eligible for analysis on the next run.

## Analysis output

Each analyzed article currently produces:

- A stance label:
  - `anti_subject`
  - `pro_subject`
  - `neutral`
  - `mixed`
  - `unclear`
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

Add your credentials to `.env`:

```dotenv
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_SERVICE_KEY=your-supabase-service-role-key
NEWSAPI_KEY=your-newsapi-key

# GitHub Models uses an OpenAI-compatible API.
OPENAI_API_KEY=github_pat_your-token
OPENAI_BASE_URL=https://models.github.ai/inference
OPENAI_MODEL=openai/gpt-4.1-mini

# Reserved for later stages.
GOOGLE_FACT_CHECK_API_KEY=
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

The limit must be between 1 and 100. NewsAPI results are requested in English and
ordered by publication time.

### Topic matching and duplicate behavior

`analyze` searches `topics.name` for an exact match. If no match exists, ingestion
continues with `topic_id = null`.

Articles are uniquely identified by URL:

- A new URL is inserted and analyzed.
- A duplicate URL with a status other than `analyzed` is retried.
- A duplicate already marked `analyzed` is skipped.

The command prints ingestion and analysis summaries containing fetched, inserted,
duplicate, failed, analyzed, and extracted-claim counts.

## Supabase integration

The project uses the existing database rather than defining a replacement schema.
The current slice reads or writes these tables:

- `topics`: exact topic lookup and active-topic listing.
- `raw_items`: source metadata, NewsAPI snippets, cleaned text, and processing status.
- `analysis`: validated article stance, framing metrics, summary, and reasoning.
- `claims`: claims extracted from an article and linked through `raw_item_id`.

The following existing tables are reserved for subsequent stages:

- `sources`
- `claim_checks`
- `topic_reports`

## Project structure

```text
biasradar-ai/
├── src/biasradar/
│   ├── config.py            # Environment-backed settings
│   ├── db.py                # Supabase reads and persistence
│   ├── news_fetcher.py      # NewsAPI client and article models
│   ├── article_cleaner.py   # Page download and Trafilatura extraction
│   ├── analyzer.py          # GitHub Models client and validated AI output
│   ├── fact_checker.py      # Placeholder for claim verification
│   ├── report_generator.py  # Placeholder for topic reports
│   ├── telegram_client.py   # Placeholder for Telegram delivery
│   └── cli.py               # Typer commands and workflow orchestration
├── prompts/
│   ├── stance_classifier.txt
│   ├── fact_checker.txt
│   └── report_generator.txt
├── tests/
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

The current test suite covers NewsAPI normalization, article extraction and fallback,
structured model-response validation, Supabase row construction, and duplicate-error
detection. Live API credentials are not required for unit tests.

## Not yet implemented

The following capabilities remain on the roadmap:

- External claim verification using Google Fact Check and other reliable evidence.
- Fact-check labels: `supported`, `contradicted`, `unverified`, `misleading`,
  `opinion`, and `needs_human_review`.
- Persistence of verification evidence in `claim_checks`.
- Topic-level aggregation across multiple articles.
- Deterministic overall bias scoring derived from article metrics rather than relying
  solely on a model-generated score.
- Stance-distribution calculations and repeated-claim clustering.
- Final reports containing stance distribution, overall bias score, repeated claims,
  fact-check notes, uncertainty, and limitations.
- Persistence of generated reports in `topic_reports`.
- Telegram report delivery.
- RSS ingestion with Feedparser.
- Source normalization and use of the `sources` table.
- Full integration tests for NewsAPI, GitHub Models, and Supabase.
- Database migrations or a documented reference schema for new installations.

Until claim verification is implemented, extracted claims and model scores should be
treated as analysis leads—not established facts or final judgments.
