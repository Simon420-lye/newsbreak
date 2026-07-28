#!/usr/bin/env python3
"""
Wire — technology news sourcing.

Changes from the tech+finance version:
  · one vertical (technology), many more sources
  · near-identical stories are CLUSTERED, not discarded — the number of
    outlets covering a story is the importance signal
  · each story gets a score (cluster size + recency) used to rank
  · keyword topic tagging (ai / chips / security / startups / policy / consumer)

Usage:
    python fetch.py
    python fetch.py --output news_data.json --limit 90
"""

import argparse
import datetime
import hashlib
import json
import re
from collections import defaultdict
from difflib import SequenceMatcher
from email.utils import parsedate_to_datetime

import feedparser
import requests

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)

# ---------------------------------------------------------------------------
# Sources. Breadth is the whole point — a story you miss is a reader you lose.
# Any feed that dies just logs a [skip]; it never breaks the run.
# ---------------------------------------------------------------------------

FEEDS = [
    # general tech press
    ("TechCrunch",        "https://techcrunch.com/feed/"),
    ("The Verge",         "https://www.theverge.com/rss/index.xml"),
    ("Ars Technica",      "https://feeds.arstechnica.com/arstechnica/index"),
    ("Wired",             "https://www.wired.com/feed/rss"),
    ("Engadget",          "https://www.engadget.com/rss.xml"),
    ("Gizmodo",           "https://gizmodo.com/feed"),
    ("VentureBeat",       "https://venturebeat.com/feed/"),
    ("ZDNet",             "https://www.zdnet.com/news/rss.xml"),
    ("CNET",              "https://www.cnet.com/rss/news/"),
    ("TechRadar",         "https://www.techradar.com/rss"),
    ("The Next Web",      "https://thenextweb.com/feed"),
    ("Digital Trends",    "https://www.digitaltrends.com/feed/"),
    ("The Register",      "https://www.theregister.com/headlines.atom"),
    ("InfoQ",             "https://feed.infoq.com/"),

    # aggregators / community
    ("Techmeme",          "https://www.techmeme.com/feed.xml"),
    ("Hacker News",       "https://hnrss.org/frontpage"),
    ("Lobsters",          "https://lobste.rs/rss"),

    # AI
    ("MIT Tech Review",   "https://www.technologyreview.com/feed/"),
    ("VentureBeat AI",    "https://venturebeat.com/category/ai/feed/"),
    ("The Decoder",       "https://the-decoder.com/feed/"),

    # hardware / semis
    ("Tom's Hardware",    "https://www.tomshardware.com/feeds/all"),
    ("AnandTech",         "https://www.anandtech.com/rss/"),

    # security
    ("Krebs on Security", "https://krebsonsecurity.com/feed/"),
    ("BleepingComputer",  "https://www.bleepingcomputer.com/feed/"),
    ("The Hacker News",   "https://feeds.feedburner.com/TheHackersNews"),

    # apple / google ecosystems
    ("9to5Mac",           "https://9to5mac.com/feed/"),
    ("9to5Google",        "https://9to5google.com/feed/"),
    ("MacRumors",         "https://feeds.macrumors.com/MacRumors-All"),
    ("Android Authority", "https://www.androidauthority.com/feed/"),

    # business of tech
    ("CNBC Tech",         "https://www.cnbc.com/id/19854910/device/rss/rss.html"),
    ("Crunchbase News",   "https://news.crunchbase.com/feed/"),
    ("Sifted",            "https://sifted.eu/feed"),
]

# ---------------------------------------------------------------------------
# Topic tagging — crude keyword match, but transparent and instant.
# ---------------------------------------------------------------------------

