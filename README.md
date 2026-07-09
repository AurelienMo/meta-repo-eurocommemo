# Meta-repo ESP — Initialisation

Ce meta-repo orchestre le pipeline agentique de recode multi-techno sur les dépôts du client.
Il contient la **configuration** (racine + `specs/`), les **plans** générés (`plans/`) et les
**sorties** du pipeline (`docs/`). Les **skills** Claude Code du pipeline ne sont pas livrés ici :
ils s'installent depuis un dépôt dédié (étape 2 ci-dessous).

## Prérequis

- `git`
- [`gh`](https://cli.github.com/) (GitHub CLI), authentifié sur GitHub :
  ```sh
  gh auth login
  ```
- `python3` (hooks de maintenance du wiki, cf. `.claude/settings.json`)
- [`graphify`](https://graphify.net) (CLI de knowledge graph des repos) sur le `PATH` :
  ```sh
  uv tool install graphifyy      # ou: pipx install graphifyy
  ```
  > Le skill `/graphify` est livré par `meta-repo-resources` (étape 2) ; la cartographie
  > cross-repo se génère via `scripts/graphify-map.sh` (cf. § « 10 »). La phase `--clone` de
  > `init-meta-repo.sh` installe le hook post-commit dans chaque repo si `graphify` est sur le PATH.

## 0. Détacher du template Git (juste après le clone) ⚠️

Ce dossier vient d'être cloné depuis `meta-repo-template.git` : son `.git` pointe
**encore sur le dépôt du template**. Tel quel, un `git push` enverrait votre
meta-repo client dans le template partagé. **Avant toute chose**, repartez d'un
historique Git vierge et rebranchez `origin` sur le dépôt dédié du client :

```sh
rm -rf .git
git init
git add -A
git commit -m "chore: bootstrap meta-repo <client> from template"
git remote add origin <url-du-meta-repo-client>
# ex : git@github.com:AurelienMo/meta-repo-<client>.git
```

> Contrôle : `git remote -v` ne doit plus afficher `meta-repo-template.git`. Tant
> que c'est le cas, l'étape n'est pas faite — `init-meta-repo.sh` le rappelle aussi.

## 1. Initialisation

Le script `scripts/init-meta-repo.sh` initialise le meta-repo **sur place**. Il est
**idempotent** : relançable sans risque, chaque étape déjà faite est sautée. Le cycle se déroule
en **deux phases**, car le bloc `repos:` de `workspace.yaml` est rempli à la main entre les deux.

```sh
# Phase 1 — placeholders + fichiers par repo + config locale + skills
scripts/init-meta-repo.sh --client ESP --repos "<repo1,repo2>" --repos-root ~/IdeaProjects/mes-repos \
    [--ai-visibility none|selective|full] [--guidelines-location meta-repo|repo|both]

# Puis : éditer workspace.yaml → déclarer chaque repo avec path: ${REPOS_ROOT}/<nom> et origin: <url git>

# Phase 2 — clone les repos manquants, détecte les stacks (docs/), valide
scripts/init-meta-repo.sh --clone --scan
```

- Sans `--client` / `--repos`, le script les **demande en invite interactive**.
- `--clone` ne clone que les repos dont l'entrée `workspace.yaml` porte un champ `origin:` ;
  les autres sont signalés « à cloner manuellement ».
- `--scan` lance `scan-stacks.sh` (invoque Claude Code → `docs/stack-snapshot.yaml`).
- `--skip-skills` saute l'étape skills ; `--force` ré-applique placeholders et scaffold.
- **Vous n'êtes pas obligé de cloner tous les repos** : la validation **tolère les repos non clonés**
  (signalés `⊘ non cloné (ignoré)`, non bloquants). Seul un repo présent mais cassé (pas un repo Git)
  est une erreur. Pour exiger la présence de tous les repos (CI), voir `--strict` à l'étape 8.

> Le `--repos-root` renseigne `repos_root:` dans `workspace.local.yaml` (non versionné). Les étapes 2
> à 8 ci-dessous détaillent chaque artefact que ce script met en place.

## 2. Installer les skills du pipeline (`.claude/skills/`) ★

Les skills (`pipeline`, `planner`, `diff-writer`, `code-reviewer`, `test-generator`, `pr-builder`,
`graphify`, …) vivent dans un dépôt GitHub dédié (`meta-repo-resources`) et sont **matérialisés
localement par un script unique**, qui applique aussi les **overrides client versionnés** de
`skills-overrides/` PAR-DESSUS la base amont. Depuis la racine du meta-repo :

```sh
python3 scripts/sync_skills.py            # auto : overlay seul si .claude/skills/ existe, sinon clone+overlay
python3 scripts/sync_skills.py --fetch    # force le refresh de la base amont puis overlay
python3 scripts/sync_skills.py --no-fetch # overlay seul (conserve l'existant, jamais de clone)
python3 scripts/sync_skills.py --dry-run  # auditer ce qui serait écrit, sans rien modifier
```

- **Fetch auto-détecté** : par défaut, si `.claude/skills/` est déjà peuplé, son contenu est
  **conservé** et seulement **surchargé** par `skills-overrides/` ; le clone amont n'a lieu que sur
  une install vierge. `--fetch` force le refresh, `--no-fetch` interdit tout clone.
- Le résultat est matérialisé dans `.claude/skills/` (**non versionné**, cf. `.gitignore`) : la
  source de vérité de la base reste `meta-repo-resources`. Le skill `feed-llm-wiki/` (versionné dans
  ce repo) est préservé.
- Les fichiers de `skills-overrides/` (**versionnés**, spécifiques au client) gagnent toujours et
  **survivent aux updates** : ré-exécuter le script les ré-applique. Voir `skills-overrides/README.md`
  pour la convention (miroir partiel, fichier par fichier).
- **Mise à jour** des skills amont : `python3 scripts/sync_skills.py --fetch`.
- **graphify** : `sync_skills.py` matérialise le skill `graphify/` dans `.claude/skills/`. Le lanceur
  de cartographie cross-repo `scripts/graphify-map.sh` est, lui, **versionné dans ce meta-repo**
  (variante workspace-aware qui résout `workspace.yaml`). Cf. § « 10 ».

> Vérifier après sync : `ls .claude/skills/` doit lister les skills du pipeline (dont `pipeline/` et
> `graphify/`) en plus de `feed-llm-wiki/` (versionné dans ce repo).

## 3. Configuration locale (non versionnée)

```sh
cp workspace.local.example.yaml workspace.local.yaml   # puis renseigner 'repos_root'
```

`repos_root` = dossier parent où vivent vos repos clonés. Résolution centralisée dans
`scripts/resolve_paths.py`.

## 4. Déclarer les repos

Éditer `workspace.yaml` → déclarer chaque repo via `${REPOS_ROOT}/<nom>` et ses dépendances
inter-repos.

## 5. Renseigner le contrat (`specs/`)

- `specs/dod.md` → coller le Definition of Done client original.
- `specs/guidelines/_global.md` → règles transverses à tous les repos.
- `specs/guidelines/{repo}.md` → règles spécifiques à chaque repo.

Les critères **mesurables** de la DoD (couverture, etc.) sont définis globalement dans
`context.yaml → definition_of_done`. Pour qu'un repo ait des seuils différents (ex. une API à 90 %
et un site vitrine à 60 %), ajouter un bloc `dod:` sous ce repo dans `workspace.yaml` — fusion
repo-wins, seules les clés présentes surchargent la baseline.

## 6. Contexte & garde-fous

Éditer `CLAUDE.md` → contexte métier client et garde-fous impératifs du pipeline.

## 7. Stacks techniques

Renseigner `tech-profile-{repo}.yaml` par repo, ou laisser le scan automatique les produire
(étape 8).

## 8. Valider, scanner, lancer

Depuis la racine du meta-repo (`<path>` = chemin de ce meta-repo, p.ex. `.`) :

```sh
./scripts/validate-meta-repo.sh "<path>"               # cohérence de la config (repos non clonés tolérés)
./scripts/validate-meta-repo.sh "<path>" --strict      # CI : exige que TOUS les repos déclarés soient clonés
./scripts/scan-stacks.sh --meta-repo "<path>"          # détection des stacks → docs/stack-snapshot.yaml
./scripts/run-pipeline.sh --meta-repo "<path>" "<intention>"   # exécution du pipeline
```

> **Repos non clonés** : par défaut la validation est *tolérante* — un repo déclaré dans
> `workspace.yaml` mais absent du disque est signalé `⊘ non cloné (ignoré)` sans bloquer (chacun ne
> clone que les projets sur lesquels il travaille). `scan-stacks.sh` ignore de même les repos absents.
> Utilisez `--strict` pour un gate CI qui exige la présence de tous les repos.

## 9. Exécution conteneurisée (optionnel)

Par défaut, les commandes d'un repo (checks de version, build, lint, test, coverage) s'exécutent
**en natif sur l'hôte**. Pour router les commandes d'un repo vers un **conteneur Docker** (afin de
ne pas dépendre des toolchains installées localement), ajouter un bloc `exec:` sous ce repo dans
`workspace.yaml` :

```yaml
repos:
  src-api:
    path: "${REPOS_ROOT}/src-api"
    exec:
      mode: compose                       # compose | native (défaut : native si absent)
      compose_file: "docker-compose.yml"  # relatif au repo (défaut)
      service: "api"                       # service compose dans lequel exécuter
      workdir: "/app"                      # chemin du projet DANS le conteneur (optionnel)
      shell: "sh -lc"                       # optionnel (défaut : sh -lc)
```

Le mode `compose` exécute la commande dans un service docker-compose **déjà lancé** via
`docker compose exec`. **Prérequis** : démarrer la stack avant le pipeline
(`docker compose -f <repo>/docker-compose.yml up -d <service>`).

**Stack hors du repo** : si le `docker-compose.yml` ne vit pas dans le repo, `compose_file`
accepte un chemin externe — absolu, `~`, `$HOME` ou `$VAR` (expansés). Un chemin relatif reste
résolu par rapport au repo. Comme c'est généralement propre à la machine, déclarez-le dans
`workspace.local.yaml` :

```yaml
repos:
  src-api:
    exec:
      mode: compose
      compose_file: "~/infra/src-api/docker-compose.yml"   # hors du repo
      service: "api"
```

**Plusieurs projets dans un même conteneur** : si un conteneur (un seul service) héberge plusieurs
projets, déclarez le chemin du projet *à l'intérieur* du conteneur via `workdir` (passé à
`docker compose exec -w`). Plusieurs repos peuvent ainsi viser le **même** `service` /
`compose_file` avec des `workdir` distincts :

