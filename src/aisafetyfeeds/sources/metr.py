"""metr.org/feed.xml — valid, but interleaved with translated duplicates.

METR publishes each translated post as its own item under a locale path
(/es/blog/..., /zh-Hans/notes/...). We keep the feed's own items verbatim, including the
full content:encoded bodies, and drop anything whose first path segment looks like a
locale tag. Matching the shape rather than a fixed list means a language METR adds later
is dropped too, without a code change.
"""

from __future__ import annotations

import re
from email.utils import parsedate_to_datetime
from urllib.parse import urlparse

from lxml import etree

from ..http import fetch_bytes
from ..models import Item, SourceResult

FEED_URL = "https://metr.org/feed.xml"
CONTENT_NS = "http://purl.org/rss/1.0/modules/content/"
DC_NS = "http://purl.org/dc/elements/1.1/"

# e.g. "es", "fr", "zh-Hans", "pt-BR" - a locale tag, not a content section.
LOCALE_SEGMENT = re.compile(r"^[a-z]{2}(-[A-Za-z]{2,8})*$")


def is_english(link: str) -> bool:
    segments = [s for s in urlparse(link).path.split("/") if s]
    return not (segments and LOCALE_SEGMENT.match(segments[0]))


def metr_english() -> SourceResult:
    try:
        root = etree.fromstring(fetch_bytes(FEED_URL))
    except Exception as exc:  # noqa: BLE001
        return SourceResult(error=f"fetch/parse failed: {exc}")

    channel = root.find("channel")
    if channel is None:
        return SourceResult(error="upstream feed has no <channel>")

    items: list[Item] = []
    for node in channel.findall("item"):
        link = (node.findtext("link") or "").strip()
        if not link or not is_english(link):
            continue
        pub = node.findtext("pubDate")
        try:
            published = parsedate_to_datetime(pub) if pub else None
        except (TypeError, ValueError):
            published = None
        if published is None:
            continue
        guid = (node.findtext("guid") or link).strip()
        items.append(
            Item(
                title=(node.findtext("title") or link).strip(),
                link=link,
                guid=guid,
                published=published,
                description=(node.findtext("description") or "").strip(),
                content_html=node.findtext(f"{{{CONTENT_NS}}}encoded"),
                author=(node.findtext(f"{{{DC_NS}}}creator") or None),
                categories=[c.text for c in node.findall("category") if c.text],
            )
        )
    if not items:
        return SourceResult(
            error="no English items survived filtering - upstream feed may have changed"
        )
    return SourceResult(items=items)
