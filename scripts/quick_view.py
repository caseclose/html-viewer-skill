#!/usr/bin/env python3
"""Zero-code dashboard for common file types, built with viewer_kit.

    quick_view.py INPUT [--out PAGE.html] [--title T] [--lang zh|en] [--limit N]

INPUT may be:
  .csv / .tsv            sortable table (+ image thumbnails for image-path cells)
  .json / .jsonl         flat records -> table; nested records -> one card each,
                         with facets for low-cardinality fields and status from
                         status/pass/success-like fields
  .log / .txt / .out     log table, rows tinted by level, level counts on top
  .md                    readable text
  a directory            images grouped by sub-directory + file listing
  an image file          the image

The page is written next to the input by default (so relative image paths
resolve); serve that directory with serve_viewer.py. For anything this doesn't
render well, write a build script with viewer_kit instead.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import viewer_kit as vk  # noqa: E402

IMG_EXT = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".svg", ".avif"}
TITLE_KEYS = ("title", "name", "prompt", "Prompt", "question", "query", "instruction",
              "input", "text", "case_id", "id", "ID")
STATUS_KEYS = ("status", "result", "verdict", "pass", "passed", "success", "ok", "correct", "label")
GOOD = {"ok", "pass", "passed", "success", "succeeded", "true", "correct", "done", "completed", "yes", "1"}
BAD = {"fail", "failed", "failure", "error", "false", "wrong", "incorrect", "timeout", "crash", "no", "0"}
WARN = {"warn", "warning", "partial", "skipped", "skip", "pending", "unknown", "running"}
LEVEL = re.compile(r"\b(CRITICAL|FATAL|ERROR|WARN(?:ING)?|INFO|DEBUG|TRACE)\b")
LEVEL_TONE = {"CRITICAL": "danger", "FATAL": "danger", "ERROR": "danger", "WARN": "warn",
              "WARNING": "warn", "INFO": "info", "DEBUG": "muted", "TRACE": "muted"}


def status_of(value) -> str | None:
    s = str(value).strip().lower()
    if s in GOOD:
        return "ok"
    if s in BAD:
        return "fail"
    if s in WARN:
        return "warn"
    return None


def image_path(value, base: Path) -> Path | None:
    if not isinstance(value, str) or len(value) > 1024 or Path(value).suffix.lower() not in IMG_EXT:
        return None
    p = Path(value)
    p = p if p.is_absolute() else base / p
    return p if p.exists() else None


def is_scalar(v) -> bool:
    return v is None or isinstance(v, (str, int, float, bool))


# --------------------------------------------------------------------- records

def load_records(path: Path, limit: int) -> list:
    if path.suffix.lower() == ".jsonl":
        out = []
        with path.open(encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    out.append(json.loads(line))
                    if len(out) >= limit:
                        break
        return out
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict):
        # {"items": [...]} style: use the biggest list of dicts if there is one
        lists = [v for v in data.values() if isinstance(v, list) and v and isinstance(v[0], dict)]
        if lists:
            return max(lists, key=len)[:limit]
        return [data]
    return data[:limit] if isinstance(data, list) else [{"value": data}]


def records_page(path: Path, root: Path, recs: list, title: str) -> str:
    dicts = [r if isinstance(r, dict) else {"value": r} for r in recs]
    keys = list(dict.fromkeys(k for r in dicts for k in r))
    flat = all(is_scalar(r.get(k)) for r in dicts for k in keys)
    base = path.parent

    # status / facet candidates
    status_key = next((k for k in keys if k in STATUS_KEYS or k.lower() in STATUS_KEYS), None)
    statuses = [status_of(r.get(status_key)) if status_key else None for r in dicts]
    facet_keys = []
    for k in keys:
        vals = [r.get(k) for r in dicts if isinstance(r.get(k), (str, bool))]
        distinct = set(map(str, vals))
        if len(dicts) >= 4 and 2 <= len(distinct) <= 8 and len(vals) >= 0.8 * len(dicts) \
                and all(len(v) <= 40 for v in distinct):
            facet_keys.append(k)
    facet_keys = facet_keys[:4]

    stats = [("records", len(dicts)), ("fields", len(keys))]
    if status_key:
        c = Counter(statuses)
        stats += [("ok", c["ok"], "ok"), ("fail", c["fail"], "fail")]
        if c["warn"]:
            stats.append(("warn", c["warn"], "warn"))
        judged = c["ok"] + c["fail"]
        if judged:
            stats.append(("pass rate", f"{c['ok'] / judged:.1%}", "ok" if c["ok"] / judged >= 0.8 else "warn"))
    summary = vk.stat_row(stats)

    if flat and len(keys) <= 40:
        cols = keys
        rows = []
        for r in dicts:
            row = []
            for k in cols:
                v = r.get(k)
                img = image_path(v, base)
                if img:
                    row.append(vk.gallery([(img, "")], root, size=64))
                elif k == status_key and status_of(v):
                    row.append(vk.badge(v, status_of(v)))
                else:
                    row.append(v)
            rows.append(row)
        body = vk.table(cols, rows, row_kinds=[("fail" if s == "fail" else "") for s in statuses])
        card = vk.card("table", "", path.name, body, chips=[("rows", len(dicts)), ("columns", len(cols))])
        return vk.page(title, [card], subtitle=str(path), summary_html=summary, wide=True)

    cards, toc = [], []
    for n, r in enumerate(dicts, 1):
        title_key = next((k for k in TITLE_KEYS if isinstance(r.get(k), str) and r.get(k).strip()), None)
        head = (r[title_key].strip().splitlines()[0][:120] if title_key else f"record {n}")
        imgs, scalars, nested = [], [], []
        for k, v in r.items():
            if k == title_key and len(str(v)) <= 120:
                continue
            found = [image_path(x, base) for x in (v if isinstance(v, list) else [v])]
            found = [p for p in found if p]
            if found:
                imgs += [(p, f"{k}") for p in found]
            elif is_scalar(v) and len(str(v)) <= 200:
                scalars.append((k, vk.badge(v, status_of(v)) if k == status_key and status_of(v) else v))
            else:
                nested.append((k, v))
        body = vk.gallery(imgs, root, hero=len(imgs) == 1)
        if title_key and len(str(r[title_key])) > 120:
            body += vk.text(r[title_key], 800)
        if scalars:
            body += vk.kv(scalars)
        for k, v in nested:
            body += vk.section(k) + (vk.text(v, 800) if isinstance(v, str) else vk.code(v, 1500))
        status = statuses[n - 1]
        tags = [f"{k}:{r.get(k)}" for k in facet_keys if r.get(k) is not None]
        anchor = f"r{n}"
        meta = f"{title_key} · #{n}" if title_key else ""
        cards.append(vk.card(anchor, f"#{n}", head, body, meta=meta, status=status, tags=tags,
                             chips=[("fields", len(r))]))
        toc.append((anchor, head[:40], status))
    facets = [(k, sorted({str(r.get(k)) for r in dicts if r.get(k) is not None})) for k in facet_keys]
    return vk.page(title, cards, toc=toc if len(cards) > 1 else (), subtitle=str(path),
                   summary_html=summary, facets=facets)


# --------------------------------------------------------------------- tables / logs / text

def csv_page(path: Path, root: Path, title: str, limit: int) -> str:
    delim = "\t" if path.suffix.lower() == ".tsv" else ","
    with path.open(encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f, delimiter=delim)
        recs = [row for _, row in zip(range(limit), reader)]
    for r in recs:  # numbers sort as numbers
        for k, v in r.items():
            try:
                r[k] = int(v) if re.fullmatch(r"-?\d+", v or "") else float(v) if re.fullmatch(r"-?[\d.]+(e[-+]?\d+)?", (v or ""), re.I) else v
            except (TypeError, ValueError):
                pass
    return records_page(path, root, recs, title)


def log_page(path: Path, root: Path, title: str, limit: int) -> str:
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    total = len(lines)
    start = max(0, total - limit)  # logs: the tail matters most
    rows, kinds, counts = [], [], Counter()
    for i, line in enumerate(lines[start:], start + 1):
        m = LEVEL.search(line[:200])
        level = m.group(1) if m else ""
        counts[level or "—"] += 1
        t = LEVEL_TONE.get(level, "")
        rows.append([i, vk.badge(level, t) if level else "", line])
        kinds.append("fail" if t == "danger" else "warning" if t == "warn" else "")
    stats = [("lines", total)] + [(lv, counts[lv], LEVEL_TONE.get(lv, "muted"))
                                  for lv in ("ERROR", "CRITICAL", "FATAL", "WARNING", "WARN", "INFO", "DEBUG") if counts[lv]]
    shown = f"showing last {len(rows):,}" if start else ""
    body = vk.table(["#", "level", "line"], rows, row_kinds=kinds, max_rows=limit)
    card = vk.card("log", "", path.name, body, meta=shown, chips=[("lines", total)])
    return vk.page(title, [card], subtitle=str(path), summary_html=vk.stat_row(stats), wide=True)


def text_page(path: Path, root: Path, title: str) -> str:
    content = path.read_text(encoding="utf-8", errors="replace")
    card = vk.card("doc", "", path.name, vk.text(content, 10**9), meta=f"{len(content):,} chars")
    return vk.page(title, [card], subtitle=str(path))


# --------------------------------------------------------------------- directories

def human(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


def dir_page(path: Path, root: Path, title: str, limit: int, out: Path) -> str:
    groups: dict[Path, list[Path]] = {}
    files = []
    for dirpath, dirnames, filenames in os.walk(path):
        dirnames[:] = sorted(d for d in dirnames if not d.startswith("."))
        for name in sorted(filenames):
            if name.startswith("."):
                continue
            p = Path(dirpath) / name
            if p.resolve() == out.resolve():
                continue
            if p.suffix.lower() in IMG_EXT:
                if "_thumb" in p.stem:
                    continue
                groups.setdefault(Path(dirpath), []).append(p)
            else:
                files.append(p)
        if sum(map(len, groups.values())) + len(files) >= limit:
            break

    def thumb(p: Path):
        t = p.with_name(p.stem + "_thumb.jpg")
        return t if t.exists() else None

    cards, toc = [], []
    for n, (d, imgs) in enumerate(sorted(groups.items()), 1):
        label = str(d.relative_to(path)) if d != path else "."
        anchor = f"d{n}"
        body = vk.gallery([(p, p.name, thumb(p)) for p in imgs], root)
        cards.append(vk.card(anchor, "", label, body, chips=[("images", len(imgs))]))
        toc.append((anchor, label))
    if files:
        rows = [[vk.link(vk.rel(p, root), str(p.relative_to(path))), p.suffix.lstrip(".") or "—",
                 vk.raw(f'<span data-v="{p.stat().st_size}">{human(p.stat().st_size)}</span>'),
                 datetime.fromtimestamp(p.stat().st_mtime).strftime("%Y-%m-%d %H:%M")] for p in files]
        cards.append(vk.card("files", "", "files", vk.table(["path", "type", "size", "modified"], rows),
                             chips=[("files", len(files))]))
        toc.append(("files", "files"))
    n_img = sum(map(len, groups.values()))
    summary = vk.stat_row([("images", n_img), ("folders with images", len(groups)), ("other files", len(files))])
    return vk.page(title, cards, toc=toc if len(toc) > 1 else (), subtitle=str(path), summary_html=summary)


# --------------------------------------------------------------------- main

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("input", type=Path)
    ap.add_argument("--out", type=Path, help="output HTML (default: next to the input)")
    ap.add_argument("--title")
    ap.add_argument("--lang", default="zh", choices=["zh", "en"])
    ap.add_argument("--limit", type=int, default=2000, help="max records / lines / files (default 2000)")
    args = ap.parse_args()

    src = args.input.expanduser().resolve()
    if not src.exists():
        sys.exit(f"not found: {src}")
    vk.set_lang(args.lang)
    root_default = src if src.is_dir() else src.parent
    out = (args.out or root_default / f"{src.stem if src.is_file() else 'index'}.view.html").resolve()
    root = out.parent
    title = args.title or src.name
    ext = src.suffix.lower()

    if src.is_dir():
        html = dir_page(src, root, title, args.limit, out)
    elif ext in (".json", ".jsonl"):
        html = records_page(src, root, load_records(src, args.limit), title)
    elif ext in (".csv", ".tsv"):
        html = csv_page(src, root, title, args.limit)
    elif ext in (".log", ".out", ".err") or (ext == ".txt" and LEVEL.search(src.read_text(errors="replace")[:20000])):
        html = log_page(src, root, title, args.limit)
    elif ext in IMG_EXT:
        html = vk.page(title, [vk.card("img", "", src.name, vk.gallery([(src, src.name)], root, hero=True))])
    else:
        html = text_page(src, root, title)

    out.write_text(html, encoding="utf-8")
    print(f"wrote {out}")
    print(f"serve with: python3 {Path(__file__).with_name('serve_viewer.py')} --dir {root} --page {out.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
