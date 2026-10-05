from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

import feedparser
import pytest

from rssfeeds.models import Item, SourceResult
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
    if not spec.allow_empty:
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


TANGLE_DAILY = (
    "<p>Intro</p>"
    "<h3 id='quick-hits'>Quick hits.</h3><p>Headline soup</p>"
    "<div class='kg-card kg-cta-card'>Today’s partner: buy</div>"
    "<h3 id='today%E2%80%99s-topic'>Today’s topic.</h3><p>The story.</p>"
    "<h4>What the left is saying.</h4><p>Left.</p>"
    "<div class='kg-card kg-cta-card'>Today’s partner: buy more</div>"
    "<h4>My take.</h4><p>Take.</p>"
    "<h3 id='under-the-radar'>Under the radar.</h3><p>Quiet story.</p>"
    "<h3 id='the-extras'>The extras.</h3><p>Fluff</p>"
    "<h3 id='have-a-nice-day'>Have a nice day.</h3><p>Puppies</p>"
) + "<p>padding</p>" * 250


def test_tangle_keeps_only_topic_and_under_the_radar() -> None:
    from rssfeeds.sources.tangle import select

    out = select("https://www.readtangle.com/x/", "Isaac Saul", ["Iran"], TANGLE_DAILY)
    assert out is not None
    for kept in ("The story.", "Left.", "Take.", "Quiet story."):
        assert kept in out
    for dropped in ("Intro", "Headline soup", "buy", "Fluff", "Puppies"):
        assert dropped not in out


def test_tangle_drops_teasers_previews_and_recaps() -> None:
    from rssfeeds.sources.tangle import select

    essay = "<p>An essay.</p>" * 300
    teaser = "<p>Watch our video</p>"
    assert select("https://www.readtangle.com/v/", "Isaac Saul", [], teaser) is None
    assert select("https://www.readtangle.com/f/", "Isaac Saul", ["Friday edition"], essay) is None
    assert select("https://www.readtangle.com/s/", "Tangle Staff", ["The Sunday"], essay) is None
    assert (
        select("https://www.readtangle.com/otherposts/r/", "Tangle Staff", ["reader-essay"], essay)
        is None
    )
    kept = select("https://www.readtangle.com/otherposts/e/", "Isaac Saul", [], essay)
    assert kept is not None and kept.count("An essay.") == 300


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        # plain tracking
        ("https://a.com/p?utm_source=tldr&id=7", "https://a.com/p?id=7"),
        # TLDR's double-escaped hrefs leave "amp;utm_source" keys
        (
            "https://qwen.ai/blog?id=qwen3.8-livetranslate&amp;utm_source=tldrai",
            "https://qwen.ai/blog?id=qwen3.8-livetranslate",
        ),
        # tracking hidden in a query-style fragment
        ("https://goodfire.com/r#?utm_source=tldrai", "https://goodfire.com/r"),
        (
            "https://baseten.co/b#quantization?utm_source=tldrai",
            "https://baseten.co/b#quantization",
        ),
        # untouched when there is nothing to strip, byte for byte
        ("https://a.com/p?foo&x=a,b:c", "https://a.com/p?foo&x=a,b:c"),
    ],
)
def test_tldr_clean_url(url: str, expected: str) -> None:
    from rssfeeds.sources.tldr import _clean_url

    assert _clean_url(url) == expected


def test_tangle_essay_drops_scripts_forms_and_share_buttons() -> None:
    from rssfeeds.sources.tangle import select

    essay = (
        "Opening line."
        + "<p>Real argument.</p>" * 200
        + "<script>share()</script>"
        + "<div class='tangle-share-row'><a href='x'><svg></svg></a></div>"
        + "<div class='kg-card kg-signup-card'><form><input></form>Join Tangle</div>"
        + "<p>Closing.</p>"
    )
    out = select("https://www.readtangle.com/otherposts/e/", "Isaac Saul", [], essay)
    assert out is not None
    assert "Opening line." in out and "Closing." in out
    for junk in ("<script", "share()", "<form", "svg", "Join Tangle"):
        assert junk not in out


