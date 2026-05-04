from odisha_ai_news.dedupe import cluster_articles, title_similarity
from odisha_ai_news.models import Language, RawArticle


def article(url: str, title: str) -> RawArticle:
    return RawArticle(
        source_id="otv",
        url=url,
        title=title,
        body_text="Long article body",
        language=Language.ENGLISH,
    )


def test_title_similarity_normalizes_case_and_punctuation() -> None:
    assert title_similarity("Odisha CM Reviews Cyclone Prep!", "odisha cm reviews cyclone prep") > 0.9


def test_cluster_articles_groups_similar_titles() -> None:
    clusters = cluster_articles(
        [
            article("https://a.example/story-1", "Odisha CM reviews cyclone preparedness"),
            article("https://b.example/story-2", "Odisha CM reviews cyclone preparedness"),
            article("https://c.example/story-3", "Cuttack wins football final"),
        ]
    )

    assert len(clusters) == 2
    assert sorted(len(cluster.urls) for cluster in clusters) == [1, 2]
