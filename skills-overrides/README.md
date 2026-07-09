# skills-overrides/ — overrides de skills versionnés (client)

Ce dossier **versionné** permet de personnaliser, par client, les skills installés depuis le dépôt
amont `meta-repo-resources` — **sans les modifier sur place** (ce qui serait écrasé à la prochaine
mise à jour) et **sans perdre la personnalisation** (le dossier matérialisé `.claude/skills/` est,
lui, non versionné).

## Comment ça marche

`scripts/sync_skills.py` matérialise `.claude/skills/` en deux temps :

1. il copie la **base amont** (`meta-repo-resources`) ;
2. il applique **par-dessus** chaque fichier présent ici — l'override gagne toujours.

Comme les overrides sont ré-appliqués à **chaque** sync, ils **survivent aux mises à jour** amont.

## Convention : miroir partiel, fichier par fichier

L'arborescence ici **miroite** celle de `.claude/skills/`. Un fichier placé ici remplace le fichier
de **même sous-chemin** dans `.claude/skills/` :

```
skills-overrides/code-reviewer/checklists/java.md   →  remplace  .claude/skills/code-reviewer/checklists/java.md
skills-overrides/diff-writer/write-java/SKILL.md    →  remplace  .claude/skills/diff-writer/write-java/SKILL.md
```

La granularité est **le fichier** : on peut surcharger une seule checklist, un seul sous-skill
techno, ou un `SKILL.md` entier. On n'est jamais obligé de recopier tout un skill.

## Règles à respecter

- **Ne rien mettre sous `.claude/`.** Les overrides vivent ici, à la racine. Le scanner de skills de
  Claude Code récurse dans `.claude/skills/` : un `SKILL.md` placé sous `.claude/` serait chargé
  comme un **skill fantôme** dupliqué.
- **Conserver le `name:` amont** dans un `SKILL.md` overridé. Si vous changez le `name:`, vous créez
  un skill au nom différent au lieu de remplacer l'original.
- **Chaque fichier doit correspondre à un chemin amont.** Un override qui ne mappe sur aucun fichier
  de la base est signalé comme **orphelin** par le script (probable renommage/suppression en amont).
  En CI, `--strict` transforme un orphelin en échec.
- La propagation vers la copie miroir interne `validator/<…>` est **automatique** (les copies y sont
  byte-identiques à l'amont). Désactivable via `python3 scripts/sync_skills.py --no-mirror`.

## Commandes utiles

```sh
python3 scripts/sync_skills.py             # auto : overlay seul si .claude/skills/ existe, sinon clone+overlay
python3 scripts/sync_skills.py --fetch     # force le refresh de la base amont puis overlay
python3 scripts/sync_skills.py --no-fetch  # overlay seul (conserve l'existant, jamais de clone)
python3 scripts/sync_skills.py --dry-run   # auditer ce qui serait écrit, sans rien modifier
```

**Fetch auto-détecté** : par défaut, si `.claude/skills/` est déjà peuplé, son contenu est
**conservé** et seulement surchargé par les overrides — aucun clone. Le clone amont n'a lieu que
sur une install vierge (ou avec `--fetch`).
