#!/usr/bin/env python3
"""repo_exec — point d'exécution central des commandes par repo.

Enveloppe une commande shell selon l'environnement d'exécution déclaré pour le repo
(bloc `exec:` dans workspace.yaml, surchargeable dans workspace.local.yaml) :

  - mode "native" (ou bloc `exec` absent) : exécution sur l'hôte, cwd = chemin du repo.
  - mode "compose" : exécution dans un service docker-compose DÉJÀ lancé, via
    `docker compose -f <compose_file> exec -T [-w <workdir>] <service> <shell> "<cmd>"`.

C'est le seul endroit qui sait router une commande vers le bon conteneur. Les skills
(toolchain-preflight, validator) passent par ici au lieu d'exécuter en direct, ce qui
permet de ne plus dépendre des toolchains installées sur l'hôte.

Stdlib uniquement (cohérent avec resolve_paths.py).

API :
  build_argv(repo_info, cmd) -> (argv, cwd)     # commande prête pour subprocess
  check(repo_info)           -> (ok, message)   # disponibilité de l'environnement

CLI :
  python3 scripts/repo_exec.py <meta_repo> <repo> -- <command...>   # exécute
  python3 scripts/repo_exec.py <meta_repo> <repo> --print -- <cmd>  # affiche, n'exécute pas
  python3 scripts/repo_exec.py <meta_repo> --check <repo>           # docker + service up
"""
import argparse
import os
import shlex
import subprocess
import sys

# Le résolveur vit dans le même dossier ; le rendre importable quel que soit le cwd.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from resolve_paths import resolve_repos  # noqa: E402

DEFAULT_COMPOSE_FILE = "docker-compose.yml"
DEFAULT_SHELL = "sh -lc"


def _exec_cfg(repo_info):
    cfg = repo_info.get("exec") or {}
    return cfg if isinstance(cfg, dict) else {}


def _cmd_str(cmd):
    """Normalise la commande (str ou liste) en une seule chaîne shell."""
    return cmd if isinstance(cmd, str) else " ".join(shlex.quote(c) for c in cmd)


def _compose_path(cfg, repo_path):
    """Chemin du fichier compose. Le bloc `exec` étant machine-spécifique, on expanse
    `~`, `$HOME` et les variables d'env : un chemin externe (absolu après expansion)
    est utilisé tel quel — la stack peut donc vivre HORS du repo. Un chemin relatif
    reste joint au repo (cas par défaut)."""
    compose_file = cfg.get("compose_file") or DEFAULT_COMPOSE_FILE
    compose_file = os.path.expanduser(os.path.expandvars(compose_file))
    return compose_file if os.path.isabs(compose_file) \
        else os.path.join(repo_path, compose_file)


def build_argv(repo_info, cmd):
    """(argv, cwd) pour exécuter `cmd` (str ou liste) selon le mode du repo.

    native  -> ['sh', '-lc', cmd] exécuté avec cwd = chemin du repo.
    compose -> docker compose -f … exec -T [-w workdir] service <shell> "cmd".
    Un shell enveloppe toujours la commande pour supporter pipes / && / variables.
    """
    cmd_str = _cmd_str(cmd)
    cfg = _exec_cfg(repo_info)
    mode = (cfg.get("mode") or "native").strip()
    repo_path = repo_info["path"]

    if mode == "native":
        return (["sh", "-lc", cmd_str], repo_path)

    if mode == "compose":
        service = cfg.get("service")
        if not service:
            raise SystemExit(
                f"ERREUR: repo '{repo_info['name']}': exec.mode=compose mais aucun "
                f"'service:' déclaré dans le bloc exec.")
        shell = cfg.get("shell") or DEFAULT_SHELL
        argv = ["docker", "compose", "-f", _compose_path(cfg, repo_path), "exec", "-T"]
        if cfg.get("workdir"):
            argv += ["-w", cfg["workdir"]]
        argv += [service] + shlex.split(shell) + [cmd_str]
        return (argv, repo_path)

    raise SystemExit(
        f"ERREUR: repo '{repo_info['name']}': exec.mode='{mode}' inconnu "
        f"(attendu : compose | native).")


