"""The single definition of what this site publishes.

Everything downstream - the XML files, docs/index.html, docs/feeds.json, the repo README
and the vault copy - is generated from this list, so the three can't drift apart.
"""

from __future__ import annotations

from dataclasses import dataclass, field

SITE_BASE = "https://yulonglin.github.io/ai-safety-feeds/"
REPO_URL = "https://github.com/yulonglin/ai-safety-feeds"


@dataclass(frozen=True)
class FeedSpec:
    slug: str
    title: str
    description: str
    org: str
    source_name: str
    source_url: str
    sources: tuple[str, ...]
    upstream_status: str
    limit: int | None = None
    include_content: bool = True
    notes: str = ""
    categories: list[str] = field(default_factory=list)

    @property
    def filename(self) -> str:
        return f"{self.slug}.xml"

    @property
    def url(self) -> str:
        return f"{SITE_BASE}feeds/{self.filename}"


OAI_ALIGNMENT = "https://alignment.openai.com/"
OAI_REPORTS = "https://alignment.openai.com/misalignment-reports/"
OAI_CARDS = "https://deploymentsafety.openai.com/"
METR_BLOG = "https://metr.org/"

FEEDS: list[FeedSpec] = [
    FeedSpec(
        slug="openai-alignment-research",
        title="OpenAI Alignment - Research and Releases",
        description=(
            "Research posts and releases from the OpenAI Alignment Research Blog, including "
            "the ones hosted on openai.com that the official feed leaves out."
        ),
        org="OpenAI",
        source_name="Research and Releases",
        source_url=OAI_ALIGNMENT,
        sources=("research",),
        upstream_status=(
            "Official /rss.xml exists but was last built 2026-07-21 and omits every "
            "externally hosted post."
        ),
    ),
    FeedSpec(
        slug="openai-alignment-notices",
        title="OpenAI Alignment - Misalignment Notices",
        description=(
            "Dated notices about live misalignment investigations, from the OpenAI "
            "Misalignment Notices and Reports page."
        ),
        org="OpenAI",
        source_name="Misalignment Notices",
        source_url=OAI_REPORTS,
        sources=("notices",),
        upstream_status="No feed of any kind upstream.",
    ),
    FeedSpec(
        slug="openai-alignment-reports",
        title="OpenAI Alignment - Misalignment Reports",
        description=(
            "Individual reports documenting misaligned model behaviour observed in training "
            "and deployment."
        ),
        org="OpenAI",
        source_name="Misalignment Reports",
        source_url=OAI_REPORTS,
        sources=("reports",),
        upstream_status="No feed of any kind upstream.",
        notes=(
            "Upstream publishes no date for these, so each entry is dated the day this "
            "generator first saw it."
        ),
    ),
    FeedSpec(
        slug="openai-alignment-all",
        title="OpenAI Alignment - everything",
        description=(
            "Research and releases, misalignment notices and misalignment reports from the "
            "OpenAI Alignment Research Blog, merged into one feed. Each entry is tagged with "
            "its section."
        ),
        org="OpenAI",
        source_name="Alignment Research Blog (all sections)",
        source_url=OAI_ALIGNMENT,
        sources=("research", "notices", "reports"),
        upstream_status="No merged feed upstream.",
    ),
    FeedSpec(
        slug="openai-alignment-all-50",
        title="OpenAI Alignment - everything (latest 50)",
        description="As openai-alignment-all, capped at the 50 most recent entries.",
        org="OpenAI",
        source_name="Alignment Research Blog (all sections)",
        source_url=OAI_ALIGNMENT,
        sources=("research", "notices", "reports"),
        limit=50,
        upstream_status="No merged feed upstream.",
    ),
    FeedSpec(
        slug="openai-system-cards",
        title="OpenAI System Cards",
        description="System cards and deployment safety updates from the OpenAI Deployment Safety Hub.",
        org="OpenAI",
        source_name="Deployment Safety Hub",
        source_url=OAI_CARDS,
        sources=("system_cards",),
        upstream_status=(
            "A /posts.xml exists but is a broken dev build: zero items and a localhost link."
        ),
    ),
    FeedSpec(
        slug="metr-en",
        title="METR - English only",
        description=(
            "METR's blog, notes and evaluation reports with translated duplicates removed. "
            "Full article text preserved."
        ),
        org="METR",
        source_name="METR feed.xml",
        source_url=METR_BLOG,
        sources=("metr",),
        upstream_status=(
            "Official feed.xml is valid but ~8.9 MB and interleaves /es/ and /zh-Hans/ "
            "duplicates of English posts."
        ),
    ),
    FeedSpec(
        slug="metr-en-50",
        title="METR - English only (latest 50)",
        description=(
            "As metr-en, capped at the 50 most recent entries. Use this one if your reader "
            "struggles with the full feed's size."
        ),
        org="METR",
        source_name="METR feed.xml",
        source_url=METR_BLOG,
        sources=("metr",),
        limit=50,
        upstream_status="Official feed.xml is ~8.9 MB with translated duplicates.",
    ),
    FeedSpec(
        slug="metr-en-lite",
        title="METR - English only (headlines and summaries)",
        description=(
            "As metr-en, but with the full article bodies stripped out - title, summary and "
            "link only. Around 50 KB instead of 5 MB, for readers that choke on large feeds."
        ),
        org="METR",
        source_name="METR feed.xml",
        source_url=METR_BLOG,
        sources=("metr",),
        include_content=False,
        upstream_status="Official feed.xml is ~8.9 MB with translated duplicates.",
        notes="Click through to read; article text is not carried in this variant.",
    ),
]
