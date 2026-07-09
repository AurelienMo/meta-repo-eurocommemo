# Wiki Schema

Conventions for this compounding knowledge base, following the
[LLM Wiki pattern](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f).
The wiki holds **synthesized** knowledge; raw sources stay immutable in their repos.

## Directory layout

| Folder | Holds |
|---|---|
| `sources/` | One digest per ingested source (a `CLAUDE.md`, a doc, meeting notes…). |
| `entities/` | One page per concrete thing: a repo/project, a service, an external system. |
| `concepts/` | Reusable domain or technical concepts (cross-cutting, not a single file). |
| `architecture/` | How pieces fit together at the workspace or project level. |
| `decisions/` | Recorded decisions (ADR-style). Created only when a real decision emerges. |
| `explorations/` | Filed answers to reusable questions/analyses. |

Meta files (not counted as content pages by `scripts/knowledge-lint.py`): `SCHEMA.md`,
`index.md`, `log.md`. Every other `*.md` page **must** be listed in `index.md` or the lint
flags it as an orphan.

## Page frontmatter

Every page starts with YAML frontmatter:

```yaml
---
title: Human-readable title
type: source | entity | concept | architecture | decision | exploration
status: draft | stable
sources:
  - path/or/url            # what this page is synthesized from
related:
  - other-page-slug        # see also
updated: YYYY-MM-DD
---
```

## Page body rules

- One-sentence lead right after the frontmatter.
- Link related pages with `[[slug]]` (the page's filename without `.md`, e.g. `[[src-eurocommemo]]`).
- Cite factual claims: wiki cross-refs as `(wiki: concepts/global-constants)`, raw sources by path.
- English only. Domain string literals (FR regulatory/business values) may stay in French.
- No secrets, PII, or customer names.

## Operating procedures

Ingest, query, and lint procedures live in the `feed-llm-wiki` skill
(`.claude/skills/feed-llm-wiki/SKILL.md`). After any change, run:

```bash
python3 scripts/knowledge-lint.py
python3 scripts/knowledge-lint.py --fix-index
```
