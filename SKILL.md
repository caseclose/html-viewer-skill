---
name: html-viewer
description: Build a good-looking local web page or dashboard from any data and serve it over a local HTTP server that prints both loopback and LAN URLs (no key by default; optional --require-key) — tables of results, metrics and eval summaries, experiment/run comparisons, JSON/JSONL/CSV records, logs, image sets and A/B comparisons, traces and timelines, directory listings, reports. Use when the user asks to "show me", "visualize", "make a dashboard / 看板", "open it in a web page / browser", "用网页展示", "起个 http 服务看看", or when a result is too large, nested, or image-heavy to read in the terminal. Also covers listing and stopping running viewers. Not for publishing to an external service; for chart design itself, also load dataviz.
---

# HTML viewer

Turn local content into a page or dashboard the user can look at in a browser,
served from their own machine. Three pieces, all in `scripts/`:

| Script | What it does |
|---|---|
| `quick_view.py` | Zero-code: renders a CSV/TSV, JSON/JSONL, log, Markdown/text file, image, or directory into a page. |
| `viewer_kit.py` | The component library: theme, layout, tables, cards, tabs, filters, galleries, timelines. Build scripts import it. |
| `serve_viewer.py` | Serves a directory over a local HTTP server (no key by default), prints loopback + LAN URLs; lists and stops viewers. |

`SKILL_DIR` below means the directory containing this `SKILL.md` (for a personal
install, `~/.claude/skills/html-viewer`); substitute its absolute path in the
commands. Needs Python 3.8+; on hosts where `python3` is older, use
`python3.9`/`python3.11` or a venv interpreter (`python3 -V` first).

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
sys.path.insert(0, "SKILL_DIR/scripts")  # absolute path of this skill's scripts/
import viewer_kit as vk
```

Script rather than hand-written HTML: data changes and the page gets regenerated,
the user can re-run it, and it scales past the records you looked at. API,
patterns for common dashboards, and gotchas: `references/page-recipe.md`.

### 4. Serve it

```bash
python3 $SKILL_DIR/scripts/serve_viewer.py --dir <DIR> [--page page.html] [--local-only] [--require-key]
```

Run in the background (`run_in_background: true`) and read the output. It prints
one `VIEWER_URL` (loopback) and one `LAN_URL` per LAN IPv4 address that answers
200 from this host; unreachable virtual/VPN addresses appear as
`LAN_URL_UNREACHABLE` and must not be handed to the user as working links.
**Hand the user both kinds of URL.** URLs are plain `http://host:port/page.html`
with no key. Default port is the first free one in 8800–8899; `--port` fixes it.
`--lan-ip IP` adds an address auto-detection missed; `--local-only` restricts
the server to `127.0.0.1`; `--require-key` restores a random `?key=...` gate.

By default the server binds `0.0.0.0` with **no authentication**. Anyone on the
same LAN who can reach the port can read the served directory. Use it only on a
trusted network, never serve a directory containing tokens, keys, `.env`, or
credentials, and stop the server when done. If the OS firewall blocks incoming
connections, the user must allow it locally. **Serve the directory holding the
page and the files it links to, nothing wider** — if assets live elsewhere,
symlink them in or serve a common parent.

### 5. Verify, then hand over

```bash
curl -s -o /dev/null -w "%{http_code}\n" "<VIEWER_URL>"
curl -s -o /dev/null -w "%{http_code}\n" "<LAN_URL>"
```

and fetch one image the page references. Then give the user both URLs, one line
on what's on the page, and how to stop it. The script probes each candidate IP
at startup, but still verify the URL you hand over; if a LAN URL is not reachable
(firewall, wrong subnet), say so explicitly instead of presenting it as working.

### 6. Other networks

Same LAN → open the `LAN_URL` directly; no tunnel needed.

Different network / internet → forward the loopback port over SSH and open the
loopback URL on the remote machine:
`ssh -L <PORT>:127.0.0.1:<PORT> user@<host>`, then
`http://localhost:<PORT>/<page>`.

Never leave an unauthenticated viewer on an untrusted network. If the page must
be reachable beyond a trusted LAN, add `--require-key` (and prefer the SSH
tunnel) so the URL carries a session key; remind the user that HTTP is plaintext
and the keyed URL is the credential.

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

`--list` shows the bind address, auth mode and every printed URL. Check `--list`
before starting another. Ports held by other processes are skipped automatically;
leave those alone.

## Rules

- **Never upload the content** to an external service to make it viewable.
- **Give both URLs.** Hand over the loopback `VIEWER_URL` and at least one
  `LAN_URL`; verify before claiming a LAN URL works.
- **No key by default.** The default server is unauthenticated and LAN-reachable;
  trusted networks only, only a directory with no secrets, stop it when done.
- **Link files, don't inline them.** Relative paths to images; no base64 of large
  files.
- **Keep the build script** next to the output and tell the user the one-line
  command to regenerate.
