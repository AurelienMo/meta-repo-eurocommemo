#!/usr/bin/env bash
# Initialise CE meta-repo sur place, après un clone direct du template.
#
# Contrairement à ia-agentique/scripts/init-meta-repo.sh (qui COPIE le template
# vers un nouveau dossier), ce script opère IN-PLACE sur le repo courant et couvre
# tout le cycle d'init : placeholders, fichiers par repo, config locale, skills,
# clone des projets enfants déclarés, maj des docs générées, validation.
#
# Il est IDEMPOTENT : chaque étape est sautée si déjà faite. On peut le relancer.
#
# Usage:
#   scripts/init-meta-repo.sh --client <nom> --repos "<repo1,repo2,...>"
#                             [--ai-visibility none|selective|full]      (défaut none)
#                             [--guidelines-location meta-repo|repo|both] (défaut meta-repo)
#                             [--repos-root <chemin>]   pré-remplit repos_root (config locale)
#                             [--clone]                 phase 2 : clone les repos déclarés
#                             [--scan]                  maj docs : lance scan-stacks.sh
#                             [--skip-skills]           ne pas lancer sync_skills.py
#                             [--force]                 ré-initialiser même si déjà fait
#
# Si --client ou --repos manquent, ils sont demandés en invite interactive.

set -euo pipefail

# ── Détection de la racine du meta-repo (in-place) ───────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

# ── Valeurs par défaut ───────────────────────────────────────────────────────
CLIENT=""
REPOS=""
AI_VISIBILITY="none"
GUIDELINES_LOCATION="meta-repo"
REPOS_ROOT_ARG=""
DO_CLONE=0
DO_SCAN=0
SKIP_SKILLS=0
FORCE=0

usage() {
  cat <<'EOF'
Usage: scripts/init-meta-repo.sh --client <nom> --repos "<repo1,repo2>"
                                 [--ai-visibility none|selective|full]
                                 [--guidelines-location meta-repo|repo|both]
                                 [--repos-root <chemin>]
                                 [--clone] [--scan] [--skip-skills] [--force]

Phase 1 (instanciation + env) :
  scripts/init-meta-repo.sh --client acme --repos "api,front" --repos-root ~/repos
Phase 2 (après avoir déclaré les repos dans workspace.yaml) :
  scripts/init-meta-repo.sh --clone --scan
EOF
}

# ── Parsing des arguments ────────────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
  case $1 in
    --client)              CLIENT="$2";              shift 2 ;;
    --repos)               REPOS="$2";               shift 2 ;;
    --ai-visibility)       AI_VISIBILITY="$2";       shift 2 ;;
    --guidelines-location) GUIDELINES_LOCATION="$2"; shift 2 ;;
    --repos-root)          REPOS_ROOT_ARG="$2";      shift 2 ;;
    --clone)               DO_CLONE=1;               shift ;;
    --scan)                DO_SCAN=1;                shift ;;
    --skip-skills)         SKIP_SKILLS=1;            shift ;;
    --force)               FORCE=1;                  shift ;;
    -h|--help)             usage; exit 0 ;;
    *) echo "Argument inconnu : $1" >&2; usage >&2; exit 1 ;;
  esac
done

# ── Validation des valeurs d'énumération ─────────────────────────────────────
if [[ ! "$AI_VISIBILITY" =~ ^(none|selective|full)$ ]]; then
  echo "Erreur : --ai-visibility doit être none, selective ou full." >&2
  exit 1
fi
if [[ ! "$GUIDELINES_LOCATION" =~ ^(meta-repo|repo|both)$ ]]; then
  echo "Erreur : --guidelines-location doit être meta-repo, repo ou both." >&2
  exit 1
fi

# ── Helper sed compatible macOS (BSD) et Linux (GNU) ─────────────────────────
sedi() {
  if sed --version 2>/dev/null | grep -q GNU; then
    sed -i "$@"
  else
    sed -i '' "$@"
  fi
}

cd "$ROOT_DIR"

# ── Garde-fou : détachement du template Git ──────────────────────────────────
origin_url="$(git remote get-url origin 2>/dev/null || true)"
if [[ "$origin_url" == *meta-repo-template* ]]; then
  echo "⚠ origin pointe encore sur le template (${origin_url})."
  echo "  Un 'git push' enverrait ce meta-repo dans meta-repo-template.git."
  echo "  Détachez Git d'abord (cf. README § 0) :"
  echo "      rm -rf .git && git init && git add -A && git commit -m 'chore: bootstrap'"
  echo "      git remote add origin <url-du-meta-repo-client>"
  echo ""
