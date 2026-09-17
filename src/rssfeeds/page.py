from __future__ import annotations

from html import escape
from itertools import groupby
from pathlib import Path

from .build import FeedStatus
from .registry import REPO_URL

CSS = """
:root{--bg:#fbfaf9;--surface:#fff;--border:#e6e2dd;--ink:#1f1d1b;--muted:#6b6560;
--accent:#3b5bdb;--warn:#b0541c;--code:#f3f1ee;--radius:12px}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--bg:#17161a;
--surface:#1f1e23;--border:#33313a;--ink:#eceaf0;--muted:#a09aa8;--accent:#8ea4ff;
--warn:#e0915c;--code:#26252b}}
:root[data-theme="dark"]{--bg:#17161a;--surface:#1f1e23;--border:#33313a;--ink:#eceaf0;
--muted:#a09aa8;--accent:#8ea4ff;--warn:#e0915c;--code:#26252b}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);
font:16px/1.6 ui-sans-serif,-apple-system,"Segoe UI",Inter,system-ui,sans-serif;
-webkit-font-smoothing:antialiased}
.wrap{max-width:860px;margin:0 auto;padding:56px 16px 80px}
h1{font-size:1.85rem;line-height:1.2;margin:0 0 .4em;letter-spacing:-.02em}
.lede{color:var(--muted);margin:0 0 2.5em;font-size:1.05rem}
h2{font-size:.78rem;text-transform:uppercase;letter-spacing:.09em;color:var(--muted);
margin:2.5em 0 1em;font-weight:600}
.card{background:var(--surface);border:1px solid var(--border);border-radius:var(--radius);
padding:20px;margin-bottom:14px}
.card h3{margin:0 0 .35em;font-size:1.06rem;letter-spacing:-.01em}
.card p{margin:0 0 .9em;color:var(--muted);font-size:.94rem}
.row{display:flex;gap:8px;align-items:stretch;flex-wrap:wrap}
code.url{flex:1 1 320px;min-width:0;background:var(--code);border:1px solid var(--border);
border-radius:8px;padding:9px 11px;font:13px/1.5 ui-monospace,SFMono-Regular,Menlo,monospace;
overflow-x:auto;white-space:nowrap;display:block}
button{background:var(--accent);color:#fff;border:0;border-radius:8px;padding:9px 15px;
font:600 13px/1.5 inherit;cursor:pointer;white-space:nowrap}
button:hover{filter:brightness(1.08)}
.meta{margin-top:12px;font-size:.83rem;color:var(--muted);display:flex;gap:14px;flex-wrap:wrap}
.meta a{color:var(--accent)}
.why{margin-top:10px;font-size:.83rem;color:var(--muted);border-left:2px solid var(--border);
padding-left:10px}
.stale{color:var(--warn);font-weight:600}
footer{margin-top:3.5em;font-size:.85rem;color:var(--muted)}
a{color:var(--accent)}
@media (max-width:520px){.wrap{padding:32px 16px 56px}h1{font-size:1.5rem}}
"""

JS = """
document.addEventListener('click',function(e){
  var b=e.target.closest('button[data-copy]');if(!b)return;
  var t=b.getAttribute('data-copy');
  navigator.clipboard.writeText(t).then(function(){
    var o=b.textContent;b.textContent='Copied';setTimeout(function(){b.textContent=o},1400);
  },function(){});
});
"""


def render_index(statuses: list[FeedStatus]) -> str:
    healthy = sum(1 for s in statuses if s.error is None)
    parts: list[str] = []
    for org, group in groupby(
        sorted(statuses, key=lambda s: (s.spec.org, s.spec.slug)), key=lambda s: s.spec.org
    ):
        parts.append(f"<h2>{escape(org)}</h2>")
        for s in group:
            sp = s.spec
            meta = [f"{s.item_count} items"]
            if s.newest:
                meta.append(f"newest {s.newest.date().isoformat()}")
            meta.append(f'<a href="{escape(sp.source_url)}">source: {escape(sp.source_name)}</a>')
            if s.error:
                meta.append('<span class="stale">last refresh failed</span>')
            why = f'<p class="why">Why this exists: {escape(sp.upstream_status)}'
            if sp.notes:
                why += f" {escape(sp.notes)}"
            why += "</p>"
            parts.append(
                f'<div class="card"><h3>{escape(sp.title)}</h3>'
                f"<p>{escape(sp.description)}</p>"
                f'<div class="row"><code class="url">{escape(sp.url)}</code>'
                f'<button data-copy="{escape(sp.url)}">Copy</button></div>'
                f'{why}<div class="meta">{" ".join(f"<span>{m}</span>" for m in meta)}</div></div>'
            )

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>RSS Feeds</title>
<meta name="description" content="Clean, public RSS endpoints for blogs whose own feeds are missing, stale, broken or noisy.">
<link rel="icon" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'><text y='.9em' font-size='90'>📡</text></svg>">
<style>{CSS}</style>
</head>
<body>
<div class="wrap">
<h1>RSS Feeds</h1>
<p class="lede">Clean RSS endpoints for blogs whose own feeds are missing, stale, broken or full of translated duplicates. Currently AI safety research; the setup takes any source. Rebuilt every 8 hours. Paste any URL below into NetNewsWire, Feedly, or anything else that speaks RSS.</p>
{"".join(parts)}
<footer>
<p>{healthy} of {len(statuses)} feeds refreshed successfully on the last run. A machine-readable list of every endpoint is at <a href="feeds.json">feeds.json</a>.</p>
<p>Generated by <a href="{REPO_URL}">{REPO_URL}</a>. Content belongs to its publishers; this site only reformats what they already publish openly.</p>
</footer>
</div>
<script>{JS}</script>
</body>
</html>
"""


def write_index(statuses: list[FeedStatus], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    html = render_index(statuses)
    if not path.exists() or path.read_text() != html:
        path.write_text(html)
