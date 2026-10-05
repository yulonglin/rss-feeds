"""The single definition of what this site publishes.

Everything downstream - the XML files, docs/index.html, docs/feeds.json, the repo README
and the vault copy - is generated from this list, so the three can't drift apart.
"""

from __future__ import annotations

from dataclasses import dataclass, field

SITE_BASE = "https://feeds.yulonglin.com/"
REPO_URL = "https://github.com/yulonglin/rss-feeds"


@dataclass(frozen=True)
class ExternalFeed:
    """A feed published by someone else that is clean as it is, listed only so the
    recommended subscription set can include it. Nothing is fetched or rebuilt."""

    title: str
    url: str
    site_url: str
    folder: str


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
    # Refuse a refresh that drops below 60% of the previous item count. Off for feeds
    # that mirror a short sliding window, where a quiet week legitimately shrinks them.
    shrink_guard: bool = True
    # Publish a valid feed with no items rather than failing, for a newsletter inbox that
    # has not received its first issue yet.
    allow_empty: bool = False
    # Built from one of Yulong's own email inboxes: held to the strict leak check, and
    # failed alone (keeping its last XML) when the inbox config is missing or malformed.
    email: bool = False
    # In the recommended set published as subscriptions.opml, under this folder.
    default: bool = False
    folder: str = "AI safety"
    categories: list[str] = field(default_factory=list)

    @property
    def filename(self) -> str:
        return f"{self.slug}.xml"

    @property
    def url(self) -> str:
        return f"{SITE_BASE}{self.filename}"


OAI_ALIGNMENT = "https://alignment.openai.com/"
OAI_REPORTS = "https://alignment.openai.com/misalignment-reports/"
OAI_CARDS = "https://deploymentsafety.openai.com/"
METR_BLOG = "https://metr.org/"
DARIO = "https://darioamodei.com/"
TLDR_AI = "https://tldr.tech/ai"
TANGLE = "https://www.readtangle.com/"
AI_DIGEST = "https://theaidigest.org/"
SCHOLAR_INBOX = "https://www.scholar-inbox.com/"
CONVERSATION = "https://theconversation.com/global/newsletters"
PROJECT_SYNDICATE = "https://www.project-syndicate.org/"
GATES_NOTES = "https://www.gatesnotes.com/"

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
            "New reports use First posted; each entry keeps the date this "
            "generator first saw it and does not jump back to the top when edited."
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
        default=True,
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
        default=True,
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
        default=True,
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
    FeedSpec(
        slug="dario-amodei",
        title="Dario Amodei",
        description=(
            "Essays and short posts from Dario Amodei's personal site, with the full text of "
            "each piece. Entries are tagged Essay or Short post, matching the site's own split."
        ),
        org="Dario Amodei",
        source_name="darioamodei.com",
        source_url=DARIO,
        sources=("dario",),
        upstream_status="No feed of any kind upstream, and no structured dates in the markup.",
        notes=(
            "The site prints a month and year rather than a full date, so every entry is "
            "dated the first of its month."
        ),
        default=True,
    ),
    FeedSpec(
        slug="tldr-ai",
        title="TLDR AI",
        description=(
            "The TLDR AI daily newsletter, one entry per issue with every story's headline, "
            "read time and summary, grouped under the issue's own sections. Sponsor slots "
            "and utm tracking are removed."
        ),
        org="TLDR",
        source_name="TLDR AI",
        source_url=TLDR_AI,
        sources=("tldr_ai",),
        upstream_status=(
            "Official /api/rss/ai exists but each item is only the emoji headline and a "
            "link: no summary and none of the stories."
        ),
        default=True,
        folder="Newsletters",
    ),
    FeedSpec(
        slug="tangle",
        title="Tangle - the good parts",
        description=(
            "Tangle's daily edition cut down to Today's topic (the story, what the left and "
            "right are saying, and Isaac Saul's take) and Under the radar, plus Isaac's "
            "standalone essays. Sponsors, quick hits, extras, teasers, paywalled previews "
            "and the Sunday recap are left out."
        ),
        org="Tangle",
        source_name="readtangle.com",
        source_url=TANGLE,
        sources=("tangle",),
        shrink_guard=False,
        upstream_status=(
            "Official /rss/ is complete but interleaves the daily with video and podcast "
            "teasers, paywalled previews, recaps, reader essays and sponsor cards."
        ),
        default=True,
        folder="Newsletters",
    ),
]

