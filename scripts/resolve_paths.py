#!/usr/bin/env python3
"""resolve_paths — résolveur unique des chemins de repos d'un meta-repo.

Seul point de vérité pour transformer les chemins déclarés dans `workspace.yaml`
(versionné, portable) en chemins absolus sur la machine courante, en appliquant
l'overlay local `workspace.local.yaml` (NON versionné, propre à chaque dev).

Ordre de priorité, par repo :
  1. overlay `repos.<nom>.path`            (override explicite par repo)
  2. workspace `repos.<nom>.path`          (avec ${REPOS_ROOT} substitué)
  3. erreur explicite si aucun chemin résoluble

La racine ${REPOS_ROOT} provient, dans l'ordre :
  overlay `repos_root:` → env REPOS_ROOT → env TARGET (rétro-compat) → erreur.

Aucune donnée machine-spécifique ne doit vivre dans `workspace.yaml` : elle va
dans `workspace.local.yaml` (gitignoré, copié depuis `workspace.local.example.yaml`).

Stdlib uniquement (cohérent avec detect_stack.py / gen_docs.py).

API :
  resolve_repos(meta_repo) -> {nom: {"name", "path", "branch_default", ...}}

CLI :
  python3 scripts/resolve_paths.py <meta_repo>            # défaut: --json
  python3 scripts/resolve_paths.py <meta_repo> --json     # map nom -> infos (JSON)
  python3 scripts/resolve_paths.py <meta_repo> --path <repo>
  python3 scripts/resolve_paths.py <meta_repo> --validate # existence + repo Git (tolérant)
  python3 scripts/resolve_paths.py <meta_repo> --validate --strict  # repo absent = erreur
"""
import argparse
import json
import os
import re
import sys

_KV = re.compile(r"^(\s*)([A-Za-z0-9_.-]+):\s*(.*)$")
_ITEM = re.compile(r"^(\s*)-\s*(.*)$")


def _clean(value):
    """Normalise une valeur scalaire YAML : commentaire inline + guillemets.

    Respecte les guillemets : un `#` DANS une valeur citée n'est pas un commentaire,
    et un commentaire APRÈS la valeur citée (`"x"  # note`) est ignoré. Une valeur
    non citée réduite à un commentaire (`# note`) devient vide — indispensable pour
    qu'une clé suivie uniquement d'un commentaire (`exec:  # ...`) soit reconnue comme
    en-tête de bloc imbriqué et non comme un scalaire.
    """
    v = value.strip()
    if not v:
        return v
    if v[0] in "\"'":
        q = v[0]
        end = v.find(q, 1)
        if end != -1:
            return v[1:end]  # contenu cité ; commentaire de fin de ligne ignoré
        return v  # guillemet non fermé : laissé tel quel
    if v.startswith("#"):
        return ""
    h = v.find(" #")
    if h != -1:
        v = v[:h].rstrip()
    return v


def _load(path):
    """Parse minimal et tolérant d'un workspace(.local).yaml.

    Retourne (top, repos) :
      top   = {clé: valeur} de premier niveau (hors bloc 'repos:')
      repos = {nom: {champ: valeur|liste}}

    Tolère les indentations mixtes (mobility: 2/4, bienici: 2/4-5). Les listes en
    bloc (`depends_on:` suivi de `- x`) et inline (`exposes: []`) sont préservées
    au mieux ; seul `path` est nécessaire à la résolution.
    """
    top, repos = {}, {}
    if not os.path.exists(path):
        return top, repos
    lines = open(path, encoding="utf-8").read().splitlines()
    n = len(lines)
    in_repos = False
    repo_indent = None
    current = None
    i = 0
    while i < n:
        raw = lines[i]
        if not raw.strip() or raw.lstrip().startswith("#"):
            i += 1
            continue
        m = _KV.match(raw)
        if not m:
            i += 1
            continue
        indent, key, val = len(m.group(1)), m.group(2), _clean(m.group(3))
        if indent == 0:
            in_repos = key == "repos"
            current = None
            repo_indent = None
            if not in_repos and val != "":
                top[key] = val
            i += 1
            continue
        if not in_repos:
            i += 1
            continue
        if repo_indent is None:
            repo_indent = indent
        if indent <= repo_indent and val == "":
            current = key
            repos.setdefault(current, {})
            i += 1
            continue
        if current is not None and indent > repo_indent:
            if val == "":
                # Bloc imbriqué sous la clé : soit une liste (`- item`), soit un
                # sous-mapping (`key: val`, ex. `dod:`). On consomme toutes les
                # lignes plus indentées que la clé et on classe selon leur forme.
                seq, submap, j = [], {}, i + 1
                while j < n:
                    sub = lines[j]
                    if not sub.strip() or sub.lstrip().startswith("#"):
                        j += 1
                        continue
                    sub_indent = len(sub) - len(sub.lstrip())
                    if sub_indent <= indent:
                        break
                    im = _ITEM.match(sub)
                    if im:
                        seq.append(_clean(im.group(2)))
                        j += 1
                        continue
                    km = _KV.match(sub)
                    if km and _clean(km.group(3)) != "":
                        submap[km.group(2)] = _clean(km.group(3))
                        j += 1
                        continue
                    break
                if submap:
                    repos[current][key] = submap
                else:
                    repos[current][key] = seq if seq else ""
                i = j
                continue
            repos[current][key] = val
        i += 1
    return top, repos


