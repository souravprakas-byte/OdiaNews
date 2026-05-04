# Architecture

## Goal

Build a near-real-time intelligence layer over Odisha news, where the output is a structured, queryable record rather than a plain summary.

## Data Flow

```text
Scheduler, every 15 minutes
  -> source adapters
  -> raw article store
  -> dedupe and cluster
  -> AI processing
  -> processed article DB
  -> API
  -> frontend, app, alerts
```

## Components

### Scheduler

Run every 15 minutes. In production, use Celery Beat, RQ Scheduler, Temporal, or a managed cron that enqueues source fetch jobs. Avoid one long global scrape job; enqueue one job per source so slow or blocked sites do not delay the whole cycle.

### Source Adapters

Each source should support the best available method in this order:

1. RSS/Atom feed
2. XML sitemap or news sitemap
3. HTML section pages
4. Browser rendering with Playwright for JavaScript-heavy pages

Adapters should return `RawArticle` records with title, body, source, URL, canonical URL, publish time, and image URL. Image extraction should first check `og:image`, then `twitter:image`, then article body images.

### Raw Store

Persist every fetched article before AI processing. This gives replay, audit, and debugging when source markup breaks.

Recommended keys:

- `source_id`
- `url`
- `canonical_url`
- `url_hash`
- `title`
- `body_text`
- `language`
- `published_at`
- `fetched_at`
- `image_url`
- `raw_html`
- `extractor_version`

### Deduplication

Use three stages:

1. Exact match by canonical URL or URL hash.
2. Near match by normalized title similarity.
3. Semantic match by article embedding with pgvector.

For the MVP, title similarity around `0.82` is a reasonable first threshold. For production, combine title similarity, same named places, publish-time proximity, and vector distance.

### AI Processing

Run AI only on the representative article for each cluster.

The LLM should return structured JSON:

- Odia summary, around 300-500 words
- named entities: people, places, organizations, events
- categories
- urgency score override or confidence
- short reason codes

Keep rule-based urgency scoring as the baseline. Let the model adjust it only when it gives a specific reason.

### API Layer

Initial endpoints:

- `GET /health`
- `GET /articles?category=&min_urgency=&limit=`
- `GET /alerts`
- `GET /articles/{id}`
- `GET /clusters/{id}`
- `GET /entities?type=&q=`

### Alerts

Push when `urgency_score >= 4`. De-duplicate alerts by cluster, not article URL, so the same story appearing on five websites does not trigger five notifications.

## Practical Deployment

Use a worker deployment with these queues:

- `fetch`: source ingestion
- `extract`: article parsing
- `dedupe`: clustering
- `ai`: summaries/entities/categories
- `alerts`: push notification fanout

Keep the API stateless. Workers own the pipeline, and the API reads from processed tables.
