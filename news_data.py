import re
import xml.etree.ElementTree as ET
from difflib import SequenceMatcher

from http_utils import request_with_retry

NEWS_URL = "https://min-api.cryptocompare.com/data/v2/news/"

RSS_SOURCES = {
    "Cointelegraph": "https://cointelegraph.com/rss",
    "Decrypt": "https://decrypt.co/feed",
    "The Block": "https://www.theblock.co/rss.xml",
}

MACRO_RSS_SOURCES = {
    "MarketWatch": "https://feeds.content.dowjones.io/public/rss/mw_topstories",
}

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; SquareBot/1.0)"}


def _parse_rss(url, source_name):
    items = []
    try:
        resp = request_with_retry("GET", url, headers=HEADERS)
        root = ET.fromstring(resp.content)
        for item in root.findall(".//item")[:10]:
            title_el = item.find("title")
            link_el = item.find("link")
            pub_el = item.find("pubDate")
            if title_el is None or not title_el.text:
                continue
            items.append({
                "title": title_el.text.strip(),
                "url": link_el.text.strip() if link_el is not None and link_el.text else "",
                "published_at": pub_el.text.strip() if pub_el is not None and pub_el.text else "",
                "source": source_name,
            })
    except Exception:
        pass
    return items


def get_rss_news(sources):
    items = []
    for name, url in sources.items():
        items.extend(_parse_rss(url, name))
    return items


def get_cryptocompare_news():
    items = []
    try:
        resp = request_with_retry("GET", NEWS_URL, params={"lang": "EN"}, headers=HEADERS)
        data = resp.json()
        for row in data.get("Data", [])[:20]:
            items.append({
                "title": row.get("title", "").strip(),
                "url": row.get("url", ""),
                "published_at": str(row.get("published_on", "")),
                "source": row.get("source", "cryptocompare"),
            })
    except Exception:
        pass
    return items


def _similar(a, b):
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()


def cluster_and_dedupe(items, similarity_threshold=0.6):
    clusters = []
    for item in items:
        if not item["title"]:
            continue
        placed = False
        for cluster in clusters:
            if _similar(cluster["title"], item["title"]) >= similarity_threshold:
                cluster["sources"].add(item["source"])
                cluster["items"].append(item)
                placed = True
                break
        if not placed:
            clusters.append({
                "title": item["title"],
                "sources": {item["source"]},
                "items": [item],
            })
    for cluster in clusters:
        cluster["importance"] = len(cluster["sources"])
    clusters.sort(key=lambda c: c["importance"], reverse=True)
    return clusters


def get_top_stories(symbols, max_stories=3):
    all_items = get_cryptocompare_news() + get_rss_news(RSS_SOURCES)
    clusters = cluster_and_dedupe(all_items)

    def relevance(cluster):
        title = cluster["title"].upper()
        score = cluster["importance"]
        for sym in symbols:
            if sym in title:
                score += 2
        return score

    clusters.sort(key=relevance, reverse=True)
    return clusters[:max_stories]


def get_macro_headlines(max_items=5):
    items = get_rss_news(MACRO_RSS_SOURCES)
    return items[:max_items]
