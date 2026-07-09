#!/usr/bin/env python3
"""Manage the pending wiki-ingest queue and drive the auto-sync hooks.

The Claude Code hooks queue ingest triggers into `.claude/.wiki-pending.json`;
the feed-llm-wiki workflow calls `clear` once the sync is done.

Queue management:
    python3 scripts/wiki-auto.py list
    python3 scripts/wiki-auto.py queue <path> [<path> ...]
    python3 scripts/wiki-auto.py clear

Auto-sync (wired in .claude/settings.json):
    python3 scripts/wiki-auto.py hook-post   # PostToolUse: queue an edited *.md
    python3 scripts/wiki-auto.py scan         # diff docs/ vs snapshot, queue changes
    python3 scripts/wiki-auto.py hook-stop    # Stop: scan + block to trigger ingest

Trigger scope: only `*.md` files under docs/ (recursive), excluding docs/index.md
and hidden files. A missing queue file is treated as empty. Stdlib only.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DOCS = REPO_ROOT / "docs"
PRODUCT = REPO_ROOT / "product"
SOURCES = REPO_ROOT / "sources"
QUEUE = REPO_ROOT / ".claude" / ".wiki-pending.json"
STATE = REPO_ROOT / ".claude" / ".docs-state.json"
AUTOSYNC_OFF = REPO_ROOT / ".claude" / ".wiki-autosync-off"

# Synthesis-only scope: per-repo docs under docs/{repo}/ are NOT wiki triggers —
# the wiki is a meta-level synthesis, not a 1:1 mirror of every project's docs.
EXCLUDED_RELPATHS = {"docs/index.md"}
ROOT_MD_TRIGGERS = {"CLAUDE.md", "AGENTS.md"}


def _read() -> list[str]:
    if not QUEUE.exists():
        return []
    try:
        data = json.loads(QUEUE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    if isinstance(data, dict):
        data = data.get("pending", [])
    return [str(x) for x in data] if isinstance(data, list) else []


def _write(items: list[str]) -> None:
    QUEUE.parent.mkdir(parents=True, exist_ok=True)
    QUEUE.write_text(json.dumps({"pending": items}, indent=2) + "\n", encoding="utf-8")


def cmd_list(_args) -> int:
    items = _read()
    if not items:
        print("wiki-auto: queue is empty.")
        return 0
    print(f"wiki-auto: {len(items)} pending ingest(s):")
    for it in items:
        print(f"  - {it}")
    return 0


def cmd_queue(args) -> int:
    items = _read()
    added = [p for p in args.paths if p not in items]
    items.extend(added)
    _write(items)
    print(f"wiki-auto: queued {len(added)} new path(s); {len(items)} pending total.")
    return 0


def cmd_clear(_args) -> int:
    had = len(_read())
    _write([])
    print(f"wiki-auto: cleared queue ({had} entr{'y' if had == 1 else 'ies'} removed).")
    return 0


# ── trigger logic & snapshot ──────────────────────────────────────────────────
def _is_trigger(path: Path) -> bool:
    """True if `path` is a *synthesis* doc that should feed the wiki.

    Scope (synthesis only): top-level docs/*.md (not recursive — per-repo
    docs/{repo}/ are excluded), product/*.md, anything under sources/, and the
    root CLAUDE.md / AGENTS.md. docs/index.md and hidden paths are excluded.
    """
    try:
        rel = path.resolve().relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return False
    parts = Path(rel).parts
    if any(p.startswith(".") for p in parts):  # hidden files/dirs
        return False
    if rel in EXCLUDED_RELPATHS:
        return False
    # (a) top-level docs/*.md  (depth 1 — excludes docs/{repo}/...)
    if len(parts) == 2 and parts[0] == "docs" and path.suffix == ".md":
        return True
    # (b) top-level product/*.md
    if len(parts) == 2 and parts[0] == "product" and path.suffix == ".md":
        return True
    # (c) anything under sources/
    if len(parts) >= 2 and parts[0] == "sources":
        return True
    # (d) root CLAUDE.md / AGENTS.md
    if rel in ROOT_MD_TRIGGERS:
        return True
    return False


def _snapshot_triggers() -> dict[str, str]:
    """{relpath: 'mtime:size'} for every synthesis trigger currently present."""
    candidates: list[Path] = []
    if DOCS.exists():
        candidates += list(DOCS.glob("*.md"))          # top-level only
    if PRODUCT.exists():
        candidates += list(PRODUCT.glob("*.md"))        # top-level only
    if SOURCES.exists():
        candidates += [p for p in SOURCES.rglob("*") if p.is_file()]
    for name in ROOT_MD_TRIGGERS:
        candidates.append(REPO_ROOT / name)
    snap: dict[str, str] = {}
    for p in candidates:
        if not p.exists() or not _is_trigger(p):
            continue
        try:
            st = p.stat()
        except OSError:
            continue
        rel = p.resolve().relative_to(REPO_ROOT).as_posix()
        snap[rel] = f"{int(st.st_mtime)}:{st.st_size}"
    return snap


def _load_state() -> dict[str, str] | None:
    if not STATE.exists():
        return None
    try:
        return json.loads(STATE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def _save_state(snap: dict[str, str]) -> None:
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(snap, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _queue_paths(paths: list[str]) -> int:
    """Add paths to the queue (dedup), return count newly added."""
    items = _read()
    added = [p for p in paths if p not in items]
    if added:
        _write(items + added)
    return len(added)


# ── hook subcommands ──────────────────────────────────────────────────────────
def _read_hook_stdin() -> dict:
    try:
        raw = sys.stdin.read()
        return json.loads(raw) if raw.strip() else {}
    except (json.JSONDecodeError, OSError):
        return {}


def cmd_hook_post(_args) -> int:
    """PostToolUse: queue the edited file if it is a docs/ *.md trigger."""
    event = _read_hook_stdin()
    ti = event.get("tool_input") or {}
    fp = ti.get("file_path") or ti.get("path") or ti.get("notebook_path")
    if fp and _is_trigger(Path(fp)):
        rel = Path(fp).resolve().relative_to(REPO_ROOT).as_posix()
        _queue_paths([rel])
    return 0  # PostToolUse never blocks


def _scan_core() -> tuple[int, int, bool]:
    """Diff docs/ *.md vs snapshot; queue changes. Returns (queued, tracked, baseline).

    Silent (no stdout) so it can be called from hook-stop, whose stdout must be
    JSON-only. Baseline (no prior state) records the snapshot without queuing.
    """
    current = _snapshot_triggers()
    previous = _load_state()
    if previous is None:  # baseline: avoid first-run flood
        _save_state(current)
        return (0, len(current), True)
    changed: list[str] = []
    for rel, sig in current.items():
        if previous.get(rel) != sig:  # added or updated
            changed.append(rel)
    for rel in previous:
        if rel not in current:  # deleted
            changed.append(f"DELETED:{rel}")
    n = _queue_paths(changed)
    _save_state(current)
    return (n, len(current), False)


def cmd_scan(_args) -> int:
    """Diff docs/ *.md vs snapshot; queue added/updated/deleted. Baseline if no state."""
    n, tracked, baseline = _scan_core()
    if baseline:
        print(f"wiki-auto: baseline snapshot recorded ({tracked} file(s)); nothing queued.")
    else:
        print(f"wiki-auto: scan queued {n} change(s) ({tracked} *.md tracked).")
    return 0


def cmd_hook_stop(_args) -> int:
    """Stop: scan for changes, then block to trigger the ingest if queue is non-empty."""
    event = _read_hook_stdin()
    if event.get("stop_hook_active"):  # we already re-prompted once — let it stop
        return 0
    if AUTOSYNC_OFF.exists():  # kill switch
        return 0
    _scan_core()  # catch rm/mv and external edits too (silent — stdout must be JSON-only)
    pending = _read()
    if not pending:
        return 0
    files = "\n".join(f"  - {p}" for p in pending)
    reason = (
        "Wiki auto-sync : des fichiers doc/ ont changé et doivent être ingérés dans wiki/.\n"
        f"Fichiers en attente ({len(pending)}) :\n{files}\n\n"
        "Lance maintenant l'ingest feed-llm-wiki pour ces chemins (les entrées "
        "`DELETED:` correspondent à des suppressions → retire/marque la page wiki "
        "correspondante). Puis exécute :\n"
        "  python3 scripts/knowledge-lint.py --fix-index\n"
        "  python3 scripts/wiki-auto.py clear"
    )
    print(json.dumps({"decision": "block", "reason": reason}))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Manage the wiki ingest queue & auto-sync.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list").set_defaults(func=cmd_list)
    q = sub.add_parser("queue")
    q.add_argument("paths", nargs="+")
    q.set_defaults(func=cmd_queue)
    sub.add_parser("clear").set_defaults(func=cmd_clear)
    sub.add_parser("scan").set_defaults(func=cmd_scan)
    sub.add_parser("hook-post").set_defaults(func=cmd_hook_post)
    sub.add_parser("hook-stop").set_defaults(func=cmd_hook_stop)
    args = ap.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
