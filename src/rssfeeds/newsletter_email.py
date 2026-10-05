"""Reading email newsletters from a kill-the-newsletter inbox and making them readable.

An HTML email is built for mail clients, not feed readers: nested layout tables, inline
styles and <style> blocks, a hidden preheader, 1x1 tracking pixels, every link wrapped
in a per-recipient click tracker, and a footer of unsubscribe and preference links. The
inbox service then appends its own settings link, which carries the inbox address.

`linearize()` flattens such an email into a plain sequence of paragraphs, headings,
lists, quotes and images with no styling, so a reader can lay it out itself. Each
source decides what the links should point at, and where the newsletter body ends.
"""

from __future__ import annotations

import hashlib
import html
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from urllib.parse import urlsplit, urlunsplit

import httpx
from lxml import etree
from lxml import html as lx

from . import private
from .http import fetch_bytes

ATOM = {"a": "http://www.w3.org/2005/Atom"}


class InboxError(Exception):
    """A fetch or parse failure whose message is safe to log: it never carries the URL."""


@dataclass(frozen=True)
class Email:
    entry_id: str
    subject: str
    received: datetime
    html: str

    def guid(self, slug: str) -> str:
        """Stable per email, and opaque: the inbox's own entry IDs are not republished."""
        return f"{slug}:{hashlib.sha256(self.entry_id.encode()).hexdigest()[:16]}"


def fetch_inbox(slug: str) -> list[Email]:
    try:
        url = private.inbox_feed_url(slug)
    except private.NotConfigured as exc:
        raise InboxError(str(exc)) from None
    try:
        root = etree.fromstring(fetch_bytes(url))
    except httpx.HTTPStatusError as exc:
        raise InboxError(f"inbox feed answered HTTP {exc.response.status_code}") from None
    except Exception as exc:  # noqa: BLE001 - str(exc) can contain the URL; never log it
        raise InboxError(f"inbox feed fetch/parse failed ({type(exc).__name__})") from None

    emails = []
    for e in root.findall("a:entry", ATOM):
        stamp = e.findtext("a:published", namespaces=ATOM) or e.findtext(
            "a:updated", namespaces=ATOM
        )
        content = e.find("a:content", ATOM)
        if not stamp or content is None or not (content.text or "").strip():
            continue
        emails.append(
            Email(
                entry_id=(e.findtext("a:id", namespaces=ATOM) or "").strip(),
                subject=" ".join((e.findtext("a:title", namespaces=ATOM) or "").split()),
                received=datetime.fromisoformat(stamp.strip()).astimezone(UTC),
                html=content.text,
            )
        )
    return emails


# --- cleaning -----------------------------------------------------------------------

_DROP_TAGS = {"head", "style", "script", "title", "meta", "link", "noscript", "form", "button"}
_BLOCKS = {"p", "h1", "h2", "h3", "h4", "h5", "h6", "ul", "ol", "blockquote", "pre", "hr"}
_CONTAINERS = {"table", "tbody", "thead", "tfoot", "tr", "td", "th", "div", "center", "section"}
_CONTAINERS |= {"article", "header", "footer", "main", "body", "html", "figure", "figcaption"}
_INLINE_KEEP = {"a", "b", "strong", "i", "em", "br", "img", "sup", "sub", "code", "li"}
_ATTRS = {"a": ("href",), "img": ("src", "alt")}


def strip_utm(url: str) -> str:
    parts = urlsplit(url)
    if "utm_" not in parts.query:
        return url
    query = "&".join(p for p in parts.query.split("&") if not p.startswith("utm_"))
    return urlunsplit(parts._replace(query=query))


def _hidden(el) -> bool:
    style = (el.get("style") or "").replace(" ", "").lower()
    return "display:none" in style or "max-height:0" in style or "mso-hide:all" in style


def _is_pixel(img) -> bool:
    def small(v):
        return (
            v is not None and v.strip().rstrip("px").isdigit() and int(v.strip().rstrip("px")) <= 3
        )

    return small(img.get("width")) or small(img.get("height")) or not img.get("src")


