# RSS Feeds

Clean, public RSS endpoints for blogs whose own feeds are missing, stale, broken or full of translated duplicates. Currently AI safety research sources; adding another is one entry in the registry. Rebuilt every 8 hours by GitHub Actions and served from GitHub Pages.

Browse the endpoints at **<https://feeds.yulonglin.com/>**. A machine-readable list is at **<https://feeds.yulonglin.com/feeds.json>**.

## The feeds

| Feed | Source | Subscribe to this URL | Items |
|---|---|---|---|
| METR - English only | [METR feed.xml](https://metr.org/) | `https://feeds.yulonglin.com/metr-en.xml` | 89 |
| METR - English only (latest 50) | [METR feed.xml](https://metr.org/) | `https://feeds.yulonglin.com/metr-en-50.xml` | 50 |
| METR - English only (headlines and summaries) | [METR feed.xml](https://metr.org/) | `https://feeds.yulonglin.com/metr-en-lite.xml` | 89 |
| OpenAI Alignment - everything | [Alignment Research Blog (all sections)](https://alignment.openai.com/) | `https://feeds.yulonglin.com/openai-alignment-all.xml` | 36 |
| OpenAI Alignment - everything (latest 50) | [Alignment Research Blog (all sections)](https://alignment.openai.com/) | `https://feeds.yulonglin.com/openai-alignment-all-50.xml` | 36 |
| OpenAI Alignment - Misalignment Notices | [Misalignment Notices](https://alignment.openai.com/misalignment-reports/) | `https://feeds.yulonglin.com/openai-alignment-notices.xml` | 3 |
| OpenAI Alignment - Misalignment Reports | [Misalignment Reports](https://alignment.openai.com/misalignment-reports/) | `https://feeds.yulonglin.com/openai-alignment-reports.xml` | 6 |
| OpenAI Alignment - Research and Releases | [Research and Releases](https://alignment.openai.com/) | `https://feeds.yulonglin.com/openai-alignment-research.xml` | 27 |
| OpenAI System Cards | [Deployment Safety Hub](https://deploymentsafety.openai.com/) | `https://feeds.yulonglin.com/openai-system-cards.xml` | 24 |

## Why each feed exists

| Source | Its own feed | What was wrong with it |
|---|---|---|
| OpenAI, Research and Releases | `alignment.openai.com/rss.xml` | Valid, but last built 2026-07-21 and missing every post hosted on openai.com proper. |
| OpenAI, Misalignment Notices | none | No feed published at all. |
| OpenAI, Misalignment Reports | none | No feed published at all, and no dates in the markup. |
| OpenAI, System Cards | `deploymentsafety.openai.com/posts.xml` | A broken dev build: 255 bytes, zero items, `<link>` of `http://localhost:4321/`. |
| METR | `metr.org/feed.xml` | Valid, but ~8.9 MB and interleaved with `/es/` and `/zh-Hans/` duplicates of English posts. |

## Things worth knowing

- **Misalignment Reports carry no publication date.** Nothing in the page markup gives one. Each report is dated the day this generator first saw it, recorded in `state/first_seen.json` and committed, so entries do not resurface as new at every refresh.
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