def test_collect_isolates_a_source_that_raises(monkeypatch, tmp_path) -> None:
    from rssfeeds import build
    from rssfeeds.sources import tangle as tangle_src

    def boom():
        raise ValueError("Invalid date value or format")

    ok = SourceResult(items=[])
    for mod, name in [
        (build.oai, "research"),
        (build.oai, "notices"),
        (build.cards, "system_cards"),
        (build.metr_src, "metr_english"),
        (build.dario_src, "dario_amodei"),
    ]:
        monkeypatch.setattr(mod, name, lambda: ok)
    monkeypatch.setattr(build.oai, "reports", lambda _fs: ok)
    monkeypatch.setattr(build.tldr_src, "tldr", lambda *_a: ok)
    monkeypatch.setattr(build.ai_digest_src, "ai_digest", lambda: ok)
    monkeypatch.setattr(build.scholar_src, "scholar_inbox", lambda: ok)
    monkeypatch.setattr(build.conversation_src, "the_conversation", lambda _p: ok)
    monkeypatch.setattr(build.ps_src, "project_syndicate", lambda _p: ok)
    monkeypatch.setattr(build.gates_src, "gates_notes", lambda: ok)
    monkeypatch.setattr(tangle_src, "tangle", boom)

    results = build.collect(FirstSeen(tmp_path / "s.json"))
    assert results["tangle"].error and "ValueError" in results["tangle"].error
    assert results["research"] is ok


def test_default_opml_is_the_configured_set_in_folders() -> None:
    from xml.etree import ElementTree as ET

    from rssfeeds.opml import default_entries, render_opml
    from rssfeeds.registry import EXTERNAL_DEFAULTS

    data = render_opml("t", default_entries())
    assert data == render_opml("t", default_entries()), "must be byte-stable"
    root = ET.fromstring(data)
    folders = {o.get("text"): o for o in root.find("body")}
    urls = {o.get("xmlUrl") for o in root.iter("outline") if o.get("xmlUrl")}

    expected = {f.url for f in FEEDS if f.default} | {e.url for e in EXTERNAL_DEFAULTS}
    assert urls == expected
    # overlapping variants stay out of the default set
    assert "https://feeds.yulonglin.com/openai-alignment-research.xml" not in urls
    assert "https://feeds.yulonglin.com/metr-en.xml" not in urls
    # every feed sits inside a folder, never at the top level
    assert all(o.get("xmlUrl") is None for o in root.find("body"))
    assert set(folders) == {f.folder for f in FEEDS if f.default} | {
        e.folder for e in EXTERNAL_DEFAULTS
    }


def test_all_opml_lists_every_published_feed() -> None:
    from xml.etree import ElementTree as ET

    from rssfeeds.opml import all_entries, render_opml

    root = ET.fromstring(render_opml("t", all_entries()))
    urls = [o.get("xmlUrl") for o in root.iter("outline") if o.get("xmlUrl")]
    assert sorted(urls) == sorted(f.url for f in FEEDS)


# --- email newsletters ------------------------------------------------------------------
# Every fixture below is synthetic. Never paste a real newsletter email here: it carries
# the private inbox address and the subscriber's tokens.

FAKE_INBOX = "zzfakeinboxid0000001"
KTN_HOST = "kill-the-newsletter.com"  # as in rssfeeds.private


@pytest.fixture
def fake_inbox(monkeypatch):
    from rssfeeds import private

    monkeypatch.setenv(private.ENV_VAR, f'{{"scholar-inbox": "{FAKE_INBOX}"}}')
    private.config.cache_clear()
    yield
    private.config.cache_clear()


def test_output_carrying_an_inbox_id_or_token_is_refused(tmp_path, fake_inbox) -> None:
    from rssfeeds.build import write_feeds

    def result(body: str) -> dict[str, SourceResult]:
        item = Item(
            title=body,  # in the title too, so feeds that drop content_html are checked
            link="https://example.com/x",
            guid="g",
            published=datetime(2026, 1, 1, tzinfo=UTC),
            content_html=body,
        )
        return dict.fromkeys(ALL_SOURCES, SourceResult(items=[item]))

    for body in (
        "https://example.com/x?sha_key=fake0token0fake0token0fake0token",
        f"see https://{KTN_HOST}/feeds/{FAKE_INBOX}",
        f"mail {FAKE_INBOX}@{KTN_HOST}",
        '<a href="https://www.scholar-inbox.com/login?sha_key=abc">x</a>',
        '<img src="https://clicks.theconversation.com/q/abc">',
    ):
        statuses = write_feeds(result(body), tmp_path)
        assert all(not s.written and "refusing to publish" in s.error for s in statuses)
        assert not list(tmp_path.glob("*.xml"))
        assert all(FAKE_INBOX not in (s.error or "") for s in statuses)


