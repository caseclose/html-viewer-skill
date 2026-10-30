# html-viewer-skill

A [Claude Code](https://claude.com/claude-code) skill that turns local data into a
good-looking web page or dashboard and serves it over a key-gated localhost HTTP
server.

把本地任意数据（表格、JSON/JSONL、日志、图片目录、评测结果、轨迹……）做成好看的网页看板，并通过本机 HTTP 服务打开。

## What's inside

| File | Purpose |
|---|---|
| `SKILL.md` | When and how Claude uses the skill: workflow, design bar, serving rules. |
| `scripts/quick_view.py` | Zero-code views for CSV/TSV, JSON/JSONL, logs, Markdown/text, images, directories. |
| `scripts/viewer_kit.py` | Component library: theme (light/dark), sidebar TOC, search, facet filters, sortable tables, tabs, grids, galleries with lightbox, timelines, JSON highlighting. Outputs one self-contained HTML file, no CDN. |
| `scripts/serve_viewer.py` | Serves a directory on `127.0.0.1` with a per-session key; `--list` / `--stop`. |
| `references/page-recipe.md` | API reference and patterns (eval dashboard, record browser, A/B compare, image wall, timeline). |

Python 3.8+, standard library only.

## Install

```bash
git clone https://github.com/caseclose/html-viewer-skill ~/.claude/skills/html-viewer
```

The docs reference `~/.tclaude/skills/html-viewer`; if you install elsewhere, update
that path in `SKILL.md` and `references/page-recipe.md`.

## Use without Claude

```bash
python3 scripts/quick_view.py results.csv            # writes results.view.html next to it
python3 scripts/serve_viewer.py --dir . --page results.view.html
# open the printed VIEWER_URL (it includes ?key=...)
```

From another machine: `ssh -L PORT:127.0.0.1:PORT user@host`, then open the URL
with `localhost`.

## Security

The server binds loopback only and requires a random key on every request. It
never exposes itself to the network; doing that is left to the user, deliberately.
