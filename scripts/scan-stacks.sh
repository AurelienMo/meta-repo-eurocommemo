#!/usr/bin/env bash
# Lance tech-detector sur tous les repos du workspace et met à jour stack-snapshot.yaml
# Usage: ./scripts/scan-stacks.sh --meta-repo <chemin-meta-repo> [--force]

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CLAUDE_BIN="${CLAUDE_BIN:-claude}"   # surchargeable (ex: CLAUDE_BIN=echo pour dry-run)

META_REPO=""
FORCE=false

# ── Parsing des arguments ─────────────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
  case $1 in
    --meta-repo) META_REPO="$2"; shift 2 ;;
    --force)     FORCE=true;     shift   ;;
    -h|--help)
      echo "Usage: $0 --meta-repo <chemin> [--force]"
      echo "  --force  : force le re-scan même si le cache est valide"
      exit 0 ;;
    *)
      echo "Argument inconnu : $1" >&2
      exit 1 ;;
  esac
done

if [[ -z "$META_REPO" ]]; then
  echo "Erreur : --meta-repo est obligatoire." >&2
  exit 1
fi

if [[ ! -d "$META_REPO" ]]; then
  echo "Erreur : répertoire introuvable : ${META_REPO}" >&2
  exit 1
fi

# ── Validation préalable ──────────────────────────────────────────────────────
echo "→ Validation du meta-repo..."
[[ -f "$META_REPO/workspace.yaml" ]]  || { echo "Erreur : workspace.yaml manquant dans ${META_REPO}" >&2; exit 1; }
[[ -d "$META_REPO/.claude" ]]         || { echo "Erreur : dossier .claude/ manquant dans ${META_REPO}" >&2; exit 1; }
python3 "${SCRIPT_DIR}/resolve_paths.py" "$META_REPO" --validate || exit 1

WORKSPACE_FILE="${META_REPO}/workspace.yaml"
SNAPSHOT_FILE="${META_REPO}/docs/stack-snapshot.yaml"

# ── Vérification du cache ─────────────────────────────────────────────────────
WORKSPACE_HASH=$(md5sum "$WORKSPACE_FILE" 2>/dev/null | awk '{print $1}' \
  || md5 -q "$WORKSPACE_FILE" 2>/dev/null \
  || echo "no-hash")

if [[ "$FORCE" == false && -f "$SNAPSHOT_FILE" ]]; then
  CACHED_HASH=$(grep "workspace_hash:" "$SNAPSHOT_FILE" | awk '{print $2}' | tr -d '"' || true)
  if [[ "$CACHED_HASH" == "$WORKSPACE_HASH" ]]; then
    echo "✓ Cache stack-snapshot.yaml valide (workspace_hash inchangé) — aucun re-scan nécessaire."
    echo "  Utiliser --force pour forcer le re-scan."
    exit 0
  else
    echo "→ workspace_hash a changé — re-scan déclenché."
  fi
fi

mkdir -p "${META_REPO}/docs"

# ── Accès aux repos enfants (--add-dir par repo résolu) ──────────────────────
ADD_DIR_FLAGS=()
while IFS= read -r repo_path; do
  [[ -n "$repo_path" ]] && ADD_DIR_FLAGS+=(--add-dir "$repo_path")
done < <(python3 "${SCRIPT_DIR}/resolve_paths.py" "$META_REPO" --json \
  | python3 -c 'import json,os,sys; [print(v["path"]) for v in json.load(sys.stdin).values() if os.path.isdir(v["path"])]' 2>/dev/null || true)

# ── Lancement du tech-detector via Claude Code (plan puis exécution) ──────────
# cwd = meta-repo : le skill /tech-detector écrit lui-même docs/stack-snapshot.yaml.
TECH_PROMPT="/tech-detector — scanne tous les repos déclarés dans workspace.yaml et mets à jour docs/stack-snapshot.yaml"

# Phase 1 — plan : aperçu de ce que tech-detector va faire (aucune écriture).
echo "→ Phase 1/2 : plan du scan tech-detector (aperçu, aucune écriture)..."
( cd "$META_REPO" && "$CLAUDE_BIN" --permission-mode plan \
    ${ADD_DIR_FLAGS[@]+"${ADD_DIR_FLAGS[@]}"} -p "$TECH_PROMPT" )

# Phase 2 — exécution : écrit réellement docs/stack-snapshot.yaml.
echo "→ Phase 2/2 : exécution du scan tech-detector..."
( cd "$META_REPO" && "$CLAUDE_BIN" --permission-mode acceptEdits \
    ${ADD_DIR_FLAGS[@]+"${ADD_DIR_FLAGS[@]}"} -p "$TECH_PROMPT" )

# ── Injection du workspace_hash dans le snapshot ──────────────────────────────
# Ajouter/mettre à jour le hash dans _meta si la clé existe déjà
if grep -q "workspace_hash:" "$SNAPSHOT_FILE" 2>/dev/null; then
  if sed --version 2>/dev/null | grep -q GNU; then
    sed -i "s/workspace_hash:.*/workspace_hash: \"${WORKSPACE_HASH}\"/" "$SNAPSHOT_FILE"
  else
    sed -i '' "s/workspace_hash:.*/workspace_hash: \"${WORKSPACE_HASH}\"/" "$SNAPSHOT_FILE"
  fi
else
  # Ajouter la clé dans _meta si le bloc existe, sinon en fin de fichier
  echo "  workspace_hash: \"${WORKSPACE_HASH}\"" >> "$SNAPSHOT_FILE"
fi

echo "✓ stack-snapshot.yaml mis à jour : ${SNAPSHOT_FILE}"