def test_inbox_errors_never_carry_the_address(monkeypatch, fake_inbox) -> None:
    import httpx

    from rssfeeds import newsletter_email
    from rssfeeds.sources.scholar_inbox import scholar_inbox

    def boom(url):
        req = httpx.Request("GET", url)
        raise httpx.HTTPStatusError(
            f"404 for {url}", request=req, response=httpx.Response(404, request=req)
        )

    monkeypatch.setattr(newsletter_email, "fetch_bytes", boom)
    res = scholar_inbox()
    assert res.error and "404" in res.error and FAKE_INBOX not in res.error

    monkeypatch.setattr(
        newsletter_email, "fetch_bytes", lambda url: (_ for _ in ()).throw(OSError(url))
    )
    res = scholar_inbox()
    assert res.error and FAKE_INBOX not in res.error and "kill-the-newsletter" not in res.error


def test_unconfigured_inbox_is_an_error_not_a_crash(monkeypatch, tmp_path) -> None:
    from rssfeeds import private
    from rssfeeds.sources.ai_digest import ai_digest

    monkeypatch.delenv(private.ENV_VAR, raising=False)
    monkeypatch.setattr(private, "LOCAL_FILE", tmp_path / "absent.json")
    private.config.cache_clear()
    try:
        assert "no inbox ID" in (ai_digest().error or "")
    finally:
        private.config.cache_clear()


SCHOLAR_CARD = """
<table><tr><td width="4">&#160;</td><td>
  <table><tr><td><span>97</span></td><td><span>ArXiv 2026 (September 30)</span></td></tr></table>
  <p><a href="https://www.scholar-inbox.com/login?sha_key=SECRET&amp;date=1&amp;paper_id=X.pdf"
        style="font-weight:700">  A Paper   About Probes </a></p>
  <!-- Authors -->
  <p style="color:#5F6368">Ada Lovelace, Alan Turing</p>
  <p><a href="https://www.scholar-inbox.com/login?sha_key=SECRET&amp;paper_id=X.pdf&amp;tab=podcast">Listen</a></p>
</td></tr></table>"""
SCHOLAR_EMAIL = f"""<html><head><style>a{{color:red}}</style></head><body>
<p>We found 134 articles relevant to you (of 2464 total).</p>
<a href="https://www.scholar-inbox.com/login?sha_key=SECRET&amp;date=1">View Full Digest</a>
<p>Dear Reader,</p>{SCHOLAR_CARD}
<p>Important: Do not share this email - it contains your personal secret key.</p>
<a href="https://scholar-inbox.com/unsubscribe_digest/TOKEN">unsubscribe</a>
<hr><p><small><a href="https://{KTN_HOST}/feeds/{FAKE_INBOX}">Kill the Newsletter! feed settings</a></small></p>
</body></html>"""


def test_scholar_digest_is_rebuilt_from_fields_only() -> None:
    from rssfeeds.newsletter_email import Email
    from rssfeeds.sources.scholar_inbox import to_item

    email = Email(
        "urn:x:1",
        "📣 Scholar Alert Digest 02/10",
        datetime(2026, 10, 2, 11, tzinfo=UTC),
        SCHOLAR_EMAIL,
    )
    item = to_item(email)
    assert item is not None
    assert item.title == "Scholar Inbox, 2 Oct 2026: 1 papers"
    body = item.content_html
    for gone in (
        "SECRET",
        "sha_key",
        "TOKEN",
        "scholar-inbox.com/login",
        "kill-the-newsletter",
        FAKE_INBOX,
        "Dear",
    ):
        assert gone not in body
    assert "<strong>A Paper About Probes</strong>" in body
    assert "Ada Lovelace, Alan Turing" in body
    assert "ArXiv 2026 (September 30) · relevance 97" in body
    assert "arxiv.org/search/?query=A+Paper+About+Probes&amp;searchtype=title" in body
    assert "Matched 134 of 2464 new papers; the top 1 are below." in body
    assert item.guid.startswith("scholar-inbox:") and "urn" not in item.guid


