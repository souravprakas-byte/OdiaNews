from __future__ import annotations

import html
import json
import os
import sys
import time
import xml.etree.ElementTree as ET
import hashlib
import string
import re
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

_model = None
def get_model():
    global _model
    if _model is None:
        _model = SentenceTransformer("all-MiniLM-L6-v2")
    return _model

SIM_THRESHOLD = 0.80

def preprocess_title(title: str) -> str:
    title = title.lower()
    title = title.translate(str.maketrans('', '', string.punctuation))
    title = re.sub(r'\s+', ' ', title).strip()
    return title

def cluster_articles(articles):
    if not articles:
        return []
    
    texts = [preprocess_title(a.title) for a in articles]
    model = get_model()
    embeddings = model.encode(texts, batch_size=32, show_progress_bar=False)

    sim_matrix = cosine_similarity(embeddings)
    
    clusters = []
    assigned_indices = set()

    for i, article in enumerate(articles):
        if i in assigned_indices:
            continue
            
        cluster_articles_list = [article]
        cluster_vectors = [embeddings[i]]
        assigned_indices.add(i)
        
        for j in range(i + 1, len(articles)):
            if j not in assigned_indices and sim_matrix[i, j] >= SIM_THRESHOLD:
                cluster_articles_list.append(articles[j])
                cluster_vectors.append(embeddings[j])
                assigned_indices.add(j)
                
        clusters.append({
            "articles": cluster_articles_list,
            "vectors": cluster_vectors,
            "centroid": np.mean(cluster_vectors, axis=0)
        })

    return clusters

def compute_priority(cluster):
    articles = cluster["articles"]
    source_count = min(len(articles), 5)

    main = articles[0]
    age_hours = 0
    if main.published_at:
        now_utc = datetime.now(timezone.utc)
        if main.published_at.tzinfo is None:
            pub_time = main.published_at.replace(tzinfo=timezone.utc)
        else:
            pub_time = main.published_at.astimezone(timezone.utc)
        delta = now_utc - pub_time
        age_hours = max(0, delta.total_seconds() / 3600.0)

    base = 0
    keywords = ["breaking", "alert", "death", "attack", "fire", "blast", "arrest", "accident", "explosion"]
    title = main.title.lower()
    
    if any(k in title for k in keywords):
        base += 3

    base += source_count
    base -= (0.3 * age_hours)

    return base

def cluster_hash(cluster):
    titles = sorted([a.title for a in cluster["articles"]])
    combined = " ".join(titles)
    return hashlib.md5(combined.encode()).hexdigest()

def fetch_existing_hashes(supabase: Client) -> set[str]:
    try:
        # Fetch up to 5000 recent hashes to keep memory low but catch everything relevant
        res = supabase.table("articles").select("content_hash").order("created_at", desc=True).limit(5000).execute()
        return {row["content_hash"] for row in res.data if row.get("content_hash")}
    except Exception as e:
        print(f"Warning: Failed to fetch hashes: {e}")
        return set()

def format_message(cluster: dict, priority: float) -> str:
    main = cluster["articles"][0]
    sources = cluster["articles"]

    urls = "\n".join([f"- {a.url}" for a in sources[:3]])
    
    combined_titles = " | ".join(list(dict.fromkeys([a.title for a in sources])))

    return f"""🚨 BREAKING NEWS (Priority {priority:.1f})

📰 {main.title}

📊 Reported by {len(sources)} sources

🧾 Summary:
{combined_titles}

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
        element = entry.find(f"{{http://www.w3.org/2005/Atom}}{{tag}}")
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
                if entry_time and entry_time < now_utc - timedelta(hours=24):
                    continue
                all_articles.append(article)
        except Exception as e:
            print(f"Feed failed: {feed_url} | Error: {e}")
    return all_articles

def main() -> dict:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    start_time = time.time()
    print("Pipeline started")

    SUPABASE_URL = os.getenv("SUPABASE_URL")
    SUPABASE_KEY = os.getenv("SUPABASE_KEY")
    TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
    TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

    if not SUPABASE_URL or not SUPABASE_KEY:
        raise RuntimeError("Missing Supabase credentials")

    supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
    
    notifier = None
    if TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID:
        notifier = TelegramNotifier(TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID)
    else:
        print("Telegram env missing; alerts disabled")

    # STEP 1 & 2: Fetch and Preprocess
    all_articles = fetch_all_articles()
    
    if not all_articles:
        print(f"Finished in {time.time()-start_time:.2f}s")
        return {"status": "completed", "clusters_processed": 0, "new_events": 0, "alerts_sent": 0}

    # STEP 3 & 4: Batch embed and Cluster
    clusters = cluster_articles(all_articles)
    print(f"Created {len(clusters)} clusters from {len(all_articles)} articles")

    # STEP 5: Generate cluster hashes
    for cluster in clusters:
        cluster["hash"] = cluster_hash(cluster)
        
    # STEP 6: Fetch existing hashes (Supabase)
    existing_hashes = fetch_existing_hashes(supabase)
    
    # STEP 7: Filter new clusters only
    new_clusters = [c for c in clusters if c["hash"] not in existing_hashes]
    print(f"Found {len(new_clusters)} new clusters")
    
    # STEP 8 & 9: Compute priority scores & Keep only breaking clusters
    breaking_clusters = []
    for cluster in new_clusters:
        priority = compute_priority(cluster)
        cluster["priority"] = priority
        if priority >= 3:
            breaking_clusters.append(cluster)
            
    print(f"Found {len(breaking_clusters)} breaking events")

    # STEP 10: Send Telegram alerts
    if notifier:
        for cluster in breaking_clusters:
            message = format_message(cluster, cluster["priority"])
            notifier.send(message)
            time.sleep(1)
            
    # STEP 11: Batch insert into Supabase
    if new_clusters:
        rows_to_insert = []
        for cluster in new_clusters:
            main_article = cluster["articles"][0]
            rows_to_insert.append({
                "title": main_article.title,
                "url": main_article.url,
                "content_hash": cluster["hash"],
                "source_count": len(cluster["articles"])
            })
        
        try:
            supabase.table("articles").insert(rows_to_insert).execute()
            print(f"Batch inserted {len(rows_to_insert)} clusters")
        except Exception as e:
            print(f"Batch insert failed: {e}")

    print(f"Pipeline finished in {time.time()-start_time:.2f}s")
    
    return {
        "clusters_processed": len(clusters),
        "new_events": len(new_clusters),
        "alerts_sent": len(breaking_clusters)
    }

if __name__ == "__main__":
    main()
