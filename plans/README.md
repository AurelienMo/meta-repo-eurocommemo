# plans/

Tous les plans d'une feature, accumulés au fil des runs.

## Contenu

Pour une feature, **trois artefacts** au plus, **appariés par la base de nom**
`<YYYY-MM-DD>_<slug>` et partageant le **même gabarit** `plans/_TEMPLATE.md` :

| Fichier | Rôle | Producteur |
|---|---|---|
| `plans/<YYYY-MM-DD>_<slug>.md` | Plan **préalable** lisible (contexte, fichiers, étapes, vérif), historisé. | plan-mode (humain / Claude) |
| `plans/<YYYY-MM-DD>_<slug>-dag.md` | Plan **DAG** lisible (groupes, table des tâches, stack/DoD), historisé. | skill `planner` |
| `plans/plan-last.yaml` | **DAG machine** (source de vérité structurée), nom stable, **pointeur de reprise** — écrasé à chaque run. | skill `planner` |

Le `.yaml` est la source de vérité machine ; les deux `.md` en sont les projections lisibles et
l'archive historique. Les deux `.md` suivent **le même squelette de sections** (`plans/_TEMPLATE.md`),
le suffixe `-dag` distingue le plan DAG du plan préalable sans collision de nom.

### Nommage `<YYYY-MM-DD>_<slug>[-dag].md`

- `<YYYY-MM-DD>` = date du jour au **format ISO** (ex. `2026-06-05`). **Jamais** `DDMMYYYY`.
- `<slug>`, par ordre de priorité (identique pour les deux fichiers d'une feature) :
  1. le ticket (`parsed_spec.ticket_id`) s'il existe et ne commence pas par `MANUAL-` — ex. `MOB-8547`, id ClickUp `868abc123` ;
  2. sinon le slug du titre (kebab-case, sans accents, tronqué à 60 car.) ;
  3. sinon `plan-<YYYY-MM-DD-HHMM>`.
- Suffixe de rôle : aucun pour le plan préalable, `-dag` pour le plan DAG.

Exemples : `2026-06-05_MOB-8547.md` + `2026-06-05_MOB-8547-dag.md`,
`2026-06-05_migration-jdbc-vers-jpa.md` + `2026-06-05_migration-jdbc-vers-jpa-dag.md`.

> Le fichier `plans/_TEMPLATE.md` n'est pas un plan : c'est le squelette partagé à recopier.

## Versionnage

Les deux artefacts ont vocation à être **versionnés** : les `.md` datés constituent l'historique des décisions de planification, `plan-last.yaml` porte le dernier DAG.

## Reprise

En cas d'interruption, le `planner` relit `plans/plan-last.yaml` (le pointeur de reprise stable) : tâches `done` conservées, `error` réinitialisées à `pending`, `pending` inchangées — le plan n'est pas regénéré depuis zéro.