CONVERSATION_EMAIL = f"""<html><head><style>.x{{}}</style></head><body>
<div style="display:none">Plus: preheader text</div>
<table><tr><td><img src="https://cdn.theconversation.com/static/tc/logos/logo.png" alt="The Conversation"></td></tr>
<tr><td>October 2, 2026</td></tr><tr><td>Global Edition</td></tr>
<tr><td><p>Editor's note with <a href="https://clicks.theconversation.com/f/a/AAA~~/BBB">an inline link</a>.</p></td></tr>
<tr><td>Lead Story</td></tr>
<tr><td><a href="https://clicks.theconversation.com/f/a/CCC~~/DDD"><img src="https://images.theconversation.com/files/1/story.jpg" width="468"></a></td></tr>
<tr><td><a href="https://clicks.theconversation.com/f/a/EEE~~/FFF">Why robots can’t fold laundry, explained at length</a></td></tr>
<tr><td>Jane Doe, University of Somewhere</td></tr>
<tr><td>A standfirst sentence about laundry.</td></tr>
<tr><td><a href="https://clicks.theconversation.com/f/a/GGG~~/HHH">Read the article</a></td></tr>
<tr><td>👋 That’s all for this week. Reply to this email to send questions about AI.</td></tr>
<tr><td>You’re receiving this newsletter from The Conversation</td></tr>
<tr><td><a href="https://clicks.theconversation.com/f/a/III~~/JJJ">Unsubscribe or manage your preferences</a>
<img src="https://clicks.theconversation.com/q/pixel" width="1" height="1"></td></tr></table>
<hr><p><small><a href="https://{KTN_HOST}/feeds/{FAKE_INBOX}">Kill the Newsletter! feed settings</a></small></p>
</body></html>"""


def test_conversation_email_is_flattened_and_untracked(tmp_path) -> None:
    from rssfeeds.sources.the_conversation import LinkCache, norm_title, render

    links = LinkCache(tmp_path / "links.json")
    links.data[norm_title("Why robots can't fold laundry, explained at length")] = (
        "https://theconversation.com/why-robots-cant-fold-laundry-123456"
    )
    content, titles, kind, first = render(CONVERSATION_EMAIL, links)
    assert titles == ["Why robots can’t fold laundry, explained at length"]
    assert kind == "AI weekly"
    assert first == "https://theconversation.com/why-robots-cant-fold-laundry-123456"
    assert (
        '<h3><a href="https://theconversation.com/why-robots-cant-fold-laundry-123456">'
        "Why robots can’t fold laundry, explained at length</a></h3>"
    ) in content
    assert "<p><em>Jane Doe, University of Somewhere</em></p>" in content
    assert "<p><strong>Lead Story</strong></p>" in content
    assert "an inline link" in content and "images.theconversation.com/files/1/story.jpg" in content
    for gone in (
        "clicks.",
        "preheader",
        "logo.png",
        "Read the article",
        "That’s all",
        "receiving",
        "Unsubscribe",
        "kill-the-newsletter",
        FAKE_INBOX,
        "style",
        "October 2, 2026",
        "Global Edition",
    ):
        assert gone not in content


def _email(subject: str, body: str, n: int = 1):
    from rssfeeds.newsletter_email import Email

    return Email(f"urn:x:{n}", subject, datetime(2026, 10, n, tzinfo=UTC), body)


CONFIRM_EMAIL = (
    "<html><body><p>Thanks for subscribing! Please confirm your subscription.</p>"
    '<p><a href="https://theaidigest.org/confirm?token=fake0token0fake0token0fake0token">'
    "Click here to confirm your subscription to this newsletter</a></p></body></html>"
)
ACCOUNT_EMAIL = (
    "<html><body><p>Use this link to sign in to your account.</p>"
    '<p><a href="https://example.org/session/abc?u=fake1user1fake1user1fake1user1">'
    "Sign in to The Conversation and Scholar Inbox right now</a></p></body></html>"
)


def test_ai_digest_publishes_nothing_until_reviewed(monkeypatch) -> None:
    from rssfeeds.sources import ai_digest as src

    issue = "<html><body><p>Real-looking issue</p><a href='https://x.org/a?k=1'>a</a></body></html>"
    monkeypatch.setattr(
        src,
        "fetch_inbox",
        lambda _slug: [
            _email("Confirm your subscription", CONFIRM_EMAIL, 1),
            _email("Your sign-in link", ACCOUNT_EMAIL, 2),
            _email("AI Digest: October", issue, 3),
        ],
    )
    res = src.ai_digest()
    assert res.error is None and res.items == []


