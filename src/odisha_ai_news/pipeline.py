from __future__ import annotations

print("MODULE LOADED")

import html
import json
import os
import sys
import xml.etree.ElementTree as ET
from collections.abc import Iterable
from datetime import datetime
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urljoin
from urllib.request import Request, urlopen

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from odisha_ai_news.ai_processing import (
    AIAnalysisCache,
    ArticleIntelligenceProvider,
    HuggingFaceArticleIntelligenceProvider,
    SimpleFallbackProcessor,
    process_article,
)
from odisha_ai_news.dedupe import cluster_articles
from odisha_ai_news.models import EntityType, Language, ProcessedArticle, RawArticle, Source
from odisha_ai_news.source_config import load_sources


class ArticleStore:
    def upsert_raw(self, articles: Iterable[RawArticle]) -> None:
        raise NotImplementedError

    def get_recent_unprocessed(self) -> list[RawArticle]:
        raise NotImplementedError

    def upsert_processed(self, articles: Iterable[ProcessedArticle]) -> None:
        raise NotImplementedError


class AlertSink:
    def publish(self, article: ProcessedArticle) -> None:
        raise NotImplementedError


class SupabaseClient:
    def __init__(self, url: str, key: str) -> None:
        self.url = url.strip().rstrip("/")
        self.key = key.strip()

    def article_exists(self, article_url: str) -> bool:
        encoded_url = quote(article_url, safe="")
        response = self._request(
            "GET",
            f"/rest/v1/articles?url=eq.{encoded_url}&select=id&limit=1",
        )
        return bool(json.loads(response.decode("utf-8")))

    def insert_article(self, article: RawArticle) -> int | str:
        payload = {
            "title": article.title,
            "source": article.source_id,
            "url": article.url,
            "content": article.body_text,
            "image_url": article.image_url,
            "published_at": datetime_to_iso(article.published_at),
        }
        response = self._request(
            "POST",
            "/rest/v1/articles",
            payload,
            prefer="return=representation",
        )
        rows = json.loads(response.decode("utf-8"))
        return rows[0]["id"]

    def insert_processed(self, article_id: int | str, processed: ProcessedArticle) -> None:
        people = [
            entity.text for entity in processed.entities if entity.type == EntityType.PERSON
        ]
        places = [
            entity.text for entity in processed.entities if entity.type == EntityType.PLACE
        ]
        organizations = [
            entity.text
            for entity in processed.entities
            if entity.type == EntityType.ORGANIZATION
        ]
        payload = {
            "article_id": article_id,
            "summary_odia": processed.odia_summary,
            "people": people,
            "places": places,
            "organizations": organizations,
            "category": ", ".join(processed.categories),
            "urgency_score": processed.urgency_score,
        }
        self._request("POST", "/rest/v1/processed_articles", payload)

    def get_ai_cache(self, article_url: str) -> dict[str, object] | None:
        encoded_url = quote(article_url, safe="")
        response = self._request(
            "GET",
            f"/rest/v1/ai_cache?url=eq.{encoded_url}&select=result&limit=1",
        )
        rows = json.loads(response.decode("utf-8"))
        if not rows:
            return None
        result = rows[0].get("result")
        return result if isinstance(result, dict) else None

    def set_ai_cache(self, article_url: str, result: dict[str, object]) -> None:
        payload = {
            "url": article_url,
            "result": result,
        }
        self._request(
            "POST",
            "/rest/v1/ai_cache?on_conflict=url",
            payload,
            prefer="resolution=merge-duplicates",
        )

    def _request(
        self,
        method: str,
        path: str,
        payload: dict[str, object] | None = None,
        *,
        prefer: str | None = None,
    ) -> bytes:
        body = json.dumps(payload).encode("utf-8") if payload is not None else None
        headers = {
            "apikey": self.key,
            "Authorization": f"Bearer {self.key}",
            "Content-Type": "application/json",
        }
        if prefer:
            headers["Prefer"] = prefer

        print(f"Supabase request headers: {mask_headers(headers)}")

        request = Request(
            f"{self.url}{path}",
            data=body,
            method=method,
        )
        for name, value in headers.items():
            request.add_header(name, value)

        with urlopen(request, timeout=20) as response:
            return response.read()

    def _headers(self) -> dict[str, str]:
        return {
            "apikey": self.key,
            "Authorization": f"Bearer {self.key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }


class TelegramNotifier:
    def __init__(self, bot_token: str, chat_id: str) -> None:
        self.bot_token = bot_token.strip()
        self.chat_id = chat_id.strip()

    def send(self, processed: ProcessedArticle) -> None:
        import requests
        import os

        BOT_TOKEN = os.getenv("BOT_TOKEN")
        CHAT_ID = os.getenv("CHAT_ID")

        if not BOT_TOKEN or not CHAT_ID:
            print("Telegram skipped: missing BOT_TOKEN or CHAT_ID")
            return

        score = processed.urgency_score or 0
        if score >= 4:
            emoji = "🔥"
        elif score >= 3:
            emoji = "⚠️"
        else:
            emoji = "🟢"

        title = safe_markdown(processed.headline)
        category = safe_markdown(", ".join(processed.categories))
        summary = safe_markdown(processed.odia_summary)
        url = processed.raw_url

        message = f"""
{emoji} {title}

📊 Urgency: {score}/5
🏷 Category: {category}

🧠 Summary:
{summary}

🔗 {url}
"""

        try:
            response = requests.post(
                f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
                json={
                    "chat_id": CHAT_ID,
                    "text": message[:4000],
                    "parse_mode": "Markdown",
                },
                timeout=10,
            )

            print(f"Telegram response status: {response.status_code}")
            if response.status_code != 200:
                print("Telegram error:", response.text)
            else:
                print("Telegram alert sent")

        except Exception as e:
            print("Telegram exception:", str(e))


class SupabaseAICache:
    def __init__(self, supabase: SupabaseClient) -> None:
        self.supabase = supabase

    def get(self, article_url: str) -> dict[str, object] | None:
        try:
            return self.supabase.get_ai_cache(article_url)
        except Exception as exc:
            print(f"AI cache lookup failed for {article_url}: {exc}")
            return None

    def set(self, article_url: str, payload: dict[str, object]) -> None:
        try:
            self.supabase.set_ai_cache(article_url, payload)
        except Exception as exc:
            print(f"AI cache store failed for {article_url}: {exc}")


def run_processing_cycle(
    *,
    store: ArticleStore,
    intelligence: ArticleIntelligenceProvider,
    alert_sink: AlertSink | None = None,
    alert_threshold: int = 4,
) -> list[ProcessedArticle]:
    candidates = store.get_recent_unprocessed()
    clusters = cluster_articles(candidates)
    by_url = {article.url: article for article in candidates}
    processed: list[ProcessedArticle] = []

    for cluster in clusters:
        representative = by_url[cluster.representative_url]
        article = process_article(representative, cluster_id=cluster.id, provider=intelligence)
        processed.append(article)

        if alert_sink and article.urgency_score >= alert_threshold:
            alert_sink.publish(article)

    store.upsert_processed(processed)
    return processed


def fetch_rss_articles(sources: list[Source], *, max_articles: int = 3) -> list[RawArticle]:
    articles: list[RawArticle] = []

    for source in sources:
        if "rss" not in source.methods:
            continue

        for feed_url in rss_candidates(source.homepage):
            try:
                feed_articles = fetch_feed(source, feed_url)
            except (HTTPError, URLError, TimeoutError, ET.ParseError):
                continue

            articles.extend(feed_articles)
            if articles:
                break

        if len(articles) >= max_articles:
            return articles[:max_articles]

    return articles[:max_articles]


def rss_candidates(homepage: str) -> tuple[str, ...]:
    return (
        urljoin(homepage, "/feed/"),
        urljoin(homepage, "/feed"),
        urljoin(homepage, "/rss"),
        urljoin(homepage, "/rss.xml"),
        urljoin(homepage, "/atom.xml"),
    )


def fetch_feed(source: Source, feed_url: str) -> list[RawArticle]:
    root = ET.fromstring(fetch_url(feed_url))
    entries = root.findall(".//item") or root.findall("{http://www.w3.org/2005/Atom}entry")
    articles: list[RawArticle] = []

    for entry in entries:
        title = text_from(entry, "title")
        url = link_from(entry)
        description = text_from(entry, "description") or text_from(entry, "summary")
        published_at = parse_feed_datetime(
            text_from(entry, "pubDate")
            or text_from(entry, "published")
            or text_from(entry, "updated")
        )

        if not title or not url:
            continue

        body_text, image_url = fetch_article_body(url)
        articles.append(
            RawArticle(
                source_id=source.id,
                url=url,
                title=html.unescape(title).strip(),
                body_text=body_text or html_to_text(description) or title,
                language=source.language or Language.MIXED,
                published_at=published_at,
                image_url=image_url,
            )
        )

    return articles


def text_from(entry: ET.Element, tag: str) -> str:
    element = entry.find(tag)
    if element is None:
        element = entry.find(f"{{http://www.w3.org/2005/Atom}}{tag}")
    return (element.text or "").strip() if element is not None else ""


def link_from(entry: ET.Element) -> str:
    link = text_from(entry, "link")
    if link:
        return link

    atom_link = entry.find("{http://www.w3.org/2005/Atom}link")
    if atom_link is not None:
        return (atom_link.attrib.get("href") or "").strip()

    return ""


def html_to_text(value: str) -> str:
    if not value:
        return ""
    parser = TextExtractor()
    parser.feed(html.unescape(value))
    return parser.text


def fetch_url(url: str) -> bytes:
    request = Request(
        url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (compatible; OdishaAINewsBot/0.1; "
                "+https://example.com/odisha-ai-news)"
            )
        },
    )
    with urlopen(request, timeout=15) as response:
        return response.read()


