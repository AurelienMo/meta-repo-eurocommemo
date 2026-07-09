# Wiki Log

Append-only record of ingests, queries, and lints.

## [2026-06-27] ingest | bootstrap LLM wiki

- Sources: `CLAUDE.md`, `.claude/CLAUDE.md`, `README.md`, `context.yaml`,
  `src-eurocommemo/CLAUDE.md` (634 lines, root only — no nested files),
  `docs/src-eurocommemo/graphify-out/GRAPH_REPORT.md`.
- Policy: `ai_visibility=selective` → sub-repo `CLAUDE.md` ingestion authorized.
- Pages created:
  - Structure: `SCHEMA.md`, `index.md`, `log.md`, `overview.md`.
  - Sources: `sources/meta-repo-claude-md.md`, `sources/src-eurocommemo-claude-md.md`.
  - Entity: `entities/src-eurocommemo.md`.
  - Concepts: `concepts/ebay-trading-integration.md`, `concepts/doctrine-listeners.md`,
    `concepts/global-constants.md`, `concepts/i18n-locale-routing.md`.
  - Architecture: `architecture/meta-repo-orchestration.md`, `architecture/eurocommemo-symfony.md`.
- Notes: first bootstrap of an empty `wiki/`. No `sources/` or `product/` dirs exist yet, so
  the seed corpus is the meta-repo + sub-repo CLAUDE.md + graphify report. The auto-sync rule
  `.claude/rules/llm-wiki-auto.md` is staged for deletion (status `D`) — hook-driven automatic
  maintenance is currently off; this pass was on-demand.

## [2026-07-09] ingest | graphify refresh + sub-repo CLAUDE.md (1 repo)

- Policy: `ai_visibility=selective` → sub-repo `CLAUDE.md` ingestion authorized.
- Graph refreshed: `docs/src-eurocommemo/graphify-out/` re-extracted (AST-only, `graphify extract`
  + `cluster-only --no-label`) from source HEAD `114a3f7`. New stats: **3492 nodes · 5297 edges ·
  329 communities** (previously 3204 · 4778 · 312). Report re-dated 2026-07-09.
- Repos ingested: `src-eurocommemo` (single root `CLAUDE.md`, ~635 lines — unchanged in substance,
  no nested files). Skipped: none.
- Pages updated:
  - `entities/src-eurocommemo.md` — resynced graph stats, bumped `updated`.
  - `architecture/eurocommemo-symfony.md` — resynced graph stats, bumped `updated`.
- Notes: `sources/src-eurocommemo-claude-md.md` reviewed — source `CLAUDE.md` content unchanged,
  digest left as-is. Architecture/overview synthesis unchanged (no material workspace-level delta).
  The `graphify` commit marker stamps the meta-repo CWD HEAD (`7245dbe0`), not the source repo —
  expected behavior, not a staleness signal.
