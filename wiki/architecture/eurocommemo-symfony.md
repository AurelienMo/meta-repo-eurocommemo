---
title: "Architecture: src-eurocommemo Symfony app"
type: architecture
status: stable
sources:
  - src-eurocommemo/CLAUDE.md
  - docs/src-eurocommemo/graphify-out/GRAPH_REPORT.md
related:
  - src-eurocommemo
  - ebay-trading-integration
  - doctrine-listeners
  - i18n-locale-routing
updated: 2026-07-09
---

The layered structure of the `src-eurocommemo` Symfony 6.4 application: storefront + EasyAdmin
back-office + eBay sync, backed by two MySQL connections.

## Source layout (`src/`)

- `Controller/` — front controllers (locale-prefixed) + `Controller/Admin/` (EasyAdmin CRUD),
  with `Controller/Admin/Ebay/` for eBay admin screens.
- `Entity/` — Doctrine entities (attribute mapping), `Entity/Ebay/` and `Entity/Enum/`
  (PHP 8.1 enums, e.g. `WebhookLogTypeEnum`).
- `EventListener/` (Doctrine + Kernel) and `EventSubscriber/` (EasyAdmin) — see [[doctrine-listeners]].
- `Service/` — business services; `Service/Ebay/{API,DTO,UseCase}` and
  `Service/Webhook/Events/Ebay/` for the marketplace integration ([[ebay-trading-integration]]).
- `Messenger/{Message,Handler}` — async eBay creation.
- `Builder/` — page-builder (Section/Block) for `Page`/`HomePage`.
- `Utilities/GlobalConstants` ([[global-constants]]), `Repository/`, `Security/`, `Form/`,
  `Field/Admin/`, `Filters/`, `Twig/`, `Dto/`, `Validator/`, `Exceptions/`, `Command/`.

Other top-level dirs: `assets/` (Encore entries), `config/packages/` (`doctrine.yaml` two
connections, `messenger.yaml`, `security.yaml`), `migrations/`, `templates/{admin,mail,front}`,
`translations/`, `lib/divarea/` (CKEditor plugin), `cron.php`.

## Data layer

- **Two connections**: `default` (primary app data) and `external` (legacy read-only). Never
  mix them; don't add entities to `external` without understanding it.
- Attribute mapping only; migrations only via `doctrine:migrations:diff`. Reserved-word tables
  overridden: `Order` → `orders`, `User` → `user`.
- Translatable + Timestampable via KnpLabs DoctrineBehaviors ([[i18n-locale-routing]]);
  file fields via VichUploader (bump `updatedAt` in setters to trigger replacement).
- Core domain entities: `Product`, `Order`, `User`, `Category` (self-referential tree),
  `OperationCommerciale`, `ProductNotation`, `Configuration` (singleton id=1), plus the eBay
  entities (`EbayConfiguration`, `CreateEbayHistory`, `WebhookLog`).

## EasyAdmin back-office

- CRUD controllers extend `AbstractCrudController` under `src/Controller/Admin/`; eBay ones
  under `Admin/Ebay/`. The dashboard redirects `/admin` to ready-to-ship paid orders.
- Custom per-product actions (eBay create/update/delete) via `Action::new()` in
  `configureActions()`; complex index queries override `createIndexQueryBuilder()`
  (`ProductCrudController` adds `soldSite`/`soldEbay` virtual columns).
- `EasyAdminSubscriber` saves page-builder elements and writes audit logs — do not bypass.
- Singleton entities (`Configuration`, `Footer`, `HomePage`) use
  `setEntityId(GlobalConstants::CONFIGURATION_ID)`. `AdminCrudController` (admins) and
  `UserCrudController` (customers) both target the `User` entity but are separate.

## Frontend (Webpack Encore 4)

jQuery 3 auto-provided; Vue 2 admin-only (batch eBay UI — do not upgrade to Vue 3 without a
rewrite); Bootstrap 5.3; FontAwesome 6. Entries: `app`, `app-paypal`, `app-hp`, `app-shop`,
`app-order`, `app-contact`, `app-profile`, `app-admin`, `admin-code-reduction-editor`, and
`email` (SCSS inlined via `twig/cssinliner-extra`). Run `yarn build` before deploy.

## Security

Custom `AppAuthenticator` (email/password, CSRF `authenticate`), `UserChecker` blocks
inactive accounts, remember-me 1 week, roles `ROLE_USER` ⊂ `ROLE_ADMIN`, admin routes require
`ROLE_ADMIN`. Password expiry +6 months; reset token 24h.

## Infrastructure

OrbStack containers: `stack-orb_php83` (run `bin/console` here, path `/var/www/eurocommemo`),
`stack-orb-encore-1` (Node/Encore), `stack-orb_database` (MySQL), `stack-orb_mailcatcher`
(dev SMTP). Production: shared hosting, PHP 8.3. A composer post-install hook copies the
`lib/divarea` CKEditor plugin into place. Graph stats: 3492 nodes · 5297 edges · 329
communities (AST-only).
