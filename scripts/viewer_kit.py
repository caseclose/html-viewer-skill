"""Shared look and building blocks for html-viewer pages and dashboards.

Build scripts import this and only decide *what* to show; the kit decides how it
looks. Output is one self-contained HTML file: CSS and JS are inlined, nothing is
loaded from a CDN, images are linked by path relative to the served directory.

    import os, sys
    sys.path.insert(0, os.path.expanduser("~/.tclaude/skills/html-viewer/scripts"))
    import viewer_kit as vk

    root = Path(__file__).resolve().parent          # the directory you serve
    body = vk.table(["name", "score"], [["a", 0.91], ["b", 0.42]])
    cards = [vk.card("c1", "1", "Results", body, status="ok")]
    Path("index.html").write_text(vk.page("Dashboard", cards, toc=[("c1", "Results", "ok")]),
                                  encoding="utf-8")

Every helper returns an `Html` string and escapes plain text it is given. Pass raw
data in; to put markup somewhere that expects text (a table cell, a kv value), wrap
it with `vk.raw(...)` or pass another helper's output (already `Html`).

Python 3.8+, standard library only.
"""
from __future__ import annotations

import html as _html
import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Sequence

# --------------------------------------------------------------------- tones
# Colour is semantic. Pick the tone by what the thing *is*, not to decorate.
TONES = ("info", "success", "accent", "warn", "highlight", "danger", "muted")

# Convenience presets: map domain words to tones so build scripts stay readable.
# Extend per use; unknown names fall back to "muted".
TONE_ALIASES = {
    # status
    "ok": "success", "pass": "success", "bad": "danger", "fail": "danger",
    "error": "danger", "warning": "warn", "neutral": "muted", "note": "muted",
    # log levels
    "debug": "muted", "info_level": "info", "critical": "danger",
    # conversations / agent traces
    "user": "info", "assistant": "success", "model": "success", "tool": "accent",
    "plan": "warn", "final": "highlight", "system": "muted",
    # diffs / comparisons
    "added": "success", "removed": "danger", "changed": "warn", "baseline": "muted",
}


def tone(name: str | None) -> str:
    name = (name or "").lower()
    return name if name in TONES else TONE_ALIASES.get(name, "muted")


UI_TEXT = {
    "zh": {
        "search": "搜索…  (/)", "expand": "展开全文", "chars": "字符", "items": "项",
        "no_match": "没有匹配的内容", "expand_all": "全部展开", "collapse_all": "全部收起",
        "theme": "切换深浅色", "copy": "复制", "copied": "已复制", "generated": "生成于",
        "rows": "行", "more_rows": "还有 {n} 行未显示", "all": "全部",
        "keys": "快捷键：/ 搜索 · j/k 上下条 · ←/→ 切图 · Esc 关闭",
    },
    "en": {
        "search": "Search…  (/)", "expand": "Show all", "chars": "chars", "items": "items",
        "no_match": "Nothing matches", "expand_all": "Expand all", "collapse_all": "Collapse all",
        "theme": "Toggle theme", "copy": "Copy", "copied": "Copied", "generated": "Generated",
        "rows": "rows", "more_rows": "{n} more rows not shown", "all": "All",
        "keys": "Keys: / search · j/k next/prev · ←/→ images · Esc close",
    },
}
UI = dict(UI_TEXT["zh"])  # active labels


def set_lang(lang: str) -> None:
    """Switch UI labels ("zh" default, "en"). Call before building any content."""
    UI.clear()
    UI.update(UI_TEXT.get(lang, UI_TEXT["en"]))


class Html(str):
    """Marks a string as markup that must not be escaped again."""


def raw(markup: str) -> Html:
    return Html(markup)


def esc(value: Any) -> str:
    if isinstance(value, Html):
        return value
    return _html.escape("" if value is None else str(value))


def rel(path: str | os.PathLike, root: str | os.PathLike) -> str:
    """Absolute path on disk -> URL relative to the served directory."""
    try:
        return Path(os.path.relpath(path, root)).as_posix()
    except ValueError:
        return str(path)


def fmt(value: Any) -> str:
    """Human formatting for numbers; everything else str()."""
    if isinstance(value, bool):
        return "✓" if value else "✗"
    if isinstance(value, int):
        return f"{value:,}"
    if isinstance(value, float):
        if value != value:  # NaN
            return "—"
        return f"{value:,.4g}" if abs(value) < 1e6 else f"{value:,.0f}"
    return "—" if value is None else str(value)


# --------------------------------------------------------------------- text

def text(value: Any, limit: int = 700) -> Html:
    """Prose. Long text shows a preview with the full text one click away."""
    value = "" if value is None else str(value)
    if len(value) <= limit:
        return Html(f'<div class="prose">{esc(value)}</div>')
    return Html(
        f'<div class="prose">{esc(value[:limit].rstrip())}<span class="fade">…</span></div>'
        f'<details class="more"><summary>{UI["expand"]} · {len(value):,} {UI["chars"]}</summary>'
        f'<div class="prose">{esc(value)}</div></details>'
    )


_JSON_TOKEN = re.compile(
    r'("(?:\\.|[^"\\])*")(\s*:)?'
    r"|(-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)"
    r"|\b(true|false|null)\b"
)


def _highlight_json(src: str) -> str:
    out, pos = [], 0
    for m in _JSON_TOKEN.finditer(src):
        out.append(esc(src[pos:m.start()]))
        string, colon, number, literal = m.groups()
        if string is not None:
            cls = "j-key" if colon else "j-str"
            out.append(f'<span class="{cls}">{esc(string)}</span>{esc(colon or "")}')
        elif number is not None:
            out.append(f'<span class="j-num">{esc(number)}</span>')
        else:
            out.append(f'<span class="j-lit">{esc(literal)}</span>')
        pos = m.end()
    out.append(esc(src[pos:]))
    return "".join(out)


