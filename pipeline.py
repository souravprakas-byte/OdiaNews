from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

from odisha_ai_news.pipeline import main


if __name__ == "__main__":
    main()
a# =========================
# Odisha AI News Pipeline
# =========================

import os
import hashlib
import time
from datetime import datetime, timedelta, timezone

import feedparser
import requests
from rapidfuzz import fuzz
from supabase import create_client

# =========================
# ENV CONFIG
# =========================

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

# Tunables
TELEGRAM_MIN_SCORE = int(os.getenv("TELEGRAM_MIN_SCORE", "70"))
TOP_N = int(os.getenv("TOP_N", "5"))
SIM_THRESHOLD = int(os.getenv("SIM_THRESHOLD", "85"))

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

# =========================
# RSS SOURCES (20)
# =========================

RSS_FEEDS = [
    # National
    "https://timesofindia.indiatimes.com/rssfeeds/-2128936835.cms",
    "https://indianexpress.com/section/india/feed/",
    "https://www.thehindu.com/news/national/feeder/default.rss",
    "https://www.ndtv.com/india-news/rss",
    "https://www.hindustantimes.com/india-news/rssfeed.xml",
    "https://www.news18.com/rss/india.xml",
    "https://www.indiatoday.in/rss/1206584",
    "https://www.firstpost.com/india/feed",
    # Breaking / live
    "https://www.livemint.com/rss/news",
    "https://www.zeenews.india.com/rss/india-national-news.xml",
    "https://www.republicworld.com/rss/india-news",
    "https://www.oneindia.com/rss/news.xml",
    # Odisha
    "https://sambad.in/feed",
    "https://odishatv.in/feed",
    "https://kalingatv.com/feed",
    "https://pragativadi.com/feed",
    "https://odishabytes.com/feed",
    "https://orissapost.com/feed",
    "https://odishasuntimes.com/feed",
    "https://kanaknews.com/feed",
]

# =========================
# UTIL
# =========================

def normalize(text: str) -> str:
    return " ".join(text.lower().split())

def title_key(title: str) -> str:
    # remove common suffixes like " - Source"
    base = title.split("-")[0].split("|")[0]
    return normalize(base)

def get_entry_time(entry):
    try:
        if getattr(entry, "published_parsed", None):
            dt = datetime(*entry.published_parsed[:6])
            return dt.replace(tzinfo=timezone.utc)
    except:
        pass
    try:
        if getattr(entry, "updated_parsed", None):
            dt = datetime(*entry.updated_parsed[:6])
            return dt.replace(tzinfo=timezone.utc)
    except:
        pass
    return None

def get_last_processed_time():
    res = (
        supabase.table("articles")
        .select("created_at")
        .order("created_at", desc=True)
        .limit(1)
        .execute()
    )
    if res.data:
        return datetime.fromisoformat(res.data[0]["created_at"].replace("Z", "+00:00"))
    return None

def url_exists(url: str) -> bool:
    res = (
        supabase.table("articles")
        .select("id")
        .eq("url", url)
        .limit(1)
        .execute()
    )
    return len(res.data) > 0

def hash_exists(content_hash: str) -> bool:
    res = (
        supabase.table("articles")
        .select("id")
        .eq("content_hash", content_hash)
        .limit(1)
        .execute()
    )
    return len(res.data) > 0

# =========================
# SCORING
# =========================

KEYWORDS = {
    "cyclone": 30, "flood": 30, "earthquake": 30,
    "death": 25, "killed": 25, "attack": 25, "fire": 25,
    "accident": 20, "injured": 20, "hospital": 15,
    "election": 20, "resign": 20, "arrest": 20,
    "cm": 10, "minister": 10, "government": 8,
    "bhubaneswar": 8, "odisha": 8,
}

def keyword_score(text: str) -> int:
    score = 0
    t = text.lower()
    for k, w in KEYWORDS.items():
        if k in t:
            score += w
    return min(score, 50)

def recency_score(entry_time: datetime) -> int:
    if not entry_time:
        return 0
    mins = (datetime.now(timezone.utc) - entry_time).total_seconds() / 60
    if mins <= 30: return 40
    if mins <= 120: return 25
    if mins <= 360: return 15
    return 5

