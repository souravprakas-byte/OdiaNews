from __future__ import annotations

import hashlib
import re
from difflib import SequenceMatcher

from odisha_ai_news.models import ArticleCluster, RawArticle


TOKEN_RE = re.compile(r"[\w\u0b00-\u0b7f]+", re.UNICODE)


def normalize_title(title: str) -> str:
    tokens = TOKEN_RE.findall(title.casefold())
    return " ".join(tokens)


def title_similarity(left: str, right: str) -> float:
    return SequenceMatcher(None, normalize_title(left), normalize_title(right)).ratio()


def canonical_key(article: RawArticle) -> str:
    url = article.canonical_url or article.url
    normalized = url.rstrip("/").casefold()
    return hashlib.sha1(normalized.encode("utf-8")).hexdigest()[:16]


def cluster_articles(
    articles: list[RawArticle],
    *,
    title_threshold: float = 0.82,
) -> list[ArticleCluster]:
    clusters: list[list[RawArticle]] = []

    for article in articles:
        for cluster in clusters:
            representative = cluster[0]
            same_url = canonical_key(article) == canonical_key(representative)
            similar_title = title_similarity(article.title, representative.title) >= title_threshold
            if same_url or similar_title:
                cluster.append(article)
                break
        else:
            clusters.append([article])

    return [_to_cluster(cluster) for cluster in clusters]


def _to_cluster(articles: list[RawArticle]) -> ArticleCluster:
    representative = max(articles, key=lambda article: len(article.body_text))
    cluster_id = hashlib.sha1(
        "|".join(sorted(canonical_key(article) for article in articles)).encode("utf-8")
    ).hexdigest()[:16]

    if len(articles) == 1:
        similarity = 1.0
    else:
        similarity = min(title_similarity(representative.title, item.title) for item in articles)

    return ArticleCluster(
        id=cluster_id,
        representative_url=representative.url,
        urls=tuple(article.url for article in articles),
        title=representative.title,
        similarity_score=round(similarity, 3),
    )
