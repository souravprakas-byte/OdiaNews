from __future__ import annotations

from dataclasses import dataclass

from odisha_ai_news.models import Category, RawArticle


@dataclass(frozen=True)
class UrgencyResult:
    score: int
    reasons: tuple[str, ...]


HIGH_SIGNAL_TERMS = {
    "breaking": 2,
    "alert": 2,
    "death": 2,
    "dead": 2,
    "killed": 2,
    "murder": 2,
    "cyclone": 2,
    "flood": 2,
    "earthquake": 2,
    "accident": 1,
    "fire": 1,
    "arrest": 1,
    "protest": 1,
    "strike": 1,
    "evacuation": 2,
    "landfall": 2,
    "red warning": 2,
    "ଆଲର୍ଟ": 2,
    "ମୃତ": 2,
    "ହତ୍ୟା": 2,
    "ବାତ୍ୟା": 2,
    "ବନ୍ୟା": 2,
    "ଗିରଫ": 1,
    "ଦୁର୍ଘଟଣା": 1,
}


URGENT_CATEGORIES = {
    Category.CRIME,
    Category.DISASTER,
    Category.HEALTH,
    Category.WEATHER,
    Category.GOVERNANCE,
}


def score_urgency(article: RawArticle, categories: tuple[Category, ...] = ()) -> UrgencyResult:
    text = f"{article.title}\n{article.body_text}".casefold()
    score = 1
    reasons: list[str] = []

    for term, weight in HIGH_SIGNAL_TERMS.items():
        if term.casefold() in text:
            score += weight
            reasons.append(f"matched term: {term}")

    if any(category in URGENT_CATEGORIES for category in categories):
        score += 1
        reasons.append("urgent category")

    if article.source_id in {"otv", "sambad", "kanak_news", "kalinga_tv"}:
        score += 1
        reasons.append("high-priority source")

    bounded = max(1, min(5, score))
    if not reasons:
        reasons.append("no urgent signals")

    return UrgencyResult(score=bounded, reasons=tuple(reasons[:6]))
