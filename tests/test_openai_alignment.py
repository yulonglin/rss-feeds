from datetime import date
from pathlib import Path

import feedparser
import pytest
from lxml import html

from rssfeeds.build import write_feeds
from rssfeeds.registry import FEEDS
from rssfeeds.sources import openai_alignment as oai
from rssfeeds.state import FirstSeen

PAGE = (Path(__file__).parent / "fixtures/openai_alignment_tables.html").read_text()
DOCS = Path(__file__).resolve().parents[1] / "docs"


def test_current_tables(monkeypatch, tmp_path):
    monkeypatch.setattr(oai, "fetch_text", lambda _: PAGE)
    notices = oai.notices()
    reports = oai.reports(FirstSeen(tmp_path / "dates.json"))
    assert notices.ok and reports.ok
    assert len(notices.items) == 3
    assert len(reports.items) == 12
    n = notices.items[0]
    assert n.title == "RubyGems"
    assert n.guid == oai.REPORTS_URL + "#notice-rubygems"
    assert (
        n.link
        == "https://openai.com/hugging-face-incident-and-misalignment/#model-misalignment-2026-09-11"
    )
    assert n.published.date() == date(2026, 9, 11)  # not May activity date
    assert n.description.startswith("We are investigating a report")
    assert n.categories == ["Misalignment Notice"]
    r = reports.items[0]
    assert r.title == "An agent used DNS to reach an external chatbot"
    assert r.link == oai.REPORTS_URL + "an-agent-used-dns-to-reach-an-external-chatbot/"
    assert r.guid == r.link
    assert r.published.date() == date(2026, 9, 25)  # not Sept 20 incident date
    assert "insufficient DNS filtering" in r.description
    assert "\n\nInternal research model · RL training\n\nUnauthorized access" in r.description
    assert r.categories == ["Misalignment Report"]


@pytest.mark.parametrize("source", ["notices", "reports"])
def test_existing_identities_and_dates_survive_redesign(source, monkeypatch):
    monkeypatch.setattr(oai, "fetch_text", lambda _: PAGE)
    result = (
        oai.notices()
        if source == "notices"
        else oai.reports(FirstSeen(DOCS.parent / "state/first_seen.json"))
    )
    previous = feedparser.parse((DOCS / f"openai-alignment-{source}.xml").read_bytes())
    expected = {e.id: (e.link, e.published_parsed[:3]) for e in previous.entries}
    actual = {
        i.guid: (i.link, (i.published.year, i.published.month, i.published.day))
        for i in result.items
    }
    assert actual == {guid: expected[guid] for guid in actual}


def test_first_posted_not_incident_or_updated_and_stable_on_rerun(monkeypatch, tmp_path):
    page = PAGE.replace(
        'data-label="Last updated"><time datetime="2026-09-25"',
        'data-label="Last updated"><time datetime="2026-10-05"',
    )
    monkeypatch.setattr(oai, "fetch_text", lambda _: page)
    path = tmp_path / "dates.json"
    fs = FirstSeen(path)
    first = oai.reports(fs).items[0]
    assert first.published.date() == date(2026, 9, 25)
    fs.save()
    page = page.replace(
        'data-label="First posted"><time datetime="2026-09-25"',
        'data-label="First posted"><time datetime="2026-10-06"',
    )
    assert oai.reports(FirstSeen(path)).items[0].published == first.published


@pytest.mark.parametrize("source", ["notices", "reports"])
@pytest.mark.parametrize("failure", ["layout", "title", "date", "fetch"])
def test_source_failure_keeps_standalone_and_combined_feeds(source, failure, monkeypatch, tmp_path):
    doc = html.fromstring(PAGE)
    table = doc.get_element_by_id("notice-entries" if source == "notices" else "report-entries")
    if failure == "layout":
        table.set("id", "changed-layout")
    elif failure == "title":
        table.cssselect("a.report-title")[0].drop_tree()
    elif failure == "date":
        table.cssselect('td[data-label="First posted"] time')[0].set("datetime", "invalid")

    def fetch(_):
        if failure == "fetch":
            raise OSError("upstream unavailable")
        return html.tostring(doc, encoding="unicode")

    monkeypatch.setattr(oai, "fetch_text", fetch)
    broken = oai.notices() if source == "notices" else oai.reports(FirstSeen(tmp_path / "s.json"))
    assert broken.error and not broken.items
    monkeypatch.setattr(oai, "fetch_text", lambda _: PAGE)
    good = oai.notices()
    results = dict.fromkeys({n for f in FEEDS for n in f.sources}, good)
    before = {}
    for spec in FEEDS:
        content = (DOCS / spec.filename).read_bytes()
        (tmp_path / spec.filename).write_bytes(content)
        before[spec.filename] = content
    results[source] = broken
    statuses = write_feeds(results, tmp_path)
    affected = [s for s in statuses if source in s.spec.sources]
    assert len(affected) == 3  # standalone plus both combined variants
    for status in affected:
        assert not status.written and status.error
        assert (tmp_path / status.spec.filename).read_bytes() == before[status.spec.filename]
    assert next(s for s in statuses if s.spec.slug == "dario-amodei").written


