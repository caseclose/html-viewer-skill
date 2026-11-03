---
name: html-viewer
description: Build and serve local HTML views of data, logs, images, evaluation results, and traces. Use for requests such as “用网页展示”, “起个 HTTP 服务看看”, or a local dashboard; also list or stop existing viewers. Supports loopback and LAN URLs, optional session keys, and no external upload. Not for deploying a public website.
---

# HTML viewer

Turn local content into a readable, interactive page using Python 3.8+ and the
standard library. Locate `scripts/` relative to this file, independent of the
installation directory. Quote filesystem paths in shell commands.

## Choose the view

Inspect representative records and the user's question before choosing a layout.
Identify the record unit, outcome fields, long/nested values, and local assets.

For CSV/TSV, JSON/JSONL, logs, text, images, or a directory, use:

```bash
python3 "$SKILL_DIR/scripts/quick_view.py" "<input>" --lang zh --limit 2000
```

The output defaults to `<input-stem>.view.html` next to a file, or
`index.view.html` inside a directory. The command prints the exact serve command.
`--out`, `--title`, and `--lang en` customize output. JSON/CSV select the first N
records, logs the last N lines, and directories at most N files; displayed counts
and rates describe that selection. Markdown is shown as escaped text.

For comparisons, joined sources, or ordered traces, write a reproducible build
script beside the output and import `viewer_kit` from this skill's `scripts/`.
Read [references/page-recipe.md](references/page-recipe.md) for the API and
examples. Use a custom build directly when quick_view cannot express the task.
Do not modify the installed skill just to style one report.

## Make the first screen useful

- Put the requested conclusion and relevant counts/metrics first. Identify any
  sampling, truncation, missing records, or incomplete runs.
- Use a sortable table for comparable rows, cards for heterogeneous records,
  stable columns for A/B comparisons, and a timeline for ordered events.
- Give cards readable titles; keep identifiers and paths in metadata. Use
  consistent status colours, and add facets where they help narrow the data.
- Collapse raw JSON, long prompts, and secondary configuration. Leave primary
  results visible. Omit empty sections and move constant fields out of tables.
- Use existing thumbnails and linked assets. The kit embeds CSS/JS and needs no
  CDN; images remain separate files. For charts, embed locally generated SVG
  or another local asset; no additional skill is required.

## Serve and verify

Check existing viewers before starting one; reuse only when its directory and
access mode suit this task:

```bash
python3 "$SKILL_DIR/scripts/serve_viewer.py" --list
python3 "$SKILL_DIR/scripts/serve_viewer.py" --dir "<view-directory>" --page "<page.html>"
```

Use the environment's supported background process mechanism, keeping its
process/session handle and startup output. `--page` is a literal relative disk
path, including Chinese, spaces, `#`, `?`, or `%`; do not URL-encode it yourself.
The entry must exist. Default ports are 8800–8899; `--port N` selects one.

The default remains **all IPv4 interfaces (`0.0.0.0`), no authentication**.
Anyone able to reach the port can read the served directory, including through
VPN/public interfaces if routing and firewalls allow it. Use a trusted network
and the smallest directory containing the page and intended assets. Check
symlink targets too; hidden files are not blocked by the HTTP server.

- `--local-only`: listen on `127.0.0.1`, without LAN URLs.
- `--require-key`: require a random session key; the first keyed browser request
  sets a cookie so relative assets work. Cookies are host scoped: open the keyed
  entry on each hostname used. HTTP and keyed URLs remain plaintext credentials.
- `--lan-ip IP`: supplement detection with an IPv4 address assigned to this host.

Fetch `VIEWER_URL` and one representative asset. In key mode, use a cookie jar
or append the session key to the asset request. Verify the rendered page when
browser tools are available: layout, image loading, search, tabs, and filters
relevant to the view. Never upload source content to an external rendering or
hosting service.

Hand over the loopback URL, available `LAN_URL` values, a brief description,
regeneration command if custom-built, and the stop command. A LAN URL means
**a HEAD probe succeeded on the serving host**, not that another device reached
it. State this limit unless cross-device access was actually tested. If there
is no LAN URL or `--local-only` was chosen, say so; do not invent a working link
or widen access to satisfy a handover rule.

For remote hosts, port forwarding and common failures are described in
[references/serving.md](references/serving.md). Keep the key when forwarding a
keyed URL. When finished, stop only the viewer(s) belonging to the task:

```bash
python3 "$SKILL_DIR/scripts/serve_viewer.py" --stop <PORT>
# --stop all only when the user wants every listed viewer stopped
```
