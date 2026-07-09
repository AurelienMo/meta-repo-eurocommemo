#!/usr/bin/env python3
"""sync_skills — matérialise .claude/skills/ depuis meta-repo-resources + overrides client.

Source de vérité des skills : dépôt GitHub `meta-repo-resources` (base, NON versionnée
dans ce meta-repo). Overrides spécifiques au client : `skills-overrides/`
(VERSIONNÉ), appliqués PAR-DESSUS la base, fichier par fichier — l'override gagne
toujours. Comme ils sont ré-appliqués après chaque clone, les overrides
**survivent aux mises à jour** de la base amont.

Pourquoi les overrides vivent hors de .claude/ : le scanner de skills de Claude
Code récurse dans les sous-dossiers de .claude/skills/ — tout SKILL.md placé sous
.claude/ devient un skill chargé. Garder skills-overrides/ à la racine évite ces
« skills fantômes » par construction.

Fetch auto-détecté : par défaut, si .claude/skills/ est déjà peuplé (base installée),
son contenu est CONSERVÉ et seulement surchargé par les overrides — aucun clone. Le
clone amont n'a lieu que sur une install vierge. --fetch force le refresh ; --no-fetch
force l'overlay seul.

Séquence :
  1. décide s'il faut cloner (auto : seulement si .claude/skills/ vide/absent)
  2. si oui : clone (ou pull) la base amont puis la matérialise SANS purge (préserve feed-llm-wiki/)
  3. applique les overrides par-dessus le contenu (conservé ou fraîchement cloné)
  4. propage chaque override à la copie miroir validator/ si elle existe
  5. signale les overrides « orphelins » (cible base absente → renommage amont ?)
  6. logue chaque action — aucune troncature silencieuse
  7. nettoie le clone temporaire (sauf --keep-clone)

Idempotent : ré-exécutable, résultat stable (copie écrasante, pas d'accumulation).
Stdlib uniquement (cohérent avec resolve_paths.py / wiki-auto.py).

CLI :
  python3 scripts/sync_skills.py                       # auto : overlay seul si base présente, sinon clone+overlay
  python3 scripts/sync_skills.py --fetch               # force le refresh amont puis overlay
  python3 scripts/sync_skills.py --no-fetch            # overlay seul (conserve l'existant, jamais de clone)
  python3 scripts/sync_skills.py --dry-run             # affiche sans rien écrire
  python3 scripts/sync_skills.py --no-mirror           # ne pas propager à validator/
  python3 scripts/sync_skills.py --keep-clone <dir>    # clone persistant (pull au lieu de re-clone)
  python3 scripts/sync_skills.py --skills-repo <url>   # override de la source amont
  python3 scripts/sync_skills.py --ref <tag|sha>       # épingle une version amont
  python3 scripts/sync_skills.py --strict              # échoue si un override est orphelin
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

SKILLS_REPO = "https://github.com/AurelienMo/meta-repo-resources"
SKILLS_DIR = ".claude/skills"
OVERRIDES_DIR = "skills-overrides"
MIRROR_ROOT = "validator"          # dossier interne où validator/ duplique les autres skills
PROTECTED = {"feed-llm-wiki"}      # livré par le template, jamais écrasé/supprimé par la base
# Fichiers de skills-overrides/ qui ne sont pas des overrides (métadonnées du dossier)
SKIP_NAMES = {".DS_Store"}
SKIP_TOP_LEVEL = {"README.md"}     # README.md À LA RACINE de skills-overrides/ uniquement


def _run(cmd, cwd=None):
    """Exécute une commande, lève SystemExit avec un message clair sur échec."""
    proc = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    if proc.returncode != 0:
        joined = " ".join(cmd)
        raise SystemExit(
            f"ERREUR: échec de `{joined}` (code {proc.returncode}).\n"
            f"{proc.stderr.strip()}\n"
            f"→ Si c'est un échec d'authentification GitHub :\n"
            f"  gh auth login")
    return proc.stdout


def fetch_base(repo_url, ref, keep_clone):
    """Récupère la base amont. Retourne (clone_dir, cleanup) où cleanup() supprime
    le clone temporaire (no-op si --keep-clone)."""
    if keep_clone:
        clone_dir = Path(keep_clone).expanduser().resolve()
        if (clone_dir / ".git").is_dir():
            _run(["git", "-C", str(clone_dir), "fetch", "--all", "--tags", "--prune"])
            _run(["git", "-C", str(clone_dir), "checkout", ref or "HEAD"])
            if not ref:
                _run(["git", "-C", str(clone_dir), "pull", "--ff-only"])
        else:
            clone_dir.parent.mkdir(parents=True, exist_ok=True)
            _run(["git", "clone", repo_url, str(clone_dir)])
            if ref:
                _run(["git", "-C", str(clone_dir), "checkout", ref])
        return clone_dir, (lambda: None)

    tmp = Path(tempfile.mkdtemp(prefix="meta-repo-resources-"))
    cmd = ["git", "clone", "--depth", "1"]
    if ref:
        cmd += ["--branch", ref]
    cmd += [repo_url, str(tmp)]
    _run(cmd)
    return tmp, (lambda: shutil.rmtree(tmp, ignore_errors=True))


def _copy(src: Path, dst: Path, dry_run: bool):
    if dry_run:
        return
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)


def materialize_base(clone_dir: Path, skills_dst: Path, dry_run: bool, log):
    """Copie clone_dir/.claude/skills/ -> skills_dst, fichier par fichier, SANS
    purge préalable (préserve les dossiers PROTECTED comme feed-llm-wiki/)."""
    src_root = clone_dir / SKILLS_DIR
    if not src_root.is_dir():
        raise SystemExit(
            f"ERREUR: la base amont ne contient pas '{SKILLS_DIR}/' "
            f"(cherché dans {src_root}).")
    count = 0
    for src in sorted(p for p in src_root.rglob("*") if p.is_file()):
        rel = src.relative_to(src_root)
        if rel.parts and rel.parts[0] in PROTECTED:
            continue  # ne jamais écraser un skill livré par le template
        if src.name in SKIP_NAMES:
            continue
        _copy(src, skills_dst / rel, dry_run)
        count += 1
    log(f"Base amont matérialisée : {count} fichier(s) dans {SKILLS_DIR}/ "
        f"(dossiers préservés : {', '.join(sorted(PROTECTED))})")


def is_populated(skills_dst: Path) -> bool:
    """Vrai si la base amont semble déjà matérialisée : au moins une entrée non
    protégée et non cachée sous .claude/skills/ (un skill autre que feed-llm-wiki/,
    ou le registry SKILL.md amont)."""
    if not skills_dst.is_dir():
        return False
    for child in skills_dst.iterdir():
        if child.name in PROTECTED or child.name.startswith("."):
            continue
        return True
    return False


def iter_override_files(overrides_root: Path):
    """Yield les chemins relatifs des fichiers d'override réels (hors métadonnées)."""
    for src in sorted(p for p in overrides_root.rglob("*") if p.is_file()):
        rel = src.relative_to(overrides_root)
        if src.name in SKIP_NAMES:
            continue
        if len(rel.parts) == 1 and rel.name in SKIP_TOP_LEVEL:
            continue
        yield rel, src


