"""project-syndicate.org - Project Syndicate commentary.

The official /rss is valid but thin: each item is a one-paragraph summary with no body,
the lead image sits only in a media:content / enclosure element that most readers do
not show, every link carries utm tracking, and only the first author is credited.

Each article page is fetched and cached in state/project_syndicate_articles.json, keyed
by the clean link, and its body is published as an anonymous reader is served it. Most
pages serve only the opening paragraph followed by a registration wall (the body carries
a `paywall` class and the page a `paywall--base` widget); those items end with a link
saying the article continues on Project Syndicate, and the rest is not fetched any other
way. Some pages (3 of 20 on 2026-10-12) serve the whole article and the author's bio,
with no paywall marker, and are published whole. Promos and "editor's picks" inlays sit
in the body as non-paragraph elements and are dropped; navigation and related-article
blocks sit outside it.

A cached page is fetched again after a day if it was cut short and after a week if it
was whole, so an article the site opens up later is picked up. When a page cannot be
fetched or parsed, the item keeps its cached copy or, if it has none, falls back to the
summary alone; either way the page is retried next run. A cache file or record that
does not parse or validate counts as never fetched.
"""

from __future__ import annotations

import html
import json
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import urlsplit

from lxml import etree
from lxml import html as lx

from .. import private
from ..http import fetch_bytes
from ..models import Item, SourceResult
from ..newsletter_email import strip_utm
from ..sanitize import safe_url, sanitize_html

FEED = "https://www.project-syndicate.org/rss"
NS = {"dc": "http://purl.org/dc/elements/1.1/", "media": "http://search.yahoo.com/mrss/"}
MAX_WORKERS = 4
# A cached page is fetched again after this long, so an article that was cut short
# (or has since been corrected) is picked up; a truncated one is checked sooner.
REFRESH_TRUNCATED = timedelta(days=1)
REFRESH_FULL = timedelta(days=7)

# Body blocks worth keeping; anything else inside the article body is site furniture.
_BLOCKS = {"p", "figure", "blockquote", "h2", "h3", "h4", "ul", "ol"}


def _clean_link(url: str) -> str:
    return strip_utm(url).split("#", 1)[0].rstrip("?")


def _join_names(names: list[str]) -> str:
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]


def _accessible_for_free(doc) -> bool | None:
    for script in doc.xpath('//script[@type="application/ld+json"]'):
        try:
            data = json.loads(script.text_content())
        except ValueError:
            continue
        for node in data.get("@graph", [data]) if isinstance(data, dict) else data:
            if isinstance(node, dict) and "isAccessibleForFree" in node:
                return bool(node["isAccessibleForFree"])
    return None


def _clean_blocks(parent, url: str, tags: set[str]) -> list[str]:
    """`parent`'s direct children of the given tags, each rebuilt through the shared
    allowlist with absolute, utm-free links."""
    blocks = []
    for el in parent:
        if not isinstance(el.tag, str) or el.tag not in tags:
            continue
        for img in el.iter("img"):
            if img.get("data-src"):  # lazy-loaded: the real image is in data-src
                img.set("src", img.get("data-src"))
        # URLs are checked here, on the parsed value, as well as in sanitize_html:
        # serialising first would percent-encode a control character and turn
        # "jav\tascript:" into a harmless-looking relative path.
        for sub in el.iter():
            for attr in ("href", "src"):
                if attr in sub.attrib:
                    safe = safe_url(sub.get(attr), url)
                    if safe:
                        sub.set(attr, strip_utm(safe))
                    else:
                        del sub.attrib[attr]
        el.tail = None
        block = sanitize_html(lx.tostring(el, encoding="unicode", method="html"), base_url=url)
        if "<img" in block or re.sub(r"<[^>]+>|&nbsp;|\s", "", block):
            blocks.append(block)
    return blocks


def parse_article(page: bytes, url: str) -> dict | None:
    """The byline, the body as served, whether the page cut it short at the paywall,
    whether the site calls the article free, and the author bio when the page has one.

    None when the page has no article body, so a layout change shows up as summary-only
    items rather than as cached emptiness.
    """
    doc = lx.fromstring(page)
    bodies = doc.cssselect("div.article__body")
    if not bodies:
        return None
    blocks = _clean_blocks(bodies[0], url, _BLOCKS)
    if not blocks:
        return None
    names = [
        " ".join(s.text_content().split())
        for s in doc.cssselect("address.article__byline span.byline")
    ]
    names = [n for n in names if n]
    bio = [
        b
        for box in doc.cssselect('aside[aria-label="Author information"] .expandable-text__content')
        for b in _clean_blocks(box, url, {"p"})
    ]
    truncated = "paywall" in (bodies[0].get("class") or "").split() or bool(
        doc.cssselect("div.paywall--base")
    )
    return {
        "byline": _join_names(names) if names else None,
        "body": "\n".join(blocks),
        "truncated": truncated,
        "free": _accessible_for_free(doc),
        "bio": "\n".join(bio),
    }


def _fetch_article(url: str) -> dict | None:
    try:
        article = parse_article(fetch_bytes(url), url)
    except Exception:  # noqa: BLE001 - this item falls back to its summary, retried next run
        return None
    # State is held to the strict leak check; one link in a body that carries a
    # token-like parameter must not refuse the whole write.
    if article is None or private.leaks(json.dumps(article)):
        return None
    return article