def parse_feed_datetime(value: str) -> datetime | None:
    if not value:
        return None

    try:
        return parsedate_to_datetime(value)
    except (TypeError, ValueError):
        pass

    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def datetime_to_iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def fetch_article_body(url: str) -> tuple[str, str | None]:
    try:
        body = fetch_url(url).decode("utf-8", errors="replace")
    except (HTTPError, URLError, TimeoutError):
        return "", None

    parser = ArticleExtractor()
    parser.feed(body)
    return parser.text, parser.image_url


class TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []

    @property
    def text(self) -> str:
        return " ".join(part.strip() for part in self.parts if part.strip())

    def handle_data(self, data: str) -> None:
        self.parts.append(data)


class ArticleExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._in_paragraph = False
        self._paragraphs: list[str] = []
        self._current: list[str] = []
        self.image_url: str | None = None

    @property
    def text(self) -> str:
        return " ".join(paragraph.strip() for paragraph in self._paragraphs if paragraph.strip())

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_dict = {key.casefold(): value for key, value in attrs if value}
        if tag == "p":
            self._in_paragraph = True
            self._current = []
        elif tag == "meta" and not self.image_url:
            name = attrs_dict.get("property") or attrs_dict.get("name")
            if name in {"og:image", "twitter:image"}:
                self.image_url = attrs_dict.get("content")
        elif tag == "img" and not self.image_url:
            self.image_url = attrs_dict.get("src")

    def handle_endtag(self, tag: str) -> None:
        if tag == "p" and self._in_paragraph:
            self._paragraphs.append(" ".join(self._current))
            self._in_paragraph = False
            self._current = []

    def handle_data(self, data: str) -> None:
        if self._in_paragraph:
            self._current.append(data)


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    print("PIPELINE STARTED - CONFIRMED")
    config_path = Path(__file__).resolve().parents[2] / "config" / "sources.yaml"
    sources = load_sources(config_path)
    articles = fetch_rss_articles(sources, max_articles=3)
    print(f"Fetched articles: {len(articles)}")
    supabase = SupabaseClient(
        require_env("SUPABASE_URL"),
        require_env("SUPABASE_KEY"),
    )
    provider = build_intelligence_provider()
    notifier = build_telegram_notifier()

    if not articles:
        print("No RSS articles fetched.")
        return

    for article in articles:
        print(f"Article title before processing: {article.title}")
        print(f"Article URL before processing: {article.url}")
        if supabase.article_exists(article.url):
            print("Skipped duplicate")
            continue

        article_id = supabase.insert_article(article)
        print("Inserted article")

        processed = process_article(article, cluster_id="test-run", provider=provider)
        supabase.insert_processed(article_id, processed)
        print("Processed stored")
        print(f"Urgency score: {processed.urgency_score}")

        if notifier:
            try:
                notifier.send(processed)
                print(f"Telegram sent | urgency={processed.urgency_score}")
            except Exception as exc:
                print(f"Telegram alert failed: {exc}")

        print(f"title: {processed.headline}")
        print(f"summary_odia: {processed.odia_summary}")
        print(f"category: {', '.join(processed.categories)}")
        print(f"urgency_score: {processed.urgency_score}")
        print()


