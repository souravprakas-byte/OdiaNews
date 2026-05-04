# Data Contracts

## Raw Article

```json
{
  "source_id": "otv",
  "url": "https://example.com/story",
  "canonical_url": "https://example.com/story",
  "title": "Headline",
  "body_text": "Full extracted article text",
  "language": "odia",
  "published_at": "2026-05-04T09:30:00+05:30",
  "fetched_at": "2026-05-04T09:36:00+05:30",
  "author": null,
  "image_url": "https://example.com/image.jpg",
  "metadata": {
    "section": "politics",
    "extractor_version": "2026-05-04.1"
  }
}
```

## Processed Article

```json
{
  "cluster_id": "8f23c9d1ac4320aa",
  "headline": "Headline",
  "odia_summary": "300-500 word Odia summary",
  "categories": ["politics", "governance"],
  "entities": [
    {
      "text": "Bhubaneswar",
      "type": "place",
      "confidence": 0.97
    }
  ],
  "urgency_score": 4,
  "urgency_reasons": ["urgent category", "matched term: red warning"],
  "image_url": "https://example.com/image.jpg",
  "processed_at": "2026-05-04T09:38:00+05:30"
}
```

## Category Set

- `politics`
- `crime`
- `business`
- `governance`
- `health`
- `education`
- `weather`
- `disaster`
- `sports`
- `culture`
- `entertainment`
- `technology`
- `other`

## Urgency Scale

- `1`: routine update
- `2`: notable but not time-sensitive
- `3`: developing story or public-interest update
- `4`: urgent public relevance, alert candidate
- `5`: emergency, breaking, safety-critical, or major statewide impact
