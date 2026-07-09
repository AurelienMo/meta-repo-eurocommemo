---
description: Branching model, conventional commits, meta-repo vs sub-repo boundaries
---

# Git Workflow

## Branch naming

- **Features:** `feature/<short-description>`
- **Bug fixes:** `fix/<short-description>`
- **Chores/docs:** `chore/<short-description>` or `docs/<short-description>`

<!-- TODO: confirm — add project-specific branch prefixes if needed -->

## Commit messages — Conventional Commits

```
<type>(<scope>): <description>

[optional body]
[optional footer]
```

Types: `feat`, `fix`, `docs`, `style`, `refactor`, `test`, `chore`, `perf`, `ci`, `revert`

- `<description>`: imperative, lowercase, no period
- `<scope>`: optional — sub-repo or module name
- Breaking changes: footer `BREAKING CHANGE: …`

## Meta-repo vs sub-repo

- **Never commit application code from the meta-repo root.**
- All application changes happen inside sub-repositories.
- Meta-repo commits are for scaffolding only: `CLAUDE.md`, `scripts/`, `docs/`, `.claude/`, `.vscode/`.

## No autonomous commits

Present a summary of changed files and **wait for an explicit user instruction** before running `git add` + `git commit`.
