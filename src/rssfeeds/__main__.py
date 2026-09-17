from __future__ import annotations

import sys
from pathlib import Path

import cyclopts

from .build import collect, write_feeds, write_manifest
from .markdown import render_readme, render_vault_doc, write_if_changed
from .page import write_index
from .state import FirstSeen

app = cyclopts.App(name="rssfeeds", help="Rebuild the public AI safety RSS endpoints.")

ROOT = Path(__file__).resolve().parents[2]


@app.default
def build(
    *,
    docs: Path = ROOT / "docs",
    state: Path = ROOT / "state" / "first_seen.json",
    readme: Path = ROOT / "README.md",
    vault: Path | None = None,
    allow_shrink: bool = False,
) -> None:
    """Fetch every source, rewrite the feeds that succeeded, and regenerate the index.

    A source that fails leaves its existing XML untouched and the command exits 1, so the
    scheduled run goes red while the healthy feeds still publish.
    """
    first_seen = FirstSeen(state)
    results = collect(first_seen)
    first_seen.save()

    statuses = write_feeds(results, docs, allow_shrink=allow_shrink)
    write_manifest(statuses, docs / "feeds.json")
    write_index(statuses, docs / "index.html")
    write_if_changed(readme, render_readme(statuses))
    if vault is not None:
        write_if_changed(vault, render_vault_doc(statuses))

    failed = []
    for s in statuses:
        mark = "ok  " if s.error is None else "FAIL"
        detail = f" ({s.error})" if s.error else ""
        newest = s.newest.date().isoformat() if s.newest else "-"
        print(f"{mark} {s.spec.slug:<28} {s.item_count:>4} items  newest {newest}{detail}")
        if s.error:
            failed.append(s.spec.slug)

    if failed:
        print(
            f"\n{len(failed)} feed(s) could not be refreshed: {', '.join(failed)}", file=sys.stderr
        )
        raise SystemExit(1)
    print(f"\nAll {len(statuses)} feeds refreshed.")


if __name__ == "__main__":
    app()
