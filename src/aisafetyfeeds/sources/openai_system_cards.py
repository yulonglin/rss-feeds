"""deploymentsafety.openai.com — OpenAI system cards.

The site ships a /posts.xml, but it is a broken dev build: 255 bytes, zero items, and a
<link> of http://localhost:4321/. The homepage is an Astro island whose props carry the
complete card list as JSON, which is a cleaner source than the rendered HTML (the visible
list is paginated behind a "View more" button).
"""

from __future__ import annotations

import html
import json
import re
from datetime import date
from urllib.parse import urljoin

from ..http import fetch_text
from ..models import Item, SourceResult

BASE = "https://deploymentsafety.openai.com/"

_ISLAND = re.compile(r"<astro-island[^>]*\bprops=\"([^\"]*)\"", re.DOTALL)


def _unwrap(node):
    """Astro serialises every value as [type_tag, value]; unwrap to plain Python."""
    if isinstance(node, list) and len(node) == 2 and isinstance(node[0], int):
        return _unwrap(node[1])
    if isinstance(node, list):
        return [_unwrap(v) for v in node]
    if isinstance(node, dict):
        return {k: _unwrap(v) for k, v in node.items()}
    return node


def system_cards() -> SourceResult:
    try:
        page = fetch_text(BASE)
    except Exception as exc:  # noqa: BLE001
        return SourceResult(error=f"fetch failed: {exc}")

    records: list[dict] = []
    for raw in _ISLAND.findall(page):
        try:
            data = _unwrap(json.loads(html.unescape(raw)))
        except json.JSONDecodeError:
            continue
        found = data.get("items") if isinstance(data, dict) else None
        if isinstance(found, list) and found:
            records = [r for r in found if isinstance(r, dict) and r.get("href")]
            break

    if not records:
        return SourceResult(
            error="no astro-island props with an items list - page layout may have changed"
        )

    items: list[Item] = []
    for rec in records:
        if rec.get("published") is False:
            continue
        try:
            published = Item.at_midnight(date.fromisoformat(str(rec["date"])[:10]))
        except (KeyError, ValueError):
            continue
        link = urljoin(BASE, str(rec["href"]))
        cats = ["System Card"]
        if rec.get("archived"):
            cats.append("Archived")
        items.append(
            Item(
                title=str(rec.get("title") or link),
                link=link,
                guid=link,
                published=published,
                description=str(rec.get("excerpt") or ""),
                categories=cats,
            )
        )
    if not items:
        return SourceResult(error="island found but yielded no dated, published cards")
    return SourceResult(items=items)
