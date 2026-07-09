# Action Logging

Every action taken by Claude on a child repository must be recorded in a per-repo log file so that any future session can reconstruct what was done, when, and with what outcome.

## Log file location

```
logs/<repo>.md
```

One file per child repository, named after the project key defined in `projects.json`:

- `logs/src-alchimia-api.md`
- `logs/src-api.md`
- `logs/src-api-shared-entities.md`
- `logs/src-cockpit.md`
- `logs/src-myprems.md`
- `logs/src-corpo-website.md`
- `logs/src-iframe-monitoring.md`
- `logs/src-keycloak-react-templates.md`
- `logs/src-lambda-pdf-engine.md`
- `logs/src-mobility-api.md`
- `logs/src-mobility-front.md`
- `logs/src-openfinance-widget.md`
- `logs/src-sharpit.md`
- `logs/src-smartaccount.md`
- `logs/src-alchimia-agents.md`

Each file lives in the meta-repo and is tracked by Git. Together they form the complete record of all Claude activity across the workspace.

## Log entry format

Every entry uses the following structure:

```
## [YYYY-MM-DD HH:MM] <repo> — <action summary>

**Target**: <child repo + branch>
**Status**: SUCCESS | FAILURE | PARTIAL
**Files affected**: <list of files created, modified, or deleted>
**Notes**: <anything requiring human attention, unexpected outcomes, or deferred items>
```

---

## When to write a log entry

Write an entry **immediately after** Claude performs any action that modifies files in a child repository. This includes:

- Creating, editing, or deleting source files
- Generating reports or documentation files
- Running scripts that produce file changes
- Applying automated transformations (e.g. codemods, OpenRewrite recipes)
- Writing or updating configuration files

One entry per action session (i.e. per user request that triggers file changes). If multiple files are touched in one request, group them in a single entry.

## Reading the log

Before starting any work on a child repo, read the full log for that repo:

```bash
cat logs/<repo>.md
```

This surfaces prior decisions and known issues so you don't repeat diagnostic work already done in a previous session.

## Maintenance

- Never delete entries — append only.
- If an action is re-run after a fix, add a new entry; do not overwrite the failed one.
- Keep the file valid Markdown so it renders cleanly on GitHub.