def require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def optional_env(name: str) -> str | None:
    value = os.environ.get(name)
    return value.strip() if value and value.strip() else None


def build_intelligence_provider() -> ArticleIntelligenceProvider:
    token = os.getenv("HF_API_TOKEN")
    if token:
        print("Using HuggingFace provider")
        return HuggingFaceArticleIntelligenceProvider(token)
    else:
        print("No HF token, using fallback")
        return SimpleFallbackProcessor()


def build_telegram_notifier() -> TelegramNotifier | None:
    bot_token = optional_env("BOT_TOKEN")
    chat_id = optional_env("CHAT_ID")
    if not bot_token or not chat_id:
        print("Telegram env missing; alerts disabled")
        return None
    return TelegramNotifier(bot_token, chat_id)


def telegram_urgency_threshold() -> int:
    value = optional_env("TELEGRAM_URGENCY_THRESHOLD")
    if not value:
        return 4

    try:
        return int(value)
    except ValueError:
        print(f"Invalid TELEGRAM_URGENCY_THRESHOLD={value}; using 4")
        return 4


def safe_markdown(text: object) -> str:
    return str(text).replace("_", "").replace("*", "")


def mask_headers(headers: dict[str, str]) -> dict[str, str]:
    masked = dict(headers)
    for key in ("apikey", "Authorization"):
        if key in masked:
            masked[key] = mask_secret(masked[key])
    return masked


def mask_secret(value: str) -> str:
    if len(value) <= 12:
        return "***"
    return f"{value[:6]}...{value[-4:]}"


if __name__ == "__main__":
    main()
