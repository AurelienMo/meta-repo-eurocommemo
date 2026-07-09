#!/usr/bin/env bash
# Vérifie la cohérence d'un meta-repo avant un run
# Usage: ./scripts/validate-meta-repo.sh <chemin-meta-repo> [--strict]
#   --strict : un repo déclaré mais non cloné devient une erreur (CI / gate de release).
#              Par défaut, un repo non cloné est toléré (tout le monde ne clone pas tout).
# Exit 0 si valide, exit 1 avec la liste des erreurs sinon

set -euo pipefail

META=""
STRICT=""

for arg in "$@"; do
  case "$arg" in
    --strict) STRICT="--strict" ;;
    -h|--help)
      echo "Usage: $0 <chemin-meta-repo> [--strict]" >&2
      exit 0 ;;
    *)
      if [[ -z "$META" ]]; then META="$arg"; else echo "Argument inconnu : $arg" >&2; exit 1; fi ;;
  esac
done

if [[ -z "$META" ]]; then
  echo "Usage: $0 <chemin-meta-repo> [--strict]" >&2
  exit 1
fi

if [[ ! -d "$META" ]]; then
  echo "Erreur : répertoire introuvable : ${META}" >&2
  exit 1
fi

ERRORS=0

pass() { echo "  ✓ $1"; }
fail() { echo "  ✗ $1" >&2; ERRORS=$((ERRORS + 1)); }

echo "=== Validation meta-repo : ${META} ==="
echo ""

# ── 1. Fichiers obligatoires ──────────────────────────────────────────────────
echo "[ Fichiers obligatoires ]"
for f in workspace.yaml context.yaml CLAUDE.md; do
  if [[ -f "${META}/${f}" ]]; then
    pass "$f"
  else
    fail "$f manquant"
  fi
done

# ── 2. Valeurs valides dans context.yaml ──────────────────────────────────────
echo ""
echo "[ Valeurs context.yaml ]"
if [[ -f "${META}/context.yaml" ]]; then
  AI_VIS=$(grep -E "^ai_visibility:" "${META}/context.yaml" | awk '{print $2}' | tr -d '"' || true)
  GL_LOC=$(grep -E "^guidelines_location:" "${META}/context.yaml" | awk '{print $2}' | tr -d '"' || true)
  RV_POS=$(grep -E "^review_position:" "${META}/context.yaml" | awk '{print $2}' | tr -d '"' || true)

  if [[ "$AI_VIS" =~ ^(none|selective|full)$ ]]; then
    pass "ai_visibility = ${AI_VIS}"
  elif [[ -z "$AI_VIS" ]]; then
    fail "ai_visibility non défini"
  else
    fail "ai_visibility invalide : '${AI_VIS}' (attendu : none | selective | full)"
  fi

  if [[ "$GL_LOC" =~ ^(meta-repo|repo|both)$ ]]; then
    pass "guidelines_location = ${GL_LOC}"
  elif [[ -z "$GL_LOC" ]]; then
    fail "guidelines_location non défini"
  else
    fail "guidelines_location invalide : '${GL_LOC}' (attendu : meta-repo | repo | both)"
  fi

  if [[ "$RV_POS" =~ ^(after_diffs|after_tests|after_validation)$ ]]; then
    pass "review_position = ${RV_POS}"
  elif [[ -z "$RV_POS" ]]; then
    fail "review_position non défini"
  else
    fail "review_position invalide : '${RV_POS}' (attendu : after_diffs | after_tests | after_validation)"
  fi
fi

# ── 3. Placeholders non remplacés ─────────────────────────────────────────────
echo ""
echo "[ Placeholders ]"
PLACEHOLDER_FOUND=0
for f in "${META}/workspace.yaml" "${META}/context.yaml" "${META}/CLAUDE.md"; do
  [[ -f "$f" ]] || continue
  if grep -q "{{" "$f" 2>/dev/null; then
    LEFTOVERS=$(grep -o "{{[^}]*}}" "$f" | sort -u | tr '\n' ' ')
    fail "$(basename "$f") contient des placeholders non remplacés : ${LEFTOVERS}"
    PLACEHOLDER_FOUND=1
  fi
done
if [[ $PLACEHOLDER_FOUND -eq 0 ]]; then
  pass "Aucun placeholder résiduel"
fi

# ── 4. Guidelines par repo ────────────────────────────────────────────────────
echo ""
echo "[ Guidelines par repo ]"
if [[ -f "${META}/workspace.yaml" ]]; then
  # Extraire les noms de repos (lignes indentées de 2 espaces suivies de ":")
  REPO_NAMES=$(grep -E "^  [a-zA-Z0-9_-]+:" "${META}/workspace.yaml" \
    | grep -v "^\s*#" \
    | awk '{print $1}' \
    | tr -d ':' || true)

  if [[ -z "$REPO_NAMES" ]]; then
    fail "Aucun repo déclaré dans workspace.yaml"
  else
    while IFS= read -r repo; do
      [[ -z "$repo" ]] && continue
      GUIDELINE="${META}/specs/guidelines/${repo}.md"
      if [[ -f "$GUIDELINE" ]]; then
        pass "specs/guidelines/${repo}.md"
      else
        fail "specs/guidelines/${repo}.md manquant"
      fi
    done <<< "$REPO_NAMES"
  fi
fi

# ── 5. Chemins des repos (résolus via scripts/resolve_paths.py) ───────────────
echo ""
echo "[ Chemins des repos ]"
RESOLVER="${META}/scripts/resolve_paths.py"
if [[ ! -f "${META}/workspace.yaml" ]]; then
  :
elif [[ ! -f "$RESOLVER" ]]; then
  fail "scripts/resolve_paths.py manquant — impossible de résoudre les chemins"
else
  # Le résolveur applique l'overlay workspace.local.yaml et expanse ${REPOS_ROOT}/$HOME.
  # Code retour non nul si un repo est introuvable ou n'est pas un repo Git.
  VALIDATE_OUT=$(python3 "$RESOLVER" "$META" --validate ${STRICT:+$STRICT} 2>&1 || true)
  while IFS= read -r line; do
    [[ -z "$line" ]] && continue
    if [[ "$line" == *"✗"* || "$line" == ERREUR:* ]]; then
      fail "${line#  ✗ }"
    else
      echo "  ${line#  }"
    fi
  done <<< "$VALIDATE_OUT"
fi

# ── Bilan ─────────────────────────────────────────────────────────────────────
echo ""
if [[ $ERRORS -eq 0 ]]; then
  echo "✓ Meta-repo valide — prêt pour un run"
  exit 0
else
  echo "✗ ${ERRORS} erreur(s) détectée(s) — corriger avant de lancer le pipeline"
  exit 1
fi
