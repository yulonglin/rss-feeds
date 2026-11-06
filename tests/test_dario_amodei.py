from datetime import UTC, date, datetime
from pathlib import Path

import feedparser
import pytest
from lxml import html

from rssfeeds.build import write_feeds
from rssfeeds.models import SourceResult
from rssfeeds.registry import FEEDS
from rssfeeds.rss import build_rss
from rssfeeds.sources import dario_amodei as dario

FIXTURES = Path(__file__).parent / "fixtures"
POST_URL = "https://darioamodei.com/post/we-must-pace-the-frontier"
ESSAY_URL = "https://darioamodei.com/essay/the-adolescence-of-technology"
PAGES = {
    POST_URL: (FIXTURES / "dario_current_post.html").read_text(),
    ESSAY_URL: (FIXTURES / "dario_current_essay.html").read_text(),
}


@pytest.mark.parametrize(
    "url,title,published,description,category",
    [
        (POST_URL, "We Must Pace the Frontier", date(2026, 9, 1), "", "Short post"),
        (
            ESSAY_URL,
            "The Adolescence of Technology",
            date(2026, 1, 1),
            "Confronting and Overcoming the Risks of Powerful AI",
            "Essay",
        ),
    ],
)
def test_current_article_layout(url, title, published, description, category, monkeypatch):
    monkeypatch.setattr(dario, "fetch_text", PAGES.__getitem__)
    item = dario._fetch_one(url)
    assert item is not None
    assert item.title == title
    assert item.link == item.guid == url
    assert item.published == datetime.combine(published, datetime.min.time(), tzinfo=UTC)
    assert item.description == description
    assert item.author == "Dario Amodei"
    assert item.categories == [category]

    body = html.fragment_fromstring(item.content_html, create_parent="div")
    assert "Opening paragraph" in body.text_content()
    assert "Closing paragraph" in body.text_content()
    assert body.text_content().count("Note text") == 1
    assert len(body.xpath('//*[@id="fn:1"]')) == 1
    assert body.cssselect('a[href="#fn:1"]')
    assert body.cssselect('a[href="#fnref:1"]')
    assert not body.cssselect('span[aria-hidden="true"]')
    assert body.cssselect('a[href="https://darioamodei.com/essay/related"]')
    assert body.cssselect('a[href="https://darioamodei.com/post/reference"]')
    assert body.cssselect('img[src="https://darioamodei.com/images/figure.png"]')
    assert not body.cssselect("h1, time, nav, footer")


@pytest.mark.parametrize("essay", [False, True])
@pytest.mark.parametrize("nested_notes", [False, True])
def test_legacy_webflow_layout_preserves_body_and_notes(essay, nested_notes, monkeypatch):
    notes = '<div class="w-richtext cc-footnotes"><p id="note">Legacy note</p></div>'
    content = '<p>Legacy body <a href="#note">1</a></p>' + (notes if nested_notes else "")
    page = (
        '<h1 class="post-title">Legacy title</h1>'
        '<div class="post-subtitle">Legacy subtitle</div>'
        '<div class="post-date">October 2024</div>'
        f'<div {"id=main-content" if essay else ""} class="w-richtext">{content}</div>'
        + ("" if nested_notes else notes)
    )
    monkeypatch.setattr(dario, "fetch_text", lambda _: page)
    item = dario._fetch_one(ESSAY_URL if essay else POST_URL)
    assert item is not None
    assert item.title == "Legacy title"
    assert item.description == "Legacy subtitle"
    assert item.published == datetime(2024, 10, 1, tzinfo=UTC)
    assert "Legacy body" in item.content_html
    assert item.content_html.count("Legacy note") == 1


@pytest.mark.parametrize(
    "text,attribute,expected",
    [
        ("September 2026", "2026-09-12", date(2026, 9, 1)),
        ("", "2026-09-12", date(2026, 9, 12)),
        ("September 12, 2026", "2026-09-12", date(2026, 9, 12)),
        ("September 2026", "invalid", date(2026, 9, 1)),
        ("invalid", "2026-02-30", None),
        ("invalid", "invalid", None),
        ("January 0000", "", None),
        ("January 10000", "", None),
        ("", "", None),
    ],
)
def test_publication_date_uses_month_before_iso_fallback(text, attribute, expected):
    el = html.Element("time", datetime=attribute)
    el.text = text
    assert dario._publication_date(el) == expected


@pytest.mark.parametrize("layout", ["legacy", "current"])
def test_article_without_subtitle_does_not_use_date_as_description(layout, monkeypatch):
    if layout == "current":
        page = PAGES[POST_URL]
    else:
        page = (
            '<h1 class="post-title">Title</h1><p class="post-date">September 2026</p>'
            '<div class="w-richtext"><p>Body</p></div>'
        )
    monkeypatch.setattr(dario, "fetch_text", lambda _: page)
    assert dario._fetch_one(POST_URL).description == ""


