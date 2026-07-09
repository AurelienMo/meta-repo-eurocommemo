---
description: >-
  Automatically maintains the LLM wiki in wiki/. Runs without manual invocation
  when docs/, product/, sources/, or sub-repo context files change. Also handles
  domain queries and periodic lint. Triggered by llm-wiki-auto rule and Claude Code hooks.
---

# Feed LLM Wiki

Maintain the compounding knowledge base in `wiki/` following [Karpathy's LLM Wiki pattern](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f).

**Automatic mode is ON** — see `.claude/rules/llm-wiki-auto.md`. Do not wait for the user to ask.

**Read first:** [`wiki/SCHEMA.md`](../../wiki/SCHEMA.md) · [`wiki/index.md`](../../wiki/index.md)

## When to run (automatic)

| Trigger | Operation |
|---|---|
| Edit to `docs/`, `product/`, `sources/` (auto-queued) | **Ingest** |
| Domain/cross-repo question | **Query** (file reusable answers) |
| Hook follow-up on `stop` with pending queue | **Ingest** |
| Sub-repo cloned / its `CLAUDE.md` changed (when `ai_visibility` ≠ `none`) | **Ingest sub-repo context** (see procedure below) |
| Reusable analysis in chat | **Query → file exploration** |
| Periodic maintenance | **Lint** |

## Ingest procedure

1. Confirm source path. **Never edit** files under `sources/` or `product/`.
2. Read source completely. Read related existing wiki pages from `wiki/index.md`.
3. Create/update `wiki/sources/<slug>.md` (one summary per source).
4. Create or update entity, concept, architecture, decision pages as needed.
5. Refresh `wiki/overview.md` if synthesis changed materially.
6. Update `wiki/index.md` — every touched page must appear.
7. Append entry to `wiki/log.md`:

```markdown
## [YYYY-MM-DD] ingest | <source title>

- Source: `<path>`
- Pages created: …
- Pages updated: …
- Notes: …
```

8. Run health check and clear the auto-sync queue:

```bash
python3 scripts/knowledge-lint.py
python3 scripts/knowledge-lint.py --fix-index
python3 scripts/wiki-auto.py clear
```

## Ingest sub-repo context (CLAUDE.md) procedure

Distil the per-repo `CLAUDE.md` files of the **linked repos** into the wiki. This is an **explicit,
on-demand / periodic pass** — sub-repo paths live outside the meta-repo, so the auto-sync hooks
(`scripts/wiki-auto.py`) cannot queue them. Run it when a sub-repo is freshly cloned, when its
`CLAUDE.md` changes, or as part of a periodic synthesis.

1. **Gate on policy.** Read `ai_visibility` from `context.yaml`.
   - `none` → repos are not expected to carry AI context files; **skip** this pass and note it in `log.md`.
   - `selective` | `full` → proceed.
2. **Resolve the repos.** `python3 scripts/resolve_paths.py . --json` → `{repo: {path, …}}`.
   Treat each repo tolerantly (mirror `resolve_paths.py --validate`): if its `path` is not a cloned
   Git directory, **skip it** (note the skip), don't fail the pass.
3. **Collect every `CLAUDE.md`.** For each cloned repo, find all `CLAUDE.md` in the tree, excluding
   vendored/build dirs:
   ```bash
   find "<repo-path>" -name CLAUDE.md \
     -not -path '*/node_modules/*' -not -path '*/vendor/*' -not -path '*/.git/*'
   ```
   Nested `CLAUDE.md` typically map architectural layers/modules. If a repo has none, skip it (note it).
   **Read only** — never edit a sub-repo.
4. **Source digest.** Create/update `wiki/sources/<repo>-claude-md.md`: one digest per repo,
   summarizing the root `CLAUDE.md` plus a short entry per nested `CLAUDE.md`. Cite each file by its
   repo-relative path (e.g. `src/Domain/.../CLAUDE.md`), not an absolute machine path.
5. **Enrich the entity page.** Update `wiki/entities/<repo>.md` with a *"Per-repo context (from
   CLAUDE.md)"* section: conventions, architecture/layering, key business rules, forbidden zones.
6. **Synthesis (only if material).** Refresh `wiki/architecture/*` and `wiki/overview.md` when the
   pass reveals something new at the workspace level (real inter-repo contracts, layering, etc.).
7. **Index + log + health.** Update `wiki/index.md` (every touched page listed); append to `wiki/log.md`:

```markdown
## [YYYY-MM-DD] ingest | sub-repo CLAUDE.md (<n> repos)

- Policy: ai_visibility=<selective|full>
- Repos ingested: … (skipped: <not cloned / no CLAUDE.md>)
- Pages created/updated: …
- Notes: …
```

Then run the health check:

```bash
python3 scripts/knowledge-lint.py
python3 scripts/knowledge-lint.py --fix-index
```

> The repos are **read-only sources**. Never modify a sub-repo. Synthesize — do not paste secrets,
> PII, or customer names into wiki pages.

## Query procedure

1. Read `wiki/index.md` → locate relevant pages.
2. Read pages + follow `related` / `[[links]]`.
3. Answer with citations: `(wiki: concepts/vop)` and raw sources where needed.
4. If answer is reusable, file to `wiki/explorations/<slug>.md` with frontmatter.
5. Update `wiki/index.md` and append to `wiki/log.md`:

```markdown
## [YYYY-MM-DD] query | <short question>

- Exploration filed: `wiki/explorations/<slug>.md` (or "none — ephemeral")
- Pages consulted: …
```

## Lint procedure

1. Read all pages listed in `wiki/index.md`; scan for orphans (pages on disk not in index).
2. Check:
   - Contradictions between pages
   - Stale `updated` dates vs newer sources in `sources/` or `product/`
   - Missing concept pages for repeated terms
   - Broken or missing cross-references
   - `overview.md` drift
3. Fix clear issues. Flag ambiguous contradictions for the user.
4. Append to `wiki/log.md`:

```markdown
## [YYYY-MM-DD] lint

- Issues found: …
- Fixes applied: …
- Open questions: …
```

5. Run `python3 scripts/knowledge-lint.py`.

## Page checklist (every new/updated page)

- [ ] YAML frontmatter (`title`, `type`, `status`, `sources`, `related`, `updated`)
- [ ] One-sentence lead
- [ ] Links to related wiki pages
- [ ] Source citations for factual claims
- [ ] Listed in `wiki/index.md`

## Boundaries

- Wiki = synthesized knowledge. Raw sources stay immutable.
- No secrets, PII, or customer names in wiki pages.
- Application code changes happen in sub-repos, not in wiki.
- English for wiki content (domain string literals may stay French).

## Examples

**Ingest:** "Ingest `sources/inbox/2026-05-meeting-notes.md` into the wiki"
→ summary page + touch entity/concept pages + index + log.

**Query + file:** "Compare legacy WebForms admin vs Lovable mock routing"
→ read wiki pages → answer → file `wiki/explorations/webforms-vs-lovable-routing.md`.

**Lint:** "Run wiki lint"
→ orphan/contradiction/stale scan → fix → log entry.

## Reference

- Pattern doc: [`docs/LLM-WIKI.md`](../../docs/LLM-WIKI.md)
- Sources layer: [`sources/README.md`](../../sources/README.md)
- Canonical deep-dives (ingest, don't replace): `docs/PRODUCT-IBANSECURE.md`, `docs/FRONT-ARCHITECTURE-LOVABLE-MOCK.md`