def _valid(record) -> bool:
    """A cache record as `parse_article` and the refresh stamp leave it, or not at all."""
    if not isinstance(record, dict):
        return False
    try:
        if datetime.fromisoformat(record["fetched"]).tzinfo is None:
            return False
    except (KeyError, TypeError, ValueError):
        return False
    return (
        isinstance(record.get("body"), str)
        and bool(record["body"].strip())
        and isinstance(record.get("truncated"), bool)
        and isinstance(record.get("free"), bool | None)
        and isinstance(record.get("byline"), str | None)
        and isinstance(record.get("bio", ""), str)
    )


def load_cache(path: Path) -> dict[str, dict]:
    """The cache, with anything unreadable or malformed treated as never fetched."""
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {k: v for k, v in data.items() if isinstance(k, str) and _valid(v)}


def _due(record: dict | None, now: datetime) -> bool:
    if record is None:
        return True
    age = now - datetime.fromisoformat(record["fetched"])
    return age >= (REFRESH_TRUNCATED if record["truncated"] else REFRESH_FULL)


def render(item, article: dict | None, link: str) -> str:
    parts = []
    # Everything that came from upstream - the image URL, the summary, the page text in
    # the cache - goes through the shared allowlist; only this function's own markup
    # (the credit line, separators, links to `link`) is written directly.
    media = item.find("media:content", NS)
    image = safe_url(media.get("url")) if media is not None else None
    if image:
        credit = (media.findtext("media:copyright", namespaces=NS) or "").strip()
        parts.append(f'<p><img src="{html.escape(image, quote=True)}" alt=""></p>')
        if credit:
            parts.append(f"<p><small>Photo: {html.escape(credit)}</small></p>")
    summary = (item.findtext("description") or "").strip()
    if summary.startswith("<"):
        parts.append(sanitize_html(summary, base_url=link))
    elif summary:
        parts.append(f"<p>{html.escape(summary)}</p>")
    href = html.escape(link, quote=True)
    if article is None:
        parts.append(f'<p><a href="{href}">Read the full commentary on Project Syndicate</a></p>')
        return "\n".join(parts)
    if article.get("byline"):
        parts.append(f"<p><em>By {html.escape(article['byline'])}</em></p>")
    parts.append("<hr>")
    parts.append(sanitize_html(article["body"], base_url=link))
    if article.get("truncated"):
        access = "registration required" if article.get("free") else "subscriber article"
        parts.append(f'<p><a href="{href}">Continues on Project Syndicate ({access})</a></p>')
        return "\n".join(parts)
    if article.get("bio"):
        parts += ["<hr>", sanitize_html(article["bio"], base_url=link)]
    parts.append(f'<p><a href="{href}">Originally published on Project Syndicate</a></p>')
    return "\n".join(parts)


def project_syndicate(cache_path: Path, *, now: datetime | None = None) -> SourceResult:
    now = now or datetime.now(UTC)
    try:
        # Parsed as bytes: the feed starts with a byte-order mark.
        channel = etree.fromstring(fetch_bytes(FEED)).find("channel")
    except Exception as exc:  # noqa: BLE001
        return SourceResult(error=f"feed fetch/parse failed: {exc}")
    if channel is None:
        return SourceResult(error="feed has no <channel>")

    entries = []
    for it in channel.findall("item"):
        link = safe_url(_clean_link((it.findtext("link") or "").strip()))
        pub = it.findtext("pubDate")
        if link and pub:
            entries.append((it, link, pub))

    cache = load_cache(cache_path)
    # Only the site's own pages are fetched: new ones, and cached ones past their refresh
    # age. A failed fetch keeps the cached copy, or the summary for a new page, and is
    # retried next run.
    due = sorted(
        {
            link
            for _, link, _ in entries
            if _due(cache.get(link), now) and urlsplit(link).netloc == "www.project-syndicate.org"
        }
    )
    stamp = now.isoformat(timespec="seconds")
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        for link, article in zip(due, pool.map(_fetch_article, due), strict=True):
            if article is not None:
                cache[link] = {**article, "fetched": stamp}

    items = []
    for it, link, pub in entries:
        article = cache.get(link)
        creator = (it.findtext("dc:creator", namespaces=NS) or "").strip()
        author = (article or {}).get("byline") or creator
        items.append(
            Item(
                title=(it.findtext("title") or link).strip(),
                link=link,
                guid=(it.findtext("guid") or link).strip(),
                published=parsedate_to_datetime(pub),
                description=re.sub(r"<[^>]+>", "", it.findtext("description") or "").strip(),
                content_html=render(it, article, link),
                author=author or None,
                categories=["Commentary"],
            )
        )

    # Articles that have left the upstream feed are dropped, so the cache stays the size
    # of one feed window.
    current = {link for _, link, _ in entries}
    kept = {k: v for k, v in sorted(cache.items()) if k in current}
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(kept, indent=2) + "\n"
    cache_path.write_text(private.ensure_clean(text, cache_path.name))
    if not items:
        return SourceResult(error="feed had no usable items - layout may have changed")
    return SourceResult(items=items)
