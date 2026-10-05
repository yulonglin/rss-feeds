"""project-syndicate.org - Project Syndicate commentary.

The official /rss is valid but thin: each item is a one-paragraph summary with no body,
the lead image sits only in a media:content / enclosure element that most readers do
not show, every link carries utm tracking, and only the first author is credited even
on co-written pieces (the full byline is read from the article page and cached in
state/project_syndicate_bylines.json). The articles are paywalled, so the body is not available and is
not reproduced. Each item is rebuilt as image (with its photo credit), summary, full
byline and a link to the article, with tracking removed.
"""

from __future__ import annotations

import html
import json
import re
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import urlsplit

from lxml import etree
from lxml import html as lx

from ..http import fetch_bytes, fetch_text
from ..models import Item, SourceResult
from ..newsletter_email import strip_utm

FEED = "https://www.project-syndicate.org/rss"
NS = {"dc": "http://purl.org/dc/elements/1.1/", "media": "http://search.yahoo.com/mrss/"}

# ".../some-headline-by-first-author-and-second-author-2026-10"
_BYLINE = re.compile(r"-by-(?P<names>.+?)-\d{4}-\d{2}$")


def _clean_link(url: str) -> str:
    return strip_utm(url).split("#", 1)[0].rstrip("?")


def byline(link: str, creator: str, cache: dict[str, str]) -> str:
    """dc:creator names only the first author. When the URL slug shows more than one
    ("...-by-first-author-and-second-author-2026-10"), the full byline is read once from
    the article page's <title> ("Headline by A & B - Project Syndicate") and cached."""
    m = _BYLINE.search(urlsplit(link).path)
    if not m or "-and-" not in m.group("names"):
        return creator
    if link not in cache:
        try:
            doc = lx.fromstring(fetch_text(link))
            title = " ".join((doc.findtext(".//title") or "").split())
        except Exception:  # noqa: BLE001 - fall back to the first author, retry next run
            return creator
        names = title.removesuffix(" - Project Syndicate").rpartition(" by ")[2]
        if not names or names == title:
            return creator
        cache[link] = names.replace(" & ", " and ")
    return cache[link]


def render(item) -> str:
    parts = []
    media = item.find("media:content", NS)
    if media is not None and media.get("url"):
        credit = (media.findtext("media:copyright", namespaces=NS) or "").strip()
        parts.append(f'<p><img src="{html.escape(media.get("url"), quote=True)}" alt=""></p>')
        if credit:
            parts.append(f"<p><small>Photo: {html.escape(credit)}</small></p>")
    summary = (item.findtext("description") or "").strip()
    parts.append(summary if summary.startswith("<") else f"<p>{html.escape(summary)}</p>")
    return "\n".join(parts)


def project_syndicate(cache_path: Path) -> SourceResult:
    try:
        # Parsed as bytes: the feed starts with a byte-order mark.
        channel = etree.fromstring(fetch_bytes(FEED)).find("channel")
    except Exception as exc:  # noqa: BLE001
        return SourceResult(error=f"feed fetch/parse failed: {exc}")
    if channel is None:
        return SourceResult(error="feed has no <channel>")

    cache = json.loads(cache_path.read_text()) if cache_path.exists() else {}
    items = []
    for it in channel.findall("item"):
        link = _clean_link((it.findtext("link") or "").strip())
        pub = it.findtext("pubDate")
        if not link or not pub:
            continue
        author = byline(link, (it.findtext("dc:creator", namespaces=NS) or "").strip(), cache)
        body = render(it)
        items.append(
            Item(
                title=(it.findtext("title") or link).strip(),
                link=link,
                guid=(it.findtext("guid") or link).strip(),
                published=parsedate_to_datetime(pub),
                description=re.sub(r"<[^>]+>", "", it.findtext("description") or "").strip(),
                content_html=body + f'\n<p><a href="{html.escape(link, quote=True)}">'
                "Read the full commentary on Project Syndicate</a></p>",
                author=author or None,
                categories=["Commentary"],
            )
        )
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps(dict(sorted(cache.items())), indent=2) + "\n")
    if not items:
        return SourceResult(error="feed had no usable items - layout may have changed")
    return SourceResult(items=items)
