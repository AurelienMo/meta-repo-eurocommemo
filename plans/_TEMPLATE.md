<!--
  Shared plan template — used by BOTH plan artifacts of a feature so they read consistently:

    plans/<YYYY-MM-DD>_<slug>.md       → préalable plan (plan-mode, human/Claude)
    plans/<YYYY-MM-DD>_<slug>-dag.md   → DAG plan (skill `planner`)

  Both files keep the SAME section headers in the SAME order. Each fills the depth
  appropriate to its role:
    - préalable : detailed Contexte / Fichiers / Étapes / Vérification ; short DAG summary + link.
    - -dag      : full DAG d'exécution (groups + task table + stack/DoD) ; Contexte/Fichiers/
                  Vérification mirrored from the spec with the same headers.

  Naming: ISO date `YYYY-MM-DD`. `<slug>` = ticket_id (unless it starts with MANUAL-),
  else kebab-case of the title (no accents, ≤ 60 chars). Same slug for both files of one feature.
  Do not delete this file; copy its skeleton when creating a plan.
-->

# Plan — <feature> (<YYYY-MM-DD>)

**Run** : <run_id> · **Ticket** : <ticket_id> · **Repo(s)** : <repos> · **Branche** : <branch> → <base> · **Risk** : <low|medium|high> · **Complexité** : <simple|moderate|complex>

> ⚠️ risk_level = high → confirmation humaine requise avant exécution. *(uniquement si high)*

## Contexte

<Pourquoi ce changement : problème/besoin, ce qui l'a déclenché, résultat attendu.>

## Fichiers concernés

### Nouveaux
| Fichier | Rôle |
|---------|------|
| … | … |

### Modifiés
| Fichier | Changement |
|---------|-----------|
| … | … |

## Étapes d'implémentation

<préalable : étapes détaillées, dans l'ordre.>
<-dag : non détaillé ici — voir « DAG d'exécution ».>

## DAG d'exécution

<-dag : section complète. préalable : résumé court + lien vers `<YYYY-MM-DD>_<slug>-dag.md`.>

### Groupes parallélisables
- Groupe 1 : <ids simultanés>
- Groupe 2 : <ids simultanés>

### Tâches
| id | skill | repo(s) | depends_on | sub_skill | notes |
|----|-------|---------|------------|-----------|-------|
| … | … | … | … | … | … |

### Stack / DoD par repo
- **<repo>** : <runtime> <version> · <package_manager> <pm_version> · DoD : <résumé>

## Vérification

1. <comment tester de bout en bout — commandes, MCP, tests>
