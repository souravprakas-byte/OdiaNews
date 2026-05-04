from __future__ import annotations

import json
from urllib.request import Request, urlopen
from typing import Any, Protocol

from odisha_ai_news.models import Category, EntityType, NamedEntity, ProcessedArticle, RawArticle
from odisha_ai_news.urgency import score_urgency


class ArticleIntelligenceProvider(Protocol):
    def summarize_odia(self, article: RawArticle) -> str:
        """Return a 300-500 word Odia summary."""

    def extract_entities(self, article: RawArticle) -> tuple[NamedEntity, ...]:
        """Return people, places, organizations, and events."""

    def categorize(self, article: RawArticle) -> tuple[Category, ...]:
        """Return one or more normalized categories."""


class AIAnalysisCache(Protocol):
    def get(self, article_url: str) -> dict[str, Any] | None:
        """Return cached AI analysis for an article URL."""

    def set(self, article_url: str, payload: dict[str, Any]) -> None:
        """Store AI analysis for an article URL."""


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


class SimpleFallbackProcessor:
    def summarize_odia(self, article: RawArticle) -> str:
        return first_two_lines(article.body_text)

    def extract_entities(self, article: RawArticle) -> tuple[NamedEntity, ...]:
        return ()

    def categorize(self, article: RawArticle) -> tuple[Category, ...]:
        return (Category.GENERAL,)

    def get_urgency_score(self, article: RawArticle) -> int:
        return 1


class HuggingFaceArticleIntelligenceProvider:
    API_URL = "https://api-inference.huggingface.co/models/facebook/bart-large-cnn"
    URGENT_TERMS = ("election", "violence", "death", "attack")

    def __init__(self, token: str) -> None:
        self.token = token.strip()
        self._cache: dict[str, dict[str, Any]] = {}

    def summarize_odia(self, article: RawArticle) -> str:
        return str(self._analyze(article).get("summary") or "")

    def extract_entities(self, article: RawArticle) -> tuple[NamedEntity, ...]:
        return ()

    def categorize(self, article: RawArticle) -> tuple[Category, ...]:
        return (Category.GENERAL,)

    def get_urgency_score(self, article: RawArticle) -> int:
        payload = self._analyze(article)
        if payload.get("failed"):
            return 1

        text = self._input_text(article).casefold()
        if any(term in text for term in self.URGENT_TERMS):
            return 4
        return 2

    def is_failed(self, article: RawArticle) -> bool:
        return bool(self._analyze(article).get("failed"))

    def _analyze(self, article: RawArticle) -> dict[str, Any]:
        if article.url not in self._cache:
            self._cache[article.url] = self._request_summary(article)
        return self._cache[article.url]

    def _request_summary(self, article: RawArticle) -> dict[str, Any]:
        text = self._input_text(article)
        try:
            import requests

            response = requests.post(
                self.API_URL,
                headers={"Authorization": f"Bearer {self.token}"},
                json={"inputs": text},
                timeout=45,
            )
            response.raise_for_status()
            payload = response.json()
            summary = payload[0]["summary_text"]
            return {"summary": summary, "failed": False}
        except Exception as exc:
            print(f"HuggingFace API failed for {article.url}: {exc}")
            return {"summary": first_two_lines(article.body_text), "failed": True}

    def _input_text(self, article: RawArticle) -> str:
        return (article.body_text or article.title)[:1000]