def code(value: Any, limit: int = 1200, lang: str = "") -> Html:
    """Monospace block with a copy button. dict/list are pretty-printed and
    highlighted as JSON; strings that parse as JSON are too."""
    if isinstance(value, (dict, list)):
        src, is_json = json.dumps(value, ensure_ascii=False, indent=2, default=str), True
    else:
        src = "" if value is None else str(value)
        is_json = False
        stripped = src.strip()
        if stripped[:1] in ("{", "["):
            try:
                src, is_json = json.dumps(json.loads(stripped), ensure_ascii=False, indent=2), True
            except ValueError:
                pass
    render = _highlight_json if is_json else esc
    label = lang or ("json" if is_json else "")
    tag = f'<span class="lang">{esc(label)}</span>' if label else ""
    if len(src) <= limit:
        return Html(f'<div class="codewrap">{tag}<pre class="code">{render(src)}</pre></div>')
    return Html(
        f'<div class="codewrap">{tag}<pre class="code">{render(src[:limit])}<span class="fade">…</span></pre></div>'
        f'<details class="more"><summary>{UI["expand"]} · {len(src):,} {UI["chars"]}</summary>'
        f'<div class="codewrap"><pre class="code">{render(src)}</pre></div></details>'
    )


def fold(summary: str, body_html: str, open_: bool = False) -> Html:
    """Collapsed-by-default panel for secondary detail (configs, raw dumps, prompts)."""
    return Html(f'<details class="fold"{" open" if open_ else ""}><summary>{esc(summary)}</summary>'
                f'<div class="fold-body">{body_html}</div></details>')


# --------------------------------------------------------------------- images

def img(path: str | os.PathLike, root: str | os.PathLike, caption: str = "",
        thumb: str | os.PathLike | None = None) -> Html:
    """One figure. `thumb` (e.g. an existing *_thumb.jpg) is shown inline; the
    full file opens in the lightbox."""
    full = esc(rel(path, root))
    shown = esc(rel(thumb, root)) if thumb else full
    cap = f"<figcaption>{esc(caption)}</figcaption>" if caption else ""
    return Html(f'<figure><img loading="lazy" decoding="async" src="{shown}" data-full="{full}" '
                f'alt="{esc(caption)}" data-caption="{esc(caption)}">{cap}</figure>')


def gallery(items: Iterable[tuple], root: str | os.PathLike, hero: bool = False,
            size: int = 168) -> Html:
    """items: (path, caption) or (path, caption, thumb). Empty -> ''.
    `size` is the thumbnail height in px; `hero` shows one large image."""
    figs = [img(it[0], root, *it[1:]) for it in items if it and it[0]]
    if not figs:
        return Html("")
    style = "" if hero or size == 168 else f' style="--thumb:{int(size)}px"'
    return Html(f'<div class="gallery{" hero" if hero else ""}"{style}>{"".join(figs)}</div>')


# --------------------------------------------------------------------- small pieces

def chip(label: str, value: Any = None) -> Html:
    if value is None:
        return Html(f'<span class="chip">{esc(label)}</span>')
    return Html(f'<span class="chip">{esc(label)} <b>{esc(fmt(value))}</b></span>')


def badge(label: Any, kind: str = "muted") -> Html:
    """kind: a tone or alias (ok, fail, warn, info, ...)."""
    return Html(f'<span class="badge t-{tone(kind)}">{esc(fmt(label))}</span>')


def meter(value: float, maximum: float = 1.0, label: str | None = None, kind: str = "") -> Html:
    """Inline progress bar with its number; good in table cells (pass rate, usage).
    kind '' picks a tone from the ratio: >=.8 success, >=.5 warn, else danger."""
    ratio = 0.0 if not maximum else max(0.0, min(1.0, float(value) / float(maximum)))
    t = tone(kind) if kind else ("success" if ratio >= 0.8 else "warn" if ratio >= 0.5 else "danger")
    shown = label if label is not None else (f"{ratio:.0%}" if maximum == 1.0 else f"{fmt(value)}/{fmt(maximum)}")
    return Html(f'<span class="meter t-{t}" data-v="{ratio:.6f}"><span class="meter-track">'
                f'<span class="meter-fill" style="width:{ratio * 100:.1f}%"></span></span>'
                f'<span class="meter-v">{esc(shown)}</span></span>')


def section(title: str) -> Html:
    return Html(f'<div class="section-title">{esc(title)}</div>')


def kv(pairs: Iterable[tuple[str, Any]]) -> Html:
    """Key/value table for metadata. Values may be Html (badges, links)."""
    rows = "".join(f"<tr><th>{esc(k)}</th><td>{esc(v) if isinstance(v, Html) else esc(fmt(v))}</td></tr>"
                   for k, v in pairs)
    return Html(f'<table class="kv">{rows}</table>')


def link(href: str, label: str) -> Html:
    return Html(f'<a href="{esc(href)}">{esc(label)}</a>')


# --------------------------------------------------------------------- structure

def block(kind: str, label: str, body_html: str, aside: str = "") -> Html:
    """One step of a timeline (log line, event, message, stage). `kind` is a tone
    or alias: info / success / warn / danger / user / tool / error / ..."""
    aside_html = f'<span class="aside">{esc(aside)}</span>' if aside else ""
    return Html(f'<div class="block t-{tone(kind)}"><div class="label"><span>{esc(label)}</span>{aside_html}</div>'
                f"{body_html}</div>")


def timeline(blocks: Sequence[str]) -> Html:
    return Html(f'<div class="timeline">{"".join(blocks)}</div>')


