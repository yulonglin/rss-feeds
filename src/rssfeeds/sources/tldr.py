"""tldr.tech - the TLDR daily newsletters (TLDR AI to start with).

TLDR does publish a feed, at /api/rss/<newsletter>, but each item is nothing more than
the issue's emoji headline and a link: no summary, no stories, no content. The issue
pages themselves carry everything, laid out as <section>s with an emoji + heading
header followed by one <article> per story. We rebuild each issue from its page as
readable HTML: grouped by section, sponsor slots dropped, utm tracking stripped.
"""

from __future__ import annotations

import html
import re
import time
from email.utils import parsedate_to_datetime
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from xml.etree import ElementTree as ET

import httpx
from lxml import html as lx

from ..http import fetch_bytes, fetch_text
from ..models import Item, SourceResult

BASE = "https://tldr.tech/"

# "Bringing Your Muse to Life (5 minute read)" -> title, "5 minute read"
# TLDR's own hiring posts run as ordinary stories, untagged.
_OWN_JOB_ADS = "https://jobs.ashbyhq.com/tldr.tech"

_TRAILING_TAG = re.compile(r"^(?P<title>.*?)\s*\((?P<tag>[^()]*)\)\s*$")


def feed_url(newsletter: str) -> str:
    return f"{BASE}api/rss/{newsletter}"


def _clean_url(url: str) -> str:
    """Drop utm_* parameters so links are the plain article URL."""
    parts = urlsplit(url)
    query = [
        (k, v)
        for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if not k.startswith("utm_")
    ]
    return urlunsplit(parts._replace(query=urlencode(query)))


def _text(el) -> str:
    return " ".join(el.text_content().split()).strip()


def _split_tag(heading: str) -> tuple[str, str]:
    m = _TRAILING_TAG.match(heading)
    if not m:
        return heading, ""
    return m.group("title"), m.group("tag")


def _body_html(div) -> str:
    """The story blurb, with TLDR's styling classes and link tracking removed."""
    for el in div.iter():
        if not isinstance(el.tag, str):
            continue
        for attr in ("class", "style", "id"):
            el.attrib.pop(attr, None)
        if el.tag == "a" and el.get("href"):
            el.set("href", _clean_url(el.get("href")))
    inner = (html.escape(div.text) if div.text else "") + "".join(
        lx.tostring(child, encoding="unicode", method="html") for child in div
    )
    inner = inner.strip()
    # Plain-text blurbs arrive bare; wrap them so readers give them paragraph spacing.
    return inner if inner.startswith("<") else f"<p>{inner}</p>"


def parse_issue(page: str) -> tuple[str, list[str]]:
    """Render one issue page as (content_html, story titles). Raises if it has no stories."""
    doc = lx.fromstring(page)
    parts: list[str] = []
    titles: list[str] = []
    for section in doc.cssselect("section"):
        header = section.find("header")
        stories = []
        for art in section.cssselect("article"):
            link = art.cssselect("a[href]")
            h = art.cssselect("h3")
            if not link or not h:
                continue
            title, tag = _split_tag(_text(h[0]))
            href = _clean_url(link[0].get("href"))
            if tag.lower() == "sponsor" or href.startswith(_OWN_JOB_ADS):
                continue
            body = art.cssselect("div.newsletter-html")
            stories.append((title, tag, href, body[0] if body else None))
        if not stories:
            continue
        if header is not None:
            emoji = header.cssselect("div")
            name = header.cssselect("h3")
            label = " ".join(
                x for x in (_text(emoji[0]) if emoji else "", _text(name[0]) if name else "") if x
            )
            if label:
                parts.append(f"<h3>{html.escape(label)}</h3>")
        for title, tag, href, body in stories:
            titles.append(title)
            meta = f" <small>· {html.escape(tag)}</small>" if tag else ""
            parts.append(
                f'<h4><a href="{html.escape(href, quote=True)}">{html.escape(title)}</a>{meta}</h4>'
            )
            if body is not None:
                parts.append(_body_html(body))
    if not titles:
        raise ValueError(
            "no stories found in any <section><article> - page layout may have changed"
        )
    return "\n".join(parts), titles


def _issues(newsletter: str) -> list[tuple[str, str, str]]:
    """(headline, link, pubDate) for every issue in TLDR's own feed."""
    channel = ET.fromstring(fetch_bytes(feed_url(newsletter))).find("channel")
    if channel is None:
        return []
    return [
        (
            (it.findtext("title") or "").strip(),
            (it.findtext("link") or "").strip(),
            (it.findtext("pubDate") or "").strip(),
        )
        for it in channel.findall("item")
        if it.findtext("link")
    ]


def _fetch_page(url: str, *, attempts: int = 3) -> str | None:
    """An issue page, or None when it stays 404 after retries.

    tldr.tech answers bursts of requests with 404s rather than 429s: fetching 20 issues
    six at a time lost 15 of them at random. So pages are fetched one at a time, a 404 is
    retried after a pause, and only a persistent 404 counts as an issue that was never
    published. Any other failure propagates.
    """
    for attempt in range(attempts):
        try:
            return fetch_text(url)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code != 404:
                raise
            if attempt + 1 < attempts:
                time.sleep(2 * (attempt + 1))
    return None


def tldr(newsletter: str, label: str) -> SourceResult:
    try:
        issues = _issues(newsletter)
    except Exception as exc:  # noqa: BLE001
        return SourceResult(error=f"feed fetch/parse failed: {exc}")
    if not issues:
        return SourceResult(error=f"{feed_url(newsletter)} listed no issues")

    try:
        pages = [_fetch_page(link) for _, link, _ in issues]
        rendered = [parse_issue(p) if p is not None else None for p in pages]
    except Exception as exc:  # noqa: BLE001
        return SourceResult(error=f"issue fetch/parse failed: {exc}")

    missing = sum(p is None for p in pages)
    if missing * 2 > len(pages):
        return SourceResult(
            error=f"{missing} of {len(pages)} issue pages returned 404 - likely rate limiting"
        )

    items = []
    for (headline, link, pub), issue in zip(issues, rendered, strict=True):
        if issue is None:
            continue
        content, titles = issue
        items.append(
            Item(
                title=headline or link.rsplit("/", 1)[-1],
                link=link,
                guid=link,
                published=Item.at_midnight(parsedate_to_datetime(pub).date()),
                description="\n".join(f"• {t}" for t in titles),
                content_html=content,
                author="TLDR",
                categories=[label],
            )
        )
    return SourceResult(items=items)