class OpenAIArticleIntelligenceProvider:
    def __init__(
        self,
        api_key: str,
        model: str = "gpt-4o-mini",
        cache: AIAnalysisCache | None = None,
    ) -> None:
        self.api_key = api_key.strip()
        self.model = model
        self.cache = cache
        self._cache: dict[str, dict[str, Any]] = {}

    def summarize_odia(self, article: RawArticle) -> str:
        return str(self._analyze(article).get("summary_odia") or "")

    def extract_entities(self, article: RawArticle) -> tuple[NamedEntity, ...]:
        payload = self._analyze(article)
        entities: list[NamedEntity] = []
        for entity_type, model_type in (
            ("people", EntityType.PERSON),
            ("places", EntityType.PLACE),
            ("organizations", EntityType.ORGANIZATION),
        ):
            for text in payload.get(entity_type, []):
                entities.append(NamedEntity(text=str(text), type=model_type, confidence=0.8))
        return tuple(entities)

    def categorize(self, article: RawArticle) -> tuple[Category, ...]:
        category = str(self._analyze(article).get("category") or Category.OTHER)
        try:
            return (Category(category),)
        except ValueError:
            return (Category.OTHER,)

    def _analyze(self, article: RawArticle) -> dict[str, Any]:
        if article.url not in self._cache:
            try:
                cached = self.cache.get(article.url) if self.cache else None
                if cached:
                    print(f"Reused OpenAI cache for {article.url}")
                    self._cache[article.url] = cached
                else:
                    analysis = self._request_analysis(article)
                    self._cache[article.url] = analysis
                    if self.cache:
                        self.cache.set(article.url, analysis)
                        print(f"Stored OpenAI cache for {article.url}")
            except Exception as exc:
                print(f"OpenAI processing failed for {article.url}: {exc}")
                self._cache[article.url] = self._fallback_analysis()
        return self._cache[article.url]

    def is_failed(self, article: RawArticle) -> bool:
        return bool(self._analyze(article).get("_openai_failed"))

    def _fallback_analysis(self) -> dict[str, Any]:
        return {
            "summary_odia": "",
            "people": [],
            "places": [],
            "organizations": [],
            "category": Category.OTHER,
            "_openai_failed": True,
        }

    def _request_analysis(self, article: RawArticle) -> dict[str, Any]:
        content = article.body_text[:6000]
        payload = {
            "model": self.model,
            "response_format": {"type": "json_object"},
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You process Odisha news. Return compact JSON with keys: "
                        "summary_odia, people, places, organizations, category. "
                        "summary_odia must be Odia. category must be one of: "
                        "politics, crime, business, governance, health, education, "
                        "weather, disaster, sports, culture, entertainment, technology, other."
                    ),
                },
                {
                    "role": "user",
                    "content": f"Title: {article.title}\n\nContent:\n{content}",
                },
            ],
        }
        request = Request(
            "https://api.openai.com/v1/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        with urlopen(request, timeout=45) as response:
            data = json.loads(response.read().decode("utf-8"))

        message = data["choices"][0]["message"]["content"]
        return json.loads(message)


def process_article(
    article: RawArticle,
    *,
    cluster_id: str,
    provider: ArticleIntelligenceProvider,
) -> ProcessedArticle:
    try:
        categories = provider.categorize(article)
        ai_failed = bool(getattr(provider, "is_failed", lambda _: False)(article))
        urgency = score_urgency(article, categories)
        summary = provider.summarize_odia(article)
        entities = provider.extract_entities(article)
        custom_urgency = getattr(provider, "get_urgency_score", lambda _: None)(article)
    except Exception as exc:
        print(f"Article processing failed for {article.url}: {exc}")
        ai_failed = True
        categories = (Category.OTHER,)
        summary = ""
        entities = ()
        urgency = None
        custom_urgency = None

    if custom_urgency is not None:
        urgency_score = int(custom_urgency)
    else:
        urgency_score = 1 if ai_failed else urgency.score
    urgency_reasons = ("ai processing failed",) if ai_failed else urgency.reasons

    return ProcessedArticle(
        raw_url=article.url,
        cluster_id=cluster_id,
        headline=article.title,
        odia_summary=summary,
        categories=categories,
        entities=entities,
        urgency_score=urgency_score,
        urgency_reasons=urgency_reasons,
        image_url=article.image_url,
    )


def first_two_lines(text: str) -> str:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if len(lines) >= 2:
        return "\n".join(lines[:2])
    return (text or "").strip()[:300]
