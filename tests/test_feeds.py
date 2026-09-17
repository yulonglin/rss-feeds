from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

import feedparser
import pytest

from aisafetyfeeds.models import Item
from aisafetyfeeds.registry import FEEDS
from aisafetyfeeds.rss import build_rss
from aisafetyfeeds.sources.metr import is_english
from aisafetyfeeds.state import FirstSeen

FEEDS_DIR = Path(__file__).resolve().parents[1] / "docs" / "feeds"


@pytest.mark.parametrize(
    "link,expected",
    [
        ("https://metr.org/blog/2026-08-31-security-update/", True),
        ("https://metr.org/notes/2026-07-24-metrics/", True),
        ("https://metr.org/evaluations/gpt-5-report/", True),
        ("https://metr.org/es/blog/2026-05-19-frontier-risk-report/", False),
        ("https://metr.org/zh-Hans/blog/2026-05-19-frontier-risk-report/", False),
        # A language METR has not added yet must also be dropped, without a code change.
        ("https://metr.org/fr/notes/whatever/", False),
        ("https://metr.org/pt-BR/blog/whatever/", False),
    ],
)
def test_locale_paths_are_dropped(link: str, expected: bool) -> None:
    assert is_english(link) is expected


def test_build_rss_is_deterministic_and_clock_independent() -> None:
    items = [
        Item(
            title="Second & later",
            link="https://example.com/b",
            guid="https://example.com/b",
            published=datetime(2026, 2, 1, tzinfo=UTC),
            description="Ampersands & em dashes - must not break the feed",
        ),
        Item(
            title="First",
            link="https://example.com/a",
            guid="https://example.com/a",
            published=datetime(2026, 1, 1, tzinfo=UTC),
        ),
    ]
    kw = {
        "title": "T",
        "link": "https://example.com/",
        "description": "D",
        "self_url": "https://example.com/f.xml",
        "source_url": "https://example.com/",
    }
    first = build_rss(items=items, **kw)
    second = build_rss(items=list(reversed(items)), **kw)
    assert first == second, "output must not depend on input order or wall-clock time"

    parsed = feedparser.parse(first)
    assert not parsed.bozo
    assert [e.title for e in parsed.entries] == ["Second & later", "First"]
    assert "lastBuildDate" in first.decode()
    assert "2026" in parsed.feed.updated


def test_first_seen_is_stable_across_runs(tmp_path: Path) -> None:
    path = tmp_path / "first_seen.json"
    a = FirstSeen(path)
    stamped = a.stamp("https://example.com/r", today=date(2026, 3, 1))
    a.save()

    # A later run on a different day must reuse the original date.
    b = FirstSeen(path)
    assert b.stamp("https://example.com/r", today=date(2026, 9, 17)) == stamped
    assert b.stamp("https://example.com/new", today=date(2026, 9, 17)).date() == date(2026, 9, 17)


def test_registry_slugs_are_unique() -> None:
    slugs = [f.slug for f in FEEDS]
    assert len(slugs) == len(set(slugs))


@pytest.mark.parametrize("spec", FEEDS, ids=lambda s: s.slug)
def test_published_feed_parses(spec) -> None:
    path = FEEDS_DIR / spec.filename
    if not path.exists():
        pytest.skip(f"{spec.filename} not generated yet")
    parsed = feedparser.parse(path.read_bytes())
    assert not parsed.bozo, parsed.get("bozo_exception")
    assert parsed.entries, "a published feed must never be empty"
    if spec.limit:
        assert len(parsed.entries) <= spec.limit
    if not spec.include_content:
        assert all(not e.get("content") for e in parsed.entries)