```yaml
# Un conteneur "devbox" héberge deux projets dans /workspace/*
repos:
  project-a:
    exec: { mode: compose, compose_file: "~/infra/devbox/docker-compose.yml", service: "devbox", workdir: "/workspace/project-a" }
  project-b:
    exec: { mode: compose, compose_file: "~/infra/devbox/docker-compose.yml", service: "devbox", workdir: "/workspace/project-b" }
```

Tout passe par `scripts/repo_exec.py` (et son wrapper `scripts/repo-exec.sh`), seul point qui sait
router une commande vers le bon conteneur. Les skills `toolchain-preflight` et `validator`
l'utilisent automatiquement.

```sh
scripts/repo-exec.sh <repo> --print -- mvn -version   # affiche la commande enveloppée (dry-run)
scripts/repo-exec.sh --check <repo>                   # docker présent + service démarré
scripts/repo-exec.sh <repo> -- mvn test               # exécute dans le conteneur (ou en natif)
```

**Override local** : un dev qui n'utilise pas Docker peut forcer le natif sans toucher au fichier
versionné, en redéclarant le bloc dans `workspace.local.yaml` :

```yaml
repos:
  src-api:
    exec:
      mode: native
```

## 10. Cartographie cross-repo (graphify)

[graphify](https://graphify.net) transforme chaque repo en **graphe de connaissances** (god nodes,
communautés, relations inter-fichiers). L'extraction est **AST-only** (tree-sitter, déterministe,
sans LLM ni clé API) : reproductible, gratuite, hors-ligne.

