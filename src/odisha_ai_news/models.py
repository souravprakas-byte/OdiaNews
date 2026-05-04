from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any


class Language(StrEnum):
    ODIA = "odia"
    ENGLISH = "english"
    MIXED = "mixed"


class Category(StrEnum):
    GENERAL = "general"
    POLITICS = "politics"
    CRIME = "crime"
    BUSINESS = "business"
    GOVERNANCE = "governance"
    HEALTH = "health"
    EDUCATION = "education"
    WEATHER = "weather"
    DISASTER = "disaster"
    SPORTS = "sports"
    CULTURE = "culture"
    ENTERTAINMENT = "entertainment"
    TECHNOLOGY = "technology"
    OTHER = "other"


class EntityType(StrEnum):
    PERSON = "person"
    PLACE = "place"
    ORGANIZATION = "organization"
    EVENT = "event"
    OTHER = "other"


@dataclass(frozen=True)
class Source:
    id: str
    name: str
    language: Language
    homepage: str
    priority: int
    methods: tuple[str, ...]
    notes: str | None = None


@dataclass(frozen=True)
class RawArticle:
    source_id: str
    url: str
    title: str
    body_text: str
    language: Language
    published_at: datetime | None = None
    fetched_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    author: str | None = None
    image_url: str | None = None
    canonical_url: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class NamedEntity:
    text: str
    type: EntityType
    confidence: float


@dataclass(frozen=True)
class ProcessedArticle:
    raw_url: str
    cluster_id: str
    headline: str
    odia_summary: str
    categories: tuple[Category, ...]
    entities: tuple[NamedEntity, ...]
    urgency_score: int
    urgency_reasons: tuple[str, ...]
    image_url: str | None
    source: str | None = None
    processed_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass(frozen=True)
class ArticleCluster:
    id: str
    representative_url: str
    urls: tuple[str, ...]
    title: str
    similarity_score: float
