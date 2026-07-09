#!/usr/bin/env bash
# Regenerate Graphify knowledge graphs for all repos declared in workspace.yaml.
#
# Graphify runs on the host filesystem directly (AST parsing — no Docker needed).
# Outputs are written to graphify-out/ inside each repo:
#   graphify-out/graph.html       — interactive browser visualization
#   graphify-out/graph.json       — machine-readable graph data
#   graphify-out/GRAPH_REPORT.md  — key concepts and connections
#
# Workspace-aware variant of the meta-repo-resources graphify-map.sh: instead of taking
# repo paths as arguments, it resolves the repos declared in workspace.yaml via resolve_paths.py.
#
# Usage:
#   scripts/graphify-map.sh                # regenerate all cloned repos
#   scripts/graphify-map.sh --repo <name>  # regenerate a single repo

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

TARGET_REPO=""

while [[ $# -gt 0 ]]; do
  case $1 in
    --repo) TARGET_REPO="$2"; shift 2 ;;
    -h|--help)
      echo "Usage: scripts/graphify-map.sh [--repo <name>]"
      exit 0
      ;;
    *) echo "Unknown argument: $1" >&2; exit 1 ;;
  esac
done

if ! command -v graphify &>/dev/null; then
  echo "✗ graphify not found. Install it first:" >&2
  echo "    uv tool install graphifyy" >&2
  echo "  Then install the Claude Code skill in this meta-repo:" >&2
  echo "    graphify install --project" >&2
  exit 1
fi

repos_json="$(python3 "${SCRIPT_DIR}/resolve_paths.py" "$ROOT_DIR" --json 2>/dev/null || echo '{}')"

if [[ "$repos_json" == '{}' ]]; then
  echo "⚠ No repos resolved from workspace.yaml (is workspace.local.yaml configured?)."
  exit 1
fi

success=0
skipped=0
failed=0

while IFS=$'\t' read -r name path; do
  [[ -z "$name" ]] && continue

  if [[ -n "$TARGET_REPO" && "$name" != "$TARGET_REPO" ]]; then
    continue
  fi

  if [[ ! -d "$path/.git" ]]; then
    echo "  ⊘ ${name}: not cloned (${path}) — skipped"
    ((skipped++)) || true
    continue
  fi

  echo "  → ${name}: running graphify in ${path}"
  if (cd "$path" && graphify . --no-viz 2>&1); then
    echo "  ✓ ${name}: graph updated → ${path}/graphify-out/"
    ((success++)) || true
  else
    echo "  ✗ ${name}: graphify failed" >&2
    ((failed++)) || true
  fi
done < <(printf '%s' "$repos_json" | python3 -c '
import json, sys
data = json.load(sys.stdin)
for name, info in data.items():
    print("\t".join([name, info.get("path", "")]))
')

echo ""
echo "Done: ${success} updated, ${skipped} skipped (not cloned), ${failed} failed."
[[ "$failed" -gt 0 ]] && exit 1 || exit 0