Prérequis :

- le CLI `graphify` sur le `PATH` (voir https://graphify.net) — le skill et le script ne font que
  l'**orchestrer** ;
- le skill `/graphify`, fourni par `meta-repo-resources` et **matérialisé par `sync_skills.py`
  (étape 2)** dans `.claude/skills/graphify/` ;
- le lanceur `scripts/graphify-map.sh`, **versionné dans ce meta-repo** (variante workspace-aware :
  il résout les repos déclarés dans `workspace.yaml` via `resolve_paths.py`).

```sh
# Générer / régénérer le graphe de tous les repos clonés
scripts/graphify-map.sh

# Un seul repo
scripts/graphify-map.sh --repo <nom>
```

Sortie : `graphify-out/` est généré **à l'intérieur de chaque repo cloné** (`graph.json`,
`graph.html`, `GRAPH_REPORT.md`). `cache/` et `.graphify_root` (chemins absolus locaux) sont
**gitignorés** — régénérables.

Interroger la cartographie (le skill `graphify` est matérialisé à l'étape 2 — `/graphify`) :

```sh
graphify query   "comment les stats sont-elles calculées ?"   # sous-graphe ciblé
graphify explain "AccountStats"                                # un nœud + ses voisins
graphify path    "<A>" "<B>"                                   # plus court chemin entre deux nœuds
```

## Structure

```
ESP/
├── README.md                ← ce fichier
├── workspace.yaml           ← repos, chemins, dépendances
├── context.yaml             ← politiques pipeline (ai_visibility, DoD mesurable, PR)
├── CLAUDE.md                ← contexte métier + garde-fous
├── tech-profile-{repo}.yaml ← stack déclarative par repo
├── specs/                   ← ENTRÉES contractuelles (humain)
│   ├── dod.md
│   └── guidelines/{_global,{repo}}.md
├── plans/                   ← plans générés (planner)
├── docs/                    ← SORTIES générées (pipeline)
├── scripts/                 ← outillage (init, sync_skills, graphify-map, repo_exec, …)
├── graphify-out/            ← graphe de connaissances par repo (graphify, cf. § 10)
├── skills-overrides/        ← overrides de skills VERSIONNÉS (client), appliqués par sync_skills.py
└── .claude/                 ← rules + settings + skills (skills + graphify via étape 2)
```
