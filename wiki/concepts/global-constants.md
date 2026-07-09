---
title: "Concept: GlobalConstants & the no-magic-numbers rule"
type: concept
status: stable
sources:
  - src-eurocommemo/CLAUDE.md
related:
  - src-eurocommemo
  - doctrine-listeners
updated: 2026-06-27
---

`GlobalConstants` (`src/Utilities/GlobalConstants`) centralizes every integer identifier and
fixed ID in `src-eurocommemo`; hardcoding these values anywhere else is a forbidden pattern.

## What it owns

- **Payment states** (`Order.statePayment`) — use `GlobalConstants::CONST_STATE_PAYMENT_*`,
  never raw integers (e.g. PROCESS / VALID).
- **Payment methods** (`Order.methodPayment`) — `CONST_METHOD_PAYMENT_*` (CB, PayPal, CHEQUE,
  VIREMENT). The CHEQUE/VIREMENT distinction governs stock re-increment on cancel
  (see [[doctrine-listeners]]).
- **Configuration singleton ID** — `CONFIGURATION_ID` (the `Configuration` entity is `id=1`,
  loaded every request by `ConfigurationListener`).
- **Fixed category root IDs** — 2-euro coins, banknotes, coffrets, country and year
  subcategories. These IDs must not change in production; if a migration changes them, update
  `GlobalConstants` first.
- **Token lifetimes** — e.g. `LIFETIME_TOKEN_INIT_PASSWORD_IN_HOURS` (24h password-init window).
- TVA IDs and other configuration IDs.

## The rule

> Never hardcode integers for payment states, payment methods, category IDs, configuration
> IDs, or TVA IDs. Use `GlobalConstants`.

This is repeated across the repo's CLAUDE.md (§3 core principles, §8 domain model, §22
new-engineer notes) and is checked as part of "verification before done":

- After modifying entities, verify the `statePayment` constants are used — never a literal
  integer payment state.
- Category root IDs are stable production contracts; treat them as immutable.

## Why it matters

Payment state and method are plain integers on `Order`, and several listeners branch on them
(`OrderListener` stock re-increment, email guards). A stray literal silently diverges from the
canonical value and breaks order/stock/eBay flows that read the same constant.
