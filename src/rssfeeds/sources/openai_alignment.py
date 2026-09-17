"""alignment.openai.com — Research and Releases, Misalignment Notices, Misalignment Reports.

The site's own /rss.xml covers only the Research section, was last built 2026-07-21, and
omits every post that lives on openai.com proper. Notices and Reports have no feed at all.
We parse the rendered pages instead.
"""

from __future__ import annotations

from datetime import date
from urllib.parse import urljoin

from lxml import html as lx

from ..http import fetch_text
from ..models import Item, SourceResult
from ..state import FirstSeen

BASE = "https://alignment.openai.com/"
REPORTS_URL = urljoin(BASE, "misalignment-reports/")


def _text(el) -> str:
    """Visible text with the site's decorative link arrow removed."""
    return " ".join(el.text_content().split()).replace(" ↗", "").strip()


def research() -> SourceResult:
    try:
        doc = lx.fromstring(fetch_text(BASE))
    except Exception as exc:  # noqa: BLE001 - reported, not swallowed
        return SourceResult(error=f"fetch/parse failed: {exc}")

    items: list[Item] = []
    for art in doc.cssselect("article.ap-post"):
        a = art.cssselect("h2 a")
        t = art.cssselect("time[datetime]")
        if not a or not t:
            continue
        link = urljoin(BASE, a[0].get("href"))
        paras = art.cssselect("p")
        items.append(
            Item(
                title=_text(a[0]),
                link=link,
                guid=link,
                published=Item.at_midnight(date.fromisoformat(t[0].get("datetime"))),
                description=_text(paras[0]) if paras else "",
                categories=["Research and Releases"],
            )
        )
    if not items:
        return SourceResult(error="no article.ap-post entries found - page layout may have changed")
    return SourceResult(items=items)


def notices() -> SourceResult:
    try:
        doc = lx.fromstring(fetch_text(REPORTS_URL))
    except Exception as exc:  # noqa: BLE001
        return SourceResult(error=f"fetch/parse failed: {exc}")

    items: list[Item] = []
    for art in doc.cssselect("article.ap-notice"):
        t = art.cssselect("time[datetime]")
        h = art.cssselect(".ap-notice-title")
        if not t or not h:
            continue
        src = art.cssselect("a.ap-notice-source")
        body = [p for p in art.cssselect("p") if "ap-notice-meta" not in (p.get("class") or "")]
        anchor = art.get("id") or ""
        items.append(
            Item(
                title=_text(h[0]),
                link=urljoin(BASE, src[0].get("href")) if src else f"{REPORTS_URL}#{anchor}",
                guid=f"{REPORTS_URL}#{anchor}" if anchor else urljoin(BASE, src[0].get("href")),
                published=Item.at_midnight(date.fromisoformat(t[0].get("datetime"))),
                description=_text(body[0]) if body else "",
                categories=["Misalignment Notice"],
            )
        )
    if not items:
        return SourceResult(
            error="no article.ap-notice entries found - page layout may have changed"
        )
    return SourceResult(items=items)


def reports(first_seen: FirstSeen) -> SourceResult:
    """Reports carry no publication date anywhere in the markup, so they are stamped
    with the date this tool first saw them (see state/first_seen.json)."""
    try:
        doc = lx.fromstring(fetch_text(REPORTS_URL))
    except Exception as exc:  # noqa: BLE001
        return SourceResult(error=f"fetch/parse failed: {exc}")

    items: list[Item] = []
    for art in doc.cssselect("article.ap-report"):
        a = art.cssselect("a.ap-report-link")
        h = art.cssselect(".ap-report-title")
        if not a or not h:
            continue
        link = urljoin(BASE, a[0].get("href"))
        summary = art.cssselect(".ap-report-summary")
        scope = art.cssselect(".ap-report-scope")
        desc = _text(summary[0]) if summary else ""
        if scope:
            desc = f"{desc}\n\n{_text(scope[0])}".strip()
        items.append(
            Item(
                title=_text(h[0]),
                link=link,
                guid=link,
                published=first_seen.stamp(link),
                description=desc,
                categories=["Misalignment Report"],
            )
        )
    if not items:
        return SourceResult(
            error="no article.ap-report entries found - page layout may have changed"
        )
    return SourceResult(items=items)