def call(name: str, arguments: Any, aside: str = "") -> Html:
    """A function/API/tool call: name header + highlighted arguments."""
    aside_html = f'<span class="aside">{esc(aside)}</span>' if aside else ""
    return Html(f'<div class="call"><div class="call-head"><span class="call-icon">ƒ</span>'
                f'<span class="call-name">{esc(name)}</span>{aside_html}</div>{code(arguments, 900)}</div>')


def compare(columns: Sequence[tuple[str, str]]) -> Html:
    """Side-by-side columns: [(title, html), ...]. Keep column order stable."""
    cols = "".join(f'<div class="col"><div class="col-title">{esc(t)}</div>{h}</div>'
                   for t, h in columns)
    return Html(f'<div class="compare" style="--cols:{len(columns)}">{cols}</div>')


def grid(items: Sequence[str], min_width: int = 280) -> Html:
    """Responsive grid of tiles/cards (e.g. one compact card per image or run)."""
    return Html(f'<div class="grid" style="--min:{int(min_width)}px">{"".join(items)}</div>')


def tabs(panels: Sequence[tuple[str, str]], tab_id: str = "") -> Html:
    """Tabbed panels: [(label, html), ...]. First tab open."""
    tab_id = tab_id or f"tabs{abs(hash(tuple(p[0] for p in panels))) % 10**8}"
    heads = "".join(f'<button type="button" class="tab{" on" if i == 0 else ""}" data-tab="{tab_id}-{i}">{esc(lbl)}</button>'
                    for i, (lbl, _) in enumerate(panels))
    bodies = "".join(f'<div class="tab-panel" id="{tab_id}-{i}"{"" if i == 0 else " hidden"}>{h}</div>'
                     for i, (_, h) in enumerate(panels))
    return Html(f'<div class="tabs"><div class="tab-bar">{heads}</div>{bodies}</div>')


def table(columns: Sequence[str], rows: Iterable[Sequence[Any]], *, max_rows: int = 2000,
          align: dict | None = None, row_kinds: Sequence[str] | None = None, caption: str = "") -> Html:
    """Sortable table (click a header). Cells may be numbers, text, None, or Html
    (badge/meter/img/link). The page search also filters rows.
    row_kinds: optional per-row tone to tint a row (e.g. 'fail')."""
    rows = list(rows)
    shown = rows[:max_rows]
    numeric = [all(isinstance(r[i], (int, float)) and not isinstance(r[i], bool)
                   for r in shown if i < len(r) and r[i] is not None) and any(
                   i < len(r) and r[i] is not None for r in shown) for i in range(len(columns))]
    align = align or {}
    head = "".join(
        f'<th class="{"num" if numeric[i] else ""}" style="{"text-align:" + align[c] if c in align else ""}">'
        f'<button type="button" class="sort" data-col="{i}">{esc(c)}<span class="arrow"></span></button></th>'
        for i, c in enumerate(columns))
    body = []
    for n, r in enumerate(shown):
        cells = []
        for i in range(len(columns)):
            v = r[i] if i < len(r) else None
            if isinstance(v, Html):
                m = re.search(r'data-v="([^"]*)"', v)
                sort_v = m.group(1) if m else re.sub(r"<[^>]+>", "", v)
                cells.append(f'<td data-v="{esc(sort_v)}">{v}</td>')
            elif numeric[i]:
                cells.append(f'<td class="num" data-v="{"" if v is None else v}">{esc(fmt(v))}</td>')
            elif isinstance(v, (dict, list)):
                s = json.dumps(v, ensure_ascii=False, default=str)
                cells.append(f'<td data-v="{esc(s[:200])}" class="mono">{esc(s if len(s) <= 160 else s[:160] + "…")}</td>')
            else:
                s = fmt(v)
                cells.append(f'<td data-v="{esc(s[:200])}">{esc(s if len(s) <= 300 else s[:300] + "…")}</td>')
        kind = f' class="t-{tone(row_kinds[n])} tinted"' if row_kinds and n < len(row_kinds) and row_kinds[n] else ""
        body.append(f'<tr data-row{kind}>{"".join(cells)}</tr>')
    more = (f'<div class="table-more">{UI["more_rows"].format(n=f"{len(rows) - len(shown):,}")}</div>'
            if len(rows) > len(shown) else "")
    cap = f'<div class="table-cap">{esc(caption)} · {len(rows):,} {UI["rows"]}</div>' if caption else ""
    return Html(f'{cap}<div class="table-wrap"><table class="data"><thead><tr>{head}</tr></thead>'
                f'<tbody>{"".join(body)}</tbody></table></div>{more}')


def stat_row(stats: Iterable[tuple]) -> Html:
    """Big-number tiles: (label, value) or (label, value, kind) or (label, value, kind, hint)."""
    tiles = []
    for s in stats:
        label, value = s[0], s[1]
        kind = tone(s[2]) if len(s) > 2 and s[2] else ""
        hint = f'<div class="stat-h">{esc(s[3])}</div>' if len(s) > 3 and s[3] else ""
        tiles.append(f'<div class="stat{" t-" + kind if kind else ""}"><div class="stat-v">{esc(fmt(value))}</div>'
                     f'<div class="stat-k">{esc(label)}</div>{hint}</div>')
    return Html(f'<div class="stats">{"".join(tiles)}</div>')


def card(anchor: str, index: str, title: str, body_html: str, *, meta: str = "",
         chips: Iterable = (), status: str | None = None, status_label: str = "",
         tags: Iterable[str] = (), compact: bool = False) -> Html:
    """One record / panel. `status` (a tone or alias) adds a badge and colours the
    TOC dot. `tags` like "group:value" drive the facet filters in page()."""
    chip_html = "".join(chip(*c) if isinstance(c, tuple) else chip(c) for c in chips)
    badge_html = badge(status_label or status, status) if status else ""
    tag_attr = f' data-tags="{esc("|".join(tags))}"' if tags else ""
    idx = f'<span class="card-index">{esc(index)}</span>' if index else ""
    return Html(
        f'<article class="card{" compact" if compact else ""}" id="{esc(anchor)}"{tag_attr}>'
        f'<header class="card-head"><div class="card-title">{idx}'
        f"<h2>{esc(title)}</h2>{badge_html}</div>"
        + (f'<div class="meta">{esc(meta)}</div>' if meta else "")
        + (f'<div class="chips">{chip_html}</div>' if chip_html else "")
        + f"</header>{body_html}</article>"
    )