fi

# ── Détermine si l'instanciation (placeholders/scaffold) reste à faire ───────
ALREADY_INIT=0
if ! grep -q '{{CLIENT}}' workspace.yaml 2>/dev/null; then
  ALREADY_INIT=1
fi

# ════════════════════════════════════════════════════════════════════════════
# Étapes 2-4 — Instanciation (placeholders + fichiers par repo)
# ════════════════════════════════════════════════════════════════════════════
if [[ "$ALREADY_INIT" -eq 1 && "$FORCE" -eq 0 ]]; then
  echo "→ Instanciation déjà effectuée ({{CLIENT}} absent de workspace.yaml). Passage aux étapes d'environnement."
  echo "  (utiliser --force pour ré-appliquer placeholders et scaffold)"
else
  # Le client et les repos ne sont requis que pour l'instanciation.
  if [[ -z "$CLIENT" ]]; then
    read -r -p "Nom du client : " CLIENT
  fi
  if [[ -z "$CLIENT" ]]; then
    echo "Erreur : le nom du client est obligatoire." >&2
    exit 1
  fi
  if [[ -z "$REPOS" ]]; then
    read -r -p "Repos (séparés par des virgules, ex: api,front) : " REPOS
  fi
  if [[ -z "$REPOS" ]]; then
    echo "Erreur : au moins un repo est obligatoire." >&2
    exit 1
  fi

  echo "→ Application des placeholders ({{CLIENT}} → ${CLIENT})..."
  for file in workspace.yaml context.yaml CLAUDE.md README.md specs/dod.md specs/guidelines/_global.md; do
    [[ -f "$file" ]] || continue
    sedi "s/{{CLIENT}}/${CLIENT}/g" "$file"
  done

  # ── Valeurs littérales de context.yaml (non-placeholders) ──────────────────
  if [[ "$AI_VISIBILITY" != "none" ]]; then
    echo "→ context.yaml : ai_visibility → ${AI_VISIBILITY}"
    sedi "s/^ai_visibility: .*/ai_visibility: ${AI_VISIBILITY}/" context.yaml
  fi
  if [[ "$GUIDELINES_LOCATION" != "meta-repo" ]]; then
    echo "→ context.yaml : guidelines_location → ${GUIDELINES_LOCATION}"
    sedi "s/^guidelines_location: .*/guidelines_location: ${GUIDELINES_LOCATION}/" context.yaml
  fi

  # ── Génération des fichiers par repo ───────────────────────────────────────
  echo "→ Génération des fichiers par repo..."
  mkdir -p docs
  IFS=',' read -ra REPO_LIST <<< "$REPOS"
  for repo in "${REPO_LIST[@]}"; do
    repo="${repo// /}"   # trim espaces
    [[ -z "$repo" ]] && continue

    if [[ ! -f "specs/guidelines/${repo}.md" && -f "specs/guidelines/exemple-projet.md" ]]; then
      cp "specs/guidelines/exemple-projet.md" "specs/guidelines/${repo}.md"
      sedi "s/exemple-projet/${repo}/g" "specs/guidelines/${repo}.md"
    fi
    if [[ ! -f "tech-profile-${repo}.yaml" && -f "tech-profile-exemple.yaml" ]]; then
      cp "tech-profile-exemple.yaml" "tech-profile-${repo}.yaml"
      sedi "s/exemple-projet/${repo}/g" "tech-profile-${repo}.yaml"
    fi
    mkdir -p "docs/${repo}"
    echo "   ✓ ${repo}"
  done

  # Supprimer les fichiers exemple (remplacés par les vrais)
  rm -f specs/guidelines/exemple-projet.md tech-profile-exemple.yaml
fi

# ════════════════════════════════════════════════════════════════════════════
# Étape 5 — Configuration locale (non versionnée)
# ════════════════════════════════════════════════════════════════════════════
if [[ ! -f workspace.local.yaml ]]; then
  echo "→ Création de workspace.local.yaml (non versionné)..."
  cp workspace.local.example.yaml workspace.local.yaml
else
  echo "→ workspace.local.yaml déjà présent (conservé)."
fi
if [[ -n "$REPOS_ROOT_ARG" ]]; then
  echo "→ workspace.local.yaml : repos_root → ${REPOS_ROOT_ARG}"
  # Échappe les '/' du chemin pour sed.
  esc="${REPOS_ROOT_ARG//\//\\/}"
  sedi "s/^repos_root: .*/repos_root: \"${esc}\"/" workspace.local.yaml
