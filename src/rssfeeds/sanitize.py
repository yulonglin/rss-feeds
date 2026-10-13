"""One HTML allowlist for fragments copied from pages another site controls.

Feed readers render content:encoded as HTML, so third-party markup is rebuilt from an
allowlist rather than cleaned of known-bad tags: a short set of tags, href on links, src
and alt on images, and only absolute http(s) URLs. Elements that carry code or foreign
content (script, style, iframe, object, embed, form, svg, math and similar) are removed
with everything inside them; any other element outside the allowlist is unwrapped, so its
text survives. lxml re-serialises the result, so text is escaped, not passed through.
"""

from __future__ import annotations

import html
import re
from urllib.parse import urljoin, urlsplit

from lxml import html as lx

ALLOWED_TAGS = frozenset(
    {"p", "h2", "h3", "h4", "blockquote", "ul", "ol", "li", "em", "strong", "b", "i"}
    | {"a", "img", "figure", "figcaption", "br"}
)
ALLOWED_ATTRS = {"a": frozenset({"href"}), "img": frozenset({"src", "alt"})}
DROP_WITH_CONTENTS = frozenset(
    {"script", "style", "iframe", "object", "embed", "form", "svg", "math"}
    | {"noscript", "template", "applet", "frame", "frameset", "head", "title", "meta"}
    | {"link", "base", "textarea", "select", "button", "input"}
)
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")


def safe_url(url: str | None, base: str | None = None) -> str | None:
    """`url` as an absolute http(s) URL, resolved against `base`, or None.

    Control characters are refused outright rather than stripped, because browsers strip
    them and so "java&#9;script:" would become a script URL after the scheme check.
    """
    url = (url or "").strip()
    if not url or _CONTROL.search(url):
        return None
    try:
        if base:
            url = urljoin(base, url)
        parts = urlsplit(url)
    except ValueError:  # e.g. "https://[bad": unparseable is refused, not raised
        return None
    if parts.scheme.lower() not in ("http", "https") or not parts.netloc:
        return None
    return url.replace(" ", "%20")


def sanitize_html(fragment: str, *, base_url: str | None = None) -> str:
    """`fragment` rebuilt through the allowlist above. Relative URLs resolve against
    `base_url`; a link with an unsafe target keeps its text, an unsafe image is removed."""
    if not fragment or not fragment.strip():
        return ""
    root = lx.fragment_fromstring(fragment, create_parent="div")
    # Comments and processing instructions have a non-string tag; they go too.
    for el in [e for e in root.iterdescendants() if not isinstance(e.tag, str)]:
        el.drop_tree()
    for el in [e for e in root.iterdescendants() if e.tag.lower() in DROP_WITH_CONTENTS]:
        el.drop_tree()
    for el in list(root.iterdescendants()):
        tag = el.tag.lower()
        if tag not in ALLOWED_TAGS:
            el.drop_tag()
            continue
        keep = ALLOWED_ATTRS.get(tag, frozenset())
        for attr in [a for a in el.attrib if a.lower() not in keep]:
            del el.attrib[attr]
        if tag == "a":
            href = safe_url(el.get("href"), base_url)
            if href:
                el.set("href", href)
            else:
                el.drop_tag()
        elif tag == "img":
            src = safe_url(el.get("src"), base_url)
            if src:
                el.set("src", src)
            else:
                el.drop_tree()
    out = html.escape(root.text or "", quote=False) + "".join(
        lx.tostring(c, encoding="unicode", method="html") for c in root
    )
    return out.strip()