@pytest.mark.parametrize(
    "failure", ["title", "empty_title", "date", "bad_date", "body", "empty_body"]
)
def test_incomplete_article_is_not_published(failure, monkeypatch):
    doc = html.fromstring(PAGES[POST_URL])
    if failure == "title":
        doc.cssselect("article h1")[0].drop_tree()
    elif failure == "empty_title":
        doc.cssselect("article h1")[0].text = " "
    elif failure == "date":
        doc.cssselect("article time")[0].drop_tree()
        # A time mentioned in the body is not publication metadata.
        doc.get_element_by_id("main-content").append(
            html.fromstring('<time datetime="2020-01-01">January 2020</time>')
        )
    elif failure == "bad_date":
        el = doc.cssselect("article time")[0]
        el.text = "Unknown date"
        el.set("datetime", "invalid")
    elif failure == "body":
        doc.get_element_by_id("main-content").drop_tree()
    else:
        body = doc.get_element_by_id("main-content")
        body.clear(keep_tail=True)
        body.set("id", "main-content")
    monkeypatch.setattr(dario, "fetch_text", lambda _: html.tostring(doc, encoding="unicode"))
    assert dario._fetch_one(POST_URL) is None


def test_legacy_footnotes_alone_are_not_an_article_body(monkeypatch):
    page = (
        '<h1 class="post-title">Title</h1><div class="post-date">September 2026</div>'
        '<div class="w-richtext cc-footnotes"><p>Only notes</p></div>'
    )
    monkeypatch.setattr(dario, "fetch_text", lambda _: page)
    assert dario._fetch_one(POST_URL) is None


def test_current_nested_footnotes_are_included_once(monkeypatch):
    doc = html.fromstring(PAGES[POST_URL])
    doc.get_element_by_id("main-content").append(
        doc.cssselect('section[aria-labelledby="footnotes"]')[0]
    )
    monkeypatch.setattr(dario, "fetch_text", lambda _: html.tostring(doc, encoding="unicode"))
    item = dario._fetch_one(POST_URL)
    assert item.content_html.count('id="fn:1"') == 1


def test_heading_footnote_does_not_pollute_feed_title(monkeypatch):
    # Mirrors the redesigned Machines of Loving Grace heading.
    doc = html.fromstring(PAGES[POST_URL])
    heading = doc.cssselect("article h1")[0]
    heading.text = "Machines of Loving Grace"
    heading.append(
        html.fromstring(
            '<sup id="title-note"><a href="#fn:1" data-footnote-ref="true">1</a>'
            '<span aria-hidden="true"><sup>1</sup> https://example.com/poem</span></sup>'
        )
    )
    monkeypatch.setattr(dario, "fetch_text", lambda _: html.tostring(doc, encoding="unicode"))
    item = dario._fetch_one(ESSAY_URL)
    assert item.title == "Machines of Loving Grace"
    assert item.content_html.count('id="fn:1"') == 1
    assert "Note text" in item.content_html


def test_sitemap_refresh_keeps_url_guids_and_is_deterministic(monkeypatch):
    sitemap = (
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        + "".join(f"<url><loc>{url}</loc><lastmod>2099-01-01</lastmod></url>" for url in PAGES)
        + f"<url><loc>{POST_URL}</loc></url><url><loc>https://darioamodei.com/</loc></url>"
        + "</urlset>"
    ).encode()
    monkeypatch.setattr(dario, "fetch_bytes", lambda _: sitemap)
    monkeypatch.setattr(dario, "fetch_text", PAGES.__getitem__)
    result = dario.dario_amodei()
    assert result.ok
    assert {item.guid for item in result.items} == set(PAGES)
    spec = next(f for f in FEEDS if f.slug == "dario-amodei")

    def render(items):
        return build_rss(
            title=spec.title,
            link=spec.source_url,
            description=spec.description,
            self_url=spec.url,
            source_url=spec.source_url,
            items=items,
        )

    first = render(result.items)
    assert first == render(dario.dario_amodei().items)
    parsed = feedparser.parse(first)
    assert not parsed.bozo
    assert {entry.id for entry in parsed.entries} == set(PAGES)
    assert all(entry.content[0].value for entry in parsed.entries)


@pytest.mark.parametrize("failure", ["metadata", "fetch"])
def test_one_broken_article_preserves_previous_feed(failure, monkeypatch, tmp_path):
    monkeypatch.setattr(dario, "_article_urls", lambda: list(PAGES))
    monkeypatch.setattr(dario, "fetch_text", PAGES.__getitem__)
    good = dario.dario_amodei()
    sources = {name for spec in FEEDS for name in spec.sources}
    results = dict.fromkeys(sources, SourceResult(error="not under test"))
    results["dario"] = good
    write_feeds(results, tmp_path)
    path = tmp_path / "dario-amodei.xml"
    before = path.read_bytes()

    def fetch(url):
        if url == POST_URL:
            if failure == "fetch":
                raise OSError("upstream unavailable")
            return "<h1>Changed layout</h1>"
        return PAGES[url]

    monkeypatch.setattr(dario, "fetch_text", fetch)
    broken = dario.dario_amodei()
    assert broken.error and not broken.items
    results["dario"] = broken
    status = next(s for s in write_feeds(results, tmp_path) if s.spec.slug == "dario-amodei")
    assert not status.written
    assert status.error
    assert path.read_bytes() == before
