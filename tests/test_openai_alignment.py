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
