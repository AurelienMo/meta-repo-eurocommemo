---
title: "Entity: src-eurocommemo"
type: entity
status: stable
sources:
  - src-eurocommemo/CLAUDE.md
  - workspace.yaml
  - docs/src-eurocommemo/graphify-out/GRAPH_REPORT.md
related:
  - src-eurocommemo-claude-md
  - eurocommemo-symfony
  - ebay-trading-integration
  - doctrine-listeners
  - global-constants
  - i18n-locale-routing
updated: 2026-07-09
---

`src-eurocommemo` is the only child repo currently in scope: a Symfony 6.4 e-commerce
platform selling commemorative coins and banknotes (2-euro coins, banknotes, sets), with a
full EasyAdmin back-office and eBay marketplace synchronization via the Trading API.

## Coordinates

- **Origin**: `git@github.com:CM-Development-687/eurocommemorative.git` (default branch `main`).
- **Local path**: resolved via `scripts/resolve_paths.py` to an OrbStack Docker volume.
- **Execution**: `exec.mode: compose` — commands run in the `php-fpm-per83` service
  (workdir `/var/www/eurocommemo`); driven through `scripts/repo_exec.py`, never directly.
- **Graph**: `docs/src-eurocommemo/graphify-out/` — 3492 nodes · 5297 edges · 329 communities
  (AST-only). Query with `graphify query "<q>" --graph docs/src-eurocommemo/graphify-out/graph.json`.

## Tech stack

PHP 8.3+ · Symfony 6.4 LTS · Doctrine ORM 2.17 (attribute mapping) · MySQL (two connections:
`default` + legacy `external`) · EasyAdmin 4.8 · KnpLabs DoctrineBehaviors 2.6 (translatable,
timestampable) · VichUploader · LiipImagine · FOSCKEditor (custom `divarea` plugin) · Symfony
Messenger (Doctrine transport) · DomPDF + FPDI (invoices) · Webpack Encore 4 (jQuery 3 + Vue 2
admin-only + Bootstrap 5.3). Payments: Société Générale ePay (Sogecommerce) + PayPal REST.
eBay: Trading API (SOAP) + Fulfillment + OAuth2. Currency: FreeCurrencyAPI.

## Per-repo context (from CLAUDE.md)

### Conventions & forbidden zones
- **Plan-first zones** (non-obvious side effects): eBay integration, `OrderListener`,
  `OperationCommercialeListener`, payment flows. Simple CRUD (new EasyAdmin field / entity
  column) may be implemented directly.
- **Never hardcode integers** for payment states/methods, category/config/TVA IDs — always
  `GlobalConstants` (see [[global-constants]]).
- **ORM**: PHP attributes only (no YAML/XML mapping); migrations only via
  `doctrine:migrations:diff` (no raw SQL); reserved-word tables overridden
  (`Order` → `orders`, `User` → `user`).
- **Minimal impact**: prefer adding fields/services over editing code wired into listeners.
- Decimal fields return `string|float` — cast `(float)` before arithmetic.

### Architecture / layering
Standard Symfony `src/` layout with eBay carved out: `Service/Ebay/{API,DTO,UseCase}`,
`Messenger/{Message,Handler}`, `Service/Webhook/Events/Ebay`, `Controller/Admin[/Ebay]`,
`EventListener` (Doctrine + Kernel), `Utilities/GlobalConstants`. Front routes are
locale-prefixed (`/{_locale}`), admin routes are not. See [[eurocommemo-symfony]].

### Key business rules
- `Configuration` is a **singleton** (`id=1`, `GlobalConstants::CONFIGURATION_ID`), loaded
  every request by `ConfigurationListener` into the Twig global context. Never create a second.
- `Order.isEbay = true` marks marketplace orders → confirmation/expedition emails are skipped
  (guard `!getIsEbay()` in `OrderListener`). Never remove this guard.
- `prixPromo` is owned by `OperationCommercialeListener` — never set manually on a product in
  an active operation. Use `Product::getPrixVenteActuel()` for the displayed price.
- Product slug `path` is prefixed with `{id}-` on first persist
  (`ProductCrudController::persistEntity`) — don't rely on `path` before the entity has an ID.
- Stock changes always go through `StockManagementService` to keep eBay in sync.
- eBay title max length **80 chars** (`Product::canBeCreateOnEbay()`).
- Invoice references: stored `Order.reference` uses prefix `F-`; display-only
  `getNumeroFactureFormated()` uses `FA-` — do not confuse them.

### Verification (run inside the PHP container via repo_exec)
`doctrine:schema:validate` after entity changes · `debug:router` / `debug:container` after
route/service changes · check `var/log/dev.log` after any eBay change · `messenger:consume
async_create_ebay` for the queue · `yarn build` before production deploy.

## Concept map

- [[ebay-trading-integration]] — the most complex subsystem (sync, webhooks, async batch).
- [[doctrine-listeners]] — entity lifecycle side effects (orders, stock, promos, ratings).
- [[global-constants]] — the no-magic-numbers discipline.
- [[i18n-locale-routing]] — locale-prefixed front vs unprefixed admin.
- [[eurocommemo-symfony]] — overall Symfony/EasyAdmin architecture.
