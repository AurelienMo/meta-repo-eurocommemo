---
title: "Overview"
type: architecture
status: stable
sources:
  - README.md
  - CLAUDE.md
  - context.yaml
  - src-eurocommemo/CLAUDE.md
related:
  - meta-repo-orchestration
  - src-eurocommemo
  - eurocommemo-symfony
updated: 2026-06-27
---

Workspace-level synthesis of the Eurocommemo meta-repo and its child projects. Start here,
then follow the links.

## The workspace

`meta-repo-eurocommemo` (client key `ESP`) orchestrates an **agentic recode pipeline** over a
client's Git repositories. It holds configuration, generated plans, and pipeline outputs;
pipeline skills are materialized from a separate resources repo. The full mechanics —
pipeline stages, repo resolution, containerized execution, graphify, policies — are in
[[meta-repo-orchestration]] (source digest: [[meta-repo-claude-md]]).

Operating policies (`context.yaml`): `ai_visibility: selective`, guidelines in the meta-repo,
review after tests, PRs onto `develop`, Conventional Commits, no autonomous commits.

## Projects in scope

Currently a single child repo:

- **[[src-eurocommemo]]** — a Symfony 6.4 e-commerce platform for commemorative coins and
  banknotes, with an EasyAdmin back-office and deep eBay Trading API synchronization. Overall
  structure in [[eurocommemo-symfony]]; source digest in [[src-eurocommemo-claude-md]].

## Cross-cutting concepts

- [[ebay-trading-integration]] — outbound product sync, async batch creation, inbound webhooks.
- [[doctrine-listeners]] — entity-lifecycle side effects (orders, stock, promos, ratings) — the
  main "plan-first" zone.
- [[global-constants]] — the no-magic-numbers discipline for payment states, category IDs, etc.
- [[i18n-locale-routing]] — locale-prefixed front routes + KnpLabs translatable entities.

## How to use this wiki

Conventions and page types are in `SCHEMA.md`. The full page list is in `index.md`. Changes
are recorded in `log.md` and validated with `python3 scripts/knowledge-lint.py`.
