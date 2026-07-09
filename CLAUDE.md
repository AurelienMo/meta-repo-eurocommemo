# CLAUDE.md — Eurocommemo

## Configuration locale (avant le premier run)

Après un clone direct de ce template, initialiser le meta-repo **en place** avec
`scripts/init-meta-repo.sh` (idempotent, en 2 phases). Détail complet : README § « 1 ».

```sh
# Phase 1 — placeholders + fichiers par repo + config locale + skills
scripts/init-meta-repo.sh --client Eurocommemo --repos "<repo1,repo2>" --repos-root <dossier-parent-des-repos>

# Puis éditer workspace.yaml → déclarer chaque repo : path: "${REPOS_ROOT}/<nom>" + origin: "<url git>"

# Phase 2 — clone les repos déclarés, détecte les stacks (docs/), valide
scripts/init-meta-repo.sh --clone --scan
```

Les chemins des repos sont déclarés dans `workspace.yaml` (versionné) via `${REPOS_ROOT}/<nom>`.
Chaque dev fournit sa configuration machine dans `workspace.local.yaml` (NON versionné) ; la phase 1
le crée pour vous (équivalent manuel : `cp workspace.local.example.yaml workspace.local.yaml` puis
renseigner `repos_root`).

`repos_root` = dossier parent où vivent vos repos clonés. Pour un repo hors de ce dossier,
ajoutez un override `repos.<nom>.path` dans `workspace.local.yaml`. Résolution centralisée
dans `scripts/resolve_paths.py` (`--json`, `--path <repo>`, `--validate`).

**Repos non clonés** : la validation est tolérante par défaut — un repo déclaré mais absent est
ignoré (`⊘ non cloné`), non bloquant (chacun ne clone que ses projets). `--strict` (sur
`validate-meta-repo.sh` / `resolve_paths.py --validate`) exige la présence de tous les repos (CI).

## Contexte

N/A

## Garde-fous

N/A

## Plans d'analyse et d'implémentation

Les plans sont sauvegardés dans le dossier `plans/` à la racine du meta-repo.

**Nomenclature** (date **ISO `YYYY-MM-DD`**, base de nom `<YYYY-MM-DD>_<slug>` partagée pour une
même feature) :

| Artefact | Fichier | Producteur |
|---|---|---|
| Plan préalable | `plans/<YYYY-MM-DD>_<slug>.md` | plan-mode (humain / Claude) |
| Plan DAG | `plans/<YYYY-MM-DD>_<slug>-dag.md` | skill `planner` |
| DAG machine | `plans/plan-last.yaml` | skill `planner` (pointeur de reprise) |

Exemple : `2026-06-09_analyse-workflows-ia-produit.md` + `2026-06-09_analyse-workflows-ia-produit-dag.md`.

Les deux `.md` suivent le **même squelette** `plans/_TEMPLATE.md` (mêmes titres, même ordre) pour
faciliter la lecture humaine. Un plan contient au minimum : contexte, fichiers concernés, étapes,
vérification. Le dossier `plans/` est versionné — chaque plan est un artefact permanent consultable
lors d'une reprise.

## Comportement pipeline

- Boucle de clarification : une question à la fois
- Ambiguïté sur la rétrocompatibilité → suspendre et demander
- Diffs atomiques : une raison par commit
- Exécution des commandes par repo (version, build, lint, test, coverage) **toujours via
  `scripts/repo_exec.py`** : il route vers un conteneur Docker (`exec.mode: compose` dans
  `workspace.yaml`) ou l'hôte (`native`, défaut). Jamais d'appel direct à `mvn`/`npm`/`pytest`.
  Voir README § « 9. Exécution conteneurisée ».

## Definition of Done (narratif)

N/A

## graphify

Each child repo has its own knowledge graph under `docs/<repo>/graphify-out/`
(one sub-folder per project), with god nodes, community structure, and cross-file
relationships. Current graphs: `docs/src-eurocommemo/graphify-out/`. The graphs are
AST-only (no semantic/INFERRED edges, community names are `Community N` placeholders).

Rules:
- For codebase questions, first run `graphify query "<question>" --graph docs/<repo>/graphify-out/graph.json` when that file exists. Use `graphify path "<A>" "<B>" --graph <...>` for relationships and `graphify explain "<concept>" --graph <...>` for focused concepts. These return a scoped subgraph, usually much smaller than GRAPH_REPORT.md or raw grep output.
- Read `docs/<repo>/graphify-out/GRAPH_REPORT.md` only for broad architecture review or when query/path/explain do not surface enough context.
- After modifying a repo's code, refresh its graph (incremental, AST-only, no API cost) by re-running the headless extraction into the same location:
  `graphify extract <repo-path> --out docs/<repo> --exclude '*.md' --exclude '*.yaml' --exclude '*.yml' --exclude '*.html' --exclude '*.jpg' --exclude '*.svg' --exclude '*.png'`
  then `graphify cluster-only docs/<repo> --no-label`. Excluding doc/image types keeps the corpus code-only so no LLM API key is required.
