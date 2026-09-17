from __future__ import annotations

from datetime import UTC, datetime
from email.utils import format_datetime
from xml.etree import ElementTree as ET

from .models import Item

ATOM = "http://www.w3.org/2005/Atom"
DC = "http://purl.org/dc/elements/1.1/"
CONTENT = "http://purl.org/rss/1.0/modules/content/"

ET.register_namespace("atom", ATOM)
ET.register_namespace("dc", DC)
ET.register_namespace("content", CONTENT)

GENERATOR = "ai-safety-feeds (https://github.com/yulonglin/ai-safety-feeds)"


def _rfc822(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return format_datetime(dt)


def build_rss(
    *,
    title: str,
    link: str,
    description: str,
    self_url: str,
    items: list[Item],
    source_url: str,
) -> bytes:
    """Render items as RSS 2.0.

    `lastBuildDate` is derived from the newest item, never from wall-clock time, so a
    run that finds no new posts produces a byte-identical file and therefore no commit.
    """
    items = sorted(items, key=lambda i: (i.published, i.guid), reverse=True)

    rss = ET.Element("rss", {"version": "2.0"})
    ch = ET.SubElement(rss, "channel")
    ET.SubElement(ch, "title").text = title
    ET.SubElement(ch, "link").text = link
    ET.SubElement(ch, "description").text = description
    ET.SubElement(ch, "language").text = "en"
    ET.SubElement(ch, "generator").text = GENERATOR
    ET.SubElement(ch, "docs").text = "https://www.rssboard.org/rss-specification"
    ET.SubElement(
        ch, f"{{{ATOM}}}link", {"href": self_url, "rel": "self", "type": "application/rss+xml"}
    )
    ET.SubElement(ch, f"{{{ATOM}}}link", {"href": source_url, "rel": "via", "type": "text/html"})
    if items:
        ET.SubElement(ch, "lastBuildDate").text = _rfc822(items[0].published)

    for it in items:
        el = ET.SubElement(ch, "item")
        ET.SubElement(el, "title").text = it.title
        ET.SubElement(el, "link").text = it.link
        ET.SubElement(
            el, "guid", {"isPermaLink": "true" if it.guid.startswith("http") else "false"}
        ).text = it.guid
        ET.SubElement(el, "pubDate").text = _rfc822(it.published)
        if it.author:
            ET.SubElement(el, f"{{{DC}}}creator").text = it.author
        for cat in it.categories:
            ET.SubElement(el, "category").text = cat
        if it.description:
            ET.SubElement(el, "description").text = it.description
        if it.content_html:
            ET.SubElement(el, f"{{{CONTENT}}}encoded").text = it.content_html

    ET.indent(rss, space="  ")
    body = ET.tostring(rss, encoding="unicode", xml_declaration=False)
    return b'<?xml version="1.0" encoding="UTF-8"?>\n' + body.encode("utf-8") + b"\n"