# --------------------------------------------------------------------- page

def page(title: str, cards: Sequence[str], *, toc: Sequence[tuple] = (), subtitle: str = "",
         summary_html: str = "", facets: Sequence[tuple[str, Sequence[str]]] = (),
         footer: str = "", wide: bool = False) -> str:
    """Whole document.

    toc:    (anchor, label) or (anchor, label, status) per card -> sidebar.
    facets: [(group, [values...]), ...] -> filter pills; cards opt in with
            tags=["group:value", ...]. OR within a group, AND across groups.
    wide:   full-width main column (tables, grids) instead of reading width.
    Labels follow set_lang().
    """
    lang = "zh" if UI["items"] == UI_TEXT["zh"]["items"] else "en"
    toc_links = "".join(
        f'<a href="#{esc(t[0])}"><span class="dot t-{tone(t[2]) if len(t) > 2 and t[2] else "none"}"></span>'
        f'<span class="toc-label">{esc(t[1])}</span></a>'
        for t in toc
    )
    toc_html = f'<nav class="toc">{toc_links}</nav>' if toc else ""
    facet_html = ""
    if facets:
        groups = "".join(
            f'<div class="facet" data-group="{esc(g)}"><span class="facet-name">{esc(g)}</span>'
            f'<button type="button" class="pill on" data-val="">{UI["all"]}</button>'
            + "".join(f'<button type="button" class="pill" data-val="{esc(v)}">{esc(v)}</button>' for v in vals)
            + "</div>"
            for g, vals in facets)
        facet_html = f'<div class="facets">{groups}</div>'
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    foot = f'{UI["generated"]} {stamp}' + (f" · {esc(footer)}" if footer else "")
    layout_cls = "layout" + ("" if toc else " no-toc") + (" wide" if wide else "")
    js = JS
    for key in ("copy", "copied", "expand_all", "collapse_all", "items"):
        js = js.replace(f"__{key.upper()}__", UI[key])
    return f"""<!doctype html>
<html lang="{esc(lang)}"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(title)}</title>
<script>document.documentElement.dataset.theme=localStorage.getItem("hv-theme")||(matchMedia("(prefers-color-scheme: dark)").matches?"dark":"light")</script>
<style>{CSS}</style></head>
<body>
<header class="topbar"><div class="topbar-in">
  <div class="brand"><div class="title">{esc(title)}</div>{f'<div class="subtitle">{esc(subtitle)}</div>' if subtitle else ""}</div>
  <div class="tools">
    <span class="count" id="hv-count">{len(cards)} {UI["items"]}</span>
    <input id="hv-search" type="search" placeholder="{esc(UI["search"])}" autocomplete="off">
    <button class="btn" id="hv-expand" type="button">{UI["expand_all"]}</button>
    <button class="btn icon" id="hv-theme" type="button" title="{UI["theme"]}" aria-label="{UI["theme"]}">◐</button>
  </div>
</div></header>
<div class="{layout_cls}">
  {toc_html}
  <main>
    {summary_html}
    {facet_html}
    {"".join(cards)}
    <div class="empty" id="hv-empty" hidden>{UI["no_match"]}</div>
    <footer class="foot">{foot}<br><span class="keys">{UI["keys"]}</span></footer>
  </main>
</div>
<div class="lightbox" id="hv-lb" hidden><button class="lb-close" type="button" aria-label="close">×</button>
  <img alt=""><div class="lb-cap"></div></div>
<script>{js}</script>
</body></html>"""


# --------------------------------------------------------------------- theme

