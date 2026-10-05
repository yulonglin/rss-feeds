"""The Conversation's email newsletters (Global daily, the AI weekly, the business weekly).

The newsletters are email-only and arrive in a kill-the-newsletter inbox. Each is a stack
of layout tables with a CSS block, logos and icons, a 1x1 tracking pixel, a sign-off
asking for replies, a "more from The Conversation" promo and an unsubscribe footer.
Every link, headlines included, goes through clicks.theconversation.com, a per-recipient
tracker whose destination is encrypted, so none of them can be published.

We flatten each email to its editorial content (the editor's note and each story's
section, image, headline, byline and standfirst) and point each headline straight at
its article. Headlines are resolved by exact title, first against the site's own
regional Atom feeds, then its search page; resolved links are kept in
state/conversation_links.json so a headline resolves once and stays put. A headline that
cannot be matched is left unlinked rather than pointed at a tracker.
"""

from __future__ import annotations

import html
import json
import re
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import quote_plus, urljoin, urlsplit

from lxml import etree
from lxml import html as lx

from ..http import fetch_bytes, fetch_text
from ..models import Item, SourceResult
from ..newsletter_email import InboxError, cut_at, fetch_inbox, linearize, text_of

SLUG = "the-conversation"
SITE = "https://theconversation.com/"
REGIONS = ("global", "us", "uk", "au", "ca", "africa", "europe", "nz")
ATOM = {"a": "http://www.w3.org/2005/Atom"}
_ARTICLE_PATH = re.compile(r"^/[a-z0-9-]+-\d{5,}$")

FOOTER = (
    "that's all for this week",
    "more from the conversation",
    "like this newsletter",
    "you're receiving this newsletter",
    "unsubscribe",
)
# Logos, section icons and the editor's avatar; story images live on images.theconversation.com.
_CHROME_IMG = ("cdn.theconversation.com/static/", "cdn.theconversation.com/newsletter_lists/")
_CHROME_IMG_HOSTS = ("storage.theconversation.com",)
_DATELINE = re.compile(r"^[A-Z][a-z]+ \d{1,2}, \d{4}$")


def norm_title(text: str) -> str:
    """Letters and digits only, so "War Games" in the email matches "WarGames" on the site."""
    return re.sub(r"[^a-z0-9]+", "", text.lower())


class LinkCache:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.data: dict[str, str] = json.loads(path.read_text()) if path.exists() else {}
        self._feeds: dict[str, str] | None = None

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(dict(sorted(self.data.items())), indent=2) + "\n")

    def _from_feeds(self) -> dict[str, str]:
        if self._feeds is None:

            def one(region: str) -> dict[str, str]:
                try:
                    root = etree.fromstring(fetch_bytes(f"{SITE}{region}/articles.atom"))
                except Exception:  # noqa: BLE001 - search is the fallback
                    return {}
                out = {}
                for e in root.findall("a:entry", ATOM):
                    link = e.find("a:link[@rel='alternate']", ATOM)
                    if link is not None:
                        out[norm_title(e.findtext("a:title", namespaces=ATOM) or "")] = link.get(
                            "href"
                        )
                return out

            self._feeds = {}
            with ThreadPoolExecutor(max_workers=4) as pool:
                for found in pool.map(one, REGIONS):
                    self._feeds.update(found)
        return self._feeds

    @staticmethod
    def _search(title: str) -> str | None:
        """Unresolved headlines stay unlinked and are retried on the next run."""
        for attempt in range(2):
            try:
                doc = lx.fromstring(fetch_text(f"{SITE}global/search?q={quote_plus(title)}"))
                break
            except Exception:  # noqa: BLE001
                if attempt:
                    return None
                time.sleep(2)
        want = norm_title(title)
        for a in doc.cssselect("a[href]"):
            href = urljoin(SITE, a.get("href"))
            if _ARTICLE_PATH.match(urlsplit(href).path) and norm_title(a.text_content()) == want:
                return href
        return None

    def resolve(self, titles: set[str]) -> None:
        todo = {norm_title(t): t for t in titles if norm_title(t) not in self.data}
        if not todo:
            return
        feeds = self._from_feeds()
        for key in list(todo):
            if key in feeds:
                self.data[key] = feeds[key]
                del todo[key]
        with ThreadPoolExecutor(max_workers=2) as pool:
            for key, url in zip(todo, pool.map(self._search, todo.values()), strict=True):
                if url:
                    self.data[key] = url

    def get(self, title: str) -> str | None:
        return self.data.get(norm_title(title))


