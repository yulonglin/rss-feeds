"""darioamodei.com - Dario Amodei's essays and short posts.

The site has no feed. Its sitemap.xml lists every page but carries only lastmod,
which is a modification date and would reorder the feed whenever a typo is fixed.
Read the displayed publication month from the current semantic article header or
the legacy Webflow markup, keeping existing feed dates stable across the redesign.
The current <time datetime> is a fallback when no month/year is displayed.
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
    try:
        return date(int(parts[1]), month, 1)
    except ValueError:
        return None


def _publication_date(el) -> date | None:
    published = _parse_month_year(_clean(el))
    if published is not None:
        return published
    try:
        return date.fromisoformat((el.get("datetime") or "").strip())
    except ValueError:
        return None


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
    """Current articles and legacy essays use #main-content; old posts use .w-richtext.

    Footnotes are a separate labelled section or legacy .w-richtext.cc-footnotes.
    Include them once, without mistaking an orphan footnote block for the article body.
    """
    blocks = (
        doc.cssselect("#main-content")
        or [
            el
            for el in doc.cssselect(".w-richtext")
            if "cc-footnotes" not in (el.get("class") or "").split()
        ][:1]
    )
    if not blocks or not any(_clean(el) for el in blocks):
        return None
    for el in doc.cssselect('.w-richtext.cc-footnotes, section[aria-labelledby~="footnotes"]'):
        if not any(el is block or block in el.iterancestors() for block in blocks):
            blocks.append(el)
    out = []
    for el in blocks:
        # The redesign duplicates each note in a hover tooltip. RSS readers do
        # not load the site's CSS, so keep the linked endnote, not its inline copy.
        for tooltip in el.cssselect('a[data-footnote-ref] + span[aria-hidden="true"]'):
            tooltip.drop_tree()
        _absolutize(el, url)
        out.append(lx.tostring(el, encoding="unicode", method="html"))
    return "\n".join(out)


def _fetch_one(url: str) -> Item | None:
    doc = lx.fromstring(fetch_text(url))

    legacy_titles = doc.cssselect("h1.post-title")
    titles = legacy_titles or doc.cssselect("article h1")
    if not titles:
        return None
    # Machines of Loving Grace has a footnote on its heading. Keep its endnote
    # in the body, but do not turn the reference/hover text into the feed title.
    for ref in titles[0].xpath(".//sup[.//a[@data-footnote-ref]]"):
        ref.drop_tree()
    title = _clean(titles[0])
    if not title:
        return None
    # The new header places its date in a sibling paragraph. Avoid dates in the
    # article body, navigation or footer when the publication header is missing.
    dates = doc.cssselect(".post-date") or titles[0].xpath("following-sibling::p/time")
    if not dates:
        return None
    published = _publication_date(dates[0])
    if published is None:
        return None

    subtitles = doc.cssselect(".post-subtitle")
    if not subtitles and not legacy_titles:
        subtitles = titles[0].xpath("following-sibling::*[1][self::p and not(.//time)]")
    content = _extract_body(doc, url)
    if content is None:
        return None

    return Item(
        title=title,
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

    missing = sum(item is None for item in fetched)
    if missing:
        return SourceResult(
            error=f"{missing} of {len(urls)} articles missing a title, publication date or body "
            "- page layout may have changed"
        )
    return SourceResult(items=[item for item in fetched if item is not None])