CSS = r"""
:root{
  --bg:#f5f6f8;--surface:#fff;--surface-2:#f8f9fb;--border:#e6e8ec;--border-strong:#d5d9e0;
  --text:#14171f;--muted:#5f6878;--faint:#9aa1ad;--accent-ui:#4f5bd5;--accent-ui-soft:#eef0fd;
  --info:#2f6fde;--info-bg:#f2f6fe;--success:#13866f;--success-bg:#f0f9f6;
  --accent:#7a4fd6;--accent-bg:#f6f3fe;--warn:#b36b00;--warn-bg:#fff8eb;
  --highlight:#d6336c;--highlight-bg:#fff2f6;--danger:#d03b3b;--danger-bg:#fff3f2;
  --muted-t:#56617a;--muted-bg:#f6f7f9;
  --radius:14px;--shadow:0 1px 2px rgba(20,23,31,.04),0 2px 8px rgba(20,23,31,.04);
  --shadow-hover:0 4px 18px rgba(20,23,31,.10);
  --sans:-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Hiragino Sans GB","Microsoft YaHei","Noto Sans CJK SC",sans-serif;
  --mono:ui-monospace,"SF Mono","JetBrains Mono",Menlo,Consolas,monospace;
  color-scheme:light;
}
[data-theme=dark]{
  --bg:#0e1015;--surface:#161921;--surface-2:#1c2029;--border:#262b36;--border-strong:#323846;
  --text:#e7e9ee;--muted:#a0a7b4;--faint:#6c7381;--accent-ui:#8b95f5;--accent-ui-soft:#232848;
  --info:#6ea2ff;--info-bg:#151d2e;--success:#3fc4a3;--success-bg:#122520;
  --accent:#b496ff;--accent-bg:#1d1830;--warn:#f0b44c;--warn-bg:#2a2112;
  --highlight:#ff7aa5;--highlight-bg:#2c1620;--danger:#ff7b72;--danger-bg:#2d1717;
  --muted-t:#a0a7b4;--muted-bg:#1a1d25;
  --shadow:0 1px 2px rgba(0,0,0,.3);--shadow-hover:0 6px 22px rgba(0,0,0,.45);
  color-scheme:dark;
}
.t-info{--k:var(--info);--k-bg:var(--info-bg)}.t-success{--k:var(--success);--k-bg:var(--success-bg)}
.t-accent{--k:var(--accent);--k-bg:var(--accent-bg)}.t-warn{--k:var(--warn);--k-bg:var(--warn-bg)}
.t-highlight{--k:var(--highlight);--k-bg:var(--highlight-bg)}.t-danger{--k:var(--danger);--k-bg:var(--danger-bg)}
.t-muted{--k:var(--muted-t);--k-bg:var(--muted-bg)}
*{box-sizing:border-box}
html{scroll-behavior:smooth}
body{margin:0;background:var(--bg);color:var(--text);font:15px/1.65 var(--sans);
  -webkit-font-smoothing:antialiased;text-rendering:optimizeLegibility}
a{color:var(--accent-ui)}
::selection{background:color-mix(in srgb,var(--accent-ui) 25%,transparent)}

/* top bar */
.topbar{position:sticky;top:0;z-index:20;border-bottom:1px solid var(--border);
  background:color-mix(in srgb,var(--bg) 82%,transparent);backdrop-filter:saturate(170%) blur(14px);
  -webkit-backdrop-filter:saturate(170%) blur(14px)}
.topbar-in{max-width:1440px;margin:0 auto;padding:12px 28px;display:flex;align-items:center;gap:20px}
.brand{min-width:0;flex:1}
.title{font-size:16px;font-weight:650;letter-spacing:-.01em;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.subtitle{font-size:12.5px;color:var(--muted);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.tools{display:flex;align-items:center;gap:8px}
.count{font-size:12.5px;color:var(--muted);font-variant-numeric:tabular-nums;margin-right:4px;white-space:nowrap}
#hv-search{width:240px;height:34px;padding:0 12px;border-radius:9px;border:1px solid var(--border);
  background:var(--surface);color:var(--text);font:inherit;font-size:13.5px;outline:none;transition:border-color .15s,box-shadow .15s}
#hv-search:focus{border-color:var(--accent-ui);box-shadow:0 0 0 3px color-mix(in srgb,var(--accent-ui) 18%,transparent)}
.btn{height:34px;padding:0 12px;border-radius:9px;border:1px solid var(--border);background:var(--surface);
  color:var(--muted);font:inherit;font-size:13px;cursor:pointer;transition:all .15s;white-space:nowrap}
.btn:hover{color:var(--text);border-color:var(--border-strong)}
.btn.icon{width:34px;padding:0;font-size:15px}

/* layout */
.layout{max-width:1360px;margin:0 auto;padding:28px;display:grid;grid-template-columns:232px minmax(0,1fr);gap:32px}
.layout.no-toc{grid-template-columns:minmax(0,1fr);max-width:1080px}
.layout.wide{max-width:1680px}.layout.no-toc.wide{max-width:1440px}
.toc{position:sticky;top:84px;align-self:start;max-height:calc(100vh - 110px);overflow:auto;padding-right:4px}
.toc a{display:flex;align-items:center;gap:9px;padding:6px 10px;margin-bottom:1px;border-radius:8px;
  font-size:13px;color:var(--muted);text-decoration:none;transition:background .12s,color .12s}
.toc a:hover{background:var(--surface);color:var(--text)}
.toc a.active{background:var(--accent-ui-soft);color:var(--accent-ui);font-weight:550}
.toc a.hidden{display:none}
.toc-label{white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.dot{width:7px;height:7px;border-radius:50%;flex:none;background:var(--k,var(--border-strong))}
@media (max-width:980px){.layout{grid-template-columns:minmax(0,1fr);padding:18px}.toc{display:none}
  #hv-search{width:150px}.topbar-in{padding:10px 18px}#hv-expand{display:none}}

/* summary tiles */
.stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin-bottom:24px}
.stat{background:var(--surface);border:1px solid var(--border);border-radius:var(--radius);padding:14px 16px;box-shadow:var(--shadow);
  position:relative;overflow:hidden}
.stat[class*=" t-"]::before{content:"";position:absolute;left:0;top:0;bottom:0;width:3px;background:var(--k)}
.stat-v{font-size:25px;font-weight:650;letter-spacing:-.02em;font-variant-numeric:tabular-nums;line-height:1.3}
.stat[class*=" t-"] .stat-v{color:var(--k)}
.stat-k{font-size:12.5px;color:var(--muted)}
.stat-h{font-size:11.5px;color:var(--faint);margin-top:2px}

/* facets */
.facets{display:flex;flex-direction:column;gap:8px;margin:-6px 0 22px}
.facet{display:flex;flex-wrap:wrap;align-items:center;gap:6px}
.facet-name{font-size:12px;color:var(--faint);margin-right:4px;min-width:56px}
.pill{height:28px;padding:0 12px;border-radius:999px;border:1px solid var(--border);background:var(--surface);
  color:var(--muted);font:inherit;font-size:12.5px;cursor:pointer;transition:all .12s}
.pill:hover{border-color:var(--border-strong);color:var(--text)}
.pill.on{background:var(--accent-ui);border-color:var(--accent-ui);color:#fff}

/* cards */
.card{background:var(--surface);border:1px solid var(--border);border-radius:var(--radius);box-shadow:var(--shadow);
  padding:24px 26px 20px;margin-bottom:24px;scroll-margin-top:86px;transition:box-shadow .2s;min-width:0}
.card:hover{box-shadow:var(--shadow-hover)}
.card.hidden{display:none}
.card.compact{padding:14px 16px 12px;margin-bottom:0}
.card.compact h2{font-size:14.5px}
.card-title{display:flex;align-items:baseline;gap:10px;flex-wrap:wrap}
.card-index{font:600 13px var(--mono);color:var(--faint)}
.card h2{margin:0;font-size:18px;font-weight:650;letter-spacing:-.01em;line-height:1.45;word-break:break-word}
.meta{margin-top:4px;font:12px/1.5 var(--mono);color:var(--faint);word-break:break-all}
.chips{display:flex;flex-wrap:wrap;gap:6px;margin-top:12px}
.chip{display:inline-flex;align-items:center;gap:5px;padding:2px 10px;border-radius:999px;font-size:12px;
  color:var(--muted);background:var(--surface-2);border:1px solid var(--border)}
.chip b{color:var(--text);font-weight:600;font-variant-numeric:tabular-nums}
.badge{display:inline-flex;align-items:center;padding:1px 9px;border-radius:999px;font-size:11.5px;font-weight:600;
  color:var(--k);background:color-mix(in srgb,var(--k) 12%,transparent);white-space:nowrap}
.section-title{margin:26px 0 12px;font-size:11.5px;font-weight:650;letter-spacing:.08em;text-transform:uppercase;color:var(--faint);
  display:flex;align-items:center;gap:10px}
.section-title::after{content:"";flex:1;height:1px;background:var(--border)}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(var(--min,280px),1fr));gap:16px;margin-bottom:24px}
.grid .gallery img{height:auto;max-height:240px;max-width:100%}

/* tabs */
.tab-bar{display:flex;gap:2px;border-bottom:1px solid var(--border);margin:6px 0 14px;overflow-x:auto}
.tab{padding:8px 14px;border:0;background:none;font:inherit;font-size:13.5px;color:var(--muted);cursor:pointer;
  border-bottom:2px solid transparent;margin-bottom:-1px;white-space:nowrap}
.tab:hover{color:var(--text)}
.tab.on{color:var(--accent-ui);border-bottom-color:var(--accent-ui);font-weight:600}

/* tables */
.table-cap{font-size:12.5px;color:var(--muted);margin:4px 0 8px}
.table-wrap{overflow:auto;max-height:70vh;border:1px solid var(--border);border-radius:10px}
table.data{border-collapse:separate;border-spacing:0;width:100%;font-size:13.5px}
table.data th{position:sticky;top:0;z-index:1;background:var(--surface-2);text-align:left;font-weight:600;
  border-bottom:1px solid var(--border);padding:0;white-space:nowrap}
table.data th.num{text-align:right}
.sort{all:unset;display:flex;align-items:center;gap:4px;width:100%;box-sizing:border-box;padding:9px 12px;cursor:pointer;
  font-size:12px;color:var(--muted);letter-spacing:.02em}
th.num .sort{justify-content:flex-end}
.sort:hover{color:var(--text)}
.arrow::after{content:"↕";opacity:.35;font-size:11px}
th[aria-sort=ascending] .arrow::after{content:"↑";opacity:1}th[aria-sort=descending] .arrow::after{content:"↓";opacity:1}
table.data td{padding:8px 12px;border-bottom:1px solid var(--border);vertical-align:top;word-break:break-word;max-width:520px}
table.data td.num{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}
table.data td.mono{font:12px var(--mono)}
table.data tbody tr:hover td{background:var(--surface-2)}
table.data tr:last-child td{border-bottom:0}
table.data tr.tinted td{background:var(--k-bg)}
table.data tr.hidden{display:none}
table.data td .gallery{margin:0}table.data td .gallery img{height:64px}
.table-more{font-size:12px;color:var(--faint);margin-top:6px}
.meter{display:inline-flex;align-items:center;gap:8px;min-width:120px}
.meter-track{flex:1;height:6px;border-radius:3px;background:var(--border);overflow:hidden;min-width:60px}
.meter-fill{display:block;height:100%;border-radius:3px;background:var(--k)}
.meter-v{font-size:12px;font-variant-numeric:tabular-nums;color:var(--muted);min-width:36px;text-align:right}

/* timeline */
.timeline{position:relative;padding-left:22px}
.timeline::before{content:"";position:absolute;left:6px;top:10px;bottom:10px;width:2px;border-radius:2px;background:var(--border)}
.block{position:relative;margin:0 0 12px;padding:12px 16px 13px;border-radius:11px;
  background:var(--k-bg);border:1px solid color-mix(in srgb,var(--k) 16%,transparent)}
.block::before{content:"";position:absolute;left:-21px;top:17px;width:10px;height:10px;border-radius:50%;
  background:var(--surface);border:2px solid var(--k)}
.block .label{display:flex;align-items:center;gap:8px;margin-bottom:6px;font-size:11.5px;font-weight:650;
  letter-spacing:.04em;text-transform:uppercase;color:var(--k)}
.block .aside{margin-left:auto;font:500 11px var(--mono);letter-spacing:0;text-transform:none;color:var(--faint)}
.block.t-highlight{box-shadow:0 0 0 3px color-mix(in srgb,var(--highlight) 8%,transparent)}

/* text & code */
.prose{white-space:pre-wrap;word-break:break-word;font-size:14.5px;line-height:1.7}
.fade{color:var(--faint)}
.codewrap{position:relative;margin-top:6px}
.code{margin:0;padding:12px 14px;border-radius:9px;background:var(--surface-2);border:1px solid var(--border);
  font:12.5px/1.6 var(--mono);white-space:pre-wrap;word-break:break-word;overflow:auto;max-height:560px}
.block .code{background:color-mix(in srgb,var(--surface) 70%,transparent)}
.lang{position:absolute;top:7px;right:54px;font:600 10px var(--mono);letter-spacing:.06em;text-transform:uppercase;color:var(--faint)}
.copy{position:absolute;top:5px;right:6px;height:22px;padding:0 8px;border-radius:6px;border:1px solid var(--border);
  background:var(--surface);color:var(--muted);font:11px var(--sans);cursor:pointer;opacity:0;transition:opacity .15s}
.codewrap:hover .copy{opacity:1}
.j-key{color:var(--accent)}.j-str{color:var(--success)}.j-num{color:var(--warn)}.j-lit{color:var(--info);font-weight:600}
.call{margin-top:10px;border:1px solid var(--border);border-radius:10px;background:var(--surface);overflow:hidden}
.call-head{display:flex;align-items:center;gap:8px;padding:7px 12px;font-size:12.5px;
  background:var(--surface-2);border-bottom:1px solid var(--border)}
.call-icon{display:inline-grid;place-items:center;width:18px;height:18px;border-radius:5px;font:italic 700 12px Georgia,serif;
  color:#fff;background:var(--accent)}
.call-name{font:600 12.5px var(--mono);color:var(--accent)}
.call .aside{margin-left:auto;font:11px var(--mono);color:var(--faint)}
.call .codewrap{margin:0}.call .code{border:0;border-radius:0;background:transparent}
details>summary{list-style:none;cursor:pointer;user-select:none}
details>summary::-webkit-details-marker{display:none}
.more>summary{display:inline-flex;align-items:center;gap:5px;margin-top:6px;font-size:12.5px;color:var(--accent-ui)}
.more>summary::before,.fold>summary::before{content:"";width:6px;height:6px;border-right:1.6px solid currentColor;
  border-bottom:1.6px solid currentColor;transform:rotate(-45deg);transition:transform .15s;margin-right:3px}
details[open]>summary::before{transform:rotate(45deg)}
.more[open]>summary{margin-bottom:6px}
.fold{margin:10px 0;border:1px solid var(--border);border-radius:10px;background:var(--surface-2)}
.fold>summary{display:flex;align-items:center;gap:6px;padding:9px 14px;font-size:13px;color:var(--muted)}
.fold>summary:hover{color:var(--text)}
.fold-body{padding:0 14px 12px}
.kv{border-collapse:collapse;font-size:13px;margin-top:8px}
.kv th{text-align:left;font-weight:500;color:var(--muted);padding:3px 18px 3px 0;white-space:nowrap;vertical-align:top}
.kv td{padding:3px 0;font-family:var(--mono);font-size:12.5px;word-break:break-all}

/* images */
.gallery{display:flex;flex-wrap:wrap;gap:12px;margin-top:10px}
.gallery figure{margin:0;display:flex;flex-direction:column;align-items:center;min-width:0}
.gallery img{display:block;height:var(--thumb,168px);width:auto;max-width:300px;object-fit:contain;border-radius:9px;cursor:zoom-in;
  border:1px solid var(--border);transition:transform .18s,box-shadow .18s;
  background:var(--surface-2) conic-gradient(var(--border) 25%,transparent 0 50%,var(--border) 0 75%,transparent 0) 0 0/14px 14px}
.gallery img:hover{transform:translateY(-2px);box-shadow:var(--shadow-hover)}
.gallery figcaption{margin-top:6px;font:11px var(--mono);color:var(--faint);max-width:300px;
  white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.gallery.hero{margin:18px 0 6px}
.gallery.hero figure{width:100%}
.gallery.hero img{height:auto;max-height:560px;max-width:100%;border-radius:12px}
.compare{display:grid;grid-template-columns:repeat(var(--cols,2),minmax(0,1fr));gap:14px;margin-top:10px}
.compare .col{min-width:0;border:1px solid var(--border);border-radius:11px;padding:12px 14px;background:var(--surface-2)}
.compare .col-title{font-size:12px;font-weight:650;letter-spacing:.04em;text-transform:uppercase;color:var(--muted);margin-bottom:8px}
.compare .gallery img{height:auto;max-height:420px;max-width:100%}

/* lightbox */
.lightbox{position:fixed;inset:0;z-index:100;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:14px;
  background:rgba(8,10,14,.9);backdrop-filter:blur(6px);animation:fade .15s}
.lightbox[hidden]{display:none}
.lightbox img{max-width:94vw;max-height:84vh;border-radius:10px;box-shadow:0 24px 70px rgba(0,0,0,.55);background:#fff}
.lb-cap{font:12.5px var(--mono);color:#c9ced8}
.lb-close{position:absolute;top:16px;right:20px;width:38px;height:38px;border-radius:50%;border:0;
  background:rgba(255,255,255,.1);color:#fff;font-size:22px;cursor:pointer}
.lb-close:hover{background:rgba(255,255,255,.2)}
@keyframes fade{from{opacity:0}to{opacity:1}}

.empty{padding:60px 0;text-align:center;color:var(--faint)}
.foot{margin:36px 0 10px;text-align:center;font-size:12px;color:var(--faint);line-height:1.9}
.keys{opacity:.8}
@media print{.topbar,.toc,.copy,.facets{display:none}.layout{display:block;padding:0}.card{box-shadow:none;break-inside:avoid}}
"""