def compute_priority(title: str, summary: str, entry_time: datetime) -> int:
    return min(keyword_score(title + " " + (summary or "")) + recency_score(entry_time), 100)

# =========================
# TELEGRAM
# =========================

def send_telegram(message: str):
    if not BOT_TOKEN or not CHAT_ID:
        print("Telegram not configured; skipping send")
        return
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    try:
        requests.post(url, json={"chat_id": CHAT_ID, "text": message}, timeout=10)
    except Exception as e:
        print("Telegram error:", e)

def send_cluster(cluster):
    rep = cluster["rep"]
    emoji = "🔥" if cluster["priority"] >= 85 else "⚠️"

    msg = f"""{emoji} BREAKING NEWS

📰 {rep['title']}

📊 Score: {cluster['priority']}
📡 Sources: {len(cluster['sources'])}

🔗 {rep['url']}
"""
    # include a few extra source links
    extra = [u for u in cluster["sources"] if u != rep["url"]][:3]
    if extra:
        msg += "\nOther sources:"
        for s in extra:
            msg += f"\n- {s}"

    send_telegram(msg)
    time.sleep(2)

# =========================
# PIPELINE
# =========================

def run_pipeline():
    print("PIPELINE STARTED")

    last_time = get_last_processed_time()
    clusters = []

    for feed in RSS_FEEDS:
        parsed = feedparser.parse(feed)
        print(f"Fetched {len(parsed.entries)} from {feed}")

        for entry in parsed.entries:
            title = getattr(entry, "title", "").strip()
            url = getattr(entry, "link", "").strip()
            summary = getattr(entry, "summary", "")

            if not title or not url:
                continue

            entry_time = get_entry_time(entry)

            # -------- NEW-NEWS FILTER --------
            if last_time and entry_time and entry_time <= last_time:
                print("Skipped old article")
                continue

            # safety: skip very old
            if entry_time and (datetime.now(timezone.utc) - entry_time > timedelta(hours=24)):
                print("Skipped >24h old article")
                continue

            # -------- DEDUP --------
            if url_exists(url):
                print("Skipped duplicate (url)")
                continue

            base = (title + " " + (summary or ""))[:800]
            content_hash = hashlib.sha1(base.encode("utf-8")).hexdigest()

            if hash_exists(content_hash):
                print("Skipped duplicate (hash)")
                continue

            # -------- PROCESS --------
            title_norm = title_key(title)
            priority = compute_priority(title, summary, entry_time)

            article = {
                "title": title,
                "url": url,
                "summary": summary or "",
                "title_norm": title_norm,
                "priority": priority,
                "hash": content_hash,
            }

            # -------- CLUSTER --------
            found = None
            for c in clusters:
                if fuzz.token_set_ratio(title_norm, c["key"]) >= SIM_THRESHOLD:
                    found = c
                    break

            if found:
                found["sources"].append(url)
                if priority > found["priority"]:
                    found["priority"] = priority
                    found["rep"] = article  # upgrade representative
                print("Cluster appended")
            else:
                clusters.append({
                    "key": title_norm,
                    "sources": [url],
                    "priority": priority,
                    "rep": article
                })
                print("Cluster created")

    # -------- SORT + LIMIT --------
    clusters.sort(key=lambda x: x["priority"], reverse=True)
    clusters = clusters[:TOP_N]

    print(f"Total clusters after limit: {len(clusters)}")

    # -------- INSERT + SEND --------
    for c in clusters:
        if c["priority"] < TELEGRAM_MIN_SCORE:
            print("Skipped low priority cluster")
            continue

        rep = c["rep"]

        try:
            supabase.table("articles").insert({
                "title": rep["title"],
                "url": rep["url"],
                "content_hash": rep["hash"],
                "source_count": len(c["sources"]),
            }).execute()
            print("Inserted new article")
        except Exception as e:
            print("Insert error:", e)
            continue

        send_cluster(c)
        print("Sent clustered news")

    print("PIPELINE DONE")


# =========================

if __name__ == "__main__":
    run_pipeline()