def _prune(root, *, link: Callable[[str, str], str | None]) -> None:
    """Remove non-content in place and rewrite or unwrap every link."""
    for el in list(root.iter()):
        if el.getparent() is None:
            continue
        if not isinstance(el.tag, str):  # comments, processing instructions
            el.drop_tree() if hasattr(el, "drop_tree") else el.getparent().remove(el)
            continue
        if el.tag in _DROP_TAGS or _hidden(el) or el.tag == "img" and _is_pixel(el):
            el.drop_tree()
    for a in list(root.iter("a")):
        href = (a.get("href") or "").strip()
        target = link(href, " ".join(a.text_content().split())) if href else None
        if target:
            a.set("href", strip_utm(target))
        else:
            a.drop_tag()  # keep the text, lose the link
    for el in root.iter():
        if not isinstance(el.tag, str):
            continue
        keep = _ATTRS.get(el.tag, ())
        for attr in list(el.attrib):
            if attr not in keep:
                del el.attrib[attr]


def _has_block(el) -> bool:
    return any(
        isinstance(d.tag, str) and (d.tag in _BLOCKS or d.tag in _CONTAINERS or d.tag == "img")
        for d in el.iterdescendants()
    )


def _inline_html(el) -> str:
    """The children of `el` as inline HTML, with unknown wrappers (span, font) unwrapped."""
    for d in list(el.iterdescendants()):
        if isinstance(d.tag, str) and d.tag not in _INLINE_KEEP and d.tag not in _BLOCKS:
            d.drop_tag()
    out = html.escape(el.text or "")
    out += "".join(lx.tostring(c, encoding="unicode", method="html") for c in el)
    return " ".join(out.split())


def _text_of(fragment: str) -> str:
    return " ".join(re.sub(r"<[^>]+>", " ", html.unescape(fragment)).split())


def _emit(el, out: list[str]) -> None:
    if el.tag == "img":
        out.append(lx.tostring(el, encoding="unicode", method="html").strip())
    elif el.tag in _BLOCKS:
        if el.tag in ("ul", "ol"):
            for li in el.iter("li"):
                for attr in list(li.attrib):
                    del li.attrib[attr]
        for d in list(el.iterdescendants()):
            if isinstance(d.tag, str) and d.tag not in _INLINE_KEEP | _BLOCKS:
                d.drop_tag()
        frag = lx.tostring(el, encoding="unicode", method="html").strip()
        if el.tag == "hr" or _text_of(frag) or "<img" in frag:
            out.append(" ".join(frag.split()) if el.tag != "pre" else frag)
    elif not _has_block(el):
        inner = _inline_html(el)
        if _text_of(inner) or "<img" in inner:
            out.append(f"<p>{inner}</p>")
    else:
        if el.text and el.text.strip():
            out.append(f"<p>{html.escape(el.text.strip())}</p>")
        for child in el:
            if isinstance(child.tag, str):
                _emit(child, out)
            if child.tail and child.tail.strip():
                out.append(f"<p>{html.escape(child.tail.strip())}</p>")


def linearize(email_html: str, *, link: Callable[[str, str], str | None]) -> list[str]:
    """Flatten an HTML email into a list of block-level HTML fragments.

    `link(href, anchor_text)` returns the URL a link should point at, or None to drop the
    link and keep its text. It sees every href, so it decides what is tracking.
    """
    doc = lx.document_fromstring(email_html)
    _prune(doc, link=link)
    body = doc.find("body")
    out: list[str] = []
    _emit(body if body is not None else doc, out)
    return [b for i, b in enumerate(out) if b != "<hr>" or (0 < i < len(out) - 1)]


def cut_at(blocks: list[str], markers: tuple[str, ...]) -> list[str]:
    """Blocks before the first one whose text starts a footer."""
    for i, b in enumerate(blocks):
        text = re.sub(r"^\W+", "", _text_of(b).replace("’", "'").lower())
        if any(text.startswith(m) for m in markers):
            return blocks[:i]
    return blocks


def text_of(fragment: str) -> str:
    return _text_of(fragment)
