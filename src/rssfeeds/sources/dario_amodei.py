"""darioamodei.com - Dario Amodei's essays and short posts.

The site is a Webflow build with no feed and no structured date metadata: no <time>,
no datePublished, no article:published_time. Its sitemap.xml lists every page but
carries only lastmod, which is a modification date and would reorder the feed whenever
a typo is fixed. The pages themselves print the real publication date in a
`div.post-date`, at month precision, so that is what we read.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import date
from urllib.parse import urljoin, urlparse

from lxml import etree
from lxml import html as lx

from ..http import fetch_bytes, fetch_text
from ..models import Item, SourceResult

BASE = "https://darioamodei.com/"
SITEMAP = urljoin(BASE, "sitemap.xml")
SITEMAP_NS = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}

MONTHS = {
    m: i
    for i, m in enumerate(
        [
            "january",
            "february",
            "march",
            "april",
            "may",
            "june",
            "july",
            "august",
            "september",
            "october",
            "november",
            "december",
        ],
        start=1,
    )
}


def _parse_month_year(text: str) -> date | None:
    """'January 2026' -> 2026-01-01. Upstream gives no day, so the first is used."""
    parts = text.strip().split()
    if len(parts) != 2:
        return None
    month = MONTHS.get(parts[0].strip().lower())
    if month is None or not parts[1].isdigit():
        return None
    return date(int(parts[1]), month, 1)


def _clean(el) -> str:
    return " ".join(el.text_content().split()).strip()


def _absolutize(fragment, page_url: str) -> None:
    for el, attr, link, _pos in fragment.iterlinks():
        if link and not urlparse(link).netloc and not link.startswith(("#", "mailto:")):
            el.set(attr, urljoin(page_url, link))


def _article_urls() -> list[str]:
    root = etree.fromstring(fetch_bytes(SITEMAP))
    locs = [(loc.text or "").strip() for loc in root.findall(".//sm:url/sm:loc", SITEMAP_NS)]
    return sorted({u for u in locs if "/post/" in u or "/essay/" in u})


def _extract_body(doc, url: str) -> str | None:
    """Essays wrap the body in #main-content; short posts use a bare .w-richtext.

    Footnote blocks are a sibling .w-richtext carrying cc-footnotes, so they are appended
    rather than mistaken for the body - otherwise a short post yields no text at all and
    an essay loses its notes.
    """
    main = doc.cssselect("#main-content")
    blocks = (
        list(main)
        and main
        or [
            el
            for el in doc.cssselect(".w-richtext")
            if "cc-footnotes" not in (el.get("class") or "")
        ][:1]
    )
    blocks += [el for el in doc.cssselect(".w-richtext.cc-footnotes") if el not in blocks]
    if not blocks:
        return None
    out = []
    for el in blocks:
        _absolutize(el, url)
        out.append(lx.tostring(el, encoding="unicode", method="html"))
    return "\n".join(out)


def _fetch_one(url: str) -> Item | None:
    doc = lx.fromstring(fetch_text(url))

    titles = doc.cssselect("h1.post-title")
    dates = doc.cssselect(".post-date")
    if not titles or not dates:
        return None
    published = _parse_month_year(_clean(dates[0]))
    if published is None:
        return None

    subtitles = doc.cssselect(".post-subtitle")
    content = _extract_body(doc, url)

    return Item(
        title=_clean(titles[0]),
        link=url,
        guid=url,
        published=Item.at_midnight(published),
        description=_clean(subtitles[0]) if subtitles else "",
        content_html=content,
        author="Dario Amodei",
        categories=["Essay" if "/essay/" in url else "Short post"],
    )


def dario_amodei() -> SourceResult:
    try:
        urls = _article_urls()
    except Exception as exc:  # noqa: BLE001
        return SourceResult(error=f"sitemap fetch/parse failed: {exc}")
    if not urls:
        return SourceResult(error="sitemap listed no /post/ or /essay/ pages")

    try:
        with ThreadPoolExecutor(max_workers=6) as pool:
            fetched = list(pool.map(_fetch_one, urls))
    except Exception as exc:  # noqa: BLE001
        return SourceResult(error=f"article fetch/parse failed: {exc}")

    items = [i for i in fetched if i is not None]
    if not items:
        return SourceResult(
            error="no article carried a parseable .post-date - page layout may have changed"
        )
    return SourceResult(items=items)
