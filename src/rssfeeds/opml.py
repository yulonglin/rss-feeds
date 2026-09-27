"""OPML subscription lists, so a reader can import a whole set in one step.

subscriptions.opml is the recommended set: the feeds marked default=True in the registry
plus EXTERNAL_DEFAULTS, grouped into folders. all.opml is every feed this site
publishes. Both carry no timestamps, so an unchanged registry produces byte-identical
files and no commit.
"""

from __future__ import annotations

from pathlib import Path
from xml.etree import ElementTree as ET

from .registry import EXTERNAL_DEFAULTS, FEEDS

# (folder, title, feed url, site url)
Entry = tuple[str, str, str, str]


def default_entries() -> list[Entry]:
    ours = [(f.folder, f.title, f.url, f.source_url) for f in FEEDS if f.default]
    theirs = [(e.folder, e.title, e.url, e.site_url) for e in EXTERNAL_DEFAULTS]
    return ours + theirs


def all_entries() -> list[Entry]:
    return [(f.folder, f.title, f.url, f.source_url) for f in FEEDS]


def render_opml(title: str, entries: list[Entry]) -> bytes:
    """Folders appear in the order they are first used, feeds in registry order."""
    opml = ET.Element("opml", {"version": "1.1"})
    head = ET.SubElement(opml, "head")
    ET.SubElement(head, "title").text = title
    body = ET.SubElement(opml, "body")
    folders: dict[str, ET.Element] = {}
    for folder, name, url, site in entries:
        if folder not in folders:
            folders[folder] = ET.SubElement(body, "outline", {"text": folder, "title": folder})
        ET.SubElement(
            folders[folder],
            "outline",
            {"text": name, "title": name, "type": "rss", "xmlUrl": url, "htmlUrl": site},
        )
    ET.indent(opml, space="  ")
    return (
        b'<?xml version="1.0" encoding="UTF-8"?>\n'
        + ET.tostring(opml, encoding="unicode").encode("utf-8")
        + b"\n"
    )


def write_opml(docs: Path) -> None:
    for name, title, entries in (
        ("subscriptions.opml", "RSS Feeds - recommended set", default_entries()),
        ("all.opml", "RSS Feeds - every feed", all_entries()),
    ):
        path = docs / name
        data = render_opml(title, entries)
        if not path.exists() or path.read_bytes() != data:
            path.write_bytes(data)