TOPICS = {
    "ai": ["ai", "a.i.", "artificial intelligence", "llm", "gpt", "openai", "anthropic",
           "claude", "gemini", "deepseek", "mistral", "machine learning", "neural",
           "chatbot", "copilot", "agentic", "inference", "training run"],
    "chips": ["chip", "semiconductor", "nvidia", "tsmc", "intel", "amd", "gpu", "foundry",
              "arm holdings", "wafer", "fab", "lithography", "asml", "broadcom"],
    "security": ["hack", "breach", "ransomware", "vulnerability", "exploit", "malware",
                 "phishing", "cve-", "zero-day", "leak", "cyberattack", "botnet"],
    "startups": ["funding", "raises", "raised", "series a", "series b", "series c",
                 "seed round", "valuation", "venture", "acquires", "acquisition",
                 "ipo", "startup"],
    "policy": ["regulation", "antitrust", "lawsuit", "sues", "european union", "ftc",
               "doj", "ban", "court", "senate", "congress", "bill", "fine", "probe",
               "investigation", "tariff"],
    "consumer": ["iphone", "android", "pixel", "samsung", "app store", "launch",
                 "review", "release", "wearable", "headset", "laptop", "smartphone"],
}

STOP = {
    "the", "a", "an", "of", "to", "in", "for", "on", "and", "is", "are", "with", "at",
    "by", "from", "as", "its", "it", "this", "that", "new", "says", "said", "will",
    "how", "why", "what", "your", "you", "not", "but", "can", "has", "have", "was",
    "were", "more", "than", "now", "just", "into", "after", "over", "about",
}


def get_feed(url):
    resp = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=15)
    resp.raise_for_status()
    return feedparser.parse(resp.content)


def parse_date(entry):
    for field in ("published", "updated"):
        raw = entry.get(field)
        if raw:
            try:
                dt = parsedate_to_datetime(raw)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=datetime.timezone.utc)
                return dt
            except Exception:
                pass
    if entry.get("published_parsed"):
        return datetime.datetime(*entry["published_parsed"][:6], tzinfo=datetime.timezone.utc)
    return None


def clean_summary(entry, limit=420):
    raw = entry.get("summary", "") or ""
    text = re.sub(r"<[^>]+>", "", raw)
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"^(Read more|Continue reading).*?$", "", text).strip()
    return text[:limit] + ("…" if len(text) > limit else "")


def extract_image(entry):
    for mc in entry.get("media_content") or []:
        if mc.get("url"):
            return mc["url"]
    for mt in entry.get("media_thumbnail") or []:
        if mt.get("url"):
            return mt["url"]
    for link in entry.get("links") or []:
        if link.get("rel") == "enclosure" and "image" in (link.get("type") or ""):
            return link.get("href")
    blob = ""
    for c in entry.get("content") or []:
        blob += c.get("value", "")
    blob += entry.get("summary", "") or ""
    m = re.search(r'<img[^>]+src=["\']([^"\']+)["\']', blob)
    if m:
        url = m.group(1)
        return "https:" + url if url.startswith("//") else url
    return None


def tag_topics(title, summary):
    blob = (title + " " + summary).lower()
    found = [t for t, words in TOPICS.items() if any(w in blob for w in words)]
    return found or ["general"]


def make_id(link):
    return hashlib.sha1(link.encode("utf-8")).hexdigest()[:12]


def significant(title):
    return {w for w in re.findall(r"[a-z0-9]+", title.lower())
            if len(w) > 3 and w not in STOP}


def normalize(entry, source):
    title = (entry.get("title") or "").strip()
    link = entry.get("link") or ""
    if not title or not link:
        return None
    summary = clean_summary(entry)
    published = parse_date(entry)
    return {
        "id": make_id(link),
        "title": title,
        "summary": summary,
        "link": link,
        "source": source,
        "image": extract_image(entry),
        "published": published.isoformat() if published else None,
        "topics": tag_topics(title, summary),
        "_tokens": significant(title),
        "_dt": published,
    }


def collect():
    items, ok, dead = [], 0, []
    for source, url in FEEDS:
        try:
            feed = get_feed(url)
        except Exception as e:
            dead.append(source)
            print(f"  [skip] {source}: {type(e).__name__}")
            continue
        n = 0
        for entry in feed.entries:
            item = normalize(entry, source)
            if item:
                items.append(item)
                n += 1
        if n:
            ok += 1
            print(f"  [ok]   {source}: {n}")
        else:
            dead.append(source)
            print(f"  [skip] {source}: no usable entries")
    print(f"\n{ok}/{len(FEEDS)} feeds responded" + (f" · dead: {', '.join(dead)}" if dead else ""))
    return items


