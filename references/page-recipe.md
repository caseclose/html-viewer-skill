# Page recipe

Build scripts import `viewer_kit` and assemble pages from its helpers. Don't put
CSS in build scripts; if the kit lacks something, add it to the kit so every page
gets it.

```python
import os, sys
from pathlib import Path
sys.path.insert(0, "SKILL_DIR/scripts")  # absolute path of this skill's scripts/
import viewer_kit as vk

ROOT = Path(__file__).resolve().parent   # the directory you will serve
vk.set_lang("zh")                        # or "en"; call before building content
```

## API

**Page**

| Helper | Use for |
|---|---|
| `page(title, cards, toc=, subtitle=, summary_html=, facets=, footer=, wide=)` | Whole document: topbar (title, count, search, expand-all, theme), optional sidebar TOC, facet filters, footer. `wide=True` for table/grid-heavy pages. |
| `stat_row([(label, value[, tone[, hint]]), ...])` | Summary tiles on top (`summary_html=`). |
| `card(anchor, index, title, body, meta=, chips=, status=, status_label=, tags=, compact=)` | One record or panel. `status` → badge + TOC dot; `tags=["group:value"]` → facet filtering. |

**Containers**

| Helper | Use for |
|---|---|
| `table(columns, rows, max_rows=, align=, row_kinds=, caption=)` | Sortable table; search filters rows. Cells: numbers, text, None, dict/list, or Html (badge, meter, link, gallery). |
| `tabs([(label, html), ...])` | Several views of the same thing. |
| `grid(items, min_width=)` | Responsive grid, usually of `card(..., compact=True)`. |
| `compare([(title, html), ...])` | Side-by-side variants. |
| `timeline([block(...), ...])` | Ordered events / steps / messages. |
| `block(kind, label, body, aside=)` | One timeline entry; `kind` is a tone or alias. |
| `fold(summary, html, open_=False)` | Collapsed secondary detail. |
| `section(title)` | Divider inside a card. |

**Content**

| Helper | Use for |
|---|---|
| `text(s, limit=700)` | Prose; long text previews and expands. |
| `code(obj_or_str, limit=1200, lang=)` | Monospace + copy button; JSON highlighted. |
| `call(name, arguments, aside=)` | A function/API/tool invocation with its arguments. |
| `kv([(k, v), ...])` | Metadata table; values may be Html. |
| `gallery([(path, caption[, thumb]), ...], root, hero=, size=)` | Images; click → lightbox, ←/→ within the card. |
| `badge(label, kind)` · `chip(label, value)` · `meter(value, max, label=, kind=)` · `link(href, label)` | Inline bits. |
| `raw(html)` · `esc(s)` · `rel(path, root)` · `fmt(value)` | Escape hatch / helpers. |

**Tones**: `info, success, accent, warn, highlight, danger, muted`. Anywhere a
`kind`/`status`/tone is accepted you can also pass an alias from `TONE_ALIASES`
(`ok, pass, fail, error, warning, user, assistant, tool, added, removed, ...`).
Add your own aliases to the dict in the build script if the domain has its own
vocabulary: `vk.TONE_ALIASES.update({"regressed": "danger", "improved": "success"})`.

Helpers escape plain text. To put markup where text is expected, pass another
helper's output or wrap with `vk.raw`. Note `Html + str` is a plain `str` again —
wrap concatenations: `vk.raw(a + b)`.

## Patterns

### Results / eval dashboard (table-first)

```python
rows, kinds = [], []
for r in results:
    rows.append([r["case"], r["model"], r["score"], vk.meter(r["pass_rate"]),
                 vk.badge(r["status"], r["status"])])
    kinds.append("fail" if r["status"] == "fail" else "")
summary = vk.stat_row([("cases", len(results)), ("pass rate", f"{rate:.1%}", "ok"),
                       ("failures", n_fail, "fail")])
by_model = vk.tabs([(m, vk.table(cols, rows_for[m])) for m in models])
cards = [vk.card("all", "", "All results", vk.table(cols, rows, row_kinds=kinds)),
         vk.card("by-model", "", "By model", by_model)]
html = vk.page("Eval 2026-10-30", cards, summary_html=summary, wide=True)
```

### Record browser (card per item, facets)

```python
cards, toc = [], []
for n, rec in enumerate(records, 1):
    body = vk.gallery([(rec["image"], "output")], ROOT, hero=True) + vk.kv(scalars(rec))
    body += vk.fold("raw", vk.code(rec))
    cards.append(vk.card(f"r{n}", f"#{n}", rec["title"], body, meta=rec["id"],
                         status=rec["status"], tags=[f"split:{rec['split']}"]))
    toc.append((f"r{n}", rec["title"][:40], rec["status"]))
html = vk.page("Records", cards, toc=toc, facets=[("split", ["train", "dev", "test"])])
```

### A/B or before/after

```python
for case in cases:
    body = vk.compare([(name, vk.gallery([(case[name], name)], ROOT) + vk.text(case[f"{name}_note"]))
                       for name in ("baseline", "candidate")])
    cards.append(vk.card(case["id"], "", case["prompt"], body, status=case["winner_status"]))
```

Keep column order identical on every card and say which is which in the subtitle.

### Image set / gallery wall

```python
tiles = [vk.card(f"i{n}", "", p.stem, vk.gallery([(p, "", thumb(p))], ROOT), compact=True,
                 tags=[f"folder:{p.parent.name}"]) for n, p in enumerate(images)]
html = vk.page("Images", [vk.grid(tiles, 240)], facets=[("folder", folders)], wide=True)
```

(Facets and search act on `.card` elements, so they also work on cards inside a grid.)

### Trace / timeline (logs, pipelines, agent runs, events)

```python
steps = [vk.block(ev["level"], ev["stage"], vk.text(ev["message"]) +
                  (vk.call(ev["fn"], ev["args"]) if ev.get("fn") else ""), aside=ev["time"])
         for ev in events]
body = vk.gallery([(final_output, "result")], ROOT, hero=True) + vk.section("steps") + vk.timeline(steps)
```

Map the domain's step types to tones once (e.g. `{"input": "info", "output": "success",
"call": "accent", "retry": "warn", "error": "danger", "result": "highlight"}`).

### Multi-page

For thousands of items, split by group into several pages and make an index page
whose table links to them (`vk.link("group_a.html", "group a")`). One page the
browser can Ctrl-F beats many, so only split when a page gets slow.

## Gotchas

- **Relative paths.** `gallery`/`img` take `root`; pass the directory you serve.
  Files outside it 404 — symlink them in or serve a common parent.
- **Thumbnails.** If the data has thumbnails, pass them as the third tuple element;
  the lightbox still opens the full file.
- **Escaping.** Data often contains `<script>`, `&`, `<`; helpers escape, raw
  f-strings don't.
- **Encoding.** Read and write with `encoding="utf-8"`.
- **Language.** `vk.set_lang("en")` before building for English labels.
