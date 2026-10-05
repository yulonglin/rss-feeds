"""AI Digest (theaidigest.org) email updates - held back, publishing nothing yet.

Email-only, arriving in a kill-the-newsletter inbox. No issue had arrived when this was
written, so there is no real email to build an allowlist of links and images from, and
a general cleaner that keeps unknown links could publish a per-subscriber link from a
confirmation or account email. Until a real issue has been inspected and saved as a
redacted fixture, this source reads the inbox (so a missing or broken inbox still shows
up as a failure) and publishes an empty feed at the stable URL.

To enable it: save a redacted issue under tests/, write a renderer that rebuilds links
and images through `newsletter_email.allowlist` the way the_conversation does, and drop
account messages with `is_account_message`.
"""

from __future__ import annotations

import sys

from ..models import SourceResult
from ..newsletter_email import InboxError, fetch_inbox, is_account_message

SLUG = "ai-digest"
SITE = "https://theaidigest.org/"


def ai_digest() -> SourceResult:
    try:
        emails = fetch_inbox(SLUG)
    except InboxError as exc:
        return SourceResult(error=str(exc))
    issues = [e for e in emails if not is_account_message(e)]
    if issues:
        print(
            f"ai-digest: {len(issues)} issue(s) held back until the format has been reviewed",
            file=sys.stderr,
        )
    return SourceResult(items=[])
