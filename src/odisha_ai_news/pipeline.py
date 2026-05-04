from __future__ import annotations

import html
import json
import os
import sys
import time
import xml.etree.ElementTree as ET
import hashlib
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urljoin
from urllib.request import Request, urlopen

from sentence_transformers import SentenceTransformer
from sklearn.metrics.pairwise import cosine_similarity
import numpy as np

import requests
from supabase import create_client, Client

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from odisha_ai_news.models import Language, RawArticle, Source

model = SentenceTransformer("all-MiniLM-L6-v2")
SIM_THRESHOLD = 0.78

def cluster_articles(articles):
    if not articles:
        return []
    
    texts = [a.title for a in articles]
    embeddings = model.encode(texts)

    clusters = []

    for i, article in enumerate(articles):
        assigned = False

        for cluster in clusters:
            sim = cosine_similarity(
                [embeddings[i]],
                [cluster["centroid"]]
            )[0][0]

            if sim > SIM_THRESHOLD:
                cluster["articles"].append(article)
                cluster["vectors"].append(embeddings[i])
                cluster["centroid"] = np.mean(cluster["vectors"], axis=0)
                assigned = True
                break

        if not assigned:
            clusters.append({
                "articles": [article],
                "vectors": [embeddings[i]],
                "centroid": embeddings[i]
            })

    return clusters

def compute_priority(cluster):
    articles = cluster["articles"]
    source_count = len(articles)

    base = max(getattr(a, "urgency_score", 1) for a in articles)

    if source_count >= 3:
        base += 1

    keywords = ["breaking", "accident", "death", "attack", "flood", "cyclone", "fire", "explosion"]

    title = articles[0].title.lower()
    if any(k in title for k in keywords):
        base += 1

    return min(base, 5)

def cluster_hash(cluster):
    titles = sorted([a.title for a in cluster["articles"]])
    combined = " ".join(titles)
    return hashlib.md5(combined.encode()).hexdigest()

def cluster_exists(supabase: Client, c_hash: str) -> bool:
    res = supabase.table("articles").select("id").eq("content_hash", c_hash).execute()
    return len(res.data) > 0

def save_cluster(supabase: Client, cluster: dict, c_hash: str) -> None:
    main = cluster["articles"][0]
    supabase.table("articles").insert({
        "title": main.title,
        "url": main.url,
        "content_hash": c_hash,
        "source_count": len(cluster["articles"])
    }).execute()

def format_message(cluster: dict, priority: int) -> str:
    main = cluster["articles"][0]
    sources = cluster["articles"]

    urls = "\n".join([f"• {a.url}" for a in sources[:3]])

    return f"""🚨 {main.title}

🧠 Confirmed by {len(sources)} sources
🔥 Priority: {priority}/5

🔗 Sources:
{urls}
"""

class TelegramNotifier:
    def __init__(self, bot_token: str, chat_id: str) -> None:
        self.bot_token = bot_token.strip()
        self.chat_id = chat_id.strip()

    def send(self, message: str) -> None:
        try:
            response = requests.post(
                f"https://api.telegram.org/bot{self.bot_token}/sendMessage",
                json={
                    "chat_id": self.chat_id,
                    "text": message[:4000],
                },
                timeout=10,
            )
            print("Telegram response status:", response.status_code)
            if response.status_code == 200:
                print("Telegram alert sent")
        except Exception as e:
            print("Telegram error:", str(e))

RSS_FEEDS = [
    "https://khabarodisha.com/rss",
    "https://odishanewsmakers.com/rss/latest-posts",
    "https://odishanewsmakers.com/rss/category/state-76",
    "https://odishanewsmakers.com/rss/category/city-74",
    "https://odia.oneindia.com/rss/feeds/odia-news-fb.xml",
    "https://odia.oneindia.com/rss/feeds/odia-odisha-fb.xml",
    "https://odia.oneindia.com/rss/feeds/odia-national-fb.xml",
    "https://odia.oneindia.com/rss/feeds/odia-business-fb.xml",
    "https://odia.oneindia.com/rss/feeds/odia-sports-fb.xml",
    "https://odia.oneindia.com/rss/feeds/odia-entertainment-fb.xml",
    "https://indianexpress.com/section/india/feed/",
    "https://indianexpress.com/section/politics/feed/",
    "https://indianexpress.com/section/business/feed/",
    "https://indianexpress.com/section/sports/feed/",
    "https://indianexpress.com/section/world/feed/",
    "https://indianexpress.com/section/technology/feed/",
    "https://indianexpress.com/section/cities/feed/",
    "https://timesofindia.indiatimes.com/rss.cms",
    "https://www.thebetterindia.com/tags/bhubaneswar/feed/feed",
    "https://www.odiastatenews.in/rss/latest-posts",
]

def fetch_rss(feed_url: str) -> list[RawArticle]:
    source = Source(
        id=feed_url,
        name=feed_url,
        language=Language.MIXED,
        homepage=feed_url,
        priority=3,
        methods=("rss",),
    )
    return fetch_feed(source, feed_url)

def fetch_feed(source: Source, feed_url: str) -> list[RawArticle]:
    try:
        root = ET.fromstring(fetch_url(feed_url))
    except Exception:
        return []
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

def get_entry_time(entry: object) -> datetime | None:
    if isinstance(entry, RawArticle):
        return entry.published_at
    return None

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

def fetch_article_body(url: str) -> tuple[str, str | None]:
    try:
        body = fetch_url(url).decode("utf-8", errors="replace")
    except (HTTPError, URLError, TimeoutError):
        return "", None
    parser = ArticleExtractor()
    parser.feed(body)
    return parser.text, parser.image_url

def require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value

def optional_env(name: str) -> str | None:
    value = os.environ.get(name)
    return value.strip() if value and value.strip() else None

def build_telegram_notifier() -> TelegramNotifier | None:
    bot_token = optional_env("BOT_TOKEN")
    chat_id = optional_env("CHAT_ID")
    if not bot_token or not chat_id:
        print("Telegram env missing; alerts disabled")
        return None
    return TelegramNotifier(bot_token, chat_id)

def fetch_all_articles() -> list[RawArticle]:
    all_articles = []
    now_utc = datetime.now(timezone.utc)
    for feed_url in RSS_FEEDS:
        try:
            print(f"Fetching: {feed_url}")
            entries = fetch_rss(feed_url)
            print(f"Fetched articles: {len(entries)}")

            for article in entries:
                entry_time = get_entry_time(article)
                if entry_time and entry_time < now_utc - timedelta(hours=2):
                    print(f"Skipping article older than 2 hours: {article.title}")
                    continue
                all_articles.append(article)
            time.sleep(1)
        except Exception as e:
            print(f"Feed failed: {feed_url} | Error: {e}")
    return all_articles

def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    print("Pipeline started")
    supabase_url = require_env("SUPABASE_URL")
    supabase_key = require_env("SUPABASE_KEY")
    supabase: Client = create_client(supabase_url, supabase_key)
    
    notifier = build_telegram_notifier()

    all_articles = fetch_all_articles()

    clusters = cluster_articles(all_articles)
    print(f"Created {len(clusters)} clusters from {len(all_articles)} articles")

    for cluster in clusters:
        priority = compute_priority(cluster)

        if priority < 3:
            continue

        c_hash = cluster_hash(cluster)

        if cluster_exists(supabase, c_hash):
            continue

        save_cluster(supabase, cluster, c_hash)

        message = format_message(cluster, priority)

        if notifier:
            notifier.send(message)
            time.sleep(2)

if __name__ == "__main__":
    main()
