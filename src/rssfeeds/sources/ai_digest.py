"""AI Digest (theaidigest.org) email updates.

Email-only, arriving in a kill-the-newsletter inbox. No issue had arrived when this was
written, so the cleaning is the general one: the email is flattened to paragraphs,
headings, lists and images; styling, tracking pixels and the hidden preheader go; utm
parameters are stripped; links to unsubscribe, preference or view-in-browser pages,
and click-tracking redirects, are unlinked; and the footer is cut. Revisit once real
issues arrive and their shape is known.
"""

from __future__ import annotations

from urllib.parse import urlsplit

from ..models import Item, SourceResult
from ..newsletter_email import InboxError, cut_at, fetch_inbox, linearize, text_of

SLUG = "ai-digest"
SITE = "https://theaidigest.org/"

FOOTER = ("unsubscribe", "you are receiving this", "you're receiving this", "manage your")
_PRIVATE_LINK_WORDS = ("unsubscribe", "preferences", "manage", "view in browser", "view online")
_TRACKER_HOSTS = ("click.", "clicks.", "track.", "links.", "email.", "pm-bounces.", "list-manage")


def link(href: str, text: str) -> str | None:
    """Keep ordinary web links; drop anything personal to the subscriber."""
    if not href.startswith(("http://", "https://")):
        return None
    host = urlsplit(href).netloc.lower()
    if host.startswith(_TRACKER_HOSTS) or any(t in host for t in _TRACKER_HOSTS[-1:]):
        return None
    lowered = f"{href} {text}".lower()
    if any(w in lowered for w in _PRIVATE_LINK_WORDS):
        return None
    return href


def ai_digest() -> SourceResult:
    try:
        emails = fetch_inbox(SLUG)
    except InboxError as exc:
        return SourceResult(error=str(exc))
    items = []
    for e in emails:
        blocks = cut_at(linearize(e.html, link=link), FOOTER)
        if not blocks:
            continue
        first = next((text_of(b) for b in blocks if text_of(b)), "")
        items.append(
            Item(
                title=e.subject or "AI Digest",
                link=SITE,
                guid=e.guid(SLUG),
                published=e.received,
                description=first[:300],
                content_html="\n".join(blocks),
                author="AI Digest",
                categories=["Newsletter"],
            )
        )
    return SourceResult(items=items)