def _headlines(email_html: str) -> set[str]:
    """Anchor texts that look like story headlines: tracked links with sentence-length text."""
    doc = lx.document_fromstring(email_html)
    out = set()
    for a in doc.iter("a"):
        text = " ".join(a.text_content().split())
        if len(text) >= 25 and not norm_title(text).startswith(("unsubscribe", "likethis")):
            out.add(text)
    return out


def _is_chrome(block: str) -> bool:
    if block.startswith("<img"):
        src = re.search(r'src="([^"]+)"', block)
        url = html.unescape(src.group(1)) if src else ""
        return any(m in url for m in _CHROME_IMG) or urlsplit(url).netloc in _CHROME_IMG_HOSTS
    text = text_of(block)
    return text in ("Read the article", "Read more", "Listen now") or not text


def kind(blocks: list[str]) -> str:
    text = " ".join(text_of(b) for b in blocks)
    if "questions about AI" in text:
        return "AI weekly"
    if "Chart of the week" in text:
        return "Business weekly"
    return "Global daily"


def render(email_html: str, links: LinkCache) -> tuple[str, list[str], str, str | None]:
    """(content_html, headlines, newsletter kind, first article url)."""
    heads = _headlines(email_html)

    def link(href: str, text: str) -> str | None:
        return links.get(text) if text in heads else None

    raw = linearize(email_html, link=link)
    category = kind(raw)
    blocks = [b for b in cut_at(raw, FOOTER) if not _is_chrome(b)]
    # The masthead repeats the date and edition already carried by the item.
    while blocks and (
        _DATELINE.match(text_of(blocks[0])) or text_of(blocks[0]) == "Global Edition"
    ):
        blocks.pop(0)

    out, titles, first_url = [], [], None
    after_headline = 0
    for b in blocks:
        text = text_of(b)
        if text in heads:
            titles.append(text)
            m = re.search(r'href="([^"]+)"', b)
            if m and first_url is None:
                first_url = html.unescape(m.group(1))
            inner = f'<a href="{m.group(1)}">{html.escape(text)}</a>' if m else html.escape(text)
            out.append(f"<h3>{inner}</h3>")
            after_headline = 1
            continue
        if after_headline == 1 and len(text) < 200 and "<a " not in b:
            out.append(f"<p><em>{html.escape(text)}</em></p>")  # byline
            after_headline = 2
            continue
        after_headline = 0
        if (
            len(text) <= 30
            and not b.startswith("<img")
            and "<a " not in b
            and not text.endswith(".")
        ):
            out.append(f"<p><strong>{html.escape(text)}</strong></p>")  # section label
        else:
            out.append(b)
    return "\n".join(out), titles, category, first_url


def the_conversation(cache_path: Path) -> SourceResult:
    try:
        emails = fetch_inbox(SLUG)
    except InboxError as exc:
        return SourceResult(error=str(exc))

    links = LinkCache(cache_path)
    links.resolve(set().union(*(_headlines(e.html) for e in emails)) if emails else set())
    links.save()

    items = []
    for e in emails:
        content, titles, category, first_url = render(e.html, links)
        if not titles:
            continue
        items.append(
            Item(
                title=e.subject,
                link=first_url or SITE,
                guid=e.guid(SLUG),
                published=e.received,
                description="\n".join(f"• {t}" for t in titles),
                content_html=content,
                author="The Conversation",
                categories=[category],
            )
        )
    if emails and not items:
        return SourceResult(error="no email had any story headlines - layout may have changed")
    return SourceResult(items=items)