# ---------------------------------------------------------------------------
# Clustering — the important part. Same story from many outlets = big story.
# ---------------------------------------------------------------------------

def cluster(items, threshold=0.62):
    """Group near-identical headlines. Returns list of clusters (lists of items)."""
    # Inverted index so we only compare plausible candidates — full pairwise
    # on 600 articles would be far too slow.
    index = defaultdict(list)
    for i, it in enumerate(items):
        for tok in it["_tokens"]:
            index[tok].append(i)

    parent = list(range(len(items)))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    for i, it in enumerate(items):
        seen = set()
        for tok in it["_tokens"]:
            for j in index[tok]:
                if j <= i or j in seen:
                    continue
                seen.add(j)
                other = items[j]
                # need at least 2 shared significant words before the expensive check
                if len(it["_tokens"] & other["_tokens"]) < 2:
                    continue
                if SequenceMatcher(None, it["title"].lower(),
                                   other["title"].lower()).ratio() >= threshold:
                    union(i, j)

    groups = defaultdict(list)
    for i in range(len(items)):
        groups[find(i)].append(items[i])
    return list(groups.values())


def build_story(group, now):
    """Collapse a cluster into one story record."""
    # Representative: prefer one with an image, then the earliest filed.
    with_img = [g for g in group if g["image"]]
    pool = with_img or group
    rep = min(pool, key=lambda g: g["_dt"] or now)

    dated = [g["_dt"] for g in group if g["_dt"]]
    newest = max(dated) if dated else None
    oldest = min(dated) if dated else None

    sources = sorted({g["source"] for g in group})
    topics = sorted({t for g in group for t in g["topics"]})

    hours = (now - newest).total_seconds() / 3600 if newest else 72
    # cluster size dominates; recency decays over ~2 days
    score = (len(sources) ** 1.6) * 12 + max(0, 48 - hours)

    return {
        "id": rep["id"],
        "title": rep["title"],
        "summary": rep["summary"],
        "link": rep["link"],
        "source": rep["source"],
        "image": rep["image"],
        "published": (newest.isoformat() if newest else None),
        "first_seen": (oldest.isoformat() if oldest else None),
        "topics": topics,
        "sources": sources,
        "outlets": len(sources),
        "score": round(score, 1),
        "also": [
            {"source": g["source"], "title": g["title"], "link": g["link"]}
            for g in sorted(group, key=lambda g: g["source"])
            if g["link"] != rep["link"]
        ][:8],
        "sentiment": None,
        "ad_slot": False,
    }


def main():
    ap = argparse.ArgumentParser(description="Fetch and rank technology news.")
    ap.add_argument("--output", default="news_data.json")
    ap.add_argument("--limit", type=int, default=90, help="max stories to keep")
    args = ap.parse_args()

    print(f"\n{'='*60}\nRun started {datetime.datetime.now():%Y-%m-%d %H:%M:%S}\n")
    items = collect()
    print(f"\nRaw articles: {len(items)}")

    now = datetime.datetime.now(datetime.timezone.utc)
    groups = cluster(items)
    print(f"Clusters: {len(groups)}")

    stories = [build_story(g, now) for g in groups]
    multi = sum(1 for s in stories if s["outlets"] > 1)
    print(f"Multi-outlet stories: {multi}")

    stories.sort(key=lambda s: s["score"], reverse=True)
    stories = stories[:args.limit]

    topic_counts = defaultdict(int)
    for s in stories:
        for t in s["topics"]:
            topic_counts[t] += 1

    payload = {
        "generated_at": now.isoformat(),
        "vertical": "technology",
        "count": len(stories),
        "topics": dict(sorted(topic_counts.items(), key=lambda kv: -kv[1])),
        "stories": stories,
    }

    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)

    print(f"\nSaved {len(stories)} stories -> {args.output}")
    print(f"Top story: [{stories[0]['outlets']} outlets] {stories[0]['title'][:70]}")
    return payload


def run(output="news_data.json"):
    import sys
    argv = sys.argv
    sys.argv = ["fetch.py", "--output", output]
    try:
        return main()
    finally:
        sys.argv = argv


if __name__ == "__main__":
    main()