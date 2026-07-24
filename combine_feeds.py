"""
RSS Aggregator — 50 ta manbani birlashtirib, yagona feed.xml yaratadi.
GitHub Actions orqali har 15 daqiqada avtomatik ishga tushadi.

Talab qilinadigan kutubxonalar: feedparser, feedgen (requirements.txt'da)
"""

import feedparser
import requests
from feedgen.feed import FeedGenerator
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import os
import re
import time
import sys

FEEDS_FILE = "feeds.txt"
OUTPUT_FILE = "docs/feed.xml"          # GitHub Pages "docs/" papkasidan xizmat qiladi
MAX_ITEMS_IN_OUTPUT = 200               # yakuniy feedda saqlanadigan maksimal element soni
MIN_ITEMS_THRESHOLD = 5                 # shundan kam bo'lsa, eski feed.xml SAQLANADI, yangisi yozilmaydi
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


def clean_xml_bytes(raw: bytes) -> bytes:
    """
    Ba'zi serverlar XML ichida ruxsat etilmagan control character'larni
    (invalid token xatosiga sabab bo'ladigan) qaytaradi. Ularni olib tashlaymiz.
    XML 1.0 standartida ruxsat etilgan: \\t \\n \\r va U+0020 dan yuqori belgilar.
    """
    try:
        text = raw.decode("utf-8", errors="ignore")
    except Exception:
        text = raw.decode("latin-1", errors="ignore")
    # Ruxsat etilmagan control character'larni olib tashlash
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", text)
    return text.encode("utf-8")


def fetch_single_feed(url: str) -> tuple[str, list]:
    """
    Bitta RSS manbani o'qiydi. Xato bo'lsa, bo'sh ro'yxat va xato matnini qaytaradi.

    Content-Type header muammosini chetlab o'tish uchun avval 'requests' orqali
    xom (raw) ma'lumotni o'zimiz yuklab olamiz, so'ng uni tozalab feedparser'ga
    beramiz — bu "text/html is not an XML media type" va ba'zi
    "not well-formed (invalid token)" xatolarini kamaytiradi.
    """
    try:
        response = requests.get(
            url,
            headers={"User-Agent": "Mozilla/5.0 (compatible; NewsAggregator/1.0)"},
            timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()
        cleaned_content = clean_xml_bytes(response.content)

        parsed = feedparser.parse(cleaned_content)

        if parsed.bozo and not parsed.entries:
            return url, [], f"Parse xatosi: {parsed.bozo_exception}"

        entries = parsed.entries[:MAX_ITEMS_PER_SOURCE]
        source_name = parsed.feed.get("title", url)
        for e in entries:
            e["_source_name"] = source_name
            e["_source_url"] = url
        return url, entries, None

    except requests.exceptions.RequestException as exc:
        return url, [], f"So'rov xatosi: {exc}"
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

    # HIMOYA QATLAMI: agar natija juda kam bo'lsa, eski feed.xml'ni buzmaymiz.
    # Sabab: vaqtinchalik tarmoq muammosi yoki manbalarning ko'pchiligi bir vaqtda
    # ishlamay qolishi mumkin — bunday holatda "deyarli bo'sh" fayl yozib,
    # avvalgi ishlagan natijani yo'qotmaslik kerak.
    if len(unique_entries) < MIN_ITEMS_THRESHOLD:
        print(
            f"\n❌ OGOHLANTIRISH: faqat {len(unique_entries)} ta element topildi "
            f"(chegara: {MIN_ITEMS_THRESHOLD}). Eski docs/{os.path.basename(OUTPUT_FILE)} "
            f"O'ZGARTIRILMAYDI — xavfsizlik uchun saqlanib qoladi."
        )
        print("Iltimos, tarmoq holati yoki manbalar ro'yxatini tekshiring.")
        sys.exit(1)

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
        struct_t = entry.get("published_parsed") or entry.get("updated_parsed")
        try:
            if struct_t:
                dt = datetime.fromtimestamp(time.mktime(struct_t), tz=timezone.utc)
            else:
                # Sana umuman topilmasa, hozirgi vaqtni qo'yamiz —
                # 1970-yil (epoch) chiqib, Make'da "juda eski" deb
                # noto'g'ri talqin qilinishining oldini olish uchun.
                dt = datetime.now(timezone.utc)
            fe.pubDate(dt)
        except Exception:
            fe.pubDate(datetime.now(timezone.utc))

    os.makedirs("docs", exist_ok=True)
    fg.rss_file(OUTPUT_FILE, pretty=True)
    print(f"\n✅ Yakuniy feed saqlandi: {OUTPUT_FILE}")

    if len(errors) == len(urls):
        print("❌ Barcha manbalar muvaffaqiyatsiz tugadi!")
        sys.exit(1)


if __name__ == "__main__":
    main()
