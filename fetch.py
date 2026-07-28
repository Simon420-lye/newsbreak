import hashlib
import re
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import json
import requests
import feedparser

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)

FEEDS = {
    "technology": [
        ("TechCrunch", "https://techcrunch.com/feed/"),
        ("The Verge", "https://www.theverge.com/rss/index.xml"),
        ("Ars Technica", "https://feeds.arstechnica.com/arstechnica/index"),
    ],
    "finance": [
        ("CNBC Markets", "https://www.cnbc.com/id/10000664/device/rss/rss.html"),
        ("MarketWatch", "https://feeds.marketwatch.com/marketwatch/topstories/"),
        ("Yahoo Finance", "https://finance.yahoo.com/news/rssindex"),
    ],
}


def get_feed(url):
    resp = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=15)
    resp.raise_for_status()
    return feedparser.parse(resp.content)


def parse_date(entry):
    """Feeds disagree on date fields. Try each, give up gracefully."""
    for field in ("published", "updated"):
        raw = entry.get(field)
        if raw:
            try:
                dt = parsedate_to_datetime(raw)
                # Some feeds omit timezone — assume UTC so sorting stays valid
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt
            except Exception:
                pass
    return None

def extract_image(entry):
    """Feeds hide images in four different places. Try all of them."""
    # 1. <media:content>
    for mc in entry.get("media_content") or []:
        if mc.get("url"):
            return mc["url"]

    # 2. <media:thumbnail>
    for mt in entry.get("media_thumbnail") or []:
        if mt.get("url"):
            return mt["url"]

    # 3. <enclosure>
    for link in entry.get("links") or []:
        if link.get("rel") == "enclosure" and "image" in (link.get("type") or ""):
            return link.get("href")

    # 4. first <img> inside the content or summary HTML
    blob = ""
    for c in entry.get("content") or []:
        blob += c.get("value", "")
    blob += entry.get("summary", "") or ""
    m = re.search(r'<img[^>]+src=["\']([^"\']+)["\']', blob)
    if m:
        url = m.group(1)
        return "https:" + url if url.startswith("//") else url

    return None

def clean_summary(entry, limit=420):
    raw = entry.get("summary", "") or ""
    text = re.sub(r"<[^>]+>", "", raw)          # strip HTML tags
    text = re.sub(r"\s+", " ", text).strip()     # collapse whitespace
    return text[:limit] + ("…" if len(text) > limit else "")


def make_id(link):
    return hashlib.sha1(link.encode("utf-8")).hexdigest()[:12]


def normalize(entry, source, category):
    """Turn a feedparser entry into OUR shape. The only place feedparser leaks."""
    title = (entry.get("title") or "").strip()
    link = entry.get("link") or ""
    if not title or not link:
        return None

    published = parse_date(entry)

    return {
        "id": make_id(link),
        "category": category,
        "title": title,
        "summary": clean_summary(entry),
        "link": link,
        "source": source,
        "image": extract_image(entry),
        "published": published.isoformat() if published else None,
    }


def collect():
    articles = []
    for category, sources in FEEDS.items():
        print(f"\n{category.upper()}")
        for source, url in sources:
            try:
                feed = get_feed(url)
            except Exception as e:
                print(f"  [skip] {source}: {e}")
                continue

            count = 0
            for entry in feed.entries:
                item = normalize(entry, source, category)
                if item:
                    articles.append(item)
                    count += 1
            print(f"  [ok]   {source}: {count} articles")

    return articles



def title_key(title):
    """Fingerprint a headline so near-identical ones collide."""
    t = title.lower()
    t = re.sub(r"[^a-z0-9 ]", "", t)        # drop punctuation
    t = re.sub(r"\s+", " ", t).strip()
    return " ".join(t.split()[:8])            # first 8 words is enough


def dedupe(articles):
    seen_ids, seen_titles = set(), set()
    out = []
    for a in articles:
        tkey = title_key(a["title"])
        if a["id"] in seen_ids or tkey in seen_titles:
            continue
        seen_ids.add(a["id"])
        seen_titles.add(tkey)
        out.append(a)
    return out


def sort_by_recency(articles):
    # Articles without a date sink to the bottom rather than crashing the sort
    return sorted(
        articles,
        key=lambda a: a["published"] or "",
        reverse=True,
    )

from difflib import SequenceMatcher

def dedupe(articles, threshold=0.75):
    seen_ids = set()
    kept = []
    for a in articles:
        if a["id"] in seen_ids:
            continue
        # Compare against what we've already kept in the same category
        is_dupe = any(
            SequenceMatcher(None, a["title"].lower(), k["title"].lower()).ratio() > threshold
            for k in kept
            if k["category"] == a["category"]
        )
        if is_dupe:
            continue
        seen_ids.add(a["id"])
        kept.append(a)
    return kept

def save(articles, path="news_data.json"):
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "counts": {
            "technology": sum(1 for a in articles if a["category"] == "technology"),
            "finance": sum(1 for a in articles if a["category"] == "finance"),
        },
        "articles": articles,
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
    return payload


#if __name__ == "__main__":
    print(f"\n{'='*60}\nRun started {datetime.now():%Y-%m-%d %H:%M:%S}")
    articles = collect()
    print(f"\nCollected: {len(articles)}")

    articles = dedupe(articles)
    print(f"After dedupe: {len(articles)}")
    articles = sort_by_recency(articles)

    payload = save(articles)
    print(f"Saved {payload['counts']['technology']} tech + "
          f"{payload['counts']['finance']} finance → news_data.json")

def run(output="news_data.json"):
    print(f"\n{'='*60}\nRun started {datetime.now():%Y-%m-%d %H:%M:%S}")

    articles = collect()
    print(f"Collected: {len(articles)}")

    articles = dedupe(articles)
    print(f"After dedupe: {len(articles)}")

    articles = sort_by_recency(articles)

    payload = save(articles, output)
    print(f"Saved {payload['counts']['technology']} tech + "
          f"{payload['counts']['finance']} finance -> {output}")
    return payload


if __name__ == "__main__":
    run()
    
    

