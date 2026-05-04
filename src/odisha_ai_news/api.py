from __future__ import annotations

from fastapi import FastAPI, Query
from pydantic import BaseModel, Field


app = FastAPI(title="Odisha AI News Intelligence Engine", version="0.1.0")


class EntityOut(BaseModel):
    text: str
    type: str
    confidence: float = Field(ge=0, le=1)


class ArticleOut(BaseModel):
    id: str
    headline: str
    source_ids: list[str]
    canonical_url: str
    odia_summary: str
    categories: list[str]
    urgency_score: int = Field(ge=1, le=5)
    urgency_reasons: list[str]
    entities: list[EntityOut]
    image_url: str | None = None
    published_at: str | None = None
    processed_at: str


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/articles", response_model=list[ArticleOut])
def list_articles(
    category: str | None = None,
    min_urgency: int = Query(default=1, ge=1, le=5),
    limit: int = Query(default=25, ge=1, le=100),
) -> list[ArticleOut]:
    """API shape placeholder; wire to the processed article database."""
    return []


@app.get("/alerts", response_model=list[ArticleOut])
def list_alerts(limit: int = Query(default=25, ge=1, le=100)) -> list[ArticleOut]:
    """Return urgency >= 4 stories once the database repository is connected."""
    return []
