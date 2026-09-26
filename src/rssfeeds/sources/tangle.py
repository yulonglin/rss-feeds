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

import html
import sys
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


# Ghost cards and embeds that are packaging, not writing: sponsor slots, signup
# forms, share buttons and the scripts that drive them.
_PACKAGING_CLASSES = ("kg-cta-card", "kg-signup-card", "tangle-share")
_PACKAGING_TAGS = {"script", "style", "form", "iframe", "noscript"}


def _is_packaging(el) -> bool:
    cls = el.get("class") or ""
    return el.tag in _PACKAGING_TAGS or any(c in cls for c in _PACKAGING_CLASSES)


def _strip_packaging(root) -> None:
    """Remove packaging anywhere in the tree, keeping the text that follows it."""
    for el in [e for e in root.iter() if isinstance(e.tag, str) and e is not root]:
        if _is_packaging(el) and el.getparent() is not None:
            el.drop_tree()  # drop_tree keeps el.tail in the parent


def _parse(body: str):
    root = lx.fragment_fromstring(body, create_parent="div")
    _strip_packaging(root)
    return root


def trim_daily(body: str) -> str | None:
    """Keep only the KEEP_SECTIONS of a daily edition. None if it has none of them."""
    root = _parse(body)
    out: list[str] = []
    keeping = False
    for el in root:
        if not isinstance(el.tag, str):
            continue
        if el.tag == "h3":
            keeping = _norm(el.text_content()) in KEEP_SECTIONS
        if keeping:
            out.append(lx.tostring(el, encoding="unicode", method="html"))
    return "\n".join(out) if out else None


def _strip_ads(body: str) -> str:
    root = _parse(body)
    lead = html.escape(root.text.strip()) if root.text and root.text.strip() else ""
    parts = [f"<p>{lead}</p>"] if lead else []
    parts += [
        lx.tostring(el, encoding="unicode", method="html") for el in root if isinstance(el.tag, str)
    ]
    return "\n".join(parts)


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


def _looks_daily(link: str, categories: list[str], body: str) -> bool:
    """A full-length entry that select() should have trimmed rather than skipped."""
    cats = {_norm(c) for c in categories}
    return (
        len(body) >= TEASER_MAX_CHARS
        and "/otherposts/" not in link
        and not cats & {"friday edition", "the sunday", "reader-essay"}
    )


def tangle() -> SourceResult:
    try:
        channel = ET.fromstring(fetch_bytes(FEED)).find("channel")
    except Exception as exc:  # noqa: BLE001
        return SourceResult(error=f"feed fetch/parse failed: {exc}")
    if channel is None:
        return SourceResult(error="feed has no <channel>")

    entries = channel.findall("item")
    items: list[Item] = []
    dailies = trimmed = 0
    for it in entries:
        link = (it.findtext("link") or "").strip()
        author = (it.findtext("dc:creator", namespaces=NS) or "").strip()
        categories = [c.text or "" for c in it.findall("category")]
        body = it.findtext("content:encoded", namespaces=NS) or ""
        try:
            content = select(link, author, categories, body)
            if _looks_daily(link, categories, body):
                dailies += 1
                trimmed += content is not None
            if content is None:
                continue
            published = parsedate_to_datetime(it.findtext("pubDate") or "").astimezone(UTC)
        except Exception as exc:  # noqa: BLE001 - one malformed entry must not sink the feed
            print(f"tangle: skipped {link or '?'}: {exc}", file=sys.stderr)
            continue
        items.append(
            Item(
                title=(it.findtext("title") or "").strip(),
                link=link,
                guid=link,
                published=published,
                description=(it.findtext("description") or "").strip(),
                content_html=content,
                author=author or None,
                categories=["Essay" if "/otherposts/" in link else "Daily edition"],
            )
        )
    if dailies and not trimmed:
        return SourceResult(
            error=f"{dailies} daily editions but none had a Today's topic section - "
            "newsletter layout may have changed"
        )
    if entries and not items:
        return SourceResult(error="every entry was filtered out - feed layout may have changed")
    return SourceResult(items=items)
