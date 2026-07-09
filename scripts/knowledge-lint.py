#!/usr/bin/env python3
"""knowledge-lint.py — Knowledge base self-check for the meta-workspace.

Checks:
  - CLAUDE.md exists (warns if < 200 lines)
  - docs/index.md references all .md files in docs/
  - Sub-repos from workspace-config.sh exist as directories
  - No orphan docs

Usage:
  python3 scripts/knowledge-lint.py
  python3 scripts/knowledge-lint.py --json
  python3 scripts/knowledge-lint.py --fix-index
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

WORKSPACE = Path(__file__).parent.parent.resolve()
DOCS_DIR = WORKSPACE / "docs"
WIKI_DIR = WORKSPACE / "wiki"
CLAUDE_MD = WORKSPACE / "CLAUDE.md"
INDEX_MD = DOCS_DIR / "index.md"
WIKI_INDEX_MD = WIKI_DIR / "index.md"
WIKI_SCHEMA_MD = WIKI_DIR / "SCHEMA.md"
WIKI_LOG_MD = WIKI_DIR / "log.md"
CONFIG_SH = WORKSPACE / "scripts" / "workspace-config.sh"

WIKI_META_FILES = {"SCHEMA.md", "index.md", "log.md"}

errors: list[str] = []
warnings: list[str] = []


def check(condition: bool, message: str, level: str = "error") -> None:
    if not condition:
        (errors if level == "error" else warnings).append(message)


def parse_sub_repos() -> list[str]:
    if not CONFIG_SH.exists():
        return []
    content = CONFIG_SH.read_text()
    in_array = False
    repos: list[str] = []
    for line in content.splitlines():
        stripped = line.strip()
        if stripped.startswith("SUB_REPOS=("):
            in_array = True
            continue
        if in_array:
            if stripped.startswith(")"):
                break
            if stripped.startswith("#") or not stripped:
                continue
            match = re.match(r'"([^"]+)"', stripped.rstrip(","))
            if match:
                repos.append(match.group(1))
    return repos


def parse_sources_dir() -> Path:
    """Resolve IBANSECURE_SOURCES_DIR (the OrbStack volumes path) from config.

    Sources the shell config and echoes the variable — handles `${VAR:-default}`
    and nested `${HOME}` correctly. Falls back to the workspace root if the
    variable is not declared.
    """
    if not CONFIG_SH.exists():
        return WORKSPACE
    try:
        import subprocess
        result = subprocess.run(
            ["bash", "-c", f'source "{CONFIG_SH}" && echo "${{IBANSECURE_SOURCES_DIR:-}}"'],
            capture_output=True, text=True, timeout=5,
        )
        value = result.stdout.strip()
        if value:
            return Path(value).resolve()
    except Exception:
        pass
    return WORKSPACE


def lint_claude_md() -> None:
    if not CLAUDE_MD.exists():
        errors.append("CLAUDE.md missing at workspace root")
        return
    lines = CLAUDE_MD.read_text().splitlines()
    check(
        len(lines) >= 200,
        f"CLAUDE.md is only {len(lines)} lines — target is 200+ (guide recommends 300–500)",
        level="warning",
    )
    print(f"  CLAUDE.md: {len(lines)} lines")


def lint_sub_repos() -> None:
    repos = parse_sub_repos()
    if not repos:
        warnings.append(
            "SUB_REPOS empty in scripts/workspace-config.sh — configure when repos are known"
        )
        return
    sources_dir = parse_sources_dir()
    for repo in repos:
        repo_dir = sources_dir / repo
        # Sub-repos live outside the workspace (managed by ibansecure-docker-images).
        # A missing volume is expected before the docker stack has been initialised —
        # warn rather than error so the linter is useful before bootstrap too.
        check(
            repo_dir.is_dir(),
            f"Sub-repo '{repo}' not found at {repo_dir} — run docker stack `--init --clone`",
            level="warning",
        )
        if repo_dir.is_dir():
            has_context = (repo_dir / "CLAUDE.md").exists() or (repo_dir / "AGENTS.md").exists()
            check(
                has_context,
                f"Sub-repo '{repo}' has no CLAUDE.md or AGENTS.md",
                level="warning",
            )


def wiki_page_paths() -> list[Path]:
    if not WIKI_DIR.exists():
        return []
    return sorted(
        p
        for p in WIKI_DIR.rglob("*.md")
        if p.name not in WIKI_META_FILES
    )


def lint_wiki() -> None:
    if not WIKI_DIR.exists():
        warnings.append("wiki/ directory missing — run LLM wiki bootstrap")
        return

    check(WIKI_SCHEMA_MD.exists(), "wiki/SCHEMA.md missing")
    check(WIKI_INDEX_MD.exists(), "wiki/index.md missing")
    check(WIKI_LOG_MD.exists(), "wiki/log.md missing")

    if not WIKI_INDEX_MD.exists():
        return

    index_content = WIKI_INDEX_MD.read_text()
    pages = wiki_page_paths()
    print(f"  wiki/: {len(pages)} page(s)")

    for page in pages:
        rel = page.relative_to(WIKI_DIR).as_posix()
        check(
            rel in index_content or page.name in index_content,
            f"wiki/{rel} not referenced in wiki/index.md (orphan page)",
            level="warning",
        )


def lint_docs_index() -> None:
    if not DOCS_DIR.exists():
        warnings.append("docs/ directory missing")
        return
    if not INDEX_MD.exists():
        warnings.append("docs/index.md missing — run --fix-index to generate")
        return

    index_content = INDEX_MD.read_text()
    md_files = [f.name for f in DOCS_DIR.glob("*.md") if f.name != "index.md"]

    for md_file in md_files:
        check(
            md_file in index_content,
            f"docs/{md_file} not referenced in docs/index.md (orphan doc)",
            level="warning",
        )


def fix_index() -> None:
    DOCS_DIR.mkdir(exist_ok=True)
    md_files = sorted(f for f in DOCS_DIR.glob("*.md") if f.name != "index.md")
    root_mds = sorted(
        f
        for name in ["CLAUDE.md", "README.md", "AGENTS.md", "META-WORKSPACE-PATTERN.md"]
        if (f := WORKSPACE / name).exists()
    )

    lines = [
        "# Knowledge Base Index\n",
        "Auto-generated by `scripts/knowledge-lint.py --fix-index`.\n",
        "Do not edit manually — re-run the script to update.\n\n",
        "## docs/\n",
    ]
    for f in md_files:
        body = f.read_text()
        first_line = body.splitlines()[0].lstrip("# ").strip() if body else f.stem
        lines.append(f"- [{f.name}](./{f.name}) — {first_line}\n")

    lines.append("\n## Meta-repo root\n")
    for f in root_mds:
        body = f.read_text()
        first_line = body.splitlines()[0].lstrip("# ").strip() if body else f.stem
        rel = f.relative_to(WORKSPACE)
        lines.append(f"- [{f.name}](../{rel}) — {first_line}\n")

    INDEX_MD.write_text("".join(lines))
    print(f"Generated {INDEX_MD}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Knowledge base linter")
    parser.add_argument("--json", action="store_true", help="Output JSON for CI")
    parser.add_argument("--fix-index", action="store_true", help="Regenerate docs/index.md")
    args = parser.parse_args()

    if args.fix_index:
        fix_index()
        return

    print("Running knowledge-lint...\n")
    lint_claude_md()
    lint_sub_repos()
    lint_docs_index()
    lint_wiki()

    if args.json:
        result = {"errors": errors, "warnings": warnings, "ok": len(errors) == 0}
        print(json.dumps(result, indent=2))
        sys.exit(0 if result["ok"] else 1)

    if errors:
        print(f"\n  ERRORS ({len(errors)}):")
        for e in errors:
            print(f"    ✗ {e}")
    if warnings:
        print(f"\n  WARNINGS ({len(warnings)}):")
        for w in warnings:
            print(f"    ⚠ {w}")
    if not errors and not warnings:
        print("\n  ✓ All checks passed")
    elif not errors:
        print(f"\n  ✓ No errors ({len(warnings)} warning(s))")

    sys.exit(1 if errors else 0)


if __name__ == "__main__":
    main()