# Email-only newsletters arrive in private kill-the-newsletter inboxes; see private.py for
# why their addresses are never committed and where they are read from.
FEEDS += [
    FeedSpec(
        slug="scholar-inbox",
        email=True,
        title="Scholar Inbox - daily paper digest",
        description=(
            "Scholar Inbox's daily digest of recommended papers, one entry per day, each paper "
            "with its title, authors, venue and relevance score, the title linking to a public "
            "arXiv or Google Scholar search."
        ),
        org="Scholar Inbox",
        source_name="Scholar Inbox",
        source_url=SCHOLAR_INBOX,
        sources=("scholar_inbox",),
        shrink_guard=False,
        upstream_status=(
            "Email only. Each digest is a stack of styled table cards, titled with an "
            "ambiguous dd/mm date, and every link in it is a personal auto-login link."
        ),
        notes="Rebuilt from each paper's fields; nothing from the email's markup or links is kept.",
        default=True,
        folder="Newsletters",
    ),
    FeedSpec(
        slug="the-conversation",
        email=True,
        title="The Conversation - newsletters",
        description=(
            "The Conversation's Global daily, AI weekly and business weekly newsletters, "
            "flattened to the editor's note and each story's section, image, headline, byline "
            "and standfirst, with every headline linked straight to its article. Entries are "
            "tagged with which newsletter they came from."
        ),
        org="The Conversation",
        source_name="The Conversation newsletters",
        source_url=CONVERSATION,
        sources=("the_conversation",),
        shrink_guard=False,
        upstream_status=(
            "Email only. Nested layout tables, logos, a tracking pixel and footers, and every "
            "link wrapped in a per-recipient click tracker."
        ),
        notes=(
            "A headline that cannot be matched to its article by exact title is left unlinked "
            "rather than pointed at the tracker."
        ),
        default=True,
        folder="Newsletters",
    ),
    FeedSpec(
        slug="ai-digest",
        email=True,
        title="AI Digest",
        description=(
            "AI Digest's email updates. Held empty for now: issues are published only once a "
            "real one has been reviewed and its links and images can be allowlisted."
        ),
        org="AI Digest",
        source_name="theaidigest.org",
        source_url=AI_DIGEST,
        sources=("ai_digest",),
        shrink_guard=False,
        allow_empty=True,
        upstream_status="Email only; no feed of any kind upstream.",
        notes="Empty until an issue has been reviewed and its formatter enabled.",
        default=True,
        folder="Newsletters",
    ),
    FeedSpec(
        slug="project-syndicate",
        title="Project Syndicate",
        description=(
            "Project Syndicate commentary, each entry with its lead image and photo credit, "
            "the summary, the full byline and a clean link to the article. The articles "
            "themselves are paywalled and are not reproduced."
        ),
        org="Project Syndicate",
        source_name="project-syndicate.org",
        source_url=PROJECT_SYNDICATE,
        sources=("project_syndicate",),
        upstream_status=(
            "Official /rss is valid but summary-only, keeps the image in an enclosure most "
            "readers ignore, tags every link with utm tracking and credits only the first "
            "author of co-written pieces."
        ),
        default=True,
        folder="Newsletters",
    ),
    FeedSpec(
        slug="gates-notes",
        title="Gates Notes",
        description=(
            "Bill Gates's essays from Gates Notes with the full text of each, including pull "
            "quotes, images and photo essays, tagged with the site's own topics."
        ),
        org="Gates Notes",
        source_name="gatesnotes.com",
        source_url=GATES_NOTES,
        sources=("gates_notes",),
        upstream_status=(
            "The old /home/rss feed is gone, and every gatesnotes.com page answers scripts "
            "with a 403. Read from the content API the site itself is built from."
        ),
        default=True,
        folder="Newsletters",
    ),
]

# Published elsewhere and already clean, so they are subscribed to directly rather than
# rebuilt here. Tag feeds live at simonwillison.net/tags/<tag>.atom.
EXTERNAL_DEFAULTS: list[ExternalFeed] = [
    ExternalFeed(
        title="Simon Willison",
        url="https://simonwillison.net/atom/entries/",
        site_url="https://simonwillison.net/",
        folder="Newsletters",
    ),
    ExternalFeed(
        title="Simon Willison - prompt injection",
        url="https://simonwillison.net/tags/prompt-injection.atom",
        site_url="https://simonwillison.net/tags/prompt-injection/",
        folder="Newsletters",
    ),
]
