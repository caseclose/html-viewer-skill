---
name: html-viewer
description: Build a good-looking local web page or dashboard from any data and serve it over a key-gated localhost HTTP server — tables of results, metrics and eval summaries, experiment/run comparisons, JSON/JSONL/CSV records, logs, image sets and A/B comparisons, traces and timelines, directory listings, reports. Use when the user asks to "show me", "visualize", "make a dashboard / 看板", "open it in a web page / browser", "用网页展示", "起个 http 服务看看", or when a result is too large, nested, or image-heavy to read in the terminal. Also covers listing and stopping running viewers. Not for publishing to an external service; for chart design itself, also load dataviz.
---

# HTML viewer

Turn local content into a page or dashboard the user can look at in a browser,
served from their own machine. Three pieces, all in `scripts/`:

| Script | What it does |
|---|---|
| `quick_view.py` | Zero-code: renders a CSV/TSV, JSON/JSONL, log, Markdown/text file, image, or directory into a page. |
| `viewer_kit.py` | The component library: theme, layout, tables, cards, tabs, filters, galleries, timelines. Build scripts import it. |
| `serve_viewer.py` | Serves a directory on 127.0.0.1 with a per-session key; lists and stops viewers. |

`SKILL_DIR` below means the directory containing this file
(`~/.tclaude/skills/html-viewer` here; adjust the paths in this file and in
`references/page-recipe.md` if installed elsewhere, e.g. `~/.claude/skills/html-viewer`). Needs Python 3.8+; on hosts where `python3` is
older, use `python3.9`/`python3.11` or a venv interpreter (`python3 -V` first).

## Workflow

### 1. Look at the data first

Read a few records / lines / files and work out the real shape: what one "item"
is, which fields are identifiers, which hold the outcome (status, score, verdict),
which point at images, which are long or nested. Then decide what the user
actually wants to learn from the page — that sets what goes on top.

### 2. Try quick_view, then decide

```bash
python3 $SKILL_DIR/scripts/quick_view.py <INPUT> [--out page.html] [--title T] [--lang zh|en]
```

It picks a layout from the input type: flat records → sortable table; nested
records → one card each with facets for low-cardinality fields and status from
`status`/`pass`/`success`-like fields; logs → level-tinted table with counts; a
directory → images grouped by folder plus a file table. It writes the page next to
the input so relative image paths resolve.

If that answers the question, go to step 3. If not — the data has domain
structure (runs × metrics, before/after pairs, a trace with steps, several sources
joined), write a build script.

### 3. Or write a build script with viewer_kit

Create `build_<thing>_view.py` next to the data (outside any repo you don't want to
dirty). It reads the source and writes the page; the kit does all styling, so the
script never contains CSS:

```python
import os, sys
sys.path.insert(0, os.path.expanduser("~/.tclaude/skills/html-viewer/scripts"))
import viewer_kit as vk
```

Script rather than hand-written HTML: data changes and the page gets regenerated,
the user can re-run it, and it scales past the records you looked at. API,
patterns for common dashboards, and gotchas: `references/page-recipe.md`.

### 4. Serve it

```bash
python3 $SKILL_DIR/scripts/serve_viewer.py --dir <DIR> [--page page.html]
```

Run in the background (`run_in_background: true`) and read the `VIEWER_URL ...`
line — that URL carries the session key and is what you give the user. Default
port is the first free one in 8800–8899; `--port` fixes it.

The server binds `127.0.0.1` only and requires the key on every request.
**Serve the directory holding the page and the files it links to, nothing
wider** — check it doesn't contain tokens, keys, `.env`, or credentials. If assets
live elsewhere, symlink them in or serve a common parent.

### 5. Verify, then hand over

```bash
curl -s -o /dev/null -w "%{http_code}\n" "<VIEWER_URL>"
```

and fetch one image the page references (same `?key=`). Then give the user the
URL, one line on what's on the page, and how to stop it.

### 6. Remote machines

If the user's browser isn't on the serving machine, give them an SSH tunnel:
`ssh -L <PORT>:127.0.0.1:<PORT> user@<host>`, then
`http://localhost:<PORT>/<page>?key=...`.

If they want it open to the network instead, that's their decision and their
command to run — it exposes the directory to everyone who can reach the host. Give
them the command (in Claude Code, prefix with `!`) instead of starting it yourself:

```
! nohup python3 -m http.server <PORT> --bind 0.0.0.0 --directory <DIR> >/tmp/viewer.log 2>&1 &
```

Say that this plain server has no key, and remind them to stop it when done.

## Design bar

The page should look like a well-made internal tool, not a debug dump. The kit
handles the visuals; these are the editorial choices it can't make for you:

- **Answer first.** `stat_row` tiles on top with the numbers the user came for
  (counts, pass rate, best score, totals, errors). Each card leads with its
  headline (result image, verdict, key metric) before details.
- **Name things by content.** Card titles from a human-readable field (prompt,
  name, title, question); IDs and paths go in `meta`.
- **Status wherever it exists.** Pass/fail/warn → `status=` on cards (also colours
  the sidebar dot), `badge` in table cells, `row_kinds` to tint failing rows.
- **Colour is semantic.** Tones: info, success, accent, warn, highlight, danger,
  muted. Map domain words to them (`TONE_ALIASES` has presets for status, log
  levels, conversation roles, diffs) and use the same mapping across the page.
- **Pick the right container.** Many comparable rows → `table` (sortable).
  Heterogeneous records → `card` per record. Same item under several views →
  `tabs`. Variants of one case → `compare`. Many small items → `grid` of compact
  cards. Ordered events → `timeline`.
- **Let the user narrow down.** Facets for categorical fields (split, model,
  status); the search box filters cards and table rows automatically.
- **Collapse the secondary.** Configs, raw JSON, long prompts → `fold`. Primary
  text gets a higher `limit` than intermediate text.
- **No empty sections**, no columns that are always blank, no repeated constant
  fields — move constants to the subtitle or a `kv` at the top.
- **Charts**: the kit has `meter` for inline ratios. For real charts, load the
  `dataviz` skill and embed the SVG with `vk.raw(...)`.

Before handing over, picture the first screen: does it answer the user's question
without scrolling?

## Managing viewers

```bash
python3 $SKILL_DIR/scripts/serve_viewer.py --list
python3 $SKILL_DIR/scripts/serve_viewer.py --stop <PORT>    # or --stop all
```

Check `--list` before starting another. Ports held by other processes are skipped
automatically; leave those alone.

## Rules

- **Never upload the content** to an external service to make it viewable.
- **Link files, don't inline them.** Relative paths to images; no base64 of large
  files.
- **Keep the build script** next to the output and tell the user the one-line
  command to regenerate.
