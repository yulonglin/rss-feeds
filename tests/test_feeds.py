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

# Derived from the registry so adding a source cannot silently break these tests.
ALL_SOURCES = tuple({name for f in FEEDS for name in f.sources})


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
        return dict.fromkeys(ALL_SOURCES, SourceResult(items=items))

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
        lambda _fs: dict.fromkeys(ALL_SOURCES, good),
    )
    cli.build(docs=docs, state=tmp_path / "s.json", readme=tmp_path / "R.md")
    before = (docs / "openai-alignment-research.xml").read_bytes()

    broken = SourceResult(error="no article.ap-post entries found - page layout may have changed")
    monkeypatch.setattr(
        cli,
        "collect",
        lambda _fs: {
            **dict.fromkeys(ALL_SOURCES, good),
            "research": broken,
        },
    )
    with pytest.raises(SystemExit) as exc:
        cli.build(docs=docs, state=tmp_path / "s.json", readme=tmp_path / "R.md")
    assert exc.value.code == 1, "a broken source must redden the run"
    assert (docs / "openai-alignment-research.xml").read_bytes() == before


@pytest.mark.parametrize(
    "text,expected",
    [
        ("January 2026", date(2026, 1, 1)),
        ("  October 2024 ", date(2024, 10, 1)),
        ("september 2026", date(2026, 9, 1)),
        ("2026", None),
        ("Jan 2026", None),
        ("Smarch 2026", None),
        ("", None),
    ],
)
def test_dario_month_year_dates(text, expected) -> None:
    from rssfeeds.sources.dario_amodei import _parse_month_year

    assert _parse_month_year(text) == expected


def test_dario_feed_carries_body_text_for_every_entry() -> None:
    """Short posts and essays use different content containers; both must yield text."""
    path = FEEDS_DIR / "dario-amodei.xml"
    if not path.exists():
        pytest.skip("dario-amodei.xml not generated yet")
    parsed = feedparser.parse(path.read_bytes())
    assert not parsed.bozo
    empty = [e.title for e in parsed.entries if not e.get("content", [{}])[0].get("value")]
    assert not empty, f"entries with no body text: {empty}"
    assert {t.term for e in parsed.entries for t in e.get("tags", [])} == {"Essay", "Short post"}


CASEBOOK_PAGE = """
<html><body><main>
<div id="report-entries">
  <details class="cb-entry" data-date="2026-09-25">
    <summary><div><h3>An agent used DNS to reach an external chatbot</h3>
      <p class="cb-meta">Report · Updated <time datetime="2026-09-25">Sep 25, 2026</time></p>
    </div><span class="cb-toggle"></span></summary>
    <div class="cb-body"><div>
      <p class="cb-eyebrow">Observation</p>
      <p class="cb-copy">An agent queried a chatbot over DNS.</p>
      <a class="cb-link" href="/misalignment-reports/an-agent-used-dns/">Read full report <span>→</span></a>
    </div>
    <dl>
      <div><dt>Model</dt><dd>Internal research model</dd></div>
      <div><dt>Observed during</dt><dd>RL training</dd></div>
      <div><dt>Report updated</dt><dd><time datetime="2026-09-25">Sep 25, 2026</time></dd></div>
    </dl></div>
  </details>
  <details class="cb-entry" data-date="2026-09-16">
    <summary><div><h3>Old report</h3>
      <p class="cb-meta">Report · Updated <time datetime="2026-09-16">Sep 16, 2026</time></p>
    </div></summary>
    <div class="cb-body"><div><p class="cb-copy">Seen before.</p>
      <a class="cb-link" href="/misalignment-reports/old/">Read full report</a></div></div>
  </details>
</div>
<div id="notice-entries">
  <details class="cb-entry cb-notice" id="notice-rubygems">
    <summary><div><h3>RubyGems</h3>
      <p class="cb-meta">Notice · <time datetime="2026-09-11">September 11, 2026</time></p>
    </div></summary>
    <div class="cb-body"><div>
      <p class="cb-eyebrow">Notice summary</p>
      <p class="cb-copy">We are investigating a report.</p>
      <a class="ap-notice-source" href="https://openai.com/x/#update">Read the update <span>↗</span></a>
    </div></div>
  </details>
</div>
</main></body></html>
"""


def test_openai_casebook_layout(monkeypatch, tmp_path):
    from rssfeeds.sources import openai_alignment as oai

    monkeypatch.setattr(oai, "fetch_text", lambda _url: CASEBOOK_PAGE)

    notices = oai.notices()
    assert notices.ok, notices.error
    [n] = notices.items
    assert n.title == "RubyGems"
    assert n.link == "https://openai.com/x/#update"
    assert n.guid == "https://alignment.openai.com/misalignment-reports/#notice-rubygems"
    assert n.published.date().isoformat() == "2026-09-11"
    assert n.description == "We are investigating a report."

    state = tmp_path / "first_seen.json"
    state.write_text('{"https://alignment.openai.com/misalignment-reports/old/": "2026-09-17"}')
    reports = oai.reports(FirstSeen(state))
    assert reports.ok, reports.error
    new, old = reports.items
    assert new.link == "https://alignment.openai.com/misalignment-reports/an-agent-used-dns/"
    assert new.title == "An agent used DNS to reach an external chatbot"
    # a report new to us takes the page's date; one already seen keeps its recorded date
    assert new.published.date().isoformat() == "2026-09-25"
    assert old.published.date().isoformat() == "2026-09-17"
    assert new.description == (
        "An agent queried a chatbot over DNS.\n\nModel: Internal research model; "
        "Observed during: RL training"
    )


TLDR_ISSUE = """
<html><body><div><div>
<h1>TLDR AI 2026-09-25</h1>
<section></section>
<section><header><div>💰</div><h3></h3></header>
  <article><a class="font-bold" href="https://ad.example/?utm_source=tldr"><h3>Cut costs (Sponsor)</h3></a>
  <div class="newsletter-html">Buy things.</div></article>
</section>
<section><header><div class="text-center">🚀</div><h3 class="text-center">Headlines &amp; Launches</h3></header>
  <article class="mt-3"><a class="font-bold" href="https://research.meta.ai/muse?utm_source=tldrai&amp;id=7"><h3>Bringing Your Muse to Life (5 minute read)</h3></a>
  <div class="newsletter-html">Meta has introduced <a class="x" href="https://meta.ai/?utm_medium=email">Muse</a>.</div></article>
  <article class="mt-3"><a class="font-bold" href="https://github.com/wbopan/tastebench"><h3>Taste-Bench</h3></a>
  <div class="newsletter-html">Plain blurb.</div></article>
</section>
</div></div></body></html>
"""


def test_tldr_issue_is_sectioned_and_sponsor_free() -> None:
    from rssfeeds.sources.tldr import parse_issue

    content, titles = parse_issue(TLDR_ISSUE)
    assert titles == ["Bringing Your Muse to Life", "Taste-Bench"]
    assert "Sponsor" not in content and "Buy things" not in content
    assert "utm_" not in content
    assert "<h3>🚀 Headlines &amp; Launches</h3>" in content
    assert (
        '<h4><a href="https://research.meta.ai/muse?id=7">Bringing Your Muse to Life</a> '
        "<small>· 5 minute read</small></h4>"
    ) in content
    assert '<a href="https://meta.ai/">Muse</a>' in content
    assert "<p>Plain blurb.</p>" in content
    assert 'class="' not in content


def test_tldr_issue_without_stories_fails_loudly() -> None:
    from rssfeeds.sources.tldr import parse_issue

    with pytest.raises(ValueError):
        parse_issue("<html><body><section></section></body></html>")