def apply_overrides(overrides_root: Path, skills_dst: Path, mirror: bool,
                    dry_run: bool, log):
    """Applique les overrides par-dessus la base. Retourne (overridden, mirrored,
    orphans) — listes de chemins relatifs."""
    overridden, mirrored, orphans = [], [], []
    for rel, src in iter_override_files(overrides_root):
        dst = skills_dst / rel
        if not dst.exists():
            orphans.append(rel)
        _copy(src, dst, dry_run)
        overridden.append(rel)

        # Propagation à la copie miroir validator/ si elle existe dans la base.
        if mirror and rel.parts and rel.parts[0] != MIRROR_ROOT:
            mir_dst = skills_dst / MIRROR_ROOT / rel
            if mir_dst.exists():
                _copy(src, mir_dst, dry_run)
                mirrored.append(rel)

    for rel in overridden:
        log(f"  override   {rel}")
    for rel in mirrored:
        log(f"  ↳ miroir    {MIRROR_ROOT}/{rel}")
    for rel in orphans:
        log(f"  ⚠ ORPHELIN  {rel} — aucun fichier base correspondant "
            f"(renommé/supprimé en amont ?)", warn=True)
    return overridden, mirrored, orphans


def sync(meta_repo: Path, repo_url: str, ref, keep_clone, mirror: bool,
         dry_run: bool, strict: bool, fetch_mode: str):
    skills_dst = meta_repo / SKILLS_DIR
    overrides_root = meta_repo / OVERRIDES_DIR

    warnings = []

    def log(msg, warn=False):
        stream = sys.stderr if warn else sys.stdout
        print(msg, file=stream)
        if warn:
            warnings.append(msg)

    prefix = "[dry-run] " if dry_run else ""

    # Décision de fetch : --fetch force, --no-fetch interdit, auto = seulement si vide.
    populated = is_populated(skills_dst)
    if fetch_mode == "force":
        do_fetch = True
    elif fetch_mode == "never":
        do_fetch = False
    else:  # "auto"
        do_fetch = not populated

    if do_fetch:
        log(f"{prefix}Clone de la base amont : {repo_url}"
            + (f" @ {ref}" if ref else ""))
        clone_dir, cleanup = fetch_base(repo_url, ref, keep_clone)
        try:
            materialize_base(clone_dir, skills_dst, dry_run, log)
        finally:
            cleanup()
    else:
        if not populated:
            raise SystemExit(
                f"ERREUR: '{SKILLS_DIR}/' est vide ou absent — rien à conserver.\n"
                f"→ Relancez avec --fetch pour cloner la base amont, ou en mode "
                f"auto (sans --no-fetch).")
        n = sum(1 for c in skills_dst.iterdir()
                if c.name not in PROTECTED and not c.name.startswith("."))
        log(f"{prefix}Base existante conservée ({n} entrée(s) dans {SKILLS_DIR}/) "
            f"— overlay seul, aucun clone.")

    if not overrides_root.is_dir():
        log(f"Aucun dossier '{OVERRIDES_DIR}/' — pas d'override à appliquer.")
        return 0

    overridden, mirrored, orphans = apply_overrides(
        overrides_root, skills_dst, mirror, dry_run, log)

    log(f"{prefix}Terminé : {len(overridden)} override(s), "
        f"{len(mirrored)} propagé(s) à {MIRROR_ROOT}/, "
        f"{len(orphans)} orphelin(s).")

    if orphans and strict:
        return 1
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Matérialise .claude/skills/ depuis meta-repo-resources + overrides client.")
    parser.add_argument(
        "--meta-repo", default=".",
        help="Racine du meta-repo (défaut : répertoire courant).")
    parser.add_argument(
        "--skills-repo", default=SKILLS_REPO,
        help=f"URL du dépôt source des skills (défaut : {SKILLS_REPO}).")
    parser.add_argument(
        "--ref", default=None,
        help="Tag/branche/sha amont à matérialiser (défaut : HEAD).")
    parser.add_argument(
        "--keep-clone", metavar="DIR", default=None,
        help="Conserve un clone persistant à DIR (pull au lieu de re-clone).")
    fetch_group = parser.add_mutually_exclusive_group()
    fetch_group.add_argument(
        "--fetch", dest="fetch_mode", action="store_const", const="force",
        help="Force le clone/refresh amont avant l'overlay.")
    fetch_group.add_argument(
        "--no-fetch", dest="fetch_mode", action="store_const", const="never",
        help="N'effectue jamais de clone : overlay sur le contenu existant.")
    parser.set_defaults(fetch_mode="auto")
    parser.add_argument(
        "--no-mirror", action="store_true",
        help=f"Ne pas propager les overrides à la copie miroir {MIRROR_ROOT}/.")
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Affiche les actions sans rien écrire.")
    parser.add_argument(
        "--strict", action="store_true",
        help="Code de sortie non nul si un override est orphelin (utile en CI).")
    args = parser.parse_args(argv)

    meta_repo = Path(args.meta_repo).expanduser().resolve()
    if not (meta_repo / SKILLS_DIR).parent.is_dir():
        raise SystemExit(
            f"ERREUR: '{meta_repo}' ne ressemble pas à un meta-repo "
            f"(pas de dossier .claude/). Utilisez --meta-repo <chemin>.")

    sys.exit(sync(
        meta_repo=meta_repo,
        repo_url=args.skills_repo,
        ref=args.ref,
        keep_clone=args.keep_clone,
        mirror=not args.no_mirror,
        dry_run=args.dry_run,
        strict=args.strict,
        fetch_mode=args.fetch_mode,
    ))


if __name__ == "__main__":
    main()