def test_account_messages_are_recognised_and_newsletters_are_not() -> None:
    from rssfeeds.newsletter_email import is_account_message

    assert is_account_message(_email("Confirm your subscription", CONFIRM_EMAIL))
    assert is_account_message(_email("Hello", ACCOUNT_EMAIL))
    assert is_account_message(_email("Welcome to Scholar Inbox", "<p>hi</p>"))
    assert not is_account_message(_email("📣 Scholar Alert Digest 02/10", SCHOLAR_EMAIL))
    assert not is_account_message(_email("Unregulated AI and security threats", CONVERSATION_EMAIL))


def test_scholar_inbox_drops_account_mail(monkeypatch) -> None:
    from rssfeeds.sources import scholar_inbox as src

    monkeypatch.setattr(
        src,
        "fetch_inbox",
        lambda _slug: [
            _email("Confirm your subscription", CONFIRM_EMAIL, 1),
            _email("Your sign-in link", ACCOUNT_EMAIL, 2),
            _email("📣 Scholar Alert Digest 02/10", SCHOLAR_EMAIL, 3),
        ],
    )
    res = src.scholar_inbox()
    assert [i.title for i in res.items] == ["Scholar Inbox, 3 Oct 2026: 1 papers"]
    body = res.items[0].content_html
    assert "token" not in body and "session" not in body


def test_conversation_drops_account_mail_and_unknown_links(monkeypatch, tmp_path) -> None:
    from rssfeeds.sources import the_conversation as src

    # Placed above the sign-off, so it is the allowlist and not the footer cut that drops it.
    sneaky = CONVERSATION_EMAIL.replace(
        "<tr><td>👋",
        "<tr><td><a href='https://theconversation.com/account/confirm?token=fake0token0fake0token0'>"
        "A long anchor that looks just like a story headline</a>"
        "<img src='https://images.theconversation.com/files/2/x.jpg?w=600&uid=fake1user1fake1user1ab'>"
        "<img src='https://tracker.example.com/open.gif?id=fake1user1fake1user1ab'></td></tr>"
        "<tr><td>👋",
        1,
    )
    assert sneaky != CONVERSATION_EMAIL
    monkeypatch.setattr(
        src,
        "fetch_inbox",
        lambda _slug: [
            _email("Confirm your subscription", CONFIRM_EMAIL, 1),
            _email("Your sign-in link", ACCOUNT_EMAIL, 2),
            _email("Unregulated AI", sneaky, 3),
        ],
    )
    monkeypatch.setattr(src.LinkCache, "resolve", lambda self, titles: None)
    cache = src.LinkCache(tmp_path / "links.json")
    cache.data[src.norm_title("Why robots can’t fold laundry, explained at length")] = (
        "https://theconversation.com/why-robots-cant-fold-laundry-123456?utm_source=x#frag"
    )
    cache.save()
    res = src.the_conversation(tmp_path / "links.json")
    assert [i.title for i in res.items] == ["Unregulated AI"]
    body = res.items[0].content_html
    assert 'href="https://theconversation.com/why-robots-cant-fold-laundry-123456"' in body
    for gone in ("token", "uid=", "tracker.example.com", "account/confirm", "utm_", "#frag"):
        assert gone not in body
    assert 'src="https://images.theconversation.com/files/2/x.jpg?w=600"' in body
    assert "A long anchor that looks just like a story headline" in body  # text kept, link not


@pytest.mark.parametrize(
    "url",
    [
        "https://theaidigest.org/confirm?token=abc",
        "https://example.org/u?email=a%40b.c",
        "https://example.org/x?id=fake1user1fake1user1fake1user1",
        "https://example.org/x#view?auth_key=1",
    ],
)
def test_leak_guard_flags_token_like_query_params(url) -> None:
    from rssfeeds import private

    assert private.leaks(f'<a href="{url}">x</a>')
    assert not private.leaks(f'<a href="{url}">x</a>', tokens=False) or "auth_key" in url


