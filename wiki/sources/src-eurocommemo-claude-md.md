---
title: "Source: src-eurocommemo CLAUDE.md"
type: source
status: stable
sources:
  - src-eurocommemo/CLAUDE.md
related:
  - src-eurocommemo
  - ebay-trading-integration
  - doctrine-listeners
  - global-constants
  - i18n-locale-routing
updated: 2026-06-27
---

Digest of the per-repo `CLAUDE.md` (634 lines) of the `src-eurocommemo` child repo — a
Symfony 6.4 e-commerce platform for commemorative coins and banknotes with deep eBay
Trading API integration. Repo resolved via `scripts/resolve_paths.py` to an OrbStack volume
(origin `git@github.com:CM-Development-687/eurocommemorative.git`).

The repo has a **single** `CLAUDE.md` at its root (no nested module-level files).

## Sections in the source

The `CLAUDE.md` is organized into 22 numbered sections. Key content distilled into wiki pages:

- **Workflow / task management / core principles** (§1–3) → [[src-eurocommemo]] per-repo context.
- **Tech stack** (§5) and **repository structure** (§6) → [[src-eurocommemo]] + [[eurocommemo-symfony]].
- **eBay integration** (§7), **messaging/queues** (§12) → [[ebay-trading-integration]].
- **Domain model** (§8), **ORM rules** (§9), **translatable entities** (§10) → [[src-eurocommemo]] + [[doctrine-listeners]].
- **Event listeners & subscribers** (§13) and **key data flows** (§15) → [[doctrine-listeners]].
- **EasyAdmin rules** (§11) → [[eurocommemo-symfony]].
- **Hardcoded-IDs / constants discipline** (§3, §8, §22) → [[global-constants]].
- **Routes** (§20) and locale prefix (§3) → [[i18n-locale-routing]].
- **Security** (§17), **infrastructure** (§18), **frontend** (§19), **env vars** (§21),
  **CLI commands** (§16) → [[src-eurocommemo]] + [[eurocommemo-symfony]].

## Highest-leverage facts (verbatim intent)

- The eBay integration, `OrderListener`, `OperationCommercialeListener`, and payment flows
  are the **non-obvious side-effect zones** — plan full impact before touching them.
- Never hardcode integers for payment states/methods/category/config/TVA IDs — use
  `GlobalConstants`. See [[global-constants]].
- ORM mapping is **PHP attributes only**; migrations only via `doctrine:migrations:diff`
  (no raw SQL); translatable entities via KnpLabs DoctrineBehaviors.
- Stock changes always go through `StockManagementService` so eBay stays in sync.
- `prixPromo` is owned by `OperationCommercialeListener` — never set manually on a product
  in an active operation.
- eBay orders carry `Order.isEbay = true` and must **not** trigger confirmation emails
  (guarded by `!getIsEbay()` in `OrderListener`).

> Read-only source. Synthesize, do not mirror; no secrets/PII in derived pages.
