"""Private inbox addresses for email-only newsletters, and the guard that keeps them private.

Some newsletters have no feed at all, so they are delivered by email to a
kill-the-newsletter.com inbox, whose Atom feed this tool reads. That feed URL is also the
inbox address: anyone who knows it can post into the inbox, or read it. So the inbox IDs
are never committed. They come from, in order:

  1. the KTN_FEEDS environment variable (a GitHub Actions secret on CI), or
  2. feeds.local.json in the repo root (gitignored; see feeds.local.example.json),

either way a JSON object mapping a feed slug to its inbox ID.

Everything published passes through `leaks()` before it is written, so an ID, the inbox
URL, or a subscriber token that a newsletter embeds in its links can never reach docs/.
"""

from __future__ import annotations

import json
import os
from functools import cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LOCAL_FILE = ROOT / "feeds.local.json"
ENV_VAR = "KTN_FEEDS"
KTN_HOST = "kill-the-newsletter.com"

# Substrings that must never appear in anything published, whatever the configured IDs.
# Each is something a newsletter or the inbox service writes into an email: any link to
# the inbox service (its settings link carries the address), Scholar Inbox's auto-login key, The Conversation's per-recipient
# click tracker, and Scholar Inbox's tokened unsubscribe link.
FIXED_MARKERS = (
    KTN_HOST,
    "sha_key",
    "clicks.theconversation.com",
    "unsubscribe_digest",
)


class NotConfigured(Exception):
    pass


@cache
def inbox_ids() -> dict[str, str]:
    raw = os.environ.get(ENV_VAR)
    if not raw and LOCAL_FILE.exists():
        raw = LOCAL_FILE.read_text()
    if not raw:
        return {}
    ids = {str(k): str(v).strip() for k, v in json.loads(raw).items() if str(v).strip()}
    if os.environ.get("GITHUB_ACTIONS") == "true":
        # GitHub masks the whole secret, not the IDs inside it, so mask each one.
        for v in ids.values():
            print(f"::add-mask::{v}", flush=True)
    return ids


def inbox_feed_url(slug: str) -> str:
    inbox = inbox_ids().get(slug)
    if not inbox:
        raise NotConfigured(f"no inbox ID for {slug!r}: set {ENV_VAR} or feeds.local.json")
    return f"https://{KTN_HOST}/feeds/{inbox}.xml"


def leaks(text: str) -> list[str]:
    """Names (never values) of the private markers present in `text`."""
    found = [f"inbox ID for {slug}" for slug, v in inbox_ids().items() if v in text]
    return found + [m for m in FIXED_MARKERS if m in text]


def scrub(text: str) -> str:
    """Remove configured IDs from a message bound for a log."""
    for v in inbox_ids().values():
        text = text.replace(v, "<inbox>")
    return text
