# Terminal Language

All conversational responses from Claude in the terminal (CLI) must be written in **French**,
regardless of the language used in the user's message.

This rule applies to:
- Text responses and explanations
- Questions asked via `AskUserQuestion`
- Status updates and progress messages
- Error messages and diagnostic summaries

This rule does **not** apply to:
- Source code identifiers, comments, and docstrings (must remain English per [[english]])
- Commit messages and branch names (must remain English per [[english]])
- Documentation files in `docs/`, `CLAUDE.md`, and `.claude/` (must remain English per [[english]])
- String literals that represent domain or regulatory data
