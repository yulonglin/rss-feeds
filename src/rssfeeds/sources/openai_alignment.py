"""OpenAI Safety & Alignment research, reports, and notices indexes."""

from __future__ import annotations

import json
import re
from datetime import date
from urllib.parse import urljoin, urlsplit, urlunsplit

from lxml import html as lx

from ..http import fetch_text
from ..models import Item, SourceResult
from ..state import FirstSeen

BASE = "https://alignment.openai.com/"
REPORTS_URL = urljoin(BASE, "misalignment-reports/")
ALIGNMENT_URL = "https://openai.com/safety-alignment/"
MISALIGNMENT_URL = urljoin(ALIGNMENT_URL, "misalignment-reports/")
_CATEGORIES = {
    "research": "Research and Releases",
    "reports": "Misalignment Report",
    "notices": "Misalignment Notice",
}
_LEGACY_NOTICE_LINKS = {
    "https://openai.com/hugging-face-incident-and-misalignment/#model-misalignment-2026-09-11": "notice-rubygems",
    "https://openai.com/hugging-face-incident-and-misalignment/#model-misalignment-2026-09-05": "notice-dsewiki",
    "https://openai.com/hugging-face-incident-and-misalignment/#model-misalignment-2026-08-26": "notice-hugging-face",
}


def _text(el) -> str:
    """Visible text with the site's decorative link arrow removed."""
    return " ".join(el.text_content().split()).replace(" ↗", "").strip()


class _IndexError(ValueError):
    """The migrated index could not be read without risking a partial feed."""


