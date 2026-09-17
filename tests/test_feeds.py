from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

import feedparser
import pytest

from rssfeeds.models import Item
from rssfeeds.registry import FEEDS
from rssfeeds.rss import build_rss
from rssfeeds.sources.metr import is_english
from rssfeeds.state import FirstSeen

FEEDS_DIR = Path(__file__).resolve().parents[1] / "docs"


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


def test_silent_truncation_is_refused(tmp_path: Path) -> None:
    """A source that still parses but returns far fewer entries must not overwrite."""
    from rssfeeds.build import write_feeds
    from rssfeeds.models import SourceResult
    from rssfeeds.registry import FEEDS

    spec = next(f for f in FEEDS if f.slug == "openai-alignment-research")

    def make(n: int) -> dict[str, SourceResult]:
        items = [
            Item(
                title=f"Post {i}",
                link=f"https://example.com/{i}",
                guid=f"https://example.com/{i}",
                published=datetime(2026, 1, 1 + i, tzinfo=UTC),
            )
            for i in range(n)
        ]
        return {
            k: SourceResult(items=items)
            for k in ("research", "notices", "reports", "system_cards", "metr")
        }

    full = write_feeds(make(20), tmp_path)
    assert next(s for s in full if s.spec is spec).item_count == 20
    before = (tmp_path / spec.filename).read_bytes()

    shrunk = next(s for s in write_feeds(make(3), tmp_path) if s.spec is spec)
    assert not shrunk.written
    assert "refusing to shrink" in (shrunk.error or "")
    assert (tmp_path / spec.filename).read_bytes() == before, "must keep the last good feed"

    forced = next(s for s in write_feeds(make(3), tmp_path, allow_shrink=True) if s.spec is spec)
    assert forced.written and forced.item_count == 3


def test_failing_source_exits_nonzero_and_preserves_the_feed(tmp_path, monkeypatch) -> None:
    """The condition that drives the feed-broken alert: a source error must exit 1."""
    import rssfeeds.__main__ as cli
    from rssfeeds.models import SourceResult

    docs = tmp_path / "docs"
    good = SourceResult(
        items=[
            Item(
                title="Kept",
                link="https://example.com/keep",
                guid="https://example.com/keep",
                published=datetime(2026, 1, 1, tzinfo=UTC),
            )
        ]
    )
    monkeypatch.setattr(
        cli,
        "collect",
        lambda _fs: dict.fromkeys(("research", "notices", "reports", "system_cards", "metr"), good),
    )
    cli.build(docs=docs, state=tmp_path / "s.json", readme=tmp_path / "R.md")
    before = (docs / "openai-alignment-research.xml").read_bytes()

    broken = SourceResult(error="no article.ap-post entries found - page layout may have changed")
    monkeypatch.setattr(
        cli,
        "collect",
        lambda _fs: {
            **dict.fromkeys(("notices", "reports", "system_cards", "metr"), good),
            "research": broken,
        },
    )
    with pytest.raises(SystemExit) as exc:
        cli.build(docs=docs, state=tmp_path / "s.json", readme=tmp_path / "R.md")
    assert exc.value.code == 1, "a broken source must redden the run"
    assert (docs / "openai-alignment-research.xml").read_bytes() == before
