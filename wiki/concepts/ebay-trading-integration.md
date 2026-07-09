---
title: "Concept: eBay Trading API integration"
type: concept
status: stable
sources:
  - src-eurocommemo/CLAUDE.md
related:
  - src-eurocommemo
  - doctrine-listeners
  - global-constants
updated: 2026-06-27
---

How `src-eurocommemo` synchronizes products to the eBay marketplace and ingests eBay events
— the most complex and side-effect-heavy subsystem in the codebase.

## Configuration & auth

- `EbayConfiguration` entity (DB table `ebay_configuration`) stores OAuth tokens (access +
  refresh), client credentials, redirect URI, runName, and the webhook toggle. eBay OAuth
  credentials live in the DB, **not** in env vars.
- `EbayApiConnector` manages OAuth tokens lazily (refresh/exchange via
  `neilcrookes/oauth2-ebay`). If `EbayConfiguration::isRefreshIsExpired()` is true, an alert
  email is sent to the developer — check this before any batch API call.
- `EbayService` retrieves/persists the OAuth configuration from the DB.

## Outbound sync (site → eBay)

`EbayTradingAPI` (`src/Service/Ebay/API/EbayTradingAPI.php`) wraps every SOAP call: create,
update stock/price/images, delete, get listings, get categories. It is orchestrated by
single-purpose use cases in `src/Service/Ebay/UseCase/`:

| Use case | Role |
|---|---|
| `CreateOnEbayUseCase` | Creates a listing, sets `Product.ebayId` + `ebayDateExport`. |
| `UpdateProductUseCase` | Diffs live eBay vs local; pushes stock/title/price/image only if different. |
| `DeleteEbayUseCase` | Ends the listing, clears `ebayId`/`ebayDateExport`, removes `CreateEbayHistory`. |
| `RunCreateProductsEbayUseCase` | Batch create via async queue; one message per eligible product. |
| `PreviewCreateProductsEbayUseCase` | Dry-run count + preview email before a batch. |
| `DefineTitleEbayUseCase` | Auto-generates `ebayTitle` (banknotes get a "Billet Souvenir {year} {country}" prefix). |
| `GetDeliveryShippingUseCase` | Resolves the `DeliveryShipping` record from product weight. |
| `GetProductsToCreateOnEbayUseCase` | Lists products eligible for eBay creation. |

### Rules
- Always check `Product::canBeCreateOnEbay()` first: `ebayTitle` ≤ 80 chars, stock > 0,
  weight set, image present, active, not "soon", mapped eBay category present.
- Never set `Product.ebayId` directly — go through the use case so `CreateEbayHistory` is tracked.
- All programmatic stock changes go through `StockManagementService::execute()`, which pushes
  the new value to eBay when `ebayId` is set. See [[doctrine-listeners]].

## Async batch creation (Messenger)

| Message | Transport | Handler |
|---|---|---|
| `CreateEbayAsyncMessage` | `async_create_ebay` (Doctrine, `messenger_messages` table) | `CreateEbayAsyncHandler` |

- `RunCreateProductsEbayUseCase` dispatches one message per product with a `DelayStamp`, and
  adds a **60-second delay every 200 messages** to respect eBay rate limits — do not remove.
- Retry: 3 attempts, 1000ms initial delay, no failure transport configured by default.
- Each handled message writes a `CreateEbayHistory` row (success or failure; errors stored as
  JSON in `CreateEbayHistory.errors`).
- Production consumption runs via `cron.php` → `messenger:consume async_create_ebay --time-limit=1800`.

## Inbound events (eBay → site)

eBay sends SOAP XML notifications to `POST /ebay/notification` (no locale prefix):

1. `WebhookController` decodes the XML, identifies the event via
   `WebhookLogTypeEnum::getFromEbay()`, writes a `WebhookLog`.
2. If `webhookEnable = true`, `WebhookMapperEventName` dispatches to tagged handlers:
   - `PaymentReceiveEvent` → creates/reuses a `User`, creates an `Order` with `isEbay=true`,
     decrements stock. **No confirmation email** (guard `isEbay`).
   - `ItemClosedEvent` → listing closure. `ItemRevisedEvent` → listing revision.
- `DiscountService` converts non-EUR eBay order discounts to EUR via `CurrencyConverter`.

## Related CLI

`app:sync-ebay-product` (match active listings to products by FR title → set `ebayId`),
`app:define-default-title-ebay` (backfill titles), `app:define-order-increment-on-order-ebay`
(backfill `fakeOrderIdEbay`), `app:clean-webhook-log`.
