from odisha_ai_news.models import Category, Language, RawArticle
from odisha_ai_news.urgency import score_urgency


def test_score_urgency_caps_at_five() -> None:
    article = RawArticle(
        source_id="otv",
        url="https://example.com/breaking",
        title="Breaking cyclone red warning after flood alert",
        body_text="Evacuation ordered after accident and fire.",
        language=Language.ENGLISH,
    )

    result = score_urgency(article, (Category.DISASTER,))

    assert result.score == 5
    assert result.reasons


def test_score_urgency_defaults_to_one() -> None:
    article = RawArticle(
        source_id="localwire",
        url="https://example.com/culture",
        title="Festival schedule announced",
        body_text="Local cultural programme details were published.",
        language=Language.ENGLISH,
    )

    assert score_urgency(article).score == 1
