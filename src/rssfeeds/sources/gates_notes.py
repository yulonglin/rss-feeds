"""gatesnotes.com - Bill Gates's essays, read from the site's content API.

The site's old /home/rss feed is gone, and every page on www.gatesnotes.com, including
its sitemap, answers scripted requests with an Akamai 403 whatever the User-Agent. The
site's articles are served to its own front end by a public, unauthenticated Kontent.ai
delivery API, and that is what this reads: one listing request for the 20 newest
articles with their linked components. Nothing is fetched from www.gatesnotes.com.

Each article body is CMS rich text interleaved with component placeholders. Pull
quotes, inline images, photo essays, notes and video posters are rendered as plain
HTML; layout components (CSS blocks, takeovers, topic cards) are dropped.
"""

from __future__ import annotations

import html
import json
import re
from datetime import datetime
from urllib.parse import urlencode, urljoin

from ..http import fetch_bytes
from ..models import Item, SourceResult

SITE = "https://www.gatesnotes.com/"
API = "https://deliver.kontent.ai/12514eb8-7b51-008e-41a9-512542cf683b/items"
LIMIT = 20

_OBJECT = re.compile(
    r'<object type="application/kenticocloud"[^>]*data-codename="([^"]+)"[^>]*></object>'
)
_EMPTY_P = re.compile(r"<p>(\s|<br>|&nbsp;)*</p>")
_IMAGE_EXT = (".jpg", ".jpeg", ".png", ".gif", ".webp")


def _val(el: dict, key: str):
    return (el.get(key) or {}).get("value")


def _image(assets) -> str:
    for a in assets or []:
        if a.get("url", "").lower().split("?")[0].endswith(_IMAGE_EXT):
            alt = html.escape(a.get("description") or "", quote=True)
            return f'<p><img src="{html.escape(a["url"], quote=True)}" alt="{alt}"></p>'
    return ""


def _absolutize(fragment: str) -> str:
    return re.sub(r'href="(/[^"]*)"', lambda m: f'href="{urljoin(SITE, m.group(1))}"', fragment)


def _component(codename: str, modular: dict, depth: int = 0) -> str:
    item = modular.get(codename)
    if item is None or depth > 4:
        return ""
    kind, el = item["system"]["type"], item["elements"]
    if kind == "quote":
        return f"<blockquote>{_rich(_val(el, 'quote_copy') or '', modular, depth)}</blockquote>"
    if kind in ("body_copy_constrained", "body_copy_block"):
        key = (
            "body_copy_and_inline_elements"
            if kind == "body_copy_constrained"
            else "body_copy_block_rt"
        )
        return _rich(_val(el, key) or "", modular, depth)
    if kind == "image_set":
        return _image(_val(el, "desktop_image")) or _image(_val(el, "mobile_image"))
    if kind == "content_combo":
        return "\n".join(_component(c, modular, depth + 1) for c in _val(el, "content_items") or [])
    if kind == "content_lockup_list_slide_or_photo_essay":
        parts = [_component(c, modular, depth + 1) for c in _val(el, "item_image_set") or []]
        caption = _rich(_val(el, "caption") or "", modular, depth)
        return "\n".join(p for p in [*parts, caption] if p)
    if kind == "note":
        eyebrow, title = _val(el, "eyebrow") or "", _val(el, "title") or ""
        if not title:
            return ""
        lead = f"<strong>{html.escape(eyebrow)}:</strong> " if eyebrow else ""
        return f"<blockquote><p>{lead}{html.escape(title)}</p></blockquote>"
    if kind == "inline_video_item":
        poster = _image(_val(el, "poster_image"))
        yt = _val(el, "youtube_id")
        caption = html.escape(_val(el, "description") or "")
        if yt:
            href = f"https://www.youtube.com/watch?v={html.escape(yt, quote=True)}"
            return f'{poster}<p><a href="{href}">Watch the video</a>{": " + caption if caption else ""}</p>'
        return (
            f"{poster}<p><em>Video on the original page{': ' + caption if caption else ''}</em></p>"
        )
    return ""  # html_block (CSS), takeover, topic: layout only


def _rich(text: str, modular: dict, depth: int = 0) -> str:
    text = _OBJECT.sub(lambda m: _component(m.group(1), modular, depth + 1), text)
    return _absolutize(_EMPTY_P.sub("", text)).strip()


def to_item(raw: dict, modular: dict) -> Item | None:
    el, system = raw["elements"], raw["system"]
    date = _val(el, "date")
    title = (_val(el, "article_title") or "").strip()
    if not date or not title:
        return None
    link = urljoin(SITE, system["name"])
    subtitle = re.sub(r"<[^>]+>", "", _val(el, "article_subtitle") or "").strip()
    hero = _image(_val(el, "page_image_set__blogroll")) or _image(
        _val(el, "page_image_set__thumbnail")
    )
    body = _rich(_val(el, "body_content") or "", modular)
    lede = f"<p><em>{html.escape(subtitle)}</em></p>" if subtitle else ""
    topics = [t["name"] for t in _val(el, "page_taxonomy_set__gn_taxonomy") or []]
    return Item(
        title=title,
        link=link,
        guid=f"gatesnotes:{system['codename']}",
        published=datetime.fromisoformat(date),
        description=subtitle or (_val(el, "page_meta_set__description") or ""),
        content_html="\n".join(p for p in (hero, lede, body) if p),
        author=(_val(el, "byline") or "Bill Gates").strip(),
        categories=topics,
    )


def gates_notes() -> SourceResult:
    query = urlencode(
        {"system.type": "article", "order": "elements.date[desc]", "limit": LIMIT, "depth": 2}
    )
    try:
        data = json.loads(fetch_bytes(f"{API}?{query}"))
    except Exception as exc:  # noqa: BLE001
        return SourceResult(error=f"content API fetch/parse failed: {exc}")
    modular = data.get("modular_content", {})
    items = [i for i in (to_item(r, modular) for r in data.get("items", [])) if i is not None]
    if not items:
        return SourceResult(
            error="content API returned no dated articles - its schema may have changed"
        )
    return SourceResult(items=items)
