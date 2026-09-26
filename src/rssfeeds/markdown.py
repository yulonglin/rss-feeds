"""Markdown rendering for the repo README and the Obsidian vault copy.

Both come from the same registry as the XML and the index page, so the list of endpoints
cannot drift between where it is published and where it is documented.
"""

from __future__ import annotations

from pathlib import Path

from .build import FeedStatus
from .registry import REPO_URL, SITE_BASE

INTRO = """# RSS Feeds

Clean, public RSS endpoints for blogs whose own feeds are missing, stale, broken or full of translated duplicates. Currently AI safety research sources; adding another is one entry in the registry. Rebuilt every 8 hours by GitHub Actions and served from GitHub Pages.

Browse the endpoints at **<{site}>**. A machine-readable list is at **<{site}feeds.json>**.
"""

WHY = """## Why each feed exists

| Source | Its own feed | What was wrong with it |
|---|---|---|
| OpenAI, Research and Releases | `alignment.openai.com/rss.xml` | Valid, but last built 2026-07-21 and missing every post hosted on openai.com proper. |
| OpenAI, Misalignment Notices | none | No feed published at all. |
| OpenAI, Misalignment Reports | none | No feed published at all, and only a last-updated date in the markup. |
| OpenAI, System Cards | `deploymentsafety.openai.com/posts.xml` | A broken dev build: 255 bytes, zero items, `<link>` of `http://localhost:4321/`. |
| METR | `metr.org/feed.xml` | Valid, but ~8.9 MB and interleaved with `/es/` and `/zh-Hans/` duplicates of English posts. |
| TLDR AI | `tldr.tech/api/rss/ai` | Headline and link only: none of the issue's stories or summaries. |
| Tangle | `readtangle.com/rss/` | Complete, but most of each daily edition and many of the entries are packaging around the one section worth reading. |
"""

NOTES = """## Things worth knowing

- **Misalignment Reports are dated when first seen, not when last updated.** The page shows only a last-updated date, and dating by it would push a report back to the top of the feed every time it is edited. Each report keeps the date this generator first saw it (the page's date, for reports seen since that date appeared), recorded in `state/first_seen.json` and committed.
- **System cards follow OpenAI's own index, not their sitemap.** The sitemap lists two further pages (`/gpt-5-codex/`, `/o3/`) that OpenAI's listing omits, and carries no dates at all. Matching the listing keeps the feed to what the publisher actually presents as current.
- **A layout change is caught two ways.** Each scraper is pinned to specific selectors, so a page that no longer matches them yields zero entries and fails loudly. A page that still matches but returns far fewer entries than the last published run is refused too, at a 60% floor, because a silently truncated feed looks normal and is therefore worse than an outright failure. Either case opens a `feed-broken` issue on the repository and reddens the scheduled run. If a drop is genuine, `uv run rssfeeds --allow-shrink` accepts it.
- **A source that fails leaves its feed alone.** If METR is unreachable the five OpenAI feeds still refresh; the workflow run goes red and the stale feed keeps its last good contents rather than emptying.
- **`lastBuildDate` comes from the newest item, never the clock.** A run that finds nothing new produces byte-identical files and therefore no commit, which keeps the git history meaningful.
- **Non-English filtering matches the shape of a locale segment**, not a fixed list, so a language METR adds later is dropped without a code change.
- **GitHub disables scheduled workflows after 60 days of repository inactivity.** Each successful refresh commits, which resets that counter; a long stretch with no new posts anywhere is the one way this could quietly stop.

## Running it locally

```
uv run rssfeeds
uv run --with feedparser python scripts/validate.py
```

Content belongs to its publishers. This repository only reformats what they already publish openly.
"""


SETUP = """## DNS setup this needs

The feeds are already built, committed and served. The only outstanding step is pointing the domain at them.

- In Cloudflare DNS for yulonglin.com, add a **CNAME** record: name `feeds`, target `yulonglin.github.io`.
- Set it to **DNS only** (grey cloud, not proxied). GitHub provisions the HTTPS certificate itself, and Cloudflare's proxy can block that validation. You can switch the proxy on later once the certificate has issued.
- GitHub Pages already has `feeds.yulonglin.com` recorded as the custom domain, so nothing is needed on that side.
- That record is also declared in the [dns repo](https://github.com/yulonglin/dns), which reconciles it into Cloudflare once a `CLOUDFLARE_API_TOKEN` secret exists there. Adding it by hand now is faster and the reconciler will simply find it already correct.
- **Until that record exists the endpoints are down.** Setting the custom domain makes GitHub Pages 301 every `yulonglin.github.io/rss-feeds/` URL to `feeds.yulonglin.com`, which does not resolve yet, so there is no working address in the meantime. Adding the CNAME fixes it with no further action; certificate issuance then takes a few minutes.
"""


def render_table(statuses: list[FeedStatus]) -> str:
    rows = ["| Feed | Source | Subscribe to this URL | Items |", "|---|---|---|---|"]
    for s in sorted(statuses, key=lambda s: (s.spec.org, s.spec.slug)):
        sp = s.spec
        rows.append(
            f"| {sp.title} | [{sp.source_name}]({sp.source_url}) | `{sp.url}` | {s.item_count} |"
        )
    return "\n".join(rows)


def render_readme(statuses: list[FeedStatus]) -> str:
    return (
        INTRO.format(site=SITE_BASE)
        + "\n## The feeds\n\n"
        + render_table(statuses)
        + "\n\n"
        + WHY
        + "\n"
        + NOTES
    )


def render_vault_doc(statuses: list[FeedStatus]) -> str:
    return (
        "# RSS Feeds\n\n"
        f"Public RSS endpoints I maintain for blogs that lack usable feeds, currently AI safety research. "
        f"Paste any URL below into NetNewsWire or Feedly. Rebuilt every 8 hours.\n\n"
        f"- Endpoint list (web page): {SITE_BASE}\n"
        f"- Machine-readable list: {SITE_BASE}feeds.json\n"
        f"- Source repository: {REPO_URL}\n\n"
        "## The feeds\n\n"
        + render_table(statuses)
        + "\n\n"
        + WHY
        + "\n"
        + SETUP
        + "\n"
        + NOTES.split("## Running it locally")[0].rstrip()
        + "\n\nGenerated from the repository registry; edit the repo, not this file.\n"
    )


def write_if_changed(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists() or path.read_text() != text:
        path.write_text(text)