def check(repo_info):
    """(ok, message) — disponibilité de l'environnement d'exécution.

    native  -> toujours OK (rien à vérifier).
    compose -> docker présent ET service listé « running ». Sinon, message de remédiation.
    """
    cfg = _exec_cfg(repo_info)
    mode = (cfg.get("mode") or "native").strip()
    name = repo_info["name"]

    if mode == "native":
        return (True, f"{name}: mode natif — aucun conteneur requis")
    if mode != "compose":
        return (False, f"{name}: exec.mode='{mode}' inconnu (attendu : compose | native)")

    service = cfg.get("service")
    if not service:
        return (False, f"{name}: exec.mode=compose sans 'service:' déclaré")
    compose_path = _compose_path(cfg, repo_info["path"])

    # 1. Docker disponible ?
    try:
        proc = subprocess.run(
            ["docker", "version", "--format", "{{.Server.Version}}"],
            capture_output=True, text=True, timeout=30)
    except FileNotFoundError:
        return (False, f"{name}: binaire 'docker' introuvable — installer Docker / Docker Desktop")
    except subprocess.TimeoutExpired:
        return (False, f"{name}: 'docker version' a dépassé le délai — le daemon répond-il ?")
    if proc.returncode != 0:
        return (False, f"{name}: daemon Docker injoignable — démarrer Docker ({proc.stderr.strip()})")

    if not os.path.exists(compose_path):
        return (False, f"{name}: fichier compose introuvable ({compose_path})")

    # 2. Service en cours d'exécution ?
    try:
        ps = subprocess.run(
            ["docker", "compose", "-f", compose_path, "ps", "--status", "running", "--services"],
            capture_output=True, text=True, timeout=30)
    except subprocess.TimeoutExpired:
        return (False, f"{name}: 'docker compose ps' a dépassé le délai")
    running = set(ps.stdout.split()) if ps.returncode == 0 else set()
    if service in running:
        return (True, f"{name}: service '{service}' en cours d'exécution")
    return (False,
            f"{name}: service '{service}' non démarré.\n"
            f"  → docker compose -f {compose_path} up -d {service}")


def _repo_info(meta_repo, repo):
    repos = resolve_repos(meta_repo)
    if repo not in repos:
        raise SystemExit(f"ERREUR: repo '{repo}' introuvable dans workspace.yaml")
    return repos[repo]


def main(argv=None):
    raw = list(sys.argv[1:] if argv is None else argv)
    # Tout ce qui suit le premier '--' est la commande à exécuter (robuste vs argparse).
    cmd = []
    if "--" in raw:
        idx = raw.index("--")
        raw, cmd = raw[:idx], raw[idx + 1:]

    parser = argparse.ArgumentParser(
        description="Exécute une commande dans l'environnement d'un repo (conteneur ou hôte).")
    parser.add_argument("meta_repo", help="Chemin du meta-repo (contenant workspace.yaml)")
    parser.add_argument("repo", nargs="?", help="Nom du repo cible")
    parser.add_argument("--check", metavar="REPO",
                        help="Vérifie la disponibilité de l'environnement (docker + service)")
    parser.add_argument("--print", dest="dry", action="store_true",
                        help="Affiche la commande enveloppée sans l'exécuter")
    args = parser.parse_args(raw)

    if args.check:
        ok, msg = check(_repo_info(args.meta_repo, args.check))
        print(("✓ " if ok else "✗ ") + msg, file=(sys.stdout if ok else sys.stderr))
        sys.exit(0 if ok else 1)

    if not args.repo:
        parser.error("repo requis (ou utilisez --check <repo>)")
    if not cmd:
        parser.error("aucune commande fournie (après '--')")

    info = _repo_info(args.meta_repo, args.repo)
    wrapped, cwd = build_argv(info, cmd)

    if args.dry:
        mode = (_exec_cfg(info).get("mode") or "native").strip()
        if mode == "native":
            print(f"cd {shlex.quote(cwd)} && {_cmd_str(cmd)}")
        else:
            print(" ".join(shlex.quote(p) for p in wrapped))
        return

    sys.exit(subprocess.run(wrapped, cwd=cwd).returncode)


if __name__ == "__main__":
    main()
