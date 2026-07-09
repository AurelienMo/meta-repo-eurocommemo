---
title: "Architecture: meta-repo orchestration"
type: architecture
status: stable
sources:
  - README.md
  - CLAUDE.md
  - context.yaml
  - .claude/skills
related:
  - meta-repo-claude-md
  - src-eurocommemo
updated: 2026-06-27
---

How the Eurocommemo meta-repo orchestrates an agentic recode pipeline across the client's Git
repositories, and where each artifact lives.

## Layers

| Layer | Location | Role |
|---|---|---|
| Config (root) | `workspace.yaml`, `context.yaml`, `CLAUDE.md` | Repos & paths, pipeline policies, business context. |
| Config (contract) | `specs/dod.md`, `specs/guidelines/{_global,{repo}}.md` | Human-authored DoD + guidelines. |
| Plans | `plans/` | Generated pre-plans + planner DAGs (`plan-last.yaml` resume pointer). |
| Outputs | `docs/` | Pipeline outputs: `stack-snapshot.yaml`, per-repo `docs/<repo>/`, graphs. |
| Logs | `logs/<repo>.md` | Append-only record of every action on a child repo. |
| Skills | `.claude/skills/` | Pipeline skills (materialized, mostly non-versioned). |
| Wiki | `wiki/` | This synthesized knowledge base. |

## The pipeline

A chain of skills, orchestrated by the `pipeline` skill, runs per recode intention:

```
ticket-fetcher → clarification-loop → intent-parser → repo-resolver → tech-detector
→ toolchain-preflight → planner → diff-writer → test-generator → validator
→ code-reviewer → pr-builder
```

- `planner` writes the DAG to `plans/` (+ `plans/plan-last.yaml`).
- `diff-writer` is the sole producer of business-code patches; `test-generator` produces tests;
  `validator` is the only skill that executes produced code (build/lint/test/coverage).
- Gates: `clarification-loop` requires `spec.validated = true`; `toolchain-preflight` blocks if
  runtime/package manager versions diverge from the pin.
- Progress tracked with native task lists; interrupted runs resume via `plans/plan-last.yaml` +
  `docs/run-log.yaml`.

## Repo resolution & execution

- Repos are declared in `workspace.yaml` via `${REPOS_ROOT}/<name>`; `repos_root` is set
  per-machine in non-versioned `workspace.local.yaml`. Resolution is centralized in
  `scripts/resolve_paths.py` (`--json`, `--path`, `--validate`).
- **Every** per-repo command (version, build, lint, test, coverage) routes through
  `scripts/repo_exec.py` — either a Docker `compose` service or the native host. `src-eurocommemo`
  uses `exec.mode: compose` (service `php-fpm-per83`). Never call `mvn`/`npm`/`pytest` directly.
- Validation is tolerant: a declared-but-not-cloned repo is skipped; `--strict` (CI) requires all.

## Knowledge tooling

- **graphify** produces an AST-only knowledge graph per repo under `docs/<repo>/graphify-out/`
  (no LLM cost). Query before grepping. Current graph: `docs/src-eurocommemo/graphify-out/`.
- **LLM wiki** (`wiki/`, this base) is the meta-level synthesis, maintained by the
  `feed-llm-wiki` skill and checked by `scripts/knowledge-lint.py`. See [[meta-repo-claude-md]].

## Policies in force (`context.yaml`)

`ai_visibility: selective` · `guidelines_location: meta-repo` · `review_position: after_tests`
· PRs base `develop`, tests required · Conventional Commits · no autonomous commits.
