from __future__ import annotations

import httpx

USER_AGENT = (
    "rss-feeds/0.1 (+https://github.com/yulonglin/rss-feeds) "
    "personal RSS mirror; contact via GitHub issues"
)

TIMEOUT = httpx.Timeout(60.0, connect=20.0)


def fetch_text(url: str) -> str:
    r = httpx.get(url, timeout=TIMEOUT, follow_redirects=True, headers={"User-Agent": USER_AGENT})
    r.raise_for_status()
    return r.text


def fetch_bytes(url: str) -> bytes:
    r = httpx.get(url, timeout=TIMEOUT, follow_redirects=True, headers={"User-Agent": USER_AGENT})
    r.raise_for_status()
    return r.content