def _objects(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _objects(child)
    elif isinstance(value, list):
        for child in value:
            yield from _objects(child)


def _index_items(doc, *, report_index: bool) -> list[dict]:
    """Read the public list backing the page's client-side Load more button.

    The initial DOM only displays one page. Next.js serializes all rows into
    JSON chunks; parse data only, never execute the embedded JavaScript. Match
    the component shape rather than unstable chunk IDs or row counts.
    """
    chunks = []
    for script in doc.xpath("//script[not(@src)]/text()"):
        prefix = "self.__next_f.push("
        if not script.startswith(prefix):
            continue
        try:
            record = json.loads(script[len(prefix) :].removesuffix(")"))
        except ValueError as exc:
            raise _IndexError("malformed alignment index data") from exc
        if isinstance(record, list) and len(record) == 2 and record[0] == 1:
            if not isinstance(record[1], str):
                raise _IndexError("malformed alignment index chunk")
            chunks.append(record[1])

    field = "type" if report_index else "topic"
    lists = []
    for line in "".join(chunks).split("\n"):
        _, _, payload = line.partition(":")
        if not payload.startswith(("[", "{")):
            continue
        try:
            row = json.loads(payload)
        except ValueError:
            continue  # Not every protocol record contains plain JSON.
        for obj in _objects(row):
            filters = obj.get("filters")
            if (
                obj.get("searchable") is True
                and (obj.get("sortByReportDate") is True) == report_index
                and isinstance(filters, list)
                and any(isinstance(f, dict) and f.get("field") == field for f in filters)
                and isinstance(obj.get("items"), list)
            ):
                lists.append(obj["items"])
    if len(lists) != 1 or not lists[0] or not all(isinstance(i, dict) for i in lists[0]):
        raise _IndexError("missing or ambiguous alignment index list")
    return lists[0]


def _count(doc, group: str) -> int:
    if group == "research":
        labels = [_text(e) for e in doc.xpath("//*[@role='status']")]
        matches = [m for label in labels if (m := re.fullmatch(r"(\d+) results?", label))]
        values = [m[1] for m in matches]
    else:
        values = [
            _text(e)
            for e in doc.xpath(f"//a[@href='#{group}']/span")
            if _text(e).isascii() and _text(e).isdecimal()
        ]
    if len(values) != 1 or int(values[0]) == 0:
        raise _IndexError(f"missing advertised {group} count")
    return int(values[0])


def _item_link(href: str) -> str:
    link = urljoin(ALIGNMENT_URL, href)
    parsed = urlsplit(link)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username is not None:
        raise _IndexError("invalid alignment item URL")
    return link


def _stable_guid(link: str, group: str) -> str:
    if group == "notices":
        anchor = _LEGACY_NOTICE_LINKS.get(link)
        return f"{REPORTS_URL}#{anchor}" if anchor else link
    parts = urlsplit(link)
    if parts.netloc == "openai.com" and parts.path.startswith("/safety-alignment/"):
        # Keep the pre-migration namespace for alignment-host articles. It
        # preserves both subscribers' GUIDs and the stored report date keys.
        return urlunsplit(
            (
                "https",
                "alignment.openai.com",
                parts.path.removeprefix("/safety-alignment"),
                parts.query,
                parts.fragment,
            )
        )
    return link


def _migrated(doc, group: str, first_seen: FirstSeen | None = None) -> SourceResult:
    try:
        is_report_index = group != "research"
        entries = _index_items(doc, report_index=is_report_index)
        if is_report_index:
            groups: dict[str, list[dict]] = {"reports": [], "notices": []}
            for entry in entries:
                filters = entry.get("filters")
                types = filters.get("type") if isinstance(filters, dict) else None
                if (
                    not isinstance(types, list)
                    or len(types) != 1
                    or not isinstance(types[0], str)
                    or types[0] not in groups
                ):
                    raise _IndexError("unknown or ambiguous alignment item type")
                groups[types[0]].append(entry)
            entries = groups[group]

        expected = _count(doc, group)
        if len(entries) != expected:
            raise _IndexError(f"incomplete alignment {group} index ({len(entries)}/{expected})")

        rows = []
        seen = set()
        for entry in entries:
            title = entry.get("title")
            href = entry.get("href")
            dates = entry.get("reportDates")
            when = dates.get("firstPosted") if isinstance(dates, dict) else None
            if not is_report_index:
                when = entry.get("date")
            if not isinstance(title, str) or not title.strip() or not isinstance(href, str):
                raise _IndexError("malformed alignment item")
            if not href.strip():
                raise _IndexError("missing alignment item link")
            link = _item_link(href)
            guid = _stable_guid(link, group)
            # Some migrated reports lack First posted; existing state is
            # authoritative. Never guess a new report date from Last updated.
            posted = first_seen.get_date(guid) if first_seen is not None else None
            if posted is None:
                if not isinstance(when, str) or when == "$undefined":
                    raise _IndexError("missing alignment item publication date")
                posted = date.fromisoformat(when)
            if guid in seen:
                raise _IndexError("duplicate alignment item GUID")
            seen.add(guid)
            desc = entry.get("description")
            rows.append((title.strip(), link, guid, posted, desc))
    except ValueError as exc:
        # No FirstSeen changes until the entire group has validated.
        return SourceResult(error=f"alignment index: {exc}")

    return SourceResult(
        items=[
            Item(
                title=title,
                link=link,
                guid=guid,
                published=first_seen.stamp(guid, today=when)
                if first_seen
                else Item.at_midnight(when),
                description=desc if isinstance(desc, str) and desc != "$undefined" else "",
                categories=[_CATEGORIES[group]],
            )
            for title, link, guid, when, desc in rows
        ]
    )


def research() -> SourceResult:
    try:
        doc = lx.fromstring(fetch_text(ALIGNMENT_URL))
    except Exception as exc:  # noqa: BLE001 - reported, not swallowed
        return SourceResult(error=f"fetch/parse failed: {exc}")

    items: list[Item] = []
    articles = doc.cssselect("article.ap-post")
    if not articles:
        return _migrated(doc, "research")
    for art in articles:
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
    # Tables put incident/activity dates first (sometimes only YYYY-MM). Never
    # mistake those, or Last updated, for publication dates.
    if entry.tag == "tbody":
        t = entry.cssselect('td[data-label="First posted"] time[datetime]')
    else:
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
        doc = lx.fromstring(fetch_text(MISALIGNMENT_URL))
    except Exception as exc:  # noqa: BLE001
        return SourceResult(error=f"fetch/parse failed: {exc}")

    items: list[Item] = []
    entries = doc.cssselect(
        "#notice-entries details.cb-notice, #notice-entries > tbody.report-entry"
    )
    if not entries:
        return _migrated(doc, "notices")
    for entry in entries:
        when = _entry_date(entry)
        h = entry.cssselect("summary h3, a.report-title")
        src = entry.cssselect("a.ap-notice-source[href], a.report-title[href]")
        body = entry.cssselect(".cb-copy, .description-content")
        anchor = entry.get("id") or ""
        if when is None or not h or not _text(h[0]) or not (anchor or src):
            return SourceResult(error="malformed notice entry - page layout may have changed")
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
        return SourceResult(error="no notice entries found - page layout may have changed")
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
    """Keep stored dates stable; seed new reports with First posted in the table
    layout, or the updated date supplied by the legacy card layout."""
    try:
        doc = lx.fromstring(fetch_text(MISALIGNMENT_URL))
    except Exception as exc:  # noqa: BLE001
        return SourceResult(error=f"fetch/parse failed: {exc}")

    items: list[Item] = []
    entries = doc.cssselect(
        "#report-entries details.cb-entry, #report-entries > tbody.report-entry"
    )
    if not entries:
        return _migrated(doc, "reports", first_seen)
    for entry in entries:
        a = entry.cssselect("a.cb-link[href], a.report-title[href]")
        h = entry.cssselect("summary h3, a.report-title")
        when = _entry_date(entry)
        if not a or not a[0].get("href") or not h or not _text(h[0]):
            return SourceResult(error="malformed report entry - page layout may have changed")
        if entry.tag == "tbody" and when is None:
            return SourceResult(
                error="missing report First posted date - page layout may have changed"
            )
        link = urljoin(BASE, a[0].get("href"))
        copy = entry.cssselect(".cb-copy, .description-content p")
        desc = "\n\n".join(_text(p) for p in copy)
        facts = _facts(entry)
        scope = "; ".join(f"{k}: {facts[k]}" for k in ("Model", "Observed during") if k in facts)
        if scope:
            desc = f"{desc}\n\n{scope}".strip()
        items.append(
            Item(
                title=_text(h[0]),
                link=link,
                guid=link,
                published=first_seen.stamp(link, today=when),
                description=desc,
                categories=["Misalignment Report"],
            )
        )
    if not items:
        return SourceResult(error="no report entries found - page layout may have changed")
    return SourceResult(items=items)