def _abs(p):
    return os.path.abspath(os.path.expanduser(os.path.expandvars(p)))


def _resolve_root(local_top, default_root=None):
    """Racine ${REPOS_ROOT} : overlay → env REPOS_ROOT → env TARGET → default_root → None.

    `default_root` permet à un script appelant (ex: detect_stack.py) de fournir sa
    propre valeur de repli sans muter l'environnement ; l'overlay reste prioritaire.
    """
    root = (local_top.get("repos_root")
            or os.environ.get("REPOS_ROOT")
            or os.environ.get("TARGET")
            or default_root)
    return _abs(root) if root else None


def _resolve_path(raw, repos_root, name):
    p = raw
    if "${REPOS_ROOT}" in p or "$REPOS_ROOT" in p:
        if not repos_root:
            raise SystemExit(
                f"ERREUR: repo '{name}': '{raw}' référence ${{REPOS_ROOT}} mais "
                f"aucune racine n'est définie.\n"
                f"→ Copiez workspace.local.example.yaml en workspace.local.yaml et "
                f"renseignez 'repos_root:', ou exportez REPOS_ROOT (ou TARGET).")
        p = p.replace("${REPOS_ROOT}", repos_root).replace("$REPOS_ROOT", repos_root)
    return _abs(p)


def resolve_repos(meta_repo, default_root=None):
    """Map {nom: infos} avec un champ `path` absolu résolu pour chaque repo."""
    meta_repo = os.path.abspath(meta_repo)
    _, ws_repos = _load(os.path.join(meta_repo, "workspace.yaml"))
    lo_top, lo_repos = _load(os.path.join(meta_repo, "workspace.local.yaml"))
    repos_root = _resolve_root(lo_top, default_root)

    out = {}
    for name in sorted(set(ws_repos) | set(lo_repos)):
        info = dict(ws_repos.get(name, {}))
        info.update(lo_repos.get(name, {}))  # overlay surcharge le versionné
        raw_path = (lo_repos.get(name, {}).get("path")
                    or ws_repos.get(name, {}).get("path"))
        if not raw_path:
            raise SystemExit(
                f"ERREUR: repo '{name}' n'a aucun champ 'path:' (ni dans "
                f"workspace.yaml ni dans workspace.local.yaml).")
        info["name"] = name
        info["path"] = _resolve_path(raw_path, repos_root, name)
        out[name] = info
    return out


def repo_paths(meta_repo, default_root=None):
    """Raccourci {nom: chemin_abs} pour les scripts. Renvoie {} si rien n'est
    résoluble (ex: aucune racine définie) plutôt que de lever, pour permettre un
    repli côté appelant."""
    try:
        return {n: i["path"] for n, i in resolve_repos(meta_repo, default_root).items()}
    except SystemExit:
        return {}


def _validate(meta_repo, strict=False):
    """Vérifie l'état de chaque repo déclaré.

    Tolérant par défaut : un repo absent (non cloné) est une note informative,
    pas une erreur — tout le monde ne clone pas tous les projets d'un meta-repo.
    Seul un repo PRÉSENT mais qui n'est pas un repo Git est une erreur.

    Avec `strict=True` (CI / gate de release), un repo absent redevient une erreur.
    """
    repos = resolve_repos(meta_repo)
    if not repos:
        print("  — Aucun repo déclaré dans workspace.yaml")
        return 0
    errors = 0
    for name, info in repos.items():
        path = info["path"]
        if not os.path.isdir(path):
            # Absent = non cloné. Le marqueur ⊘ (≠ ✗) signale « ignoré » aux
            # appelants qui routent les erreurs sur ✗ (cf. validate-meta-repo.sh).
            print(f"  ⊘ {name}: non cloné (ignoré) ({path})")
            if strict:
                print(f"  ✗ {name}: répertoire introuvable ({path})", file=sys.stderr)
                errors += 1
        elif not os.path.isdir(os.path.join(path, ".git")):
            print(f"  ✗ {name}: pas un repo Git ({path})", file=sys.stderr)
            errors += 1
        else:
            print(f"  ✓ {name} → {path}")
    return 1 if errors else 0


def main(argv=None):
    parser = argparse.ArgumentParser(description="Résout les chemins des repos d'un meta-repo.")
    parser.add_argument("meta_repo", help="Chemin du meta-repo (contenant workspace.yaml)")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--json", action="store_true", help="Map nom -> infos (JSON)")
    group.add_argument("--path", metavar="REPO", help="Chemin absolu d'un seul repo")
    group.add_argument("--validate", action="store_true", help="Vérifie existence + repo Git (tolérant aux absents)")
    parser.add_argument("--strict", action="store_true", help="Avec --validate : un repo absent devient une erreur")
    args = parser.parse_args(argv)

    if args.validate:
        sys.exit(_validate(args.meta_repo, strict=args.strict))

    repos = resolve_repos(args.meta_repo)

    if args.path:
        if args.path not in repos:
            sys.exit(f"ERREUR: repo '{args.path}' introuvable dans workspace.yaml")
        print(repos[args.path]["path"])
        return

    print(json.dumps(repos, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
