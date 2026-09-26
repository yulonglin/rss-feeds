"""readtangle.com - Tangle, Isaac Saul's politics newsletter, trimmed to the parts worth reading.

Tangle's own feed (/rss/, a Ghost site) is complete, but it mixes the daily edition with
a lot else: one-paragraph teasers for videos and podcasts, previews of paywalled Friday
editions, the Sunday recap of the week just read, and reader essays. The daily edition
itself is also mostly packaging around one good section: sponsor cards, "Quick hits",
"The extras", "Have a nice day".

What this feed keeps:
  - daily editions, cut down to "Today's topic" (the story, what the left and the right
    are saying, and Isaac's take) and "Under the radar" (one under-covered story);
  - standalone essays Isaac Saul writes under /otherposts/.
Everything else is dropped.
"""

from __future__ import annotations

from datetime import UTC
from email.utils import parsedate_to_datetime
from xml.etree import ElementTree as ET

from lxml import html as lx

from ..http import fetch_bytes
from ..models import Item, SourceResult

FEED = "https://www.readtangle.com/rss/"
NS = {
    "content": "http://purl.org/rss/1.0/modules/content/",
    "dc": "http://purl.org/dc/elements/1.1/",
}

KEEP_SECTIONS = ("today's topic", "under the radar")
# Video and podcast teasers are a paragraph and a link; real posts run to thousands.
TEASER_MAX_CHARS = 2500


def _norm(text: str) -> str:
    return " ".join(text.replace("’", "'").split()).strip(" .").lower()


def _is_ad(el) -> bool:
    return "kg-cta-card" in (el.get("class") or "")


def trim_daily(body: str) -> str | None:
    """Keep only the KEEP_SECTIONS of a daily edition. None if it has none of them."""
    root = lx.fragment_fromstring(body, create_parent="div")
    out: list[str] = []
    keeping = False
    for el in root:
        if not isinstance(el.tag, str):
            continue
        if el.tag == "h3":
            keeping = _norm(el.text_content()) in KEEP_SECTIONS
        if keeping and not _is_ad(el):
            out.append(lx.tostring(el, encoding="unicode", method="html"))
    return "\n".join(out) if out else None


def _strip_ads(body: str) -> str:
    root = lx.fragment_fromstring(body, create_parent="div")
    return "\n".join(
        lx.tostring(el, encoding="unicode", method="html")
        for el in root
        if isinstance(el.tag, str) and not _is_ad(el)
    )


def select(link: str, author: str, categories: list[str], body: str) -> str | None:
    """The content to publish for one upstream entry, or None to leave it out."""
    if len(body) < TEASER_MAX_CHARS:
        return None  # video / podcast teaser
    cats = {_norm(c) for c in categories}
    if "friday edition" in cats or "the sunday" in cats or "reader-essay" in cats:
        return None  # paywalled preview, weekly recap, reader essay
    if "/otherposts/" in link:
        return _strip_ads(body) if author == "Isaac Saul" else None
    return trim_daily(body)


def tangle() -> SourceResult:
    try:
        channel = ET.fromstring(fetch_bytes(FEED)).find("channel")
    except Exception as exc:  # noqa: BLE001
        return SourceResult(error=f"feed fetch/parse failed: {exc}")
    if channel is None:
        return SourceResult(error="feed has no <channel>")

    entries = channel.findall("item")
    items: list[Item] = []
    for it in entries:
        link = (it.findtext("link") or "").strip()
        author = (it.findtext("dc:creator", namespaces=NS) or "").strip()
        categories = [c.text or "" for c in it.findall("category")]
        body = it.findtext("content:encoded", namespaces=NS) or ""
        content = select(link, author, categories, body)
        if content is None:
            continue
        items.append(
            Item(
                title=(it.findtext("title") or "").strip(),
                link=link,
                guid=link,
                published=parsedate_to_datetime(it.findtext("pubDate") or "").astimezone(UTC),
                description=(it.findtext("description") or "").strip(),
                content_html=content,
                author=author or None,
                categories=["Essay" if "/otherposts/" in link else "Daily edition"],
            )
        )
    if entries and not items:
        return SourceResult(
            error="no entry had a Today's topic section - newsletter layout may have changed"
        )
    return SourceResult(items=items)
