---
title: "Source: meta-repo CLAUDE.md & README"
type: source
status: stable
sources:
  - CLAUDE.md
  - .claude/CLAUDE.md
  - README.md
  - context.yaml
related:
  - meta-repo-orchestration
  - src-eurocommemo
updated: 2026-06-27
---

Digest of the meta-repo's own operating instructions: how the Eurocommemo workspace is
initialized, configured, and how the agentic recode pipeline is driven.

## What the meta-repo is

A **meta-repo** orchestrating a multi-tech agentic recode pipeline over a client's Git
repositories (client key `ESP` in `context.yaml`, product name "Eurocommemo"). It holds
configuration (root + `specs/`), generated plans (`plans/`), and pipeline outputs (`docs/`).
Pipeline skills are **not** versioned here — they are materialized from a dedicated
`meta-repo-resources` repo via `scripts/sync_skills.py` (the `feed-llm-wiki` skill is the
exception: versioned in this repo). See `README.md` (`CLAUDE.md`).

## Initialization (two-phase, idempotent)

`scripts/init-meta-repo.sh` initializes in place:

1. **Phase 1** — placeholders, per-repo files, local config, skills:
   `init-meta-repo.sh --client Eurocommemo --repos "<repo1,repo2>" --repos-root <parent-dir>`.
   Then edit `workspace.yaml` to declare each repo (`path: ${REPOS_ROOT}/<name>` + `origin`).
2. **Phase 2** — clone declared repos, detect stacks (`docs/`), validate:
   `init-meta-repo.sh --clone --scan`.

Repo paths are declared in versioned `workspace.yaml` via `${REPOS_ROOT}/<name>`; each dev
supplies machine config in **non-versioned** `workspace.local.yaml` (`repos_root`). Path
resolution is centralized in `scripts/resolve_paths.py` (`--json`, `--path <repo>`,
`--validate`). See [[meta-repo-orchestration]].

**Tolerant validation**: a declared-but-not-cloned repo is ignored (`⊘ non cloné`), not
blocking — each dev clones only their projects. `--strict` (CI) requires all repos present.

## Policies (`context.yaml`)

- `client: ESP`, `language.code: en`, `commit_convention: conventional-commits`.
- `ai_visibility: selective` — `CLAUDE.md` and `.ai-hints.md` are allowed inside the client
  repos (this is what authorizes ingesting `src-eurocommemo`'s `CLAUDE.md` into the wiki).
- `guidelines_location: meta-repo` — guideline files live under `specs/guidelines/`.
- `review_position: after_tests` — reviewer sees code **and** tests.
- `pr_rules`: base branch `develop`, tests required, `min_coverage_delta: 0`.
- `definition_of_done`: measurable baseline (overridable per repo via `workspace.yaml → repos.{repo}.dod`).

## Conventions (root `CLAUDE.md` + `.claude/rules/`)

- **Plans** saved under `plans/`: `plans/<YYYY-MM-DD>_<slug>.md` (pre-plan) +
  `plans/<YYYY-MM-DD>_<slug>-dag.md` (planner DAG) + `plans/plan-last.yaml` (resume pointer),
  all sharing skeleton `plans/_TEMPLATE.md`.
- **Per-repo command execution** always via `scripts/repo_exec.py` (routes to a Docker
  `compose` service or native host) — never call `mvn`/`npm`/`pytest` directly.
- **English** for all code, commits, docs, rules (`.claude/rules/english.md`); **French** for
  conversational CLI responses (`.claude/rules/terminal-language.md`).
- **Action logging**: every action on a child repo is appended to `logs/<repo>.md`
  (`.claude/rules/action-logging.md`).
- **Git workflow** (`.claude/rules/git-workflow.md`): Conventional Commits; never commit app
  code from the meta-repo root; no autonomous commits (wait for explicit instruction).
- **Anti-canary**: every CLI response begins with an identity anchor line injected by a hook.

## graphify

Each child repo has its own knowledge graph under `docs/<repo>/graphify-out/`. Current graph:
`docs/src-eurocommemo/graphify-out/` (AST-only, no LLM cost). Query before grepping:
`graphify query "<question>" --graph docs/<repo>/graphify-out/graph.json`.
