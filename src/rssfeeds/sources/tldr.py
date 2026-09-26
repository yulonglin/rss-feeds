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
from urllib.parse import urlsplit, urlunsplit
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


def _strip_utm(query: str) -> tuple[str, bool]:
    """Remove utm_* pairs from a query string, keeping every other byte as it was."""
    kept, dropped = [], False
    for pair in query.split("&"):
        key = pair.split("=", 1)[0]
        # TLDR double-escapes some hrefs upstream, leaving "amp;utm_source=..." keys.
        if key.removeprefix("amp;").startswith("utm_"):
            dropped = True
        elif pair:
            kept.append(pair)
    return "&".join(kept), dropped


def _clean_url(url: str) -> str:
    """Drop utm_* tracking from the query and from a query-style fragment
    ("#?utm_source=..." or "#section?utm_source=..."). A URL with no tracking is
    returned exactly as given, so nothing else about it gets re-encoded."""
    parts = urlsplit(url)
    query, q_dropped = _strip_utm(parts.query)
    frag, f_dropped = parts.fragment, False
    if "?" in frag:
        anchor, _, frag_query = frag.partition("?")
        frag_query, f_dropped = _strip_utm(frag_query)
        frag = f"{anchor}?{frag_query}" if frag_query else anchor
    if not (q_dropped or f_dropped):
        return url
    return urlunsplit(parts._replace(query=query, fragment=frag))


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
    """An issue page, or None when it still can't be fetched after retries.

    tldr.tech answers bursts of requests with 404s rather than 429s: fetching 20 issues
    six at a time lost 15 of them at random. So pages are fetched one at a time, and a
    404, a 429, a 5xx or a dropped connection is retried after a pause. A page that
    still fails is left out of this run; tldr() fails the source if most pages do.
    """
    for attempt in range(attempts):
        try:
            return fetch_text(url)
        except httpx.HTTPStatusError as exc:
            code = exc.response.status_code
            if code != 404 and code != 429 and code < 500:
                raise
        except httpx.TransportError:
            pass
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
            error=f"{missing} of {len(pages)} issue pages could not be fetched - likely rate limiting"
        )

    items = []
    for (headline, link, pub), issue in zip(issues, rendered, strict=True):
        if issue is None:
            continue
        content, titles = issue
        try:
            published = Item.at_midnight(parsedate_to_datetime(pub).date())
        except (TypeError, ValueError):
            continue  # an undated issue can't be placed in the feed
        items.append(
            Item(
                title=headline or link.rsplit("/", 1)[-1],
                link=link,
                guid=link,
                published=published,
                description="\n".join(f"• {t}" for t in titles),
                content_html=content,
                author="TLDR",
                categories=[label],
            )
        )
    return SourceResult(items=items)