fi

# ════════════════════════════════════════════════════════════════════════════
# Étape 6 — Skills du pipeline (.claude/skills/)
# ════════════════════════════════════════════════════════════════════════════
if [[ "$SKIP_SKILLS" -eq 1 ]]; then
  echo "→ Skills : ignoré (--skip-skills)."
else
  echo "→ Synchronisation des skills (sync_skills.py)..."
  if ! python3 scripts/sync_skills.py; then
    echo "   ⚠ sync_skills.py a échoué (réseau/accès GitHub ?). À relancer plus tard :" >&2
    echo "     python3 scripts/sync_skills.py --fetch" >&2
  fi
fi

# ════════════════════════════════════════════════════════════════════════════
# Étape 7 — Clone des projets enfants déclarés (phase 2)
# ════════════════════════════════════════════════════════════════════════════
if [[ "$DO_CLONE" -eq 1 ]]; then
  echo "→ Clone des projets enfants déclarés dans workspace.yaml..."
  repos_json="$(python3 scripts/resolve_paths.py "$ROOT_DIR" --json 2>/dev/null || echo '{}')"
  # Parse en Python (stdlib) : pour chaque repo, émet "path<TAB>origin<TAB>branch".
  while IFS=$'\t' read -r path origin branch; do
    [[ -z "$path" ]] && continue
    name="$(basename "$path")"
    if [[ -d "$path/.git" ]]; then
      echo "   ✓ ${name} déjà cloné (${path})"
      continue
    fi
    if [[ -z "$origin" ]]; then
      echo "   ⚠ ${name} : pas de champ 'origin:' dans workspace.yaml → à cloner manuellement (${path})"
      continue
    fi
    echo "   → git clone ${origin} → ${path}"
    if [[ -n "$branch" ]]; then
      git clone --branch "$branch" "$origin" "$path" || echo "   ✗ échec du clone de ${name}" >&2
    else
      git clone "$origin" "$path" || echo "   ✗ échec du clone de ${name}" >&2
    fi
    if [[ -d "$path/.git" ]] && command -v graphify &>/dev/null; then
      echo "   → Graphify hook : installation du post-commit dans ${name}"
      (cd "$path" && graphify hook install) || echo "   ⚠ graphify hook install a échoué pour ${name}" >&2
    fi
  done < <(printf '%s' "$repos_json" | python3 -c '
import json, sys
data = json.load(sys.stdin)
for info in data.values():
    print("\t".join([info.get("path", ""), info.get("origin", ""), info.get("branch_default", "")]))
')
fi

# ════════════════════════════════════════════════════════════════════════════
# Étape 8 — Mise à jour des docs générées (détection de stacks)
# ════════════════════════════════════════════════════════════════════════════
if [[ "$DO_SCAN" -eq 1 ]]; then
  echo "→ Détection des stacks (scan-stacks.sh → docs/stack-snapshot.yaml)..."
  ./scripts/scan-stacks.sh --meta-repo "$ROOT_DIR" || echo "   ⚠ scan-stacks.sh a échoué (voir ci-dessus)." >&2
fi

# ════════════════════════════════════════════════════════════════════════════
# Étape 9 — Validation (non bloquante)
# ════════════════════════════════════════════════════════════════════════════
echo "→ Validation de la cohérence du meta-repo..."
if ! ./scripts/validate-meta-repo.sh "$ROOT_DIR"; then
  echo "   ⚠ Validation incomplète — attendu tant que les repos ne sont pas déclarés/clonés." >&2
fi

# ════════════════════════════════════════════════════════════════════════════
# Étape 10 — Résumé & étapes restantes
# ════════════════════════════════════════════════════════════════════════════
echo ""
echo "✓ Initialisation traitée pour : ${ROOT_DIR}"
echo ""
echo "Étapes restantes :"
echo "  1. Éditer workspace.yaml → déclarer chaque repo :"
echo "       <nom>:"
echo "         path: \"\${REPOS_ROOT}/<nom>\""
echo "         origin: \"git@github.com:AurelienMo/<nom>.git\"   # requis pour --clone"
echo "         branch_default: develop"
echo "  2. Cloner + scanner les repos déclarés :"
echo "       scripts/init-meta-repo.sh --clone --scan"
echo "  3. Renseigner le contrat : specs/dod.md, specs/guidelines/*.md, CLAUDE.md"
echo "  4. Lancer le pipeline :"
echo "       ./scripts/run-pipeline.sh --meta-repo \"${ROOT_DIR}\" \"<intention>\""
