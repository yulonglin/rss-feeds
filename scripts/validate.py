"""Check every published feed is well-formed and parses as RSS in a real reader library."""

from __future__ import annotations

import sys
from pathlib import Path

import feedparser

from rssfeeds.registry import FEEDS

FEEDS_DIR = Path(__file__).resolve().parents[1] / "docs"


def main() -> int:
    paths = sorted(FEEDS_DIR.glob("*.xml"))
    if not paths:
        print("no feeds found", file=sys.stderr)
        return 1

    # A newsletter inbox that has not received its first issue publishes an empty feed.
    may_be_empty = {f.filename for f in FEEDS if f.allow_empty}
    failures = 0
    for p in paths:
        parsed = feedparser.parse(p.read_bytes())
        entries = len(parsed.entries)
        if parsed.bozo or (entries == 0 and p.name not in may_be_empty):
            reason = parsed.get("bozo_exception", "zero entries")
            print(f"FAIL {p.name}: {reason}", file=sys.stderr)
            failures += 1
        else:
            size_kb = p.stat().st_size / 1024
            print(f"ok   {p.name:<32} {entries:>4} entries  {size_kb:>8.1f} KB")

    if failures:
        print(f"\n{failures} feed(s) failed validation", file=sys.stderr)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