def test_leak_guard_passes_ordinary_links() -> None:
    from rssfeeds import private

    ok = (
        '<a href="https://arxiv.org/search/?query=A+Paper&amp;searchtype=title">x</a>'
        '<img src="https://images.theconversation.com/files/1/a.jpg?ixlib=rb-4.1.1&amp;rect=0%2C141%2C7548%2C4246&amp;q=45&amp;w=668">'
        '<a href="http://[broken">y</a>'
    )
    assert private.leaks(ok) == []


MALFORMED_CONFIGS = [
    "not json at all",
    '["abcdef1234567890abcd"]',
    "null",
    '"abcdef1234567890abcd"',
    '{"scholar-inbox": 5}',
    '{"scholar-inbox": ""}',
    '{"scholar-inbox": {"id": "abcdef1234567890abcd"}}',
    '{"scholar-inbox": "abcdef1234567890abcd", "the-conversation": null}',
    '{"scholar-inbox": "https://example.com/abcdef1234567890abcd.xml"}',
]


@pytest.mark.parametrize("raw", MALFORMED_CONFIGS)
def test_malformed_inbox_config_fails_only_the_email_feeds(raw, tmp_path, monkeypatch, capsys):
    import rssfeeds.__main__ as cli
    from rssfeeds import build, private
    from rssfeeds.registry import FEEDS

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
    for mod, name in [
        (build.oai, "research"),
        (build.oai, "notices"),
        (build.cards, "system_cards"),
        (build.metr_src, "metr_english"),
        (build.dario_src, "dario_amodei"),
        (build.tangle_src, "tangle"),
        (build.gates_src, "gates_notes"),
    ]:
        monkeypatch.setattr(mod, name, lambda: good)
    monkeypatch.setattr(build.oai, "reports", lambda _fs: good)
    monkeypatch.setattr(build.tldr_src, "tldr", lambda *_a: good)
    monkeypatch.setattr(build.ps_src, "project_syndicate", lambda _p: good)

    def no_network(url):
        raise AssertionError("an email source fetched despite a malformed config")

    monkeypatch.setattr("rssfeeds.newsletter_email.fetch_bytes", no_network)
    monkeypatch.setenv(private.ENV_VAR, raw)
    private.config.cache_clear()

    docs = tmp_path / "docs"
    docs.mkdir()
    email_specs = [f for f in FEEDS if f.email]
    assert email_specs
    for spec in email_specs:
        (docs / spec.filename).write_bytes(b"<previous/>")
    try:
        with pytest.raises(SystemExit) as exc:
            cli.build(docs=docs, state=tmp_path / "s.json", readme=tmp_path / "R.md")
    finally:
        private.config.cache_clear()
    assert exc.value.code == 1
    for spec in FEEDS:
        if spec.email:
            assert (docs / spec.filename).read_bytes() == b"<previous/>"
        else:
            assert b"Kept" in (docs / spec.filename).read_bytes(), spec.slug
    out = capsys.readouterr()
    assert "abcdef1234567890abcd" not in _unmasked(out.out + out.err)
    assert "KTN_FEEDS" in out.out


def _unmasked(log: str) -> str:
    """The log minus GitHub's ::add-mask:: commands, which the runner consumes and never
    shows, and which must name the value they mask. Everything else is checked as is."""
    return "\n".join(line for line in log.splitlines() if not line.startswith("::add-mask::"))


def test_on_github_actions_every_inbox_id_is_masked(monkeypatch, capsys) -> None:
    """With GITHUB_ACTIONS=true each configured ID, and each ID-shaped string in a config
    too malformed to parse, is registered as a mask before anything else can print it."""
    from rssfeeds import private

    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    for raw, expected in [
        (f'{{"scholar-inbox": "{FAKE_INBOX}"}}', {FAKE_INBOX}),
        ('["abcdef1234567890abcd"]', {"abcdef1234567890abcd"}),
    ]:
        monkeypatch.setenv(private.ENV_VAR, raw)
        private.config.cache_clear()
        try:
            private.config()
        finally:
            private.config.cache_clear()
        out = capsys.readouterr().out
        assert {line.removeprefix("::add-mask::") for line in out.splitlines()} == expected