def _migrated_page(items, *, report_index=False, counts=None):
    """Minimal equivalent of the public HTML payload, with Load more rows off-DOM."""
    import json

    field = "type" if report_index else "topic"
    props = {"searchable": True, "items": items, "filters": [{"field": field}]}
    if report_index:
        props["sortByReportDate"] = True
    row = "abc:" + json.dumps(["$", "$L9", None, props]) + "\n"
    cut = len(row) // 2  # RSC transport is allowed to split a JSON row
    chunks = "".join(
        f"<script>self.__next_f.push({json.dumps([1, part])})</script>"
        for part in (row[:cut], row[cut:])
    )
    if report_index:
        badges = "".join(
            f'<a href="#{group}">{group}<span>{count}</span></a>'
            for group, count in (counts or {"notices": 1, "reports": 2}).items()
        )
    else:
        badges = f'<p role="status">{counts if counts is not None else len(items)} results</p>'
    return f"<html>{badges}<ul><li>Only one initial row</li></ul>{chunks}</html>"


def test_migrated_research_load_more_preserves_ids(monkeypatch):
    rows = [
        {
            "title": "Research item",
            "href": "/safety-alignment/hello-world/",
            "date": "2025-12-01",
        },
        {
            "title": "Publisher entry",
            "href": "https://openai.com/index/example/",
            "date": "2026-11-20",
            "description": "Description",
        },
    ]

    def fetch(url):
        assert url == oai.ALIGNMENT_URL
        return _migrated_page(rows)

    monkeypatch.setattr(oai, "fetch_text", fetch)
    r = oai.research()
    assert r.ok and len(r.items) == 2
    assert r.items[0].guid == "https://alignment.openai.com/hello-world/"
    assert r.items[0].link == "https://openai.com/safety-alignment/hello-world/"
    assert r.items[0].published.date() == date(2025, 12, 1)
    assert r.items[1].guid == r.items[1].link == rows[1]["href"]
    assert r.items[1].description == "Description"
    assert r.items[1].categories == ["Research and Releases"]


def _migrated_report_rows():
    return [
        {
            "title": "An existing report",
            "href": "/safety-alignment/misalignment-reports/old/",
            "date": "2026-11-20",
            "reportDates": {"lastUpdated": "2026-11-20"},
            "filters": {"type": ["reports"]},
        },
        {
            "title": "A new report",
            "href": "/safety-alignment/misalignment-reports/new/",
            "date": "2026-11-20",
            "reportDates": {"firstPosted": "2026-11-19", "lastUpdated": "2026-11-20"},
            "filters": {"type": ["reports"]},
        },
        {
            "title": "RubyGems",
            "href": "https://openai.com/hugging-face-incident-and-misalignment/"
            "#model-misalignment-2026-09-11",
            "date": "2026-09-11",
            "reportDates": {"firstPosted": "2026-09-11"},
            "filters": {"type": ["notices"]},
        },
    ]


def test_migrated_reports_and_notices_use_stable_dates_and_guids(monkeypatch, tmp_path):
    rows = _migrated_report_rows()

    def fetch(url):
        assert url == oai.MISALIGNMENT_URL
        return _migrated_page(rows, report_index=True)

    monkeypatch.setattr(oai, "fetch_text", fetch)
    state = tmp_path / "dates.json"
    state.write_text('{"https://alignment.openai.com/misalignment-reports/old/": "2026-09-17"}')
    first_seen = FirstSeen(state)
    reports = oai.reports(first_seen)
    notices = oai.notices()
    assert reports.ok and len(reports.items) == 2
    assert notices.ok and len(notices.items) == 1
    old, new = reports.items
    assert old.guid == oai.REPORTS_URL + "old/"
    assert old.link == oai.MISALIGNMENT_URL + "old/"
    assert old.published.date() == date(2026, 9, 17)
    assert new.published.date() == date(2026, 11, 19)
    assert new.categories == ["Misalignment Report"]
    n = notices.items[0]
    assert n.guid == oai.REPORTS_URL + "#notice-rubygems"
    assert n.link == rows[-1]["href"]
    assert n.published.date() == date(2026, 9, 11)
    assert n.categories == ["Misalignment Notice"]
    first_seen.save()
    rows[1]["reportDates"]["firstPosted"] = "2026-11-21"
    assert oai.reports(FirstSeen(state)).items == reports.items


@pytest.mark.parametrize("problem", ["truncated", "duplicate", "missing-date"])
def test_migrated_reports_fail_closed_without_recording_dates(monkeypatch, tmp_path, problem):
    rows = _migrated_report_rows()
    rows[0]["reportDates"]["firstPosted"] = "2026-11-17"
    if problem == "truncated":
        rows.pop(1)
    elif problem == "duplicate":
        rows[1]["href"] = rows[0]["href"]
    else:
        del rows[1]["reportDates"]["firstPosted"]
    monkeypatch.setattr(oai, "fetch_text", lambda _: _migrated_page(rows, report_index=True))
    state = tmp_path / "dates.json"
    first_seen = FirstSeen(state)
    result = oai.reports(first_seen)
    assert result.error and not result.items
    first_seen.save()
    assert state.read_text() == "{}\n"


def test_migrated_research_rejects_payload_shorter_than_advertised(monkeypatch):
    rows = [{"title": "A", "href": "/index/a/", "date": "2026-11-20"}]
    monkeypatch.setattr(oai, "fetch_text", lambda _: _migrated_page(rows, counts=2))
    result = oai.research()
    assert result.error and "incomplete" in result.error
    assert not result.items
