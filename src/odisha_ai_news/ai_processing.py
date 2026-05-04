from __future__ import annotations

from typing import Protocol

from odisha_ai_news.models import Category, NamedEntity, ProcessedArticle, RawArticle
from odisha_ai_news.urgency import score_urgency


class ArticleIntelligenceProvider(Protocol):
    def summarize_odia(self, article: RawArticle) -> str:
        """Return a 300-500 word Odia summary."""

    def extract_entities(self, article: RawArticle) -> tuple[NamedEntity, ...]:
        """Return people, places, organizations, and events."""

    def categorize(self, article: RawArticle) -> tuple[Category, ...]:
        """Return one or more normalized categories."""


class PlaceholderIntelligenceProvider:
    """Deterministic provider for local tests before connecting an LLM."""

    def summarize_odia(self, article: RawArticle) -> str:
        trimmed = article.body_text.strip().replace("\n", " ")[:900]
        return f"{article.title}\n\n{trimmed}"

    def extract_entities(self, article: RawArticle) -> tuple[NamedEntity, ...]:
        return ()

    def categorize(self, article: RawArticle) -> tuple[Category, ...]:
        text = f"{article.title} {article.body_text}".casefold()
        if any(term in text for term in ("murder", "arrest", "crime", "ହତ୍ୟା", "ଗିରଫ")):
            return (Category.CRIME,)
        if any(term in text for term in ("cyclone", "flood", "ବାତ୍ୟା", "ବନ୍ୟା")):
            return (Category.DISASTER, Category.WEATHER)
        if any(term in text for term in ("election", "assembly", "bjp", "bjd", "congress")):
            return (Category.POLITICS,)
        return (Category.OTHER,)


def process_article(
    article: RawArticle,
    *,
    cluster_id: str,
    provider: ArticleIntelligenceProvider,
) -> ProcessedArticle:
    categories = provider.categorize(article)
    urgency = score_urgency(article, categories)
    return ProcessedArticle(
        raw_url=article.url,
        cluster_id=cluster_id,
        headline=article.title,
        odia_summary=provider.summarize_odia(article),
        categories=categories,
        entities=provider.extract_entities(article),
        urgency_score=urgency.score,
        urgency_reasons=urgency.reasons,
        image_url=article.image_url,
    )
