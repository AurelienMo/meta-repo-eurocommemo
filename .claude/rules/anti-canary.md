---
description: Anti-hallucination canary — identity anchor line required at the start of every CLI response
---

# Anti-Canary

Every CLI response **must** begin with an identity anchor line sourced from the `ANTI-CANARY`
context injected by the `UserPromptSubmit` hook.

## Required format

```
👤 {first_name} ({git_email})
```

Place this on its own line, immediately before the response body. No other text before it.

Example:
```
👤 Aurelien (morvan.aurelien@gmail.com)

Voici la réponse…
```

## When ANTI-CANARY context is present

Read `first_name` and `git_email` from the injected context and render them verbatim.
Do not substitute values from memory or prior turns — the hook provides fresh data each turn.

## When ANTI-CANARY context is absent

Write `[canary: no data]` on the first line to alert the user that the hook did not fire.

## Purpose

This canary lets the user instantly detect identity drift or hallucination: a wrong name or
email is a visible signal that something is wrong, before reading the rest of the response.
