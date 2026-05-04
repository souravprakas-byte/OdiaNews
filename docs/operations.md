# Operations

## Refresh Cycle

Run ingestion every 15 minutes:

```text
*/15 * * * * enqueue_fetch_jobs
```

Each cycle should:

1. Load active sources from `config/sources.yaml`.
2. Enqueue one fetch job per source.
3. Upsert raw article records.
4. Cluster recent unprocessed articles.
5. Process one representative article per cluster.
6. Store processed output.
7. Publish alerts for clusters with urgency `>= 4`.

## Failure Handling

- Treat source failures as isolated events.
- Retry fetch failures with exponential backoff.
- Track parser failures by source and extractor version.
- Alert maintainers when one source has 3 consecutive failed cycles.
- Keep raw HTML for a short retention window to debug selector breakage.

## Observability

Minimum metrics:

- articles fetched per source
- extraction success rate
- duplicate cluster size
- AI processing latency
- AI token cost per cycle
- alert count by urgency
- source failure streak

## Compliance

- Respect `robots.txt` and source terms.
- Prefer RSS feeds and sitemaps over page scraping.
- Store excerpts and structured metadata for internal intelligence workflows.
- Link users back to original publishers for full article reading.

## Alert Policy

Send push alerts only once per cluster. Recommended payload:

```json
{
  "cluster_id": "8f23c9d1ac4320aa",
  "headline": "Headline",
  "urgency_score": 4,
  "summary_short": "One or two sentence alert summary",
  "image_url": "https://example.com/image.jpg",
  "source_count": 3
}
```