JS = r"""
(() => {
  const $ = (s, r = document) => r.querySelector(s), $$ = (s, r = document) => [...r.querySelectorAll(s)];
  const root = document.documentElement;

  $("#hv-theme").onclick = () => {
    root.dataset.theme = root.dataset.theme === "dark" ? "light" : "dark";
    localStorage.setItem("hv-theme", root.dataset.theme);
  };

  // copy buttons
  $$(".codewrap").forEach(w => {
    const b = document.createElement("button");
    b.className = "copy"; b.type = "button"; b.textContent = "__COPY__";
    b.onclick = () => navigator.clipboard?.writeText($("pre", w).innerText).then(() => {
      b.textContent = "__COPIED__"; setTimeout(() => b.textContent = "__COPY__", 1200);
    });
    w.appendChild(b);
  });

  // expand / collapse all
  const ex = $("#hv-expand"); let open = false;
  ex.onclick = () => { open = !open; $$("details").forEach(d => d.open = open);
    ex.textContent = open ? "__COLLAPSE_ALL__" : "__EXPAND_ALL__"; };

  // tabs
  $$(".tab").forEach(t => t.onclick = () => {
    const bar = t.parentElement;
    $$(".tab", bar).forEach(x => { x.classList.toggle("on", x === t); document.getElementById(x.dataset.tab).hidden = x !== t; });
  });

  // sortable tables
  $$("table.data").forEach(tbl => $$("th", tbl).forEach((th, col) => $(".sort", th).onclick = () => {
    const dir = th.getAttribute("aria-sort") === "ascending" ? "descending" : "ascending";
    $$("th", tbl).forEach(x => x.removeAttribute("aria-sort")); th.setAttribute("aria-sort", dir);
    const body = tbl.tBodies[0], rows = [...body.rows], s = dir === "ascending" ? 1 : -1;
    const val = r => r.cells[col]?.dataset.v ?? "";
    rows.sort((a, b) => { const x = val(a), y = val(b), nx = parseFloat(x), ny = parseFloat(y);
      if (x === "" && y !== "") return 1; if (y === "" && x !== "") return -1;
      return (!isNaN(nx) && !isNaN(ny) && /^-?[\d.eE+-]+$/.test(x) && /^-?[\d.eE+-]+$/.test(y))
        ? s * (nx - ny) : s * x.localeCompare(y, undefined, {numeric: true}); });
    rows.forEach(r => body.appendChild(r));
  }));

  // filtering: search (cards + table rows) and facets (cards)
  const cards = $$(".card"), rows = $$("tr[data-row]"), q = $("#hv-search"),
        count = $("#hv-count"), empty = $("#hv-empty");
  const tocFor = id => $(`.toc a[href="#${CSS.escape(id)}"]`);
  const sel = {};  // group -> Set(values)
  $$(".facet").forEach(f => { const g = f.dataset.group; sel[g] = new Set();
    $$(".pill", f).forEach(p => p.onclick = () => {
      const v = p.dataset.val;
      if (!v) sel[g].clear(); else sel[g].has(v) ? sel[g].delete(v) : sel[g].add(v);
      $$(".pill", f).forEach(x => x.classList.toggle("on", x.dataset.val ? sel[g].has(x.dataset.val) : !sel[g].size));
      apply();
    }); });
  const facetOk = c => { const tags = (c.dataset.tags || "").split("|");
    return Object.entries(sel).every(([g, vs]) => !vs.size || [...vs].some(v => tags.includes(`${g}:${v}`))); };
  function apply() {
    const term = q.value.trim().toLowerCase(); let n = 0;
    cards.forEach(c => { const hit = facetOk(c) && (!term || c.textContent.toLowerCase().includes(term));
      c.classList.toggle("hidden", !hit); tocFor(c.id)?.classList.toggle("hidden", !hit); n += hit; });
    rows.forEach(r => r.classList.toggle("hidden", !!term && !r.textContent.toLowerCase().includes(term)));
    const filtered = term || Object.values(sel).some(s => s.size);
    count.textContent = filtered ? `${n} / ${cards.length} __ITEMS__` : `${cards.length} __ITEMS__`;
    empty.hidden = n > 0;
  }
  let t; q.oninput = () => { clearTimeout(t); t = setTimeout(apply, 120); };

  // active TOC entry
  if ("IntersectionObserver" in window && $(".toc")) {
    const io = new IntersectionObserver(es => es.forEach(e => {
      if (e.isIntersecting) { $$(".toc a.active").forEach(a => a.classList.remove("active"));
        const a = tocFor(e.target.id); if (a) { a.classList.add("active"); a.scrollIntoView({block: "nearest"}); } }
    }), {rootMargin: "-90px 0px -65% 0px"});
    cards.forEach(c => io.observe(c));
  }

  // lightbox
  const lb = $("#hv-lb"), lbImg = $("img", lb), lbCap = $(".lb-cap", lb); let group = [], idx = 0;
  const show = i => { idx = (i + group.length) % group.length; const im = group[idx];
    lbImg.src = im.dataset.full || im.src; lbCap.textContent = `${im.dataset.caption || ""}  ${idx + 1}/${group.length}`; };
  document.addEventListener("click", e => {
    const im = e.target.closest(".gallery img"); if (!im) return;
    group = $$(".gallery img", im.closest(".card") || document); show(group.indexOf(im)); lb.hidden = false;
  });
  lb.onclick = e => { if (e.target !== lbImg) lb.hidden = true; };

  // keyboard
  const visible = () => cards.filter(c => !c.classList.contains("hidden"));
  document.addEventListener("keydown", e => {
    if (!lb.hidden) { if (e.key === "Escape") lb.hidden = true;
      if (e.key === "ArrowRight") show(idx + 1); if (e.key === "ArrowLeft") show(idx - 1); return; }
    if (e.target.matches("input,textarea")) { if (e.key === "Escape") { q.value = ""; apply(); q.blur(); } return; }
    if (e.key === "/") { e.preventDefault(); q.focus(); return; }
    if (e.key === "j" || e.key === "k") {
      const vs = visible(), y = window.scrollY + 100;
      let i = e.key === "j" ? vs.findIndex(c => c.offsetTop > y + 5)
                            : vs.map(c => c.offsetTop < y - 5).lastIndexOf(true);
      if (i === -1) i = e.key === "j" ? vs.length - 1 : 0;
      vs[i]?.scrollIntoView({behavior: "smooth"});
    }
  });
})();
"""
