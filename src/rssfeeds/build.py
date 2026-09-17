from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from pathlib import Path
from xml.etree import ElementTree as ET

from .models import SourceResult
from .registry import FEEDS, REPO_URL, SITE_BASE, FeedSpec
from .rss import build_rss
from .sources import dario_amodei as dario_src
from .sources import metr as metr_src
from .sources import openai_alignment as oai
from .sources import openai_system_cards as cards
from .state import FirstSeen

# A refresh that returns far fewer entries than the last published run usually means the
# page still matches our selectors but no longer lays out the way it did - a silent
# truncation, which is worse than an outright failure because it looks like a normal feed.
SHRINK_THRESHOLD = 0.6


@dataclass
class FeedStatus:
    spec: FeedSpec
    written: bool
    item_count: int
    newest: datetime | None
    error: str | None


def collect(first_seen: FirstSeen) -> dict[str, SourceResult]:
    """Run every source independently: one site being down must not block the others."""
    return {
        "research": oai.research(),
        "notices": oai.notices(),
        "reports": oai.reports(first_seen),
        "system_cards": cards.system_cards(),
        "metr": metr_src.metr_english(),
        "dario": dario_src.dario_amodei(),
    }


def _inspect(path: Path) -> tuple[int, datetime | None]:
    """Item count and newest pubDate of a feed already on disk."""
    if not path.exists():
        return 0, None
    try:
        channel = ET.parse(path).getroot().find("channel")
    except ET.ParseError:
        return 0, None
    if channel is None:
        return 0, None
    items = channel.findall("item")
    newest = None
    for it in items:
        raw = it.findtext("pubDate")
        if not raw:
            continue
        try:
            dt = parsedate_to_datetime(raw)
        except (TypeError, ValueError):
            continue
        if newest is None or dt > newest:
            newest = dt
    return len(items), newest


def write_feeds(
    results: dict[str, SourceResult], out_dir: Path, *, allow_shrink: bool = False
) -> list[FeedStatus]:
    out_dir.mkdir(parents=True, exist_ok=True)
    statuses: list[FeedStatus] = []

    for spec in FEEDS:
        path = out_dir / spec.filename
        broken = [n for n in spec.sources if not results[n].ok]
        if broken:
            reasons = "; ".join(f"{n}: {results[n].error or 'no items'}" for n in broken)
            count, newest = _inspect(path)
            statuses.append(FeedStatus(spec, False, count, newest, reasons))
            continue

        items = [i for name in spec.sources for i in results[name].items]
        items.sort(key=lambda i: (i.published, i.guid), reverse=True)
        if spec.limit:
            items = items[: spec.limit]
        if not spec.include_content:
            items = [i.model_copy(update={"content_html": None}) for i in items]

        previous_count, _ = _inspect(path)
        floor = int(previous_count * SHRINK_THRESHOLD)
        if not allow_shrink and previous_count and len(items) < floor:
            statuses.append(
                FeedStatus(
                    spec,
                    False,
                    previous_count,
                    _inspect(path)[1],
                    f"refusing to shrink {previous_count} -> {len(items)} entries "
                    f"(below the {floor} floor); source layout may have changed. "
                    f"Re-run with --allow-shrink if the drop is real.",
                )
            )
            continue

        xml = build_rss(
            title=spec.title,
            link=spec.source_url,
            description=spec.description,
            self_url=spec.url,
            items=items,
            source_url=spec.source_url,
        )
        if not path.exists() or path.read_bytes() != xml:
            path.write_bytes(xml)
        statuses.append(
            FeedStatus(spec, True, len(items), items[0].published if items else None, None)
        )

    return statuses


def write_manifest(statuses: list[FeedStatus], path: Path) -> None:
    """Machine-readable list so another site can render the endpoints without scraping."""
    payload = {
        "site": SITE_BASE,
        "repo": REPO_URL,
        "generated": datetime.now(UTC).strftime("%Y-%m-%d"),
        "feeds": [
            {
                "slug": s.spec.slug,
                "title": s.spec.title,
                "description": s.spec.description,
                "org": s.spec.org,
                "feed_url": s.spec.url,
                "source_name": s.spec.source_name,
                "source_url": s.spec.source_url,
                "upstream_status": s.spec.upstream_status,
                "notes": s.spec.notes,
                "items": s.item_count,
                "newest": s.newest.date().isoformat() if s.newest else None,
                "healthy": s.error is None,
            }
            for s in statuses
        ],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    new = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
    # Only the "generated" date moves day to day; don't rewrite if nothing else changed.
    if path.exists():
        try:
            old = json.loads(path.read_text())
            if {**old, "generated": None} == {**payload, "generated": None}:
                return
        except json.JSONDecodeError:
            pass
    path.write_text(new)
