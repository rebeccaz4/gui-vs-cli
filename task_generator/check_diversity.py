#!/usr/bin/env python3
"""Analyze per-app diversity of finalized tasks in task_generator/tasks/.

For each app, reports:
  - task count + difficulty distribution
  - unique verifier subcommands used (+ top-used ones)
  - lexical diversity of task descriptions (avg / max pairwise Jaccard
    similarity on token sets; type-token ratio)
  - near-duplicate pairs (Jaccard >= 0.6)
  - rough category coverage via keyword buckets

Run:  python task_generator/check_diversity.py [--app blender] [--json]
"""
from __future__ import annotations

import argparse
import json
import re
from collections import Counter, defaultdict
from itertools import combinations
from pathlib import Path

TASKS_DIR = Path(__file__).resolve().parent / "tasks"

STOPWORDS = {
    "the", "a", "an", "and", "or", "of", "to", "in", "on", "at", "for", "with",
    "is", "are", "be", "then", "it", "this", "that", "as", "by", "from", "if",
    "into", "so", "its", "your", "you", "will", "have", "has", "use", "using",
    "open", "save", "set", "click", "select", "go", "add", "new", "default",
    "file", "files", "home", "user", "documents", "pictures", "music", "videos",
    "desktop", "path", "should", "make", "create", "enter", "press", "type",
    "not", "no", "yes", "also", "any", "all", "each", "same", "value", "values",
}

CATEGORY_KEYWORDS = {
    "core": ["edit", "create", "draw", "write", "record", "render", "play", "convert"],
    "settings": ["preference", "setting", "option", "configure", "enable", "disable", "auto-save", "autosave"],
    "shortcut": ["shortcut", "keybinding", "hotkey", "ctrl+", "shift+", "alt+"],
    "plugin": ["extension", "plugin", "package", "addon", "add-on", "install"],
    "ui_layout": ["sidebar", "toolbar", "pane", "minimap", "layout", "view", "panel"],
    "bookmarks": ["bookmark", "favorite", "pin", "collection", "folder"],
    "export": ["export", "save as", "import", "png", "jpeg", "pdf", "csv", "xlsx", "flac", "mp3", "ogg", "wav"],
    "history": ["history", "recent", "cache", "clear"],
    "network": ["proxy", "cookie", "https", "javascript", "privacy", "tracking"],
    "workspace": ["workspace", "project", "launch", "build task", "interpreter"],
    "theme": ["theme", "dark mode", "color scheme", "font size", "appearance"],
}


def tokenize(text: str) -> set[str]:
    toks = re.findall(r"[a-zA-Z][a-zA-Z0-9_-]{2,}", text.lower())
    return {t for t in toks if t not in STOPWORDS}


def jaccard(a: set[str], b: set[str]) -> float:
    if not a and not b:
        return 0.0
    return len(a & b) / len(a | b)


def load_tasks() -> dict[str, list[dict]]:
    by_app: dict[str, list[dict]] = defaultdict(list)
    for task_file in sorted(TASKS_DIR.glob("*/task.json")):
        try:
            data = json.loads(task_file.read_text())
        except Exception as e:
            print(f"[skip] {task_file}: {e}")
            continue
        app = data.get("app") or task_file.parent.name.split("_", 1)[0]
        data["_path"] = str(task_file)
        by_app[app].append(data)
    return by_app


def verifier_subcmd(command: str) -> str:
    return command.strip().split()[0] if command.strip() else ""


def analyze_app(app: str, tasks: list[dict]) -> dict:
    n = len(tasks)
    diff = Counter(t.get("metadata", {}).get("estimated_difficulty", "?") for t in tasks)

    subcmds: Counter[str] = Counter()
    for t in tasks:
        for v in t.get("verification", []) or []:
            sc = verifier_subcmd(v.get("command", ""))
            if sc:
                subcmds[sc] += 1

    token_sets = [tokenize(t.get("task", "")) for t in tasks]
    all_tokens: Counter[str] = Counter()
    for s in token_sets:
        all_tokens.update(s)
    total_tok = sum(all_tokens.values()) or 1
    ttr = len(all_tokens) / total_tok

    pairs = list(combinations(range(n), 2))
    sims = [jaccard(token_sets[i], token_sets[j]) for i, j in pairs]
    avg_sim = sum(sims) / len(sims) if sims else 0.0
    max_sim = max(sims) if sims else 0.0
    near_dupes = [
        (tasks[i]["id"], tasks[j]["id"], round(s, 3))
        for (i, j), s in zip(pairs, sims) if s >= 0.6
    ]

    category_hits: Counter[str] = Counter()
    for t in tasks:
        text = t.get("task", "").lower()
        for cat, kws in CATEGORY_KEYWORDS.items():
            if any(kw in text for kw in kws):
                category_hits[cat] += 1

    return {
        "app": app,
        "task_count": n,
        "difficulty_dist": dict(sorted(diff.items(), key=lambda x: str(x[0]))),
        "unique_verifier_subcommands": len(subcmds),
        "top_verifier_subcommands": subcmds.most_common(5),
        "lexical_type_token_ratio": round(ttr, 3),
        "avg_pairwise_jaccard": round(avg_sim, 3),
        "max_pairwise_jaccard": round(max_sim, 3),
        "near_duplicate_pairs": near_dupes,
        "category_coverage": dict(category_hits),
    }


def format_report(rows: list[dict]) -> str:
    lines = []
    lines.append(f"{'app':<18} {'n':>3} {'uniq_cmds':>9} {'avg_sim':>7} {'max_sim':>7} {'ttr':>6}  diff  near_dup  categories")
    lines.append("-" * 120)
    for r in sorted(rows, key=lambda x: x["avg_pairwise_jaccard"]):
        diff = ",".join(f"{k}:{v}" for k, v in r["difficulty_dist"].items())
        cats = ",".join(sorted(r["category_coverage"].keys()))
        lines.append(
            f"{r['app']:<18} {r['task_count']:>3} {r['unique_verifier_subcommands']:>9} "
            f"{r['avg_pairwise_jaccard']:>7.3f} {r['max_pairwise_jaccard']:>7.3f} "
            f"{r['lexical_type_token_ratio']:>6.3f}  {diff}  {len(r['near_duplicate_pairs'])}  {cats}"
        )
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--app", help="Only analyze one app")
    ap.add_argument("--json", action="store_true", help="Emit JSON instead of table")
    ap.add_argument("--verbose", action="store_true", help="Show near-duplicate pairs and top commands")
    args = ap.parse_args()

    by_app = load_tasks()
    if args.app:
        by_app = {args.app: by_app.get(args.app, [])}

    rows = [analyze_app(app, tasks) for app, tasks in by_app.items() if tasks]

    if args.json:
        print(json.dumps(rows, indent=2))
        return

    print(format_report(rows))
    if args.verbose:
        for r in sorted(rows, key=lambda x: x["avg_pairwise_jaccard"]):
            print(f"\n== {r['app']} ==")
            print(f"  top cmds: {r['top_verifier_subcommands']}")
            if r["near_duplicate_pairs"]:
                print("  near-duplicate pairs (Jaccard >= 0.6):")
                for a, b, s in r["near_duplicate_pairs"]:
                    print(f"    {s}  {a}  <>  {b}")


if __name__ == "__main__":
    main()