def test_linearize_strips_layout_and_tracking() -> None:
    from rssfeeds.newsletter_email import linearize

    blocks = linearize(
        '<html><body><table><tr><td style="padding:4px"><span style="color:red">Hello <b>there</b></span></td></tr>'
        '<tr><td><a href="https://x.org/a?utm_source=n&amp;id=2">kept</a><img src="https://t.co/p.gif" width="1"></td></tr>'
        "</table></body></html>",
        link=lambda h, t: h,
    )
    assert blocks == ["<p>Hello <b>there</b></p>", '<p><a href="https://x.org/a?id=2">kept</a></p>']


def test_project_syndicate_item_is_rebuilt(tmp_path, monkeypatch) -> None:
    from rssfeeds.sources import project_syndicate as ps

    feed = b"""\xef\xbb\xbf<?xml version="1.0" encoding="utf-8"?>
<rss version="2.0" xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:media="http://search.yahoo.com/mrss/"><channel>
<item><title>Care First</title>
<link>https://www.project-syndicate.org/commentary/care-by-ann-lee-2-and-bo-wu-2026-10?utm_source=rss&amp;utm_medium=feed</link>
<description><![CDATA[<p>Summary text.</p>]]></description><dc:creator>Ann Lee</dc:creator>
<pubDate>Fri, 02 Oct 2026 14:31:14 GMT</pubDate>
<guid isPermaLink="true">https://www.project-syndicate.org/commentary/care-by-ann-lee-2-and-bo-wu-2026-10</guid>
<media:content url="https://webapi.project-syndicate.org/library/a.jpg" medium="image"><media:copyright>Someone/AFP</media:copyright></media:content>
</item></channel></rss>"""
    monkeypatch.setattr(ps, "fetch_bytes", lambda url: feed)
    monkeypatch.setattr(
        ps,
        "fetch_text",
        lambda url: (
            "<html><head><title>Care First by Ann Lee &amp; Bo Wu - Project Syndicate</title></head></html>"
        ),
    )
    res = ps.project_syndicate(tmp_path / "bylines.json")
    (item,) = res.items
    assert (
        item.link
        == "https://www.project-syndicate.org/commentary/care-by-ann-lee-2-and-bo-wu-2026-10"
    )
    assert item.author == "Ann Lee and Bo Wu"
    assert "utm_" not in item.content_html
    assert '<img src="https://webapi.project-syndicate.org/library/a.jpg"' in item.content_html
    assert "Photo: Someone/AFP" in item.content_html and "<p>Summary text.</p>" in item.content_html

    # The byline is cached, so a later run that cannot reach the page keeps it.
    monkeypatch.setattr(ps, "fetch_text", lambda url: (_ for _ in ()).throw(OSError("down")))
    assert ps.project_syndicate(tmp_path / "bylines.json").items[0].author == "Ann Lee and Bo Wu"


def test_gates_notes_components_render_as_plain_html() -> None:
    from rssfeeds.sources.gates_notes import to_item

    obj = '<object type="application/kenticocloud" data-type="item" data-rel="link" data-codename="{}"></object>'
    raw = {
        "system": {"codename": "an_essay", "name": "an-essay"},
        "elements": {
            "date": {"value": "2026-08-26T07:00:00Z"},
            "article_title": {"value": "An essay"},
            "article_subtitle": {"value": "<p>A subtitle.</p>"},
            "byline": {"value": "Bill Gates"},
            "body_content": {
                "value": obj.format("css")
                + '<p>First <a href="/other-essay">para</a>.</p>'
                + obj.format("q")
                + "<p><br></p>"
            },
            "page_taxonomy_set__gn_taxonomy": {"value": [{"name": "Save lives"}]},
        },
    }
    modular = {
        "css": {
            "system": {"type": "html_block"},
            "elements": {"html_block_text": {"value": "<style>x</style>"}},
        },
        "q": {"system": {"type": "quote"}, "elements": {"quote_copy": {"value": "<p>Quoted.</p>"}}},
    }
    item = to_item(raw, modular)
    assert item.link == "https://www.gatesnotes.com/an-essay"
    assert item.guid == "gatesnotes:an_essay"
    assert item.categories == ["Save lives"]
    assert item.content_html == (
        "<p><em>A subtitle.</em></p>\n"
        '<p>First <a href="https://www.gatesnotes.com/other-essay">para</a>.</p>'
        "<blockquote><p>Quoted.</p></blockquote>"
    )
