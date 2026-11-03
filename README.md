# html-viewer-skill

[English](#english) · [中文](#中文)

---

## English

A [Claude Code](https://claude.com/claude-code) skill that turns local data into a
good-looking web page or dashboard and serves it over a local HTTP server that
is reachable from both this machine and the LAN. No session key by default.

### What's inside

| File | Purpose |
|---|---|
| `SKILL.md` | When and how Claude uses the skill: workflow, design bar, serving rules. |
| `scripts/quick_view.py` | Zero-code views for CSV/TSV, JSON/JSONL, logs, Markdown/text, images, directories. |
| `scripts/viewer_kit.py` | Component library: theme (light/dark), sidebar TOC, search, facet filters, sortable tables, tabs, grids, galleries with lightbox, timelines, JSON highlighting. Outputs one self-contained HTML file, no CDN. |
| `scripts/serve_viewer.py` | Serves a directory on `0.0.0.0` with no key, prints `VIEWER_URL` + reachable `LAN_URL`s (each probed at startup); `--local-only`, `--require-key`, `--lan-ip`, `--list` / `--stop`. |
| `references/page-recipe.md` | API reference and patterns (eval dashboard, record browser, A/B compare, image wall, timeline). |

Python 3.8+, standard library only.

### Install

```bash
git clone https://github.com/caseclose/html-viewer-skill ~/.claude/skills/html-viewer
```

For a single project instead, clone into `<project>/.claude/skills/html-viewer`.
The skill locates its scripts relative to its own directory, so either location works.

### Use without Claude

```bash
python3 scripts/quick_view.py results.csv            # writes results.view.html next to it
python3 scripts/serve_viewer.py --dir . --page results.view.html
# printed: VIEWER_URL http://127.0.0.1:8800/results.view.html
#          LAN_URL    http://192.168.1.23:8800/results.view.html
```

Open `VIEWER_URL` on this machine, or `LAN_URL` from a phone / another computer
on the same network. There is no `?key=...` to copy. Use `--lan-ip IP` if
auto-detection misses an interface, `--local-only` to bind loopback only, and
`--require-key` to restore the original keyed URLs.

From a different network: `ssh -L PORT:127.0.0.1:PORT user@host`, then open the
loopback URL with `localhost`.

### Security

The viewer has **no authentication by default** and binds `0.0.0.0`, so any
device on the same LAN that can reach the port can read the served directory.
Only use it on a trusted network, serve a directory with no secrets, and stop it
with `--stop PORT` when done. `--local-only` restricts it to this machine;
`--require-key` adds a random `?key=...` gate (HTTP is plaintext, so the keyed
URL is the credential). An OS firewall may prompt for permission to accept
incoming connections.

---

## 中文

一个 [Claude Code](https://claude.com/claude-code) skill：把本地任意数据（表格、JSON/JSONL、日志、图片目录、评测结果、轨迹……）做成好看的网页或看板，通过本机 HTTP 服务打开，本机与局域网都能访问，默认不带密钥。

### 包含什么

| 文件 | 作用 |
|---|---|
| `SKILL.md` | Claude 何时、如何使用这个 skill：工作流程、设计要求、起服务的规则。 |
| `scripts/quick_view.py` | 不用写代码，直接把 CSV/TSV、JSON/JSONL、日志、Markdown/文本、图片、目录生成网页。 |
| `scripts/viewer_kit.py` | 组件库：主题（浅色/深色）、侧边目录、搜索、筛选按钮、可排序表格、标签页、网格、可放大的图片墙、时间线、JSON 高亮。输出单个自包含的 HTML 文件，不依赖 CDN。 |
| `scripts/serve_viewer.py` | 默认监听 `0.0.0.0`、无密钥，输出 `VIEWER_URL`（本机）与 `LAN_URL`（局域网，启动时逐个探测可达性）；支持 `--local-only`、`--require-key`、`--lan-ip`、`--list` / `--stop`。 |
| `references/page-recipe.md` | API 说明和常见写法（评测看板、逐条浏览、A/B 对比、图片墙、时间线）。 |

需要 Python 3.8+，只用标准库。

### 安装

```bash
git clone https://github.com/caseclose/html-viewer-skill ~/.claude/skills/html-viewer
```

只给某个项目用的话，克隆到 `<项目>/.claude/skills/html-viewer`。skill 按自身所在目录定位脚本，两种位置都能用。

### 不通过 Claude 直接使用

```bash
python3 scripts/quick_view.py results.csv            # 在同目录生成 results.view.html
python3 scripts/serve_viewer.py --dir . --page results.view.html
# 输出：VIEWER_URL http://127.0.0.1:8800/results.view.html
#       LAN_URL    http://192.168.1.23:8800/results.view.html
```

本机打开 `VIEWER_URL`，同一局域网内的手机或其他电脑打开 `LAN_URL`，无需复制 `?key=...`。自动探测漏掉网卡时用 `--lan-ip IP` 补上；`--local-only` 只监听本机；`--require-key` 恢复原来的带密钥链接。

跨网段访问：先执行 `ssh -L 端口:127.0.0.1:端口 用户@主机`，再把链接里的地址换成 `localhost` 打开。

### 安全说明

**默认不带任何鉴权**，且监听 `0.0.0.0`：同一局域网内能访问该端口的设备都可以读取被托管的目录。请只在可信内网使用，不要托管含密钥、令牌、`.env` 或凭据的目录，用完执行 `--stop 端口` 关闭。`--local-only` 可限制为仅本机访问；`--require-key` 可恢复随机 `?key=...` 密钥（HTTP 明文，带密钥的链接即凭证）。系统防火墙可能弹出「允许接受传入连接」的授权提示。
