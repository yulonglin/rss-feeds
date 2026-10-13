"""apolloresearch.ai - Apollo Research's blog and its three research listings.

The site is a Webflow build with no feed: no <link rel="alternate">, and /rss.xml, /feed,
/blog/rss.xml and each section's rss.xml all 404. Each section is its own CMS collection
with its own URL prefix, so the four listings never share an entry:

- /blog lists every post as a `.blog_card` on one page.
- /science, /monitoring and /governance each carry an "All research" grid under
  `#research`: one pinned `.fidings_card` repeated on every page, then the rest, paginated
  by a Webflow `?<id>_page=N` "Load more" link. The highlight cards higher up on
  /monitoring repeat the grid's entries in another date format and are not read.

Feeds follow these listings, not the sitemap, which can carry a page the listing omits.
Dates come from the listing (`21 July 2026`); the body and summary from each article page.
"""

from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, date, datetime
from urllib.parse import urljoin

from lxml import html as lx

from ..http import fetch_text
from ..models import Item, SourceResult
from ..sanitize import safe_url, sanitize_html

BASE = "https://www.apolloresearch.ai/"
# A runaway "next" chain means the pagination markup changed; stop rather than loop.
MAX_PAGES = 20

# Monitoring posts quote agent transcripts that contain example credentials in real key
# formats (Stripe live keys, October 2026). Published as is, they trip secret scanning,
# which can block the refresh commit, so well-known key formats are masked, placeholders
# such as a short sk_live_ example included.
CREDENTIAL = re.compile(
    r"\b(?:[sr]k_(?:live|test)_[A-Za-z0-9]+"
    r"|sk-(?:proj-|ant-)?[A-Za-z0-9_-]{20,}"
    r"|AKIA[0-9A-Z]{16}"
    r"|gh[pousr]_[A-Za-z0-9]{30,}"
    r"|xox[abprs]-[A-Za-z0-9-]{10,})"
)
REDACTED = "[credential redacted]"


@dataclass(frozen=True)
class Section:
    path: str
    card: str
    date: str
    next_link: str
    subtitle: str | None = None
    tags: str | None = None
    category: str | None = None
    title: str = '[fs-cmsfilter-field="name"]'


BLOG = Section(
    path="blog",
    card=".blog_card",
    date=".blog_card-meta .text-size-small",
    next_link=".w-pagination-next[href]",
    subtitle='[fs-cmsfilter-field="subtitle"]',
    category="Blog",
)


def _research(path: str) -> Section:
    return Section(
        path=path,
        card="#research .fidings_card",
        date=".fidings_card-right .text-size-small",
        next_link="#research .w-pagination-next[href]",
        tags='.hide [fs-cmsfilter-field="filter"]',
    )


SECTIONS = {
    "blog": BLOG,
    "science": _research("science"),
    "monitoring": _research("monitoring"),
    "governance": _research("governance"),
}


def _clean(el) -> str:
    return " ".join(el.text_content().split())


def parse_date(text: str) -> date | None:
    """'21 July 2026' -> 2026-07-21; anything else -> None."""
    try:
        return datetime.strptime(" ".join(text.split()), "%d %B %Y").replace(tzinfo=UTC).date()
    except ValueError:
        return None


def _cards(doc, section: Section, page_url: str) -> list[Item]:
    items = []
    for card in doc.cssselect(section.card):
        titles = card.cssselect(section.title)
        dates = card.cssselect(section.date)
        hrefs = [a.get("href") for a in card.cssselect("a[href]")]
        link = safe_url(hrefs[0], page_url) if hrefs else None
        published = parse_date(_clean(dates[0])) if dates else None
        if not titles or not link or published is None:
            continue
        subtitle = card.cssselect(section.subtitle) if section.subtitle else []
        tags = [_clean(t) for t in card.cssselect(section.tags)] if section.tags else []
        items.append(
            Item(
                title=_clean(titles[0]),
                link=link,
                guid=link,
                published=Item.at_midnight(published),
                description=_clean(subtitle[0]) if subtitle else "",
                categories=[section.category] if section.category else [t for t in tags if t],
            )
        )
    return items


def _listing(section: Section) -> list[Item]:
    """Every card across the listing's pages, de-duplicated by link: the pinned research
    card is repeated on each page."""
    url = urljoin(BASE, section.path)
    seen_pages: set[str] = set()
    items: dict[str, Item] = {}
    while url not in seen_pages:
        if len(seen_pages) >= MAX_PAGES:
            raise RuntimeError(f"more than {MAX_PAGES} listing pages - pagination may have changed")
        seen_pages.add(url)
        doc = lx.fromstring(fetch_text(url))
        for item in _cards(doc, section, url):
            items.setdefault(item.link, item)
        nxt = doc.cssselect(section.next_link)
        if not nxt:
            break
        url = urljoin(url, nxt[0].get("href"))
    return list(items.values())


def _with_body(item: Item) -> Item:
    """The article's body, footnotes and meta description added to its listing entry. A
    page that fails to load keeps the listing entry as it is rather than dropping it."""
    try:
        doc = lx.fromstring(fetch_text(item.link))
    except Exception:  # noqa: BLE001
        return item
    blocks = doc.cssselect(".blog-rich-text") + doc.cssselect(".paper-right_footnotes")
    body = "\n".join(
        sanitize_html(lx.tostring(el, encoding="unicode", method="html"), base_url=item.link)
        for el in blocks
    ).strip()
    meta = doc.cssselect('meta[name="description"]')
    description = " ".join((meta[0].get("content") or "").split()) if meta else ""
    return item.model_copy(
        update={
            "content_html": CREDENTIAL.sub(REDACTED, body) or None,
            "description": CREDENTIAL.sub(REDACTED, description or item.description),
        }
    )


def apollo(section_name: str) -> SourceResult:
    section = SECTIONS[section_name]
    try:
        listed = _listing(section)
    except Exception as exc:  # noqa: BLE001
        return SourceResult(error=f"/{section.path} listing fetch/parse failed: {exc}")
    if not listed:
        return SourceResult(
            error=f"no dated cards matched {section.card!r} - page layout may have changed"
        )
    with ThreadPoolExecutor(max_workers=6) as pool:
        return SourceResult(items=list(pool.map(_with_body, listed)))
