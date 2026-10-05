"""Scholar Inbox daily paper digests, rebuilt as a plain list of papers.

Scholar Inbox is email-only and arrives in a kill-the-newsletter inbox. The email is a
stack of styled table "cards", and every link in it is an auto-login link carrying the
subscriber's secret key (the email itself says not to share it), as is the unsubscribe
link. So nothing from the email's markup is republished: each digest is rebuilt from an
allowlist of fields per paper (relevance score, venue and date, title, authors), and
each title links to a public title search instead (arXiv for arXiv papers, Google
Scholar otherwise). The subject line's "02/10" is ambiguous between day and month, so
items are retitled with the full date and the paper count.
"""

from __future__ import annotations

import html
import re
from urllib.parse import quote_plus

from lxml import html as lx

from ..models import Item, SourceResult
from ..newsletter_email import (
    Email,
    InboxError,
    allowlist,
    fetch_inbox,
    is_account_message,
    keep_params,
)

SLUG = "scholar-inbox"
SITE = "https://www.scholar-inbox.com/"
_COUNT = re.compile(r"We found (\d[\d,]*) articles relevant to you \(of (\d[\d,]*) total\)")


def _text(el) -> str:
    return " ".join(el.text_content().split()) if el is not None else ""


def _search_url(title: str, venue: str) -> str:
    if venue.lower().startswith("arxiv"):
        return f"https://arxiv.org/search/?query={quote_plus(title)}&searchtype=title"
    return f"https://scholar.google.com/scholar?q={quote_plus(chr(34) + title + chr(34))}"


def parse_digest(email_html: str) -> tuple[list[dict[str, str]], str]:
    """Papers in the digest, and its "N relevant of M" line (or "")."""
    doc = lx.document_fromstring(email_html)
    papers = []
    for a in doc.iter("a"):
        href = a.get("href") or ""
        if "paper_id=" not in href or "tab=" in href:
            continue
        title = _text(a)
        card = a.getparent().getparent() if a.getparent() is not None else None
        if not title or card is None:
            continue
        badges = [_text(s) for s in card.cssselect("table span")]
        authors_p = a.getparent().getnext()
        while authors_p is not None and not isinstance(authors_p.tag, str):  # <!-- Authors -->
            authors_p = authors_p.getnext()
        papers.append(
            {
                "title": title,
                "score": badges[0] if badges and badges[0].isdigit() else "",
                "venue": badges[1] if len(badges) > 1 else "",
                "authors": _text(authors_p) if authors_p is not None else "",
            }
        )
    m = _COUNT.search(_text(doc))
    summary = f"Matched {m.group(1)} of {m.group(2)} new papers" if m else ""
    return papers, summary


def _public_search(url: str) -> str | None:
    """Only the title searches this module builds, with only their own parameters."""
    if url.startswith("https://arxiv.org/search/?"):
        return keep_params(url, frozenset({"query", "searchtype"}))
    if url.startswith("https://scholar.google.com/scholar?"):
        return keep_params(url, frozenset({"q"}))
    return None


def render(papers: list[dict[str, str]], summary: str) -> str:
    lede = f"{summary}; the top {len(papers)} are below." if summary else ""
    out = [f"<p>{html.escape(lede)}</p>"] if lede else []
    out.append("<ol>")
    for p in papers:
        meta = " · ".join(
            x for x in (p["venue"], f"relevance {p['score']}" if p["score"] else "") if x
        )
        url = html.escape(_search_url(p["title"], p["venue"]), quote=True)
        out.append(
            f'<li><p><a href="{url}"><strong>{html.escape(p["title"])}</strong></a><br>'
            f"{html.escape(p['authors'])}<br><small>{html.escape(meta)}</small></p></li>"
        )
    out.append("</ol>")
    return allowlist("\n".join(out), link=_public_search, image=lambda _url: None)


def to_item(email: Email) -> Item | None:
    if is_account_message(email):
        return None  # sign-in links, confirmations: personal, never published
    papers, summary = parse_digest(email.html)
    if not papers:
        return None
    day = email.received.strftime("%-d %b %Y")
    return Item(
        title=f"Scholar Inbox, {day}: {len(papers)} papers",
        link=SITE,
        guid=email.guid(SLUG),
        published=email.received,
        description="\n".join(f"• {p['title']}" for p in papers),
        content_html=render(papers, summary),
        author="Scholar Inbox",
        categories=["Paper digest"],
    )


def scholar_inbox() -> SourceResult:
    try:
        emails = fetch_inbox(SLUG)
    except InboxError as exc:
        return SourceResult(error=str(exc))
    items = [i for i in map(to_item, emails) if i is not None]
    if emails and not items:
        return SourceResult(error="no digest had any paper cards - email layout may have changed")
    return SourceResult(items=items)
