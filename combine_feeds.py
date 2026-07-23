"""
RSS Aggregator — 50 ta manbani birlashtirib, yagona feed.xml yaratadi.
GitHub Actions orqali har 15 daqiqada avtomatik ishga tushadi.

Talab qilinadigan kutubxonalar: feedparser, feedgen (requirements.txt'da)
"""

import feedparser
from feedgen.feed import FeedGenerator
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import time
import sys

FEEDS_FILE = "feeds.txt"
OUTPUT_FILE = "docs/feed.xml"          # GitHub Pages "docs/" papkasidan xizmat qiladi
MAX_ITEMS_IN_OUTPUT = 200               # yakuniy feedda saqlanadigan maksimal element soni
MAX_ITEMS_PER_SOURCE = 10               # har bir manbadan olinadigan maksimal element
REQUEST_TIMEOUT = 15                    # sekund, har bir manba uchun
MAX_WORKERS = 10                        # parallel so'rovlar soni


def load_feed_urls(path: str) -> list[str]:
    """feeds.txt dan URL'larni o'qiydi, izoh (#) va bo'sh qatorlarni tashlab ketadi."""
    urls = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#"):
                urls.append(line)
    return urls


def fetch_single_feed(url: str) -> tuple[str, list]:
    """Bitta RSS manbani o'qiydi. Xato bo'lsa, bo'sh ro'yxat va xato matnini qaytaradi."""
    try:
        parsed = feedparser.parse(url, request_headers={
            "User-Agent": "Mozilla/5.0 (compatible; NewsAggregator/1.0)"
        })
        if parsed.bozo and not parsed.entries:
            return url, [], f"Parse xatosi: {parsed.bozo_exception}"
        entries = parsed.entries[:MAX_ITEMS_PER_SOURCE]
        source_name = parsed.feed.get("title", url)
        for e in entries:
            e["_source_name"] = source_name
            e["_source_url"] = url
        return url, entries, None
    except Exception as exc:
        return url, [], str(exc)


def get_entry_timestamp(entry) -> float:
    """Elementning sanasini unix timestamp ko'rinishida qaytaradi (saralash uchun)."""
    for key in ("published_parsed", "updated_parsed"):
        t = entry.get(key)
        if t:
            return time.mktime(t)
    return 0.0


def get_entry_id(entry) -> str:
    """Dublikatlarni aniqlash uchun barqaror ID (link asosida hash)."""
    link = entry.get("link", "") or entry.get("id", "")
    return hashlib.md5(link.encode("utf-8")).hexdigest()


def main():
    urls = load_feed_urls(FEEDS_FILE)
    print(f"Jami manbalar soni: {len(urls)}")

    all_entries = []
    errors = []

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {executor.submit(fetch_single_feed, u): u for u in urls}
        for future in as_completed(futures):
            url, entries, error = future.result()
            if error:
                errors.append((url, error))
                print(f"  [XATO] {url} -> {error}")
            else:
                all_entries.extend(entries)
                print(f"  [OK]   {url} -> {len(entries)} ta element")

    # Dublikatlarni olib tashlash (link bo'yicha)
    seen_ids = set()
    unique_entries = []
    for e in all_entries:
        eid = get_entry_id(e)
        if eid not in seen_ids:
            seen_ids.add(eid)
            unique_entries.append(e)

    # Eng yangi elementlarni tepaga chiqarish
    unique_entries.sort(key=get_entry_timestamp, reverse=True)
    unique_entries = unique_entries[:MAX_ITEMS_IN_OUTPUT]

    print(f"\nJami yig'ilgan: {len(all_entries)}, dublikatsiz: {len(unique_entries)}")
    print(f"Muvaffaqiyatsiz manbalar: {len(errors)} / {len(urls)}")

    # Yakuniy feed.xml yaratish
    fg = FeedGenerator()
    fg.title("Combined Security & Geopolitics Feed")
    fg.link(href="https://github.com/", rel="alternate")
    fg.description("50+ manbadan avtomatik yig'ilgan xavfsizlik, mudofaa, "
                    "geosiyosat va kiberxavfsizlik yangiliklari")
    fg.language("en")
    fg.lastBuildDate(datetime.now(timezone.utc))

    for entry in unique_entries:
        fe = fg.add_entry()
        fe.id(entry.get("link", get_entry_id(entry)))
        fe.title(entry.get("title", "No title"))
        fe.link(href=entry.get("link", ""))
        description = entry.get("summary", entry.get("description", ""))
        fe.description(description)
        source_name = entry.get("_source_name", "Unknown")
        fe.author(name=source_name)
        pub_date = entry.get("published", entry.get("updated"))
        if pub_date:
            try:
                fe.pubDate(entry.get("published_parsed") or entry.get("updated_parsed"))
            except Exception:
                pass

    import os
    os.makedirs("docs", exist_ok=True)
    fg.rss_file(OUTPUT_FILE, pretty=True)
    print(f"\n✅ Yakuniy feed saqlandi: {OUTPUT_FILE}")

    if len(errors) == len(urls):
        print("❌ Barcha manbalar muvaffaqiyatsiz tugadi!")
        sys.exit(1)


if __name__ == "__main__":
    main()
