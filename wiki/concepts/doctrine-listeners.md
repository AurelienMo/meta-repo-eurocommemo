---
title: "Concept: Doctrine listeners & lifecycle side effects"
type: concept
status: stable
sources:
  - src-eurocommemo/CLAUDE.md
related:
  - src-eurocommemo
  - ebay-trading-integration
  - global-constants
updated: 2026-06-27
---

The event listeners and subscribers in `src-eurocommemo` carry most of the business logic as
entity-lifecycle side effects — the primary "non-obvious side-effect" zone the repo warns to
plan around before touching `Order`, `Product`, `ProductNotation`, or `OperationCommerciale`.

## Listeners & subscribers

| Listener / Subscriber | Trigger | Effect |
|---|---|---|
| `ConfigurationListener` | `kernel.request` | Loads singleton `Configuration` (id=1); sets `seo`/`contact`/`logo`/`favicon` on Request attributes (available in all templates). |
| `MaintenanceListener` | `kernel.request` | Redirects to `app_page_maintenance` if `Configuration.maintenance = true`. Whitelist includes `admin`, `app_login`, profiler routes. |
| `OrderListener` | Doctrine `onFlush` (Order) | Tracking number set → `dateExpedition` + expedition email (not eBay). Payment cancel (cheque/virement only) → re-increments stock. Payment validated → assigns `orderIncrement` + `reference` + confirmation email (not eBay). |
| `ProductListener` | Doctrine `preUpdate` | When `Product.stock` goes from ≤0 to >0 → sends availability alerts to all `ProductAlert` subscribers and deletes their records. |
| `ProductNotationListener` | Doctrine `postUpdate` (ProductNotation) | When review moderation becomes non-zero → recomputes `Product.notationAverage` from approved notations. |
| `OperationCommercialeListener` | `postPersist`/`postUpdate`/`postRemove` (OperationCommerciale) | Sets/clears `Product.prixPromo` for all products in the promo's categories. Only sets if not already set. Calls `$em->flush()` internally. |
| `EasyAdminSubscriber` | EasyAdmin persist/update/delete events | Saves page-builder elements (Page/HomePage); writes audit logs (User/Category/Page/Faq/HomePage). |

## Critical rules

- **`OperationCommercialeListener` flushes inside lifecycle callbacks.** Never flush inside a
  loop that modifies products in the same request — it can trigger the listener recursively.
- **`OrderListener` re-increments stock on cancel only for `CHEQUE` and `VIREMENT`.** CB and
  PayPal cancellations do not (stock was never decremented until IPN confirmation).
- **`prixPromo` is owned by `OperationCommercialeListener`** — never set it by hand on a
  product in an active operation (it gets overwritten on the next flush). See [[src-eurocommemo]].
- eBay-origin orders (`isEbay = true`) skip all `OrderListener` emails — never remove the guard.

## Key data flows driven by listeners

- **CB payment (Sogecommerce ePay)**: `PaymentController` creates Order (`statePayment=PROCESS`)
  → user pays → ePay IPN `POST /{_locale}/payment/ipn` → `PaymentCbHelper::checkSignature` →
  on AUTHORISED set VALID + transaction data → clear cart → `OrderHelper::decreaseStockOrder`
  (→ `StockManagementService` → eBay sync) → flush triggers `OrderListener` → assign
  `orderIncrement`/`reference` + confirmation email.
- **Admin product update**: `ProductCrudController::updateEntity` → `addParentCategories` →
  persist → if `ebayId` set, `UpdateProductUseCase` diffs & pushes to eBay. See
  [[ebay-trading-integration]].
- **Commercial operation applied**: enable `OperationCommerciale` → `postPersist` sets
  `prixPromo = prixVente * (1 - percentage/100)` for products without one → flush → visible
  immediately; disable/delete clears them.

## Stock single source of truth

`StockManagementService` (`execute()` / `defineStock()`) is the only sanctioned way to change
stock programmatically — it pushes to eBay when `ebayId` is set (constants `PLATFORM_EUROCOMMEMO`,
`PLATFORM_EBAY`). Never `$product->setStock()` + flush directly.
