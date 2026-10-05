"""Private inbox addresses for email-only newsletters, and the guard that keeps them private.

Some newsletters have no feed at all, so they are delivered by email to a
kill-the-newsletter.com inbox, whose Atom feed this tool reads. That feed URL is also the
inbox address: anyone who knows it can post into the inbox, or read it. So the inbox IDs
are never committed. They come from, in order:

  1. the KTN_FEEDS environment variable (a GitHub Actions secret on CI), or
  2. feeds.local.json in the repo root (gitignored; see feeds.local.example.json),

either way a JSON object mapping a feed slug to its inbox ID. The config is parsed and
validated once into an `InboxConfig`; a malformed one fails only the email sources.

Everything published - every feed, feeds.json, the OPML files, index.html, the README
and the state files - passes through `leaks()` before it is written, so an inbox ID, a
link to the inbox service, or a subscriber token a newsletter embeds in a link can never
reach the repository. `leaks()` and `scrub()` never raise.
"""

from __future__ import annotations

import html
import json
import os
import re
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path
from urllib.parse import parse_qsl, urlsplit

ROOT = Path(__file__).resolve().parents[2]
LOCAL_FILE = ROOT / "feeds.local.json"
ENV_VAR = "KTN_FEEDS"
KTN_HOST = "kill-the-newsletter.com"

# Substrings that must never appear in anything published, whatever the configured IDs:
# any link to the inbox service (its settings link carries the address), Scholar Inbox's
# auto-login key, The Conversation's per-recipient click tracker, and Scholar Inbox's
# tokened unsubscribe link.
FIXED_MARKERS = (
    KTN_HOST,
    "sha_key",
    "clicks.theconversation.com",
    "unsubscribe_digest",
)

# Query parameters that carry identity or credentials by name, whatever their value.
SENSITIVE_PARAMS = {
    "token",
    "access_token",
    "auth",
    "key",
    "api_key",
    "apikey",
    "sig",
    "signature",
    "secret",
    "uid",
    "userid",
    "user_id",
    "email",
    "mail",
    "session",
    "sessionid",
    "sid",
    "otp",
    "login",
    "subscriber",
    "subscriber_id",
    "recipient",
}
_SENSITIVE_SUFFIXES = ("token", "_key", "secret", "_sig", "_uid", "_email")
_ID_SHAPE = re.compile(r"[A-Za-z0-9_-]{8,64}")
_URL = re.compile(r"https?://[^\s\"'<>]+")
_RANDOM = re.compile(r"[A-Za-z0-9_\-.~]{24,}")


class NotConfigured(Exception):
    pass


class LeakError(ValueError):
    """Raised instead of writing text that `leaks()` flags. The message holds names only."""


@dataclass(frozen=True)
class InboxConfig:
    ids: dict[str, str] = field(default_factory=dict)
    # Safe to log: names the source and the problem, never a value.
    error: str | None = None
    # Strings that look like inbox IDs in a config too malformed to parse; still guarded.
    suspects: tuple[str, ...] = ()

    @property
    def secrets(self) -> tuple[str, ...]:
        return (*self.ids.values(), *self.suspects)


def parse_config(raw: str, source: str) -> InboxConfig:
    """Validate a KTN_FEEDS-shaped string. Never raises; never echoes a value."""
    # Anything ID-shaped in the raw text is guarded even if the whole thing is malformed.
    suspects = tuple(
        s
        for s in re.findall(r"[A-Za-z0-9]{16,64}", raw)
        if re.search(r"\d", s) and re.search(r"[a-z]", s, re.IGNORECASE)
    )

    def bad(problem: str) -> InboxConfig:
        return InboxConfig(error=f"{source} {problem}", suspects=suspects)

    try:
        data = json.loads(raw)
    except ValueError:
        return bad("is not valid JSON")
    if not isinstance(data, dict):
        return bad("must be a JSON object mapping feed slug to inbox ID")
    wrong = sorted(
        str(k) for k, v in data.items() if not isinstance(v, str) or not _ID_SHAPE.fullmatch(v)
    )
    if wrong:
        return bad(f"has a missing or malformed inbox ID for {wrong}")
    return InboxConfig(ids=dict(data), suspects=suspects)


@cache
def config() -> InboxConfig:
    raw = os.environ.get(ENV_VAR)
    source = ENV_VAR
    if not raw:
        source = LOCAL_FILE.name
        try:
            raw = LOCAL_FILE.read_text() if LOCAL_FILE.exists() else ""
        except OSError:
            return InboxConfig(error=f"{source} could not be read")
    cfg = parse_config(raw, source) if raw and raw.strip() else InboxConfig()
    if os.environ.get("GITHUB_ACTIONS") == "true":
        # GitHub masks the whole secret, not the IDs inside it, so mask each one.
        for v in cfg.secrets:
            print(f"::add-mask::{v}", flush=True)
    return cfg


def inbox_feed_url(slug: str) -> str:
    cfg = config()
    if cfg.error:
        raise NotConfigured(cfg.error)
    inbox = cfg.ids.get(slug)
    if not inbox:
        raise NotConfigured(f"no inbox ID for {slug!r}: set {ENV_VAR} or feeds.local.json")
    return f"https://{KTN_HOST}/feeds/{inbox}.xml"


def _token_params(text: str) -> list[str]:
    found = []
    for url in _URL.findall(html.unescape(text)):
        try:
            parts = urlsplit(url)
        except ValueError:  # e.g. a malformed IPv6 host; not ours to judge
            continue
        query = parts.query
        if "?" in parts.fragment:
            query += "&" + parts.fragment.partition("?")[2]
        for key, value in parse_qsl(query, keep_blank_values=True):
            k = key.lower()
            if k in SENSITIVE_PARAMS or k.endswith(_SENSITIVE_SUFFIXES):
                found.append(f"sensitive query parameter {key!r}")
            elif (
                _RANDOM.fullmatch(value)
                and re.search(r"\d", value)
                and re.search(r"[A-Za-z]", value)
            ):
                found.append(f"token-like value in query parameter {key!r}")
    return found


def leaks(text: str, *, tokens: bool = True) -> list[str]:
    """Names (never values) of the private markers present in `text`. Never raises.

    `tokens` also flags token-like query parameters. It is on for everything this tool
    writes about itself and for feeds built from Yulong's own inboxes, where any token
    would be his; it is off for public publishers' feeds, whose own links legitimately
    carry share and tracking parameters that are theirs, not a subscriber's.
    """
    try:
        cfg = config()
        found = ["an inbox ID" for v in cfg.secrets if v and v in text]
        found += [m for m in FIXED_MARKERS if m in text]
        if tokens:
            found += _token_params(text)
        return sorted(set(found))
    except Exception as exc:  # noqa: BLE001 - a guard that crashes would block every feed
        return [f"leak check failed ({type(exc).__name__})"]


def ensure_clean(text: str, what: str) -> str:
    """Return `text` if it is safe to write; raise LeakError naming what was found."""
    found = leaks(text)
    if found:
        raise LeakError(f"refusing to write {what}: contains {found}")
    return text


def scrub(text: str) -> str:
    """Remove configured or suspected IDs from a message bound for a log. Never raises."""
    try:
        for v in config().secrets:
            text = text.replace(v, "<inbox>")
        return text
    except Exception:  # noqa: BLE001
        return "<message withheld: scrub failed>"
