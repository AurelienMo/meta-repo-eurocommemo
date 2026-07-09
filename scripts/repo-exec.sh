#!/usr/bin/env bash
# Exécute une commande dans l'environnement d'exécution d'un repo (conteneur Docker
# ou hôte), selon le bloc `exec:` déclaré dans workspace.yaml. Enveloppe léger autour
# de scripts/repo_exec.py — le meta-repo est déduit du chemin de ce script.
#
# Usage:
#   scripts/repo-exec.sh <repo> -- <commande...>     # exécute la commande
#   scripts/repo-exec.sh <repo> --print -- <cmd...>  # affiche sans exécuter (dry-run)
#   scripts/repo-exec.sh --check <repo>              # docker présent + service démarré
#
# Exemples:
#   scripts/repo-exec.sh src-api -- mvn -version
#   scripts/repo-exec.sh src-api --print -- mvn test
#   scripts/repo-exec.sh --check src-api

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
META="$(cd "${SCRIPT_DIR}/.." && pwd)"

if [[ $# -eq 0 || "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  # En-tête uniquement : lignes de commentaire jusqu'à la première ligne non commentée.
  awk 'NR==1{next} /^#/{sub(/^# ?/,""); print; next} {exit}' "${BASH_SOURCE[0]}"
  exit 0
fi

# --check est un mode à part : `repo_exec.py <meta> --check <repo>`.
if [[ "${1:-}" == "--check" ]]; then
  shift
  exec python3 "${SCRIPT_DIR}/repo_exec.py" "$META" --check "$@"
fi

# Mode exécution : on insère le meta-repo en premier argument, le reste est relayé tel
# quel (repo, --print éventuel, puis `-- <commande>`).
exec python3 "${SCRIPT_DIR}/repo_exec.py" "$META" "$@"
