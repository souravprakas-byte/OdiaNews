# Odisha AI News Intelligence Engine

Near-real-time Odisha-focused news aggregation and intelligence pipeline with structured outputs, Odia summaries, deduplication, entity extraction, urgency scoring, and API-ready records.

## What This Starter Includes

- Multi-source configuration for 20+ Odisha/Odia/English news outlets
- Adapter-friendly ingestion pipeline for RSS, sitemaps, and article pages
- Raw and processed article schemas
- Deduplication strategy using canonical URL, title similarity, and embedding hooks
- Rule-based urgency scoring with an ML/LLM extension point
- AI processing contracts for Odia summaries, named entities, categories, and alerts
- FastAPI service shape for downstream frontend/mobile apps
- Operational notes for 15-minute refresh cycles

## Suggested Stack

- Python 3.11+
- FastAPI for the API layer
- PostgreSQL + pgvector for articles, clusters, entities, and vector dedupe
- Redis + RQ/Celery for scheduled jobs and processing queues
- Playwright or httpx + BeautifulSoup for site adapters
- OpenAI-compatible LLM provider for Odia summaries and structured extraction

## Repo Layout

```text
config/
  sources.yaml              # Odisha source registry
docs/
  architecture.md           # Practical architecture and data flow
  data-contracts.md         # Structured output schemas
  operations.md             # Scheduler, refresh, alerting, observability
src/odisha_ai_news/
  api.py                    # FastAPI routes
  models.py                 # Core dataclasses/enums
  pipeline.py               # End-to-end orchestration
  dedupe.py                 # Similarity and cluster logic
  urgency.py                # Hybrid urgency scoring rules
  source_config.py          # YAML loader
  ai_processing.py          # LLM processing interface
tests/
  test_dedupe.py
  test_urgency.py
```

## First Run

Install dependencies:

```bash
pip install -e ".[dev]"
```

Run tests:

```bash
pytest
```

Start the API:

```bash
uvicorn odisha_ai_news.api:app --reload
```

## MVP Build Order

1. Connect PostgreSQL tables from `docs/data-contracts.md`.
2. Implement RSS/sitemap fetchers for sources with stable feeds.
3. Add per-site HTML selectors only where feed content is incomplete.
4. Store every fetched URL in `raw_articles` before AI processing.
5. Cluster duplicates before spending LLM tokens.
6. Process only the best representative article per cluster.
7. Trigger push alerts for processed articles with urgency score `>= 4`.

## Notes

The source catalog is intentionally configuration-first. News websites frequently change layouts, so source adapters should treat `config/sources.yaml` as the editable control plane and fall back from RSS to sitemap to HTML scraping as needed.
