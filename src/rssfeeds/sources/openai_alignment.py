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


def _entry_date(entry) -> date | None:
    t = entry.cssselect(".cb-meta time[datetime]") or entry.cssselect("time[datetime]")
    if not t:
        return None
    try:
        # Tolerate a full timestamp ("2026-09-25T10:00:00Z") as well as a bare date.
        return date.fromisoformat((t[0].get("datetime") or "")[:10])
    except ValueError:
        return None


def notices() -> SourceResult:
    try:
        doc = lx.fromstring(fetch_text(REPORTS_URL))
    except Exception as exc:  # noqa: BLE001
        return SourceResult(error=f"fetch/parse failed: {exc}")

    items: list[Item] = []
    for entry in doc.cssselect("#notice-entries details.cb-notice"):
        when = _entry_date(entry)
        h = entry.cssselect("summary h3")
        if when is None or not h:
            continue
        src = entry.cssselect("a.ap-notice-source")
        body = entry.cssselect(".cb-copy")
        anchor = entry.get("id") or ""
        items.append(
            Item(
                title=_text(h[0]),
                link=urljoin(BASE, src[0].get("href")) if src else f"{REPORTS_URL}#{anchor}",
                guid=f"{REPORTS_URL}#{anchor}" if anchor else urljoin(BASE, src[0].get("href")),
                published=Item.at_midnight(when),
                description=_text(body[0]) if body else "",
                categories=["Misalignment Notice"],
            )
        )
    if not items:
        return SourceResult(
            error="no details.cb-notice entries found - page layout may have changed"
        )
    return SourceResult(items=items)


def _facts(entry) -> dict[str, str]:
    """The Model / Observed during / Report updated pairs under each report."""
    facts = {}
    for dt in entry.cssselect("dl dt"):
        dd = dt.getnext()
        if dd is not None and dd.tag == "dd":
            facts[_text(dt)] = _text(dd)
    return facts


def reports(first_seen: FirstSeen) -> SourceResult:
    """Reports show only a last-updated date. Dating by it would move a report to the top
    of the feed every time OpenAI edits it, so each report keeps the date it was first
    seen (state/first_seen.json); a report new to us is seeded with the page's date."""
    try:
        doc = lx.fromstring(fetch_text(REPORTS_URL))
    except Exception as exc:  # noqa: BLE001
        return SourceResult(error=f"fetch/parse failed: {exc}")

    items: list[Item] = []
    for entry in doc.cssselect("#report-entries details.cb-entry"):
        a = entry.cssselect("a.cb-link")
        h = entry.cssselect("summary h3")
        if not a or not h:
            continue
        link = urljoin(BASE, a[0].get("href"))
        copy = entry.cssselect(".cb-copy")
        desc = _text(copy[0]) if copy else ""
        facts = _facts(entry)
        scope = "; ".join(f"{k}: {facts[k]}" for k in ("Model", "Observed during") if k in facts)
        if scope:
            desc = f"{desc}\n\n{scope}".strip()
        items.append(
            Item(
                title=_text(h[0]),
                link=link,
                guid=link,
                published=first_seen.stamp(link, today=_entry_date(entry)),
                description=desc,
                categories=["Misalignment Report"],
            )
        )
    if not items:
        return SourceResult(
            error="no details.cb-entry report entries found - page layout may have changed"
        )
    return SourceResult(items=items)
