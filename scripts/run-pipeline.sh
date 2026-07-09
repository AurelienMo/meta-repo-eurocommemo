#!/usr/bin/env bash
# Point d'entrée principal du pipeline agentique de recode
#
# Usage :
#   ./scripts/run-pipeline.sh "<intention en texte libre>"
#   ./scripts/run-pipeline.sh --ticket <TICKET-ID>
#   ./scripts/run-pipeline.sh --spec <chemin/spec.yaml>
#   ./scripts/run-pipeline.sh --resume <run-id> [--entry A|B|C|D]
#
# Le meta-repo cible est TOUJOURS celui qui contient ce script (déduit de son
# emplacement) : le pipeline porte forcément sur le meta-repo courant.
#
# Points d'entrée (--entry) :
#   A → intent-parser      (défaut — depuis le besoin brut ou ticket)
#   B → code-reader        (spec.yaml déjà validée)
#   C → diff-writer        (spec + context-cache valides)
#   D → code-reviewer      (diffs déjà générés)
#
# Le pipeline est piloté par le CLI Claude Code réel : on se place dans le
# meta-repo (cwd = racine projet) et on invoque `claude -p "<prompt>"` ; les skills
# sont résolus via /skill-name dans le prompt. CLAUDE_BIN permet de surcharger le
# binaire (ex: CLAUDE_BIN=echo pour un dry-run de la commande construite).

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CLAUDE_BIN="${CLAUDE_BIN:-claude}"

# Le meta-repo cible est forcément celui qui contient ce script.
META_REPO="$(cd "${SCRIPT_DIR}/.." && pwd)"
TICKET=""
SPEC=""
RESUME=""
ENTRY="A"
INTENT=""

# ── Parsing des arguments ─────────────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
  case $1 in
    --ticket)    TICKET="$2";    shift 2 ;;
    --spec)      SPEC="$2";      shift 2 ;;
    --resume)    RESUME="$2";    shift 2 ;;
    --entry)     ENTRY="$2";     shift 2 ;;
    -h|--help)
      sed -n '2,22p' "$0" | sed 's/^# \?//'
      exit 0 ;;
    -*)
      echo "Argument inconnu : $1" >&2
      exit 1 ;;
    *)
      INTENT="$1"
      shift ;;
  esac
done

# ── Validation ────────────────────────────────────────────────────────────────
if [[ ! "$ENTRY" =~ ^[ABCD]$ ]]; then
  echo "Erreur : --entry doit être A, B, C ou D." >&2
  exit 1
fi

# Vérifier qu'au moins une source d'intention est fournie
if [[ -z "$INTENT" && -z "$TICKET" && -z "$SPEC" && -z "$RESUME" ]]; then
  echo "Erreur : fournir une intention (texte), --ticket, --spec ou --resume." >&2
  echo "Usage: $0 \"<intention>\"" >&2
  exit 1
fi

if [[ -n "$SPEC" && ! -f "$SPEC" ]]; then
  echo "Erreur : fichier spec introuvable : ${SPEC}" >&2
  exit 1
fi

# ── Validation du meta-repo ───────────────────────────────────────────────────
echo "→ Validation du meta-repo..."
[[ -d "$META_REPO" ]]                 || { echo "Erreur : meta-repo introuvable : ${META_REPO}" >&2; exit 1; }
[[ -f "$META_REPO/workspace.yaml" ]]  || { echo "Erreur : workspace.yaml manquant dans ${META_REPO}" >&2; exit 1; }
[[ -d "$META_REPO/.claude" ]]         || { echo "Erreur : dossier .claude/ manquant dans ${META_REPO}" >&2; exit 1; }
python3 "${SCRIPT_DIR}/resolve_paths.py" "$META_REPO" --validate || exit 1

# ── Mapping point d'entrée → skill de départ ─────────────────────────────────
case "$ENTRY" in
  A) START_SKILL=$([[ -n "$TICKET" ]] && echo "/ticket-fetcher" || echo "/intent-parser") ;;
  B) START_SKILL="/code-reader"   ;;
  C) START_SKILL="/diff-writer"   ;;
  D) START_SKILL="/code-reviewer" ;;
esac

# ── Construction du prompt ────────────────────────────────────────────────────
PROMPT="${START_SKILL} — pilote le pipeline de recode multi-repo."
[[ -n "$TICKET" ]] && PROMPT+=$'\n'"Ticket source : ${TICKET}"
[[ -n "$SPEC"   ]] && PROMPT+=$'\n'"Spec validée : ${SPEC}"
[[ -n "$RESUME" ]] && PROMPT+=$'\n'"Reprends le pipeline depuis plans/plan-last.yaml (run ${RESUME})."
[[ -n "$INTENT" ]] && PROMPT+=$'\n'"Intention : ${INTENT}"

# ── Accès aux repos enfants (--add-dir par repo résolu) ──────────────────────
ADD_DIR_FLAGS=()
while IFS= read -r repo_path; do
  [[ -n "$repo_path" ]] && ADD_DIR_FLAGS+=(--add-dir "$repo_path")
done < <(python3 "${SCRIPT_DIR}/resolve_paths.py" "$META_REPO" --json \
  | python3 -c 'import json,sys; [print(v["path"]) for v in json.load(sys.stdin).values()]' 2>/dev/null || true)

# ── Affichage du résumé avant lancement ──────────────────────────────────────
echo ""
echo "  meta-repo : ${META_REPO}"
echo "  entry     : ${ENTRY} (${START_SKILL})"
[[ -n "$TICKET" ]] && echo "  ticket    : ${TICKET}"
[[ -n "$SPEC"   ]] && echo "  spec      : ${SPEC}"
[[ -n "$RESUME" ]] && echo "  resume    : ${RESUME}"
[[ -n "$INTENT" ]] && echo "  intention : ${INTENT}"
[[ ${#ADD_DIR_FLAGS[@]} -gt 0 ]] && echo "  add-dir   : $((${#ADD_DIR_FLAGS[@]} / 2)) repo(s) enfant(s)"
echo ""

# ── Lancement ─────────────────────────────────────────────────────────────────
echo "→ Lancement du pipeline..."
( cd "$META_REPO" && "$CLAUDE_BIN" --permission-mode plan \
    ${ADD_DIR_FLAGS[@]+"${ADD_DIR_FLAGS[@]}"} -p "$PROMPT" )
