# html-viewer-skill

[English](#english) · [中文](#中文)

---

## English

A [Claude Code](https://claude.com/claude-code) skill that turns local data into a
good-looking web page or dashboard and serves it over a key-gated localhost HTTP
server.

### What's inside

| File | Purpose |
|---|---|
| `SKILL.md` | When and how Claude uses the skill: workflow, design bar, serving rules. |
| `scripts/quick_view.py` | Zero-code views for CSV/TSV, JSON/JSONL, logs, Markdown/text, images, directories. |
| `scripts/viewer_kit.py` | Component library: theme (light/dark), sidebar TOC, search, facet filters, sortable tables, tabs, grids, galleries with lightbox, timelines, JSON highlighting. Outputs one self-contained HTML file, no CDN. |
| `scripts/serve_viewer.py` | Serves a directory on `127.0.0.1` with a per-session key; `--list` / `--stop`. |
| `references/page-recipe.md` | API reference and patterns (eval dashboard, record browser, A/B compare, image wall, timeline). |

Python 3.8+, standard library only.

### Install

```bash
git clone https://github.com/caseclose/html-viewer-skill ~/.claude/skills/html-viewer
```

The docs reference `~/.tclaude/skills/html-viewer`; if you install elsewhere, update
that path in `SKILL.md` and `references/page-recipe.md`.

### Use without Claude

```bash
python3 scripts/quick_view.py results.csv            # writes results.view.html next to it
python3 scripts/serve_viewer.py --dir . --page results.view.html
# open the printed VIEWER_URL (it includes ?key=...)
```

From another machine: `ssh -L PORT:127.0.0.1:PORT user@host`, then open the URL
with `localhost`.

### Security

The server binds loopback only and requires a random key on every request. It
never exposes itself to the network; doing that is left to the user, deliberately.

---

## 中文

一个 [Claude Code](https://claude.com/claude-code) skill：把本地任意数据（表格、JSON/JSONL、日志、图片目录、评测结果、轨迹……）做成好看的网页或看板，并通过只监听本机、带访问密钥的 HTTP 服务打开。

### 包含什么

| 文件 | 作用 |
|---|---|
| `SKILL.md` | Claude 何时、如何使用这个 skill：工作流程、设计要求、起服务的规则。 |
| `scripts/quick_view.py` | 不用写代码，直接把 CSV/TSV、JSON/JSONL、日志、Markdown/文本、图片、目录生成网页。 |
| `scripts/viewer_kit.py` | 组件库：主题（浅色/深色）、侧边目录、搜索、筛选按钮、可排序表格、标签页、网格、可放大的图片墙、时间线、JSON 高亮。输出单个自包含的 HTML 文件，不依赖 CDN。 |
| `scripts/serve_viewer.py` | 在 `127.0.0.1` 上提供目录访问，每次启动生成随机密钥；支持 `--list` 列出、`--stop` 关闭。 |
| `references/page-recipe.md` | API 说明和常见写法（评测看板、逐条浏览、A/B 对比、图片墙、时间线）。 |

需要 Python 3.8+，只用标准库。

### 安装

```bash
git clone https://github.com/caseclose/html-viewer-skill ~/.claude/skills/html-viewer
```

文档里写的路径是 `~/.tclaude/skills/html-viewer`；如果装在别的位置，请同步修改 `SKILL.md` 和 `references/page-recipe.md` 里的路径。

### 不通过 Claude 直接使用

```bash
python3 scripts/quick_view.py results.csv            # 在同目录生成 results.view.html
python3 scripts/serve_viewer.py --dir . --page results.view.html
# 打开输出的 VIEWER_URL（链接里带 ?key=...）
```

在另一台机器上看：先执行 `ssh -L 端口:127.0.0.1:端口 用户@主机`，再把链接里的地址换成 `localhost` 打开。

### 安全说明

服务只监听本机回环地址，每个请求都必须带上随机密钥。它不会自己对网络开放；是否对外开放刻意留给使用者自己决定。
