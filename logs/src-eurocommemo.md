# Log — src-eurocommemo

## [2026-07-09 03:49] src-eurocommemo — Commit: feature de configuration Sendcloud backoffice

**Target**: src-eurocommemo @ main (commit `e0f8256`)
**Status**: SUCCESS
**Files affected** (8, un seul commit atomique `feat(sendcloud): add backoffice configuration page`):
- `migrations/Version20260709120000.php` (new)
- `src/Entity/Sendcloud/SendcloudConfiguration.php` (new)
- `src/Repository/Sendcloud/SendcloudConfigurationRepository.php` (new)
- `src/Service/Sendcloud/SendcloudConfigurationService.php` (new)
- `src/Controller/Admin/Sendcloud/SendcloudConfigurationController.php` (new + fix redirect `AdminUrlGenerator`)
- `src/Form/Sendcloud/SendcloudConfigurationFormType.php` (new + libellés/champs)
- `templates/admin/sendcloud/configuration/index.html.twig` (new)
- `src/Controller/Admin/DashboardController.php` (entrée de menu Sendcloud)
**Notes**: Regroupe le travail des sessions précédentes (page de config + fix `ea`) en un commit unique, la feature n'ayant jamais été commitée. Non poussé (rule "no autonomous commits").

## [2026-07-09 18:10] src-eurocommemo — Fix: erreur `Variable "ea" does not exist` à l'enregistrement de la config Sendcloud

**Target**: src-eurocommemo @ main (uncommitted)
**Status**: SUCCESS
**Files affected**:
- `src/Controller/Admin/Sendcloud/SendcloudConfigurationController.php` — la redirection post-save `redirectToRoute('sendcloud_configuration')` perdait le paramètre `eaContext`, donc la requête GET suivante n'avait pas de contexte EasyAdmin et le template `@EasyAdmin/page/content.html.twig` échouait sur `ea`. Remplacé par une redirection via `AdminUrlGenerator->setRoute('sendcloud_configuration')->generateUrl()` (injecté dans `index()`), qui conserve `eaContext` et la locale.
**Notes**: Cause racine : les routes custom montées dans un menu EasyAdmin ne disposent de la variable `ea` que si `eaContext` est présent dans l'URL (ajouté auto par le menu au 1er affichage, mais pas propagé par un `redirectToRoute` nu). Vérifié : `php -l` OK, `cache:clear` OK. Non vérifié : re-test navigateur du cycle enregistrer→redirection (pas de credentials admin).

## [2026-07-09 17:45] src-eurocommemo — Backoffice: page de configuration Sendcloud (identifiant / mot de passe / toggle webhooks)

**Target**: src-eurocommemo @ main (uncommitted)
**Status**: SUCCESS
**Files affected**:
- `src/Entity/Sendcloud/SendcloudConfiguration.php` (new) — entité singleton : `publicKey`, `secretKey` (string nullable), `webhookEnable` (bool default false), `updatedAt`, + `isConfigured()`. Calquée sur `Entity/Ebay/EbayConfiguration`.
- `src/Repository/Sendcloud/SendcloudConfigurationRepository.php` (new) — `findFirst()` (pattern EbayConfigurationRepository).
- `src/Service/Sendcloud/SendcloudConfigurationService.php` (new) — get-or-create `getConfiguration()` + `save()` (positionne `updatedAt` avant flush).
- `src/Form/Sendcloud/SendcloudConfigurationFormType.php` (new) — `publicKey` (TextType), `secretKey` (PasswordType, `always_empty=false`), `webhookEnable` (CheckboxType).
- `src/Controller/Admin/Sendcloud/SendcloudConfigurationController.php` (new) — route `sendcloud_configuration` (`/admin/sendcloud-configuration`), page custom EasyAdmin (handleRequest → save + flash).
- `templates/admin/sendcloud/configuration/index.html.twig` (new) — étend `@EasyAdmin/page/content.html.twig`, une carte de formulaire.
- `src/Controller/Admin/DashboardController.php` — nouveau sous-menu `Sendcloud → Configuration Sendcloud` (`ROLE_ADMIN`) inséré après le sous-menu Ebay.
- `migrations/Version20260709120000.php` (new) — `CREATE TABLE sendcloud_configuration`. Écrite à la main (pas `make:migration`) pour éviter tout DROP d'auto-diff.
- `docs/src-eurocommemo/graphify-out/*` — graphe rafraîchi (7 fichiers re-extraits).

**Notes**: Implémente `plans/2026-07-09_sendcloud-configuration-backoffice.md`. Périmètre volontairement borné — **aucune** consommation/déclenchement des webhooks ni appel API Sendcloud (chantier ultérieur) ; le toggle est un simple réglage persisté. Les vars `SENDCLOUD_*` de `.env.local` restent en place (non lues aujourd'hui), la nouvelle entité devient la source de vérité pour le futur connecteur.
**Contradiction relevée** : les entrées de log antérieures décrivant une intégration Sendcloud étendue (contrôleurs de shipping, migrations `Version20260705*`, WebhookLog Sendcloud) NE correspondent PAS à ce working tree — git status propre, aucun code/migration Sendcloud, aucun stash, DB en sync (`Executed Unavailable = 0`, Current = Latest = `Version20260708224710`). Ce travail a manifestement été perdu/réinitialisé sur un autre checkout ; l'implémentation a donc démarré d'une base vierge côté Sendcloud.
**Vérifié (via `scripts/repo_exec.py` → conteneur `php-fpm-per83`)** : `php -l` sur les 7 fichiers PHP (OK), migration appliquée (`doctrine:migrations:migrate`, 1 requête), colonnes confirmées (`id, public_key, secret_key, updated_at, webhook_enable`), `doctrine:schema:validate` mapping OK + aucun diff en attente sur `sendcloud_configuration` (le "not in sync" global est une dérive pré-existante sur d'autres tables), `lint:twig` OK, `debug:router sendcloud_configuration` OK (route sous `/{_locale}/admin`, protégée ROLE_ADMIN), `cache:clear` OK (autowiring service/contrôleur OK).
**Non vérifié** : scénario navigateur manuel en session admin (saisie + persistance + case webhook + accès non-admin refusé) — non piloté cette session (pas de credentials admin fournis).
**Note outillage** : `repo_exec.py` n'exécute correctement que si la commande est passée en tokens séparés après `--` ; une commande passée en chaîne unique est sur-échappée (`sh -lc ''"'"'…'"'"''`) et échoue en "not found". Bug de wrapper hors périmètre, non corrigé.

## [2026-07-09 16:30] src-eurocommemo — Snapshot delivery/billing address on checkout orders + relabel address step

**Target**: src-eurocommemo @ branch `main` (working tree, not committed)
**Status**: SUCCESS (`php -l` clean on both PHP files; `lint:twig`/`lint:yaml`/`lint:container`/`cache:clear` all pass via `scripts/repo_exec.py`; `doctrine:schema:validate` mapping OK — no mapping change made, no new migration needed; `vendor/bin/phpunit` reports "No tests executed!", same as always, no test suite in this repo)
**Files affected**:
- `src/Entity/OrderAddress.php` — new `fromUser(User $user): self` factory, mirroring the existing `fromDto()` used by the eBay import flow. Maps `User`'s single inline address (`address`/`addressComplement`/`postalCode`/`commune`/`country`/`countryZone`/`countryZoneCommune`/`phone`) onto the flat `OrderAddress` fields, preferring `countryZoneCommune`'s own `getTitle()`/`getPostalCode()` (magic `__call`-proxied translation accessors, same ones `CountryZoneCommune::__toString()` already relies on) over the free-text `postalCode`/`commune` fields when a zone commune is selected — mirrors `User::getFullAddress()`'s existing priority rule. No new `use` import needed (`User` is in the same `App\Entity` namespace).
- `src/Service/CartHelper.php` — `cartToOrder()`: right after `$order->setUser($user)`, added `$order->setDeliveryAddress(OrderAddress::fromUser($user))` and `$order->setBillingAddress(OrderAddress::fromUser($user))` (two separate calls, not one shared instance, since `Order::replaceAddress()` mutates the passed object's `type` in place). Added `use App\Entity\OrderAddress;`.
- `translations/shop.fr.yml` / `.en.yml` / `.de.yml` — relabeled the `address`, `yourAddress`, `modifier` keys under `shop.order` to explicitly say "adresse de livraison et de facturation" / "shipping & billing address" / "Liefer- und Rechnungsadresse".
- `templates/order/paiement.html.twig`, `templates/mail/mail_order.html.twig`, `templates/mail/mail_order_waiting_payment.html.twig`, `templates/order/pdf-preparation.html.twig` — the shipping-address recap/display blocks now read field-by-field from `order.deliveryAddress` (fullName/line1/line2/postalCode/city/countryCode via the existing `countryCodeToCountryEntity()` Twig function) instead of `app.user.*`/`order.user.*`, mirroring the pattern `templates/order/pdf-invoice.html.twig` already uses for `order.billingAddress`.
**Notes**: Plan `plans/2026-07-09_checkout-delivery-billing-address-snapshot.md`. Business rule confirmed with the user: the address is always identical for delivery and billing — no dual-address UI, both `OrderAddress` rows are populated from the exact same `User` data. No migration needed (`order_address` table already exists, built for the eBay import feature — see the 2026-07-08 21:00 entry below) and no new form field needed (the single-address form at `/order/information` is untouched). `templates/order/pdf-invoice.html.twig` needed **no change** — it already prefers `order.billingAddress` over `order.user.*`, so it now picks up the snapshot automatically. `templates/order/delivery.html.twig` intentionally keeps reading `app.user.fullAddress` (only the translation-key relabel applies there) since the `Order` doesn't exist yet at that step of the tunnel — it's only created later inside `cartToOrder()` during `/order/payment`. **Not yet functionally verified end-to-end**: needs a human to place a real test order (virement/chèque to avoid live PayPal), check the two new `order_address` rows in DB, confirm the confirmation email/payment recap/packing slip/invoice PDF all show the address correctly, and confirm that editing the profile address afterwards does NOT change what a past order displays (the whole point of the snapshot). No commit made — awaiting explicit instruction per git-workflow rule.

## [2026-07-09 15:00] src-eurocommemo — `app:ebay:fulfillment-order`: prompt to update addresses of an already-imported order from eBay

**Target**: src-eurocommemo @ current branch (uncommitted)
**Status**: SUCCESS (`php -l` clean on both files; `lint:container` passes via `scripts/repo_exec.py . src-eurocommemo` — new use case autowired into the command; `--help` shows the new `-u/--update-addresses` option)
**Files affected**:
- `src/Service/Ebay/UseCase/UpdateEbayOrderAddressesUseCase.php` (new) — `findExistingEbayOrder(string): ?Order` (same criteria as import: `orderIdEbay` + `isEbay = true`) and `replaceAddress(Order, string $type, FulfillmentShipToDTO): void` which rebuilds an `OrderAddress` via `OrderAddress::fromDto()` and calls `Order::setDeliveryAddress`/`setBillingAddress` then a single `flush()` (relies on the collection's `orphanRemoval` + `cascade: persist`). Autowired (no `services.yaml` change — covered by `App\: resource: '../src/'`).
- `src/Command/GetEbayFulfillmentOrderCommand.php` — inject `UpdateEbayOrderAddressesUseCase`; new `-u/--update-addresses` option; `execute()` now routes to `import()` on `--import` OR `--update-addresses` and passes `$input`. `import()` short-circuits via `findExistingEbayOrder()` BEFORE the buyer-email check (email only needed for creation) → new `handleExistingOrder()`. Per-address flow (`maybeUpdateAddress()`): shows `Current (DB)` vs `eBay` diff (`formatAddress()`), then a per-address `ConfirmationQuestion` (default No); `--update-addresses` applies without prompt; non-interactive without the flag leaves each address unchanged. Only `OrderAddress` (delivery + billing) is touched — the linked `User` address is intentionally left alone. Creation path unchanged (the `EbayOrderAlreadyImportedException` catch is now a concurrency safety net).
**Notes**: Plan `plans/2026-07-09_ebay-fulfillment-order-update-addresses.md`. Introduced `ConfirmationQuestion` (first use in the project — still `QuestionHelper`-based, consistent with `CreateUserCommand`/`DebugCommand`; the project has no `SymfonyStyle`). Knowledge graph refreshed (`graphify extract` + `cluster-only --no-label`, 7 files re-extracted). Not yet run (needs a real, already-imported eBay order id): manual scenarios 4–6 of the plan — interactive per-address y/N, `--update-addresses --no-interaction`, and creation non-regression. No automated command test (project `tests/` still has only `bootstrap.php`, no `CommandTester`). No commit made — awaiting explicit instruction per git-workflow rule.

## [2026-07-09 10:00] src-eurocommemo — Add `--import` to `app:ebay:fulfillment-order`, extract shared `ImportFulfillmentOrderUseCase`

**Target**: src-eurocommemo @ current branch (uncommitted)
**Status**: SUCCESS (`lint:container` passes via `scripts/repo_exec.py`; `php -l` clean on all 3 touched/new files)
**Files affected**:
- `src/Service/Ebay/UseCase/ImportFulfillmentOrderUseCase.php` (new) — shared import logic extracted from `PaymentReceiveEvent`'s former private methods (`defineOrderInformation`, `getBuyer`, `allItemsIsPresent`, `defineOrderLine`), now driven by `ImportBuyerDTO` instead of `PaymentReceiveEventDTO` so it has no webhook dependency. `execute(FulfillmentOrderDTO, ImportBuyerDTO, \DateTime): Order` throws `EbayOrderAlreadyImportedException` / `CountryNotFoundException` / `EbayProductsMissingException`. `setOrderIdEbay()` moved out of `defineOrderInformation()` into `execute()`, keyed off `FulfillmentOrderDTO::getOrderId()` (same value the webhook already used).
- `src/Service/Webhook/Events/Ebay/PaymentReceiveEvent.php` — constructor reduced to 4 dependencies; `handle()` now builds `ImportBuyerDTO::fromPaymentReceiveEvent()` and delegates to the use case, catching the three typed exceptions to preserve the exact prior mail/skip behavior (early duplicate check kept before the Fulfillment API call to avoid extra calls on webhook redeliveries). All moved private methods and their now-unused imports removed.
- `src/Command/GetEbayFulfillmentOrderCommand.php` — new `-i/--import` option; wires `ImportFulfillmentOrderUseCase` via constructor; new private `import()` method builds `ImportBuyerDTO::fromFulfillmentOrder()`, rejects with an explicit error when the buyer email is masked/absent in the Fulfillment payload, uses the order's real `creationDate` for `createdAt`, and maps the three typed exceptions to console messages/exit codes. Existing read-only/`--raw` behavior unchanged.
**Notes**: Plan `plans/2026-07-08_import-ebay-order-fulfillment-command.md`, steps 3–7 (steps 1–2 — the two exceptions and `ImportBuyerDTO` — were already done in a prior session). `ImportEbayOrderCommand` (Trading API) intentionally untouched, including its pre-existing debug `dd()`/`file_put_contents` and commented-out duplicate check — confirmed still present and out of scope. Knowledge graph refreshed (`graphify extract` + `cluster-only`, 20 files re-extracted). Not yet run: manual import scenario against a real sandbox/production order (plan's Vérification steps 3–6) — needs a real, not-yet-imported eBay order id to exercise `--import`, idempotence, and the pays/produit error paths; webhook non-regression on staging also still pending. No commit made — awaiting explicit instruction per git-workflow rule.

## [2026-07-08 21:00] src-eurocommemo — Migrate eBay order enrichment from Trading API to Fulfillment API + OrderAddress snapshot (delivery/billing)

**Target**: src-eurocommemo @ current branch (uncommitted)
**Status**: PARTIAL (code complete, `php -l` clean on all files, migration dry-run clean via `doctrine:migrations:migrate --dry-run` — 4 SQL queries, no errors; user opted to run the real migration and end-to-end webhook/order verification themselves rather than have it done in this session)
**Files affected**:
- `src/Service/Ebay/DTO/Output/Fulfillment/FulfillmentOrderDTO.php` — added `getBuyerRegistrationAddress(): ?FulfillmentShipToDTO` (reads `buyer.buyerRegistrationAddress`, same shape as `shipTo`, reuses `FulfillmentShipToDTO`).
- `src/Entity/OrderAddress.php` (new) — address snapshot entity discriminated by `type` (`delivery`/`billing`), flat fields (fullName/line1/line2/city/postalCode/countryCode/phone), `fromDto(?FulfillmentShipToDTO)` factory.
- `src/Repository/OrderAddressRepository.php` (new) — standard `ServiceEntityRepository`.
- `src/Entity/Order.php` — `OneToMany` relation to `OrderAddress` (cascade persist/remove, orphanRemoval), `getAddresses()`/`getDeliveryAddress()`/`getBillingAddress()`/`setDeliveryAddress()`/`setBillingAddress()` accessors.
- `migrations/Version20260708190052.php` (new, via `doctrine:migrations:diff`) — creates `order_address` table + FK to `orders` (`ON DELETE CASCADE`). Two unrelated stray `DROP INDEX external_id` statements (on `orders` and `user`, pre-existing schema drift — same pattern already seen and stripped in the 2026-07-06 Sendcloud migration) were removed from the auto-generated diff so this migration only touches `order_address`.
- `src/Service/Webhook/Events/Ebay/PaymentReceiveEvent.php` — enrichment call switched from `EbayTradingAPI::getOrder()` to `FulfillmentApiV1::getOrder()` (webhook trigger/XML parsing/dedup unchanged); `defineOrderInformation()` now takes `?FulfillmentAmountDTO` instead of `?ShippingCostDTO`; `allItemsIsPresent()`/`defineOrderLine()` now operate on `FulfillmentLineItemDTO` (product match: `ebayId` ← `getLegacyItemId()`, unchanged fallback to `ebayTitle`); snapshots both `OrderAddress` (delivery from `getShipTo()`, billing from `getBuyerRegistrationAddress()`) onto the order before persist — no extra `persist()` call needed, cascades from `Order`.
- `src/Command/GetEbayFulfillmentOrderCommand.php` — removed the debug `dd($order)` left over from the prior read-only exploration session.
**Notes**: Out of scope confirmed unchanged: `EbayTradingAPI::completeSell()` / `OrderCrudController::admin_delivery_validate()`, `ImportEbayOrderCommand` (still Trading API), webhook notification mechanism (still Trading API XML for order id/Ack/dedup). Still needed before considering this reliable (user will do this themselves): run the real migration on dev, run `app:ebay:fulfillment-order -o <real order id>` to confirm `getShipTo()`/`getBuyerRegistrationAddress()` return two distinct addresses, replay a test webhook and check `order_address` rows + `Order::getDeliveryAddress()`/`getBillingAddress()`, and compare amounts/line items between old (`EbayTradingAPI::getOrder()`) and new (`FulfillmentApiV1::getOrder()`) paths on 2-3 real orders. No commit made — awaiting explicit instruction per git-workflow rule.

## [2026-07-08 12:00] src-eurocommemo — eBay Sell Fulfillment API v1: fetch order detail by eBay order ID

**Target**: src-eurocommemo @ current branch (uncommitted)
**Status**: SUCCESS (`lint:container` passes; end-to-end run against real order `02-14852-44592` returns correct status/buyer/ship-to/total/line items; `--raw` dumps full JSON incl. `paymentSummary.payments[]`; invalid order ID returns a clean error via `ExternalEbayApiException`, no fatal)
**Files affected**:
- `src/Service/Ebay/DTO/Output/Fulfillment/FulfillmentAmountDTO.php` (new) — wraps eBay `Amount` objects (`value`/`currency`).
- `src/Service/Ebay/DTO/Output/Fulfillment/FulfillmentShipToDTO.php` (new) — wraps `fulfillmentStartInstructions[0].shippingStep.shipTo` (name, address, phone, email).
- `src/Service/Ebay/DTO/Output/Fulfillment/FulfillmentLineItemDTO.php` (new) — wraps one entry of `lineItems[]` (sku, title, quantity, costs, fulfillment status).
- `src/Service/Ebay/DTO/Output/Fulfillment/FulfillmentOrderDTO.php` (new) — main hydrated DTO for the full `getOrder` response: typed getters for order id/status/buyer/pricing/shipTo/lineItems, plus a generic `get('a.b.c')` dot-path accessor and `getPayload()` so any field of the response is reachable, typed or not.
- `src/Service/Ebay/API/FulfillmentApiV1.php` (new) — `getOrder(string $orderId): FulfillmentOrderDTO`, calls `GET /sell/fulfillment/v1/order/{orderId}` via the existing `$ebayJsonApi` Guzzle client (same pattern as `AccoungApiV1`), Bearer token from `GetEbayConfigurationUseCase` (auto-refreshes OAuth token), throws `ExternalEbayApiException` on non-200.
- `src/Command/GetEbayFulfillmentOrderCommand.php` (new) — `app:ebay:fulfillment-order --orderId=<id> [--raw]`, console command to exercise the service (human-readable summary or raw JSON dump).
**Notes**: Additive only — the existing Trading API-based order import (`ImportEbayOrderCommand`, `EbayTradingAPI::getOrder`) is untouched. No config/service wiring needed (Guzzle client `ebay_json_api` and `$ebayJsonApi` binding already existed). OAuth scope `sell.fulfillment` was already present on the connected account (no 403 encountered) — if it were missing, the fix is reconnecting via `/admin/ebay-configuration` with that scope added to the consent URL, not a code change. No unit tests: `tests/` has no framework wired up beyond `bootstrap.php`.

## [2026-07-06 15:30] src-eurocommemo — Sendcloud parcel creation from admin (label create/download/cancel), status webhook, expedition-flow fix

**Target**: src-eurocommemo @ branch `feature/sendcloud-dynamic-checkout` (same branch, still uncommitted)
**Status**: SUCCESS (php -l, lint:twig, lint:yaml, cache:clear all pass; migration applied; the 4 new routes registered per `debug:router`; end-to-end test pending — needs real keys + `SENDCLOUD_SENDER_ADDRESS_ID` and a paid order)
**Files affected**:
- `.env` — added `SENDCLOUD_SENDER_ADDRESS_ID=` to the Sendcloud block (value = id of the sender address configured in the client's panel; real value in `.env.local`).
- `config/services.yaml` — bound `$sendcloudSenderAddressId`.
- `src/Entity/Sendcloud/SendcloudParcel.php` (new) — parcel history entity: order FK, `parcelId` (unique), `shipmentId`, `trackingNumber`, `trackingUrl`, `labelUrl`, `status`, `statusCode`, `cancelled`, timestamps.
- `src/Repository/Sendcloud/SendcloudParcelRepository.php` (new) — `findActiveForOrder()`, `findOneByParcelId()`.
- `migrations/Version20260706151849.php` — creates `sendcloud_parcel` (pre-existing `external_id` drift stripped again). Applied.
- `src/Service/SendcloudApiConnector.php` — new `createShipment(array): array` (`POST /api/v3/shipments/announce`), `cancelShipment(string): array` (`POST /api/v3/shipments/{id}/cancel`), `downloadLabel(string): string` (GET absolute `documents[].link` URL), `getSenderAddressId(): ?int`; constructor takes `$sendcloudSenderAddressId`.
- `src/Service/SendcloudParcelService.php` (new) — `createParcelForOrder(Order): SendcloudParcel` (payload: `to_address` from order user, `from_address.sender_address_id`, `ship_with.shipping_option_code` = the Dynamic Checkout identifier captured at checkout, `to_service_point.id` when applicable, weight = order products + `DeliveryWeightAdditional`, same logic as `CartHelper::getWeightCart`; sets `numSuiviLivraison` → triggers expedition email via the fixed listener); `cancelParcelForOrder(Order)` (marks cancelled, clears tracking + `dateExpedition` without triggering a spurious email); `getLabelPdf(SendcloudParcel): string`.
- `src/Controller/Admin/SendcloudOrderController.php` (new) — 3 `ROLE_ADMIN` routes: `admin_sendcloud_create_label`, `admin_sendcloud_cancel_label` (flash + redirect back), `admin_sendcloud_download_label` (streams the PDF).
- `src/Twig/SendcloudParcelExtension.php` (new) — `sendcloud_active_parcel(Order)` Twig function.
- `templates/admin/order/order_delivery_action.html.twig` — Sendcloud branch FIRST (create/download/cancel buttons + shipped date + tracking); also fixes the template-level defect where a Sendcloud order (delivery null) fell into the "Confirmer la récupération" branch.
- `src/Controller/Admin/OrderCrudController.php` — `admin_delivery_validate()`: Sendcloud orders now take the "shipped" branch (manual tracking entry still possible), no longer the "collected in store" branch.
- `src/EventListener/OrderListener.php` — expedition email now fires for Sendcloud orders too, and only when the new tracking number is non-null (clearing it — label cancellation — no longer sends an email; latent pre-existing bug).
- `src/Entity/WebhookLog.php` — added `PLATFORM_SENDCLOUD = 'sendcloud'`.
- `src/Controller/WebhookController.php` — new `POST /sendcloud/webhook` (`webhook_sendcloud`): verifies `Sendcloud-Signature` (HMAC-SHA256 of raw body with the secret key, `hash_equals`), logs via the existing `createWebhookLog()`, updates the matching `SendcloudParcel` status/tracking on `parcel_status_changed`.

**Notes**: Per user decisions: parcel creation is **manual from admin** (not automatic at payment). Webhook URL to declare in the Sendcloud panel: `https://<domain>/sendcloud/webhook`. Human verification needed: set `SENDCLOUD_SENDER_ADDRESS_ID` in `.env.local` (panel → Settings → Addresses), pay an order with a Sendcloud option, use the admin buttons, confirm the parcel appears in the panel with the right carrier/service point, the label PDF downloads, cancellation works, and the classic static-grid + in-store flows are unchanged. Webhook payload field names (`parcel.status.id/message`) follow the parcel representation — confirm against a real webhook delivery and adjust the two field reads if needed. Still no commit — awaiting explicit instruction.

## [2026-07-06 05:45] src-eurocommemo — Loader while the SPP widget loads when a service-point option is pre-checked

**Target**: src-eurocommemo @ branch `feature/sendcloud-dynamic-checkout` (same branch, still uncommitted)
**Status**: SUCCESS (lint:twig OK, Encore rebuilt; visual check pending — throttle network and reload with a relay option selected)
**Files affected**:
- `templates/_loader.html.twig` — visibility class parametrized: `container-loader {{ loader_class|default('hide') }}` (backward-compatible, default unchanged).
- `templates/order/delivery.html.twig` — computes `preselectedServicePoint` (pre-checked radio is a `service_point_delivery` option) and renders a server-side-visible `#service-point-loader` wrapper (reusing `_loader.html.twig` with `loader_class: 'show'`) just before the picker block; hidden via `d-none` otherwise.
- `assets/app-order.js` — picker init hides `#service-point-loader` right after the initial visibility pass. That code runs at `window.load`, which fires only after the deferred SPP script (`api.min.js`) has executed — so the loader covers exactly the "widget JS not yet loaded" window the user asked about. Encore rebuilt (`yarn dev`).

**Notes**: The delivery options themselves are fetched server-side (present at first paint) — the only async part in the browser is the SPP widget script + our `window.load` glue; the loader bridges that gap when returning to `/order/delivery` with a relay option restored from session.

## [2026-07-06 05:15] src-eurocommemo — Service Point Picker map for Dynamic Checkout service-point options

**Target**: src-eurocommemo @ branch `feature/sendcloud-dynamic-checkout` (same branch as previous entry, still uncommitted)
**Status**: SUCCESS (php -l, lint:twig, lint:yaml, cache:clear, migration applied, Encore build all pass; end-to-end map test pending — needs the real Sendcloud keys already set locally by the user)
**Files affected**:
- `src/Service/SendcloudApiConnector.php` — added `getPublicKey(): string` (SPP widget needs the public key in the browser); removed the debug `dump($content)`.
- `src/Entity/Order.php` — 6 new nullable snapshot fields `sendcloudServicePoint{Id,Name,Street,PostalCode,City,PostNumber}` + getters/setters + `hasSendcloudServicePoint(): bool`.
- `migrations/Version20260706030805.php` — adds the 6 `sendcloud_service_point_*` columns to `orders` (pre-existing `external_id` drift stripped again). Applied.
- `src/Controller/OrderController.php` — `delivery()` POST: when the selected Dynamic Checkout option is `service_point_delivery`, requires `service_point[id]` (flash `shop.order.servicePointMissing` + redirect otherwise) and stores the snapshot in session (`sendcloudServicePoint`, cleared with the other session resets); GET: passes `sendcloudPublicKey` + `sessionServicePoint` to the template. `paiement()`: guard redirecting back to `/order/delivery` if a service-point option is selected without a chosen point. Removed both debug `dump()`s (the one in the `catch` called `$e->getResponse()` which `GuzzleException` doesn't guarantee — would have fataled on connect errors).
- `src/Service/CartHelper.php` — `cartToOrder()`: persists the session service point onto the new `Order` fields when the option is `service_point_delivery`; `removeAllCartItem()`: clears `selectedSendcloudOption` + `sendcloudServicePoint` from session after order completion.
- `templates/order/delivery.html.twig` — new `javascripts` block (SPP CDN script `https://embed.sendcloud.sc/spp/1.0.0/api.min.js` + `encore_entry_script_tags('app-order')`, which was NOT loaded on this page before — only its CSS was); `data-method-type`/`data-carrier-code` attributes on the Sendcloud radios; one shared `#service-point-picker` block (button + selected summary + inline error + 6 hidden `service_point[...]` inputs).
- `assets/app-order.js` — picker glue: shows the block only when the checked radio is `service_point_delivery`, scopes `sendcloud.servicePoints.open()` `carriers` to the radio's carrier code, resets the selection on carrier switch, fills the hidden inputs from the widget callback, blocks submit inline if no point chosen. Encore rebuilt (`yarn dev`, 58 files to `public/build`).
- `templates/mail/mail_order.html.twig` + `mail_order_waiting_payment.html.twig` — the Sendcloud branch now shows the pickup point address when `order.hasSendcloudServicePoint`, else the customer address as before.
- `translations/shop.{fr,en,de}.yml` — added `servicePointOpen` / `servicePointModify` / `servicePointMissing` keys.

**Notes**: Follow-up to the previous entry — the user tested live and found that service-point options (Colissimo / Mondial Relay) rendered but showed no map; the map is Sendcloud's separate Service Point Picker widget (public-key-only, browser-side), now wired to the Dynamic Checkout options. One shared picker serves all service-point carriers. Assumption flagged for human verification: SPP's `carriers` config uses the same carrier codes as Dynamic Checkout's `carrier.code` (e.g. `colissimo`, `mondial_relay`) — if the map opens unfiltered/empty for one carrier, that mapping needs a lookup table. Kept the user's manual branch edits (connector URL `/api/v3/...`, DTO `logo` field, carrier-name-only labels). Still no commit — awaiting explicit instruction.

## [2026-07-06 00:00] src-eurocommemo — Add Sendcloud Dynamic Checkout at delivery step

**Target**: src-eurocommemo @ branch `feature/sendcloud-dynamic-checkout` (new branch, cut from `main`)
**Status**: SUCCESS (lints, DI container compile, migration applied and schema-validated all pass; no test suite exists in this repo to run — `vendor/bin/phpunit` reports "No tests executed!")
**Files affected**:
- `.env` — new `### Sendcloud ###` block: `SENDCLOUD_BASE_URL`, `SENDCLOUD_PUBLIC_KEY`, `SENDCLOUD_SECRET_KEY` (mirrors the existing PayPal block; real keys go in `.env.local`, not committed).
- `config/packages/eight_points_guzzle.yaml` — new `sendcloud_api` Guzzle client (base URL from env, `Accept: application/json`, 30s timeout).
- `config/services.yaml` — bound `$sendcloudApiClient`, `$sendcloudPublicKey`, `$sendcloudSecretKey` in `_defaults.bind`.
- `src/Dto/Sendcloud/SendcloudDeliveryOptionDTO.php` (new) — array-hydrated DTO for one Sendcloud `delivery_options[]` entry (identifier type/value, carrier code/name, title, method type, shipping rate).
- `src/Service/SendcloudApiConnector.php` (new) — `getDynamicCheckoutDeliveryOptions(?string $toCountryCode, ?string $toPostalCode, float $totalWeightGrams, float $totalPrice): SendcloudDeliveryOptionDTO[]`, calls Sendcloud API v3 `POST checkout/delivery-options` with Basic Auth (mirrors `PaypalApiConnector`'s shape).
- `src/Entity/Order.php` — 7 new nullable string fields (`sendcloudCheckoutIdentifierType/Value`, `sendcloudCarrierCode/Name`, `sendcloudMethodTitle/Type`, `sendcloudShippingRate`) + getters/setters + `hasSendcloudDynamicCheckout(): bool`.
- `migrations/Version20260705235928.php` — adds the 7 `sendcloud_*` columns to `orders` (unrelated pre-existing `external_id` index drift on `orders`/`user`, surfaced by `make:migration`, deliberately stripped from this migration — same drift already noted in the 2026-07-02 eBay shipping-service log entry above).
- `src/Service/CartHelper.php` — new `getTotalAmountCart(): float` (extracted from the `sumCart` Twig computation in `delivery.html.twig`); `cartToOrder()` gets an `elseif ($session->get('selectedSendcloudOption'))` branch alongside the existing static-`Delivery` branch, persisting the session-stored, server-resolved option onto the new `Order` fields.
- `src/Controller/OrderController.php` — constructor now also injects `SendcloudApiConnector` and the default PSR `LoggerInterface`. `delivery()` GET path calls the connector (weight/price/country/postal code from the current cart and user), catches `GuzzleException` (logs + falls back to the existing static grid only), and stores the fetched options in session. POST path recognizes a `sendcloud:<identifier>` prefixed `delivery` value, resolves it **server-side** against the session-stored list (never trusts a client-submitted price/carrier), and rejects unknown identifiers with a flash + redirect.
- `templates/order/delivery.html.twig` — the static-grid radio's `checked` attribute (previously hardcoded) is now conditional on no Sendcloud option being selected; added a loop rendering one radio per fetched Sendcloud option.
- `templates/mail/mail_order.html.twig` and `mail_order_waiting_payment.html.twig` — added an `elseif order.hasSendcloudDynamicCheckout` branch showing the carrier/method instead of the "pickup in store" wording.
- `translations/shop.fr.yml` / `.en.yml` / `.de.yml` — added `shop.order.deliveryMissing` key (used by the new flash-error path).

**Notes**: Implements `plans/2026-07-06_sendcloud-dynamic-checkout.md` (design doc, itself built after finding and explicitly being told to ignore an older unmerged branch `feature/sendcloud-service-point-checkout` with unrelated Sendcloud plumbing for a different widget). Dynamic Checkout is a server-side REST call (Sendcloud API v3, beta), not a browser widget, so no new JS/CDN script was added. Scope is limited to selecting and persisting the customer's choice — booking the actual shipment (Sendcloud Shipments API) is out of scope and was not touched. **End-to-end functional test not run** (needs real `SENDCLOUD_PUBLIC_KEY`/`SENDCLOUD_SECRET_KEY` from the already-configured Sendcloud panel account, which only a human has): a person should set those in `.env.local`, walk `/order/information` → `/order/delivery` → `/order/payment` → `/order/complete`, and confirm live carrier/price options render and the choice round-trips onto the order and confirmation email as described above. No commit made yet — awaiting explicit instruction per this meta-repo's `git-workflow` rule.

## [2026-07-02 01:40] src-eurocommemo — Invoice PDF: show shipping service name + logo when showOnInvoice

**Target**: src-eurocommemo @ branch chore/sync-from-template (working tree)
**Status**: SUCCESS (Twig lint OK; visual PDF check pending — needs a real order + uploaded logo)
**Files affected**:
- `templates/order/pdf-invoice.html.twig` — added a conditional row in the totals table, just before `TOTAL Livraison`. Shows the shipping service label + logo when `order.shippingService is not null and order.shippingService.showOnInvoice`. Label = `description ?? shippingService` (human name, falls back to the raw token). Logo via `{{ absolute_url }}/uploads/images/logo/<logoName>` (mirrors existing site-logo `<img>`; Dompdf has `setIsRemoteEnabled(true)`), rendered only if `logoName` set.

**Notes**: Pure Twig change — no PHP needed (invoice = `OrderHelper::generateInvoice()` → Dompdf renders this template with the full `order` entity). `bin/console lint:twig` passes. No CLI path to regenerate an invoice (only controller routes: `OrderController:344`, `PaymentController:129`, and the import/webhook flows), so end-to-end PDF check is human: upload a PNG logo + set `show_on_invoice=1` on a service via back-office, link it to an order (`orders.shipping_service_id`), regenerate/download the invoice, confirm the row appears; counter-test with `show_on_invoice=0` → row absent. **Caveat**: Dompdf SVG support is partial — recommend PNG/JPG logos for reliable rendering.

## [2026-07-02 01:10] src-eurocommemo — Persist eBay ShippingService on Order (webhook + import command)

**Target**: src-eurocommemo @ branch chore/sync-from-template (working tree)
**Status**: SUCCESS (structural/compile verified; end-to-end import test pending a real eBay orderId)
**Files affected**:
- `src/Service/Ebay/DTO/Output/OrderEbayResponseDTO.php` — new `getShippingService(): ?string` reading `OrderArray.Order.ShippingServiceSelected.ShippingService`.
- `src/Entity/Order.php` — new `shippingService` `ManyToOne` → `Ebay\ShippingService` (JoinColumn `shipping_service_id`, nullable, `ON DELETE SET NULL`) + `shippingServiceCode` string(255) nullable (raw token, always captured) + getters/setters (mirrors existing `shippingProvider`).
- `src/Command/ImportEbayOrderCommand.php` — injected `ShippingServiceRepository`; after `defineOrderInformation()`, sets `shippingServiceCode` = token and resolves `shippingService` via `findOneByToken()`.
- `src/Service/Webhook/Events/Ebay/PaymentReceiveEvent.php` — same injection + same call-site block (the two paths duplicate `defineOrderInformation()` and are NOT shared, so the change is applied in both).
- `migrations/Version20260701230332.php` — `orders` ADD `shipping_service_id` + `shipping_service_code`, FK to `ebay_shipping_service(id)` ON DELETE SET NULL, index (unrelated `external_id` drift stripped).

**Notes**: Storage form chosen by user = **relation + raw token** (FK for future invoice logo/`showOnInvoice`, string so the eBay token is never lost even if absent from the synced `ebay_shipping_service` table). Verified: migration applied; `information_schema` confirms both columns + FK `FK_E52FFDEE55A7F9B8` → `ebay_shipping_service`; `doctrine:schema:validate` mapping OK (only remaining "not in sync" is the pre-existing `external_id` drift on `orders`/`user`, unrelated); `cache:clear` OK → the new `ShippingServiceRepository` DI compiles in both the command and the webhook handler. **End-to-end functional test not run**: importing a real order (`app:import:ebay-order --orderId <id>`) creates a real Order + invoice + stock decrement, so it needs a real not-yet-imported eBay orderId from a human; then check `orders.shipping_service_code` / `shipping_service_id`. Webhook path is code-identical to the command path.

## [2026-07-02 00:05] src-eurocommemo — ShippingService: logo upload (Vich) + `showOnInvoice` flag + EasyAdmin CRUD

**Target**: src-eurocommemo @ branch chore/sync-from-template (working tree)
**Status**: SUCCESS
**Files affected**:
- `src/Entity/Ebay/ShippingService.php` — `#[Vich\Uploadable]`; new fields `logoName` (string, nullable), `logoFile` (`File`, Vich mapping `logo`, not persisted), `showOnInvoice` (bool, default false). `setLogoFile()` bumps `updatedAt` (Vich change detection), pattern from `Entity/Category.php`.
- `src/Controller/Admin/Ebay/ShippingServiceCrudController.php` — new EasyAdmin CRUD (edit only): `disable(NEW, DELETE)`, read-only token/description/category, `BooleanField` `showOnInvoice`, `ImageField('logoName')` (index) + `VichImageType` upload field (forms, allow_delete). Mirrors `ShippingProviderCrudController` + `CategoryCrudController:118`.
- `src/Controller/Admin/DashboardController.php` — menu entry « Services de livraison » under the Ebay submenu (+ 2 imports).
- `migrations/Version20260701220045.php` — `ALTER TABLE ebay_shipping_service ADD show_on_invoice TINYINT(1) NOT NULL, ADD logo_name VARCHAR(255) DEFAULT NULL` (unrelated `external_id` index drops stripped to keep it atomic).

**Notes**: Invoice display itself is a **future feature** — only the `showOnInvoice` flag is stored now; no PDF logic touched. Reused the pre-existing Vich `logo` mapping (`config/packages/vich_uploader.yaml` → `/uploads/images/logo`). Migration applied; `information_schema` confirms both columns; `doctrine:schema:validate` mapping OK (the only remaining "not in sync" is the pre-existing `external_id` drift on `orders`/`user`, unrelated); `cache:clear` OK. **Idempotence proven**: set `show_on_invoice=1`+`logo_name` on `FR_ColiposteColissimo`, re-ran `ebay:list-shipping-services` (83 → 83), values preserved (sync upsert doesn't touch logo/flag); test row reset afterwards. Back-office click-through (upload a real logo, toggle flag) still to be done by a human.

## [2026-07-01 21:50] src-eurocommemo — Add `ebay:list-shipping-services` command + persist eBay France shipping services

**Target**: src-eurocommemo @ branch chore/sync-from-template (working tree)
**Status**: SUCCESS
**Files affected**:
- `src/Entity/Ebay/ShippingService.php` — new Doctrine entity (table `ebay_shipping_service`): `shippingService` (unique token), `description`, `shippingCategory`, `internationalService` (bool), `shippingServiceId` (int), `updatedAt`.
- `src/Repository/Ebay/ShippingServiceRepository.php` — new repository with `findOneByToken()`.
- `src/Service/Ebay/API/EbayTradingAPI.php` — added `getShippingServiceDetails()` calling Trading API `GeteBayDetails` with `DetailName=ShippingServiceDetails` (mirrors existing `getShippingDetails()` which uses `ShippingCarrierDetails`, left untouched). SiteID 71 (France) comes from the `ebay_api_trading` Guzzle client default headers; auth via `X-EBAY-API-IAF-TOKEN` (OAuth access_token from `ebay_configuration`).
- `src/Command/ListEbayShippingServicesCommand.php` — new command `ebay:list-shipping-services`: fetches, upserts (idempotent on token, in-memory dedup for repeated tokens), renders a table.
- `migrations/Version20260701214731.php` — creates `ebay_shipping_service` (unrelated auto-detected `external_id` index drops on `orders`/`user` were stripped to keep the migration atomic).

**Notes**: Ran end-to-end via `scripts/repo_exec.py` (compose → `php-fpm-per83`). API `Ack=Success`; **83 distinct shipping services** persisted for eBay France (31 international). Re-run confirmed idempotent (still 83). eBay returns duplicate tokens across categories (e.g. `PromotionalShippingMethod`) → handled by in-memory dedup before flush. Requires a valid non-expired OAuth token in `ebay_configuration` (refresh handled by `GetEbayConfigurationUseCase`).
**META-REPO side change (not this repo)**: fixed a real bug in `scripts/resolve_paths.py` `_clean()` (meta-repo) — inline YAML comments after a key-only line (`exec:  # ...`) or after a quoted value (`"svc"  # ...`) were not stripped, so the `exec:` compose block leaked and `repo_exec.py` wrongly fell back to native (no `php` on host). Not committed — awaiting user review.

## [2026-06-28 23:50] src-eurocommemo — Fix EasyAdmin "Can't read property sendcloudInfo" on Order edit

**Target**: src-eurocommemo @ branch chore/sync-from-template (working tree)
**Status**: SUCCESS
**Files affected**:
- `src/Controller/Admin/OrderCrudController.php` — `configureFields()` else branch: replaced `Field::new('sendcloudInfo', …)` (non-existent Order property → Symfony PropertyAccess error on the EDIT form) with `Field::new('adminObject', 'Expédition Sendcloud')->setTemplatePath(...)->onlyOnDetail()`; panel `FormField::addPanel("Sendcloud")->onlyOnDetail()`. `configureActions()`: enabled `Action::DETAIL` on PAGE_INDEX.

**Notes**: Root cause — `Field::new()` first arg is read as an entity property; on a form
(EDIT/NEW) EA maps it via Symfony Form which requires a readable property, unlike INDEX/DETAIL
where `isReadable()` tolerates it and `setTemplatePath` is honored. Moved the read-only parcels
block to the DETAIL view (idiomatic, matches the other `adminObject` template fields). Sendcloud
action buttons (create label / cancel / return) unchanged on INDEX + EDIT. Verified: `php -l` OK,
`lint:twig` OK, `cache:clear` OK. Back-office click-through (open edit, open detail) to confirm by human.

## [2026-06-29 00:00] src-eurocommemo — Add Transporteur + Actif filters to SendcloudShippingMethodCrudController

**Target**: src-eurocommemo @ branch chore/sync-from-template (working tree)
**Status**: SUCCESS
**Files affected**:
- `src/Repository/Sendcloud/SendcloudShippingMethodRepository.php` (added `findDistinctCarriers()`)
- `src/Controller/Admin/Sendcloud/SendcloudShippingMethodCrudController.php` (added constructor injecting the repository, `configureFilters()` with a dynamic `ChoiceFilter` on `carrier` and a `BooleanFilter` on `active`, plus the related imports)

**Notes**: EasyAdmin CRUD now exposes two index filters. Carrier choices are populated
from distinct values present in DB via `findDistinctCarriers()`. `php -l` passes on both
files (run inside the `php-fpm-per83` compose container; `repo_exec.py` fell back to native
where PHP is absent). No schema change, no migration. Functional check in the back-office
(filter panel) still to be done by a human.

## [2026-07-03 00:55] src-eurocommemo — Move shipping service logo next to invoice totals block

**Target**: src-eurocommemo, branch `main` (working tree, not committed)
**Status**: SUCCESS
**Files affected**: `templates/order/pdf-invoice.html.twig`
**Notes**: The shipping service logo (when `showOnInvoice` and `logoName` are set) now renders
in the previously empty area left of the totals block (TOTAL HT / TVA / TTC / Livraison / TTC),
using a `rowspan` cell spanning all total rows (5, or 6 with a discount code). The logo `<img>`
was removed from the bottom `.container-payment` block; the textual line
"Livraison : <description>" is kept there. `lint:twig` passes (run in the `php-fpm-per83`
compose container via `repo_exec.py`). Visual check of a generated Dompdf invoice (with and
without shipping logo / discount code) still to be done by a human. No commit made per the
no-autonomous-commits rule.

## [2026-07-03 01:05] src-eurocommemo — Refine shipping logo placement on invoice PDF

**Target**: src-eurocommemo, branch `main` (working tree, not committed)
**Status**: SUCCESS
**Files affected**: `templates/order/pdf-invoice.html.twig`
**Notes**: The shipping logo cell next to the totals block is now right-aligned
(`text-right`, `padding-right: 10px`) so the logo sits against the totals table, and the
logo was reduced from 60px to 40px max-height (130px max-width). `lint:twig` passes in the
`php-fpm-per83` compose container. Note: the logo `src` uses a hardcoded
`https://eurocommemo.orb.local` base (user change kept as-is) — to revisit before production.

## [2026-07-05 10:03] src-eurocommemo — Add service-point delivery type to the tariff grid (Sendcloud step 1/10)

**Target**: src-eurocommemo, branch `feature/sendcloud-service-point-checkout` (commit `7d3b0c4`)
**Status**: SUCCESS
**Files affected**: `src/Entity/Enum/DeliveryTypeEnum.php` (new), `src/Entity/Delivery.php`,
`src/Repository/DeliveryRepository.php`, `src/Service/OrderHelper.php`,
`migrations/Version20260705100348.php` (new)
**Notes**: Step 1/10 of `plans/2026-07-04_sendcloud-livraison-point-relais-tunnel-achat.md`,
executed per the approved execution plan at
`~/.claude/plans/je-veux-impl-menter-le-dazzling-snowglobe.md` (one commit per step, stop after
each for user confirmation). Added string-backed `DeliveryTypeEnum` (`home`/`service_point`),
mapped on `Delivery::$type` (Doctrine `enumType`, default `home`), threaded an optional `$type`
parameter through `DeliveryRepository::findDeliveryByWeightAndCountry()` /
`findDeliveryByWeight()` and `OrderHelper::getDelivery()` — all existing call sites keep working
unchanged (default `Home`). `lint:container`, `doctrine:schema:validate` (mapping OK; DB
out-of-sync is expected until the migration runs) and `cache:clear` all pass via
`scripts/repo_exec.py`. Migration generated but **not applied** — user will run
`doctrine:migrations:migrate` manually per their explicit instruction. Next: step 2 (Sendcloud
entities) awaiting user go-ahead.

## [2026-07-05 10:15] src-eurocommemo — Add Sendcloud configuration, shipping-method and parcel entities (Sendcloud step 2/10)

**Target**: src-eurocommemo, branch `feature/sendcloud-service-point-checkout` (commit `817346f`)
**Status**: SUCCESS
**Files affected**: `src/Entity/Sendcloud/SendcloudConfiguration.php` (new),
`src/Entity/Sendcloud/SendcloudShippingMethod.php` (new),
`src/Entity/Sendcloud/SendcloudParcel.php` (new),
`src/Repository/Sendcloud/SendcloudConfigurationRepository.php` (new),
`src/Repository/Sendcloud/SendcloudShippingMethodRepository.php` (new),
`src/Repository/Sendcloud/SendcloudParcelRepository.php` (new), `src/Entity/Delivery.php`
(added `sendcloudShippingMethod` link), `src/Entity/Order.php` (7 nullable `servicePoint*`
snapshot columns + `hasServicePoint()`/`getServicePointFullAddress()`),
`migrations/Version20260705101512.php` (new)
**Notes**: Step 2/10 of `plans/2026-07-04_sendcloud-livraison-point-relais-tunnel-achat.md`.
Mirrors `EbayConfiguration`/`ShippingService`/`ListEbayShippingServicesCommand` patterns.
Cross-checked the hand-written migration against Doctrine's own (read-only)
`doctrine:schema:update --dump-sql` diff and reconciled two discrepancies: (1) decimal
`minWeight`/`maxWeight` needed `float|string|null` PHP types (Doctrine's `decimal` DBAL type
maps to `string`, matching the project's existing convention e.g. `Order::$amountCmd`);
(2) `servicePoint*` string columns on `Order` needed to stay unlengthed `VARCHAR(255)`
(matching the entity mapping's un-lengthed `#[ORM\Column(type: 'string', nullable: true)]`
style) rather than the tighter `VARCHAR(100)`/`VARCHAR(20)`/`VARCHAR(50)` originally sketched
in the source plan's SQL prose — kept consistent with the mapping to avoid a
`doctrine:schema:validate` mismatch once applied. FK/index names adopted Doctrine's own
generated hash-style names (matching the project's other migrations) instead of hand-picked
descriptive names. `lint:container` and `doctrine:schema:validate` (mapping OK) pass via
`scripts/repo_exec.py`; migration generated but **not applied** (user's call, as agreed).
Next: step 3 (Sendcloud API client + configuration service) awaiting go-ahead.

## [2026-07-05 10:25] src-eurocommemo — Add Sendcloud API client and configuration service (Sendcloud step 3/10)

**Target**: src-eurocommemo, branch `feature/sendcloud-service-point-checkout` (commit `c9f28ee`)
**Status**: SUCCESS
**Files affected**: `.env`, `config/packages/eight_points_guzzle.yaml`, `config/services.yaml`,
`src/Service/Sendcloud/SendcloudService.php` (new),
`src/Service/Sendcloud/API/SendcloudApiClient.php` (new),
`src/Service/Sendcloud/Exception/SendcloudApiException.php` (new),
`src/Service/Sendcloud/Exception/SendcloudNotConfiguredException.php` (new)
**Notes**: Step 3/10 of `plans/2026-07-04_sendcloud-livraison-point-relais-tunnel-achat.md`.
Mirrors `EbayService`/`PaypalApiConnector` patterns: new `sendcloud_api` Guzzle client
(`eight_points_guzzle.yaml`) bound as `$sendcloudApiClient`, Basic-auth per request
(`'auth' => [publicKey, secretKey]`, same style as `PaypalApiConnector::getAccessToken()`).
`SendcloudApiClient` guards every call behind `SendcloudService::isConfigured()`
(→ `SendcloudNotConfiguredException`) and wraps non-2xx/Guzzle failures in
`SendcloudApiException`. `lint:container`, `lint:yaml config`, `cache:clear` and `php -l` on
the new files all pass via `scripts/repo_exec.py`. **Not functionally verified against the
live Sendcloud API** — no test credentials available yet (per user's explicit call); the user
will validate `getShippingMethods()`/`createParcel()` manually once they have test keys.
Next: step 4 (admin configuration page + shipping-method sync) awaiting go-ahead.

## [2026-07-05 10:38] src-eurocommemo — Admin configuration page and shipping-method sync (Sendcloud step 4/10)

**Target**: src-eurocommemo, branch `feature/sendcloud-service-point-checkout` (commit `adbcbd8`)
**Status**: SUCCESS
**Files affected**: `src/Service/Sendcloud/SendcloudShippingMethodSyncService.php` (new),
`src/Form/Sendcloud/SendcloudConfigurationFormType.php` (new),
`src/Controller/Admin/Sendcloud/SendcloudConfigurationController.php` (new),
`src/Controller/Admin/Sendcloud/SendcloudShippingMethodCrudController.php` (new),
`templates/admin/sendcloud/configuration/index.html.twig` (new),
`src/Command/SyncSendcloudShippingMethodsCommand.php` (new),
`src/Controller/Admin/DashboardController.php` (Sendcloud submenu),
`src/Entity/Sendcloud/SendcloudShippingMethod.php` (getter rename, see below)
**Notes**: Step 4/10 of `plans/2026-07-04_sendcloud-livraison-point-relais-tunnel-achat.md`.
Mirrors `EbayConfigurationController`/`ShippingServiceCrudController`/
`ListEbayShippingServicesCommand`. Two bugs caught by verification and fixed before commit:
(1) `lint:container` failed because `SendcloudShippingMethodSyncService`'s constructor
parameter was named `$sendcloudApiClient` (type `SendcloudApiClient`), which collided with
`config/services.yaml`'s bind `$sendcloudApiClient: '@eight_points_guzzle.client.sendcloud_api'`
(the raw Guzzle client) — Symfony's named bind wins over type-based autowiring regardless of
the declared type, so it tried to inject the wrong object; renamed the parameter to
`$apiClient`. (2) `SendcloudShippingMethod`'s boolean getter was named `isServicePoint()` for
property `$isServicePoint`, which doesn't match Symfony PropertyAccessor's `get/is/has` +
`ucfirst(property)` convention (would need `getIsServicePoint()` or `isIsServicePoint()`) —
this is the same pattern already used correctly elsewhere in the codebase (`Order::$isEbay` →
`getIsEbay()`); renamed to `getIsServicePoint()` so EasyAdmin's `BooleanField` can actually
read the value. Verified: `lint:container` OK, `lint:twig templates/admin/sendcloud` OK,
`doctrine:schema:validate` mapping OK, `cache:clear` OK, `debug:router` shows both new admin
routes, `bin/console list sendcloud` shows the new command. **Not functionally verified**:
no Sendcloud test credentials yet, so the sync was not run against the live API. Next: step 5
(service-point tariffs in the Delivery CRUD) awaiting go-ahead.

## [2026-07-05 10:45] src-eurocommemo — Allow creating service-point delivery tariffs in BO (Sendcloud step 5/10)

**Target**: src-eurocommemo, branch `feature/sendcloud-service-point-checkout` (commit `f7af4a9`)
**Status**: SUCCESS
**Files affected**: `src/Controller/Admin/DeliveryCrudController.php`
**Notes**: Step 5/10 of `plans/2026-07-04_sendcloud-livraison-point-relais-tunnel-achat.md`.
Added `ChoiceField('type')` (Domicile/Point relais, `renderAsBadges()` for the index list) and
`AssociationField('sendcloudShippingMethod')` to the "Tarifs" panel of the Delivery tariff CRUD.
`lint:container` and `php -l` pass via `scripts/repo_exec.py`. **Not browser-tested**: the
migrations from steps 1-2 haven't been applied yet (user's call), so the admin page can't
actually be loaded against a matching DB schema right now — the user should verify the form
in the browser once migrations are applied. Next: step 6 (expose service-point option in the
checkout funnel) awaiting go-ahead.

## [2026-07-05 10:58] src-eurocommemo — Expose service-point delivery option in the funnel (Sendcloud step 6/10)

**Target**: src-eurocommemo, branch `feature/sendcloud-service-point-checkout` (commit `de66cd5`)
**Status**: SUCCESS
**Files affected**: `src/Controller/OrderController.php` (`delivery()`, `paiement()`),
`templates/order/delivery.html.twig`, `templates/order/paiement.html.twig`,
`translations/shop.fr.yml`, `translations/shop.en.yml`, `translations/shop.de.yml`
**Notes**: Step 6/10 of `plans/2026-07-04_sendcloud-livraison-point-relais-tunnel-achat.md`.
`delivery()` now passes `deliveryServicePoint`, `sendcloudPublicKey` (null when Sendcloud isn't
configured, which hides the option) and `sessionServicePoint`; its POST branch validates
`service_point[id]` server-side when the chosen tariff `isServicePoint()`, flashing
`shop.order.servicePointMissing` and redirecting back otherwise. `paiement()` re-checks the
same guard before `cartToOrder()`. Used `addFlash('danger', ...)` rather than the source
plan's literal `'error'` label — confirmed via grep that `danger` is the project's actual
convention (`OrderController.php:92`, `SecurityController.php`) and maps to the Bootstrap
`alert-danger` class the templates render; `alert-error` isn't a real Bootstrap class. Also
added the `app.flashes` display loop to `delivery.html.twig`, which didn't have one before —
without it the new flash would never be visible (mirrors the loop already in
`order/informations.html.twig`). The delivery-step markup (radio, `#service-point-picker`
div, hidden inputs, `#service-point-selected`) is in place but **inert** — the Sendcloud
widget script and `app-order.js` wiring land in step 7, per the plan's own staging. Verified:
`lint:twig templates/order`, `lint:yaml translations`, `lint:container`, `php -l`, `cache:clear`
all pass via `scripts/repo_exec.py`. **Not browser-tested** (migrations not yet applied).
Next: step 7 (open the Sendcloud picker widget) awaiting go-ahead.

## [2026-07-05 11:26] src-eurocommemo — Open Sendcloud service-point picker on delivery step (Sendcloud step 7/10)

**Target**: src-eurocommemo, branch `feature/sendcloud-service-point-checkout` (commit `5dc598d`)
**Status**: SUCCESS
**Files affected**: `assets/app-order.js`, `templates/order/delivery.html.twig`
**Notes**: Step 7/10 of `plans/2026-07-04_sendcloud-livraison-point-relais-tunnel-achat.md`.
Added the `javascripts` block (Sendcloud widget script + `encore_entry_script_tags`), plus
`data-label-open`/`data-label-modify` attributes on the picker button and a
`#service-point-inline-error` div (both additions beyond the source plan's literal snippet,
needed so the JS doesn't hardcode French strings and so the submit guard shows an inline
message instead of a blocking `alert()`, which the plan's prose flagged as undesirable UX).
`app-order.js` wires: radio-driven show/hide of `#service-point-picker`, `sendcloud.servicePoints.open()`
on button click reading config from the `data-*` attributes, success callback filling the 7
hidden inputs + rendering the chosen point + swapping the button label, and a submit-time
guard on the delivery form. Verified: `lint:twig templates/order`, `lint:container` pass via
`scripts/repo_exec.py`. Additionally ran a real Encore build — the `php-fpm-per83` container
has no Node, so used the project's own dedicated `encore` node:18-alpine service already
running in the same docker-compose stack (`docker compose exec encore sh -lc "cd /eurocommemo
&& yarn dev"`, not through `repo_exec.py` since that wrapper only routes to the repo's single
declared PHP exec target) — compiled successfully, confirmed `service-point-picker` string
present in the built `public/build/app-order.js`. **Not verified**: no live Sendcloud test
keys, so `sendcloud.servicePoints.open()` itself was never exercised in a real browser; no
migrations applied yet either, so the full page can't be loaded end-to-end. Next: step 8
(snapshot the chosen service point onto the Order) awaiting go-ahead.

## [2026-07-05 11:35] src-eurocommemo — Snapshot selected service point on order creation (Sendcloud step 8/10)

**Target**: src-eurocommemo, branch `feature/sendcloud-service-point-checkout` (commit `4e7df20`)
**Status**: SUCCESS
**Files affected**: `src/Service/CartHelper.php` (`cartToOrder()`, `removeAllCartItem()`),
`templates/mail/mail_order.html.twig`
**Notes**: Step 8/10 of `plans/2026-07-04_sendcloud-livraison-point-relais-tunnel-achat.md`.
`cartToOrder()` now copies the session `servicePoint` array onto the Order's 7 snapshot fields
right after `setDelivery($delivery)`, guarded by `$delivery->isServicePoint()`.
`removeAllCartItem()` purges the `servicePoint` session key after flush — safe because it's
always called after `cartToOrder()` already ran and persisted the snapshot (verified call
order across all 3 payment completion flows: `OrderController.php` cheque/wire-transfer branch,
and `PaymentController.php`'s CB/PayPal branches, all confirmed in step 6's exploration).
Mail template gained an `{% elseif order.hasServicePoint %}` branch in the reception block.
Verified: `lint:twig templates/mail`, `lint:container`, `php -l` all pass via
`scripts/repo_exec.py`. **Not end-to-end tested**: migrations still not applied, so no order
can actually be created against the current DB to confirm the snapshot round-trips correctly.
Next: step 9 (create/cancel/download Sendcloud labels from admin) awaiting go-ahead.

## [2026-07-05 11:50] src-eurocommemo — Create, cancel and download shipping labels from admin (Sendcloud step 9/10)

**Target**: src-eurocommemo, branch `feature/sendcloud-service-point-checkout` (commit `bb6dd79`)
**Status**: SUCCESS
**Files affected**: `src/Service/Sendcloud/SendcloudParcelService.php` (new),
`src/Controller/Admin/Sendcloud/SendcloudOrderController.php` (new),
`src/Twig/GetActiveSendcloudParcelExtension.php` (new),
`src/Controller/Admin/OrderCrudController.php` (3 new actions + repository dep),
`templates/admin/order/order_delivery_action.html.twig` (tracking display)
**Notes**: Step 9/10 of `plans/2026-07-04_sendcloud-livraison-point-relais-tunnel-achat.md`.
`SendcloudParcelService::createLabelForOrder()` builds the parcel payload (name/email/phone
from `User`, `to_service_point`/`to_post_number` when `order.hasServicePoint()`, weight summed
from `orderProducts` + `DeliveryWeightAdditionalRepository` converted g→kg to a 3-decimal
string, `shipment.id` from the linked `SendcloudShippingMethod`), persists the resulting
`SendcloudParcel`, and stamps `numSuiviLivraison`/`dateExpedition` on the Order.
`cancelLabelForOrder()` / `getLabelPdf()` proxy the API client. One deliberate deviation from
the source plan's literal text: the plan suggested exposing `Order::getActiveSendcloudParcel()`
"alimenté par le repository" — but entities in this codebase have no DI access to repositories,
so instead I followed the project's own established pattern (`src/Twig/GetDeliveryShippingEbayExtension.php`)
and added a `GetActiveSendcloudParcelExtension` Twig function backed by
`SendcloudParcelRepository`, used both in the CRUD template and in `OrderCrudController`'s
`displayIf()` closures (which capture `$this` non-statically, unlike the `cancelOrder` action's
`static` closure, since they need the injected repository). Verified: `lint:container`,
`lint:twig templates/admin/order`, `php -l` on all 4 touched/new PHP files,
`doctrine:schema:validate` (mapping still OK), `cache:clear`, and `debug:router` confirms all 3
new routes. **Not functionally verified**: no Sendcloud test keys (label creation was never
called against the live API) and migrations still not applied (can't load the admin order
listing against the current DB to see the new actions/tracking render). Next: step 10 (parcel
status webhook) awaiting go-ahead — this is the final step of the plan.

## [2026-07-05 12:05] src-eurocommemo — Handle parcel status webhook (Sendcloud step 10/10 — plan complete)

**Target**: src-eurocommemo, branch `feature/sendcloud-service-point-checkout` (commit `1766151`)
**Status**: SUCCESS
**Files affected**: `src/Controller/WebhookController.php` (new `webhookSendcloud()` action),
`src/Entity/Enum/WebhookLogTypeEnum.php` (`ParcelStatusChanged` + `getFromSendcloud()`),
`src/Entity/WebhookLog.php` (`PLATFORM_SENDCLOUD`),
`src/Service/Webhook/DTO/Sendcloud/ParcelStatusChangedDTO.php` (new),
`src/Service/Webhook/Events/Sendcloud/ParcelStatusChangedEvent.php` (new)
**Notes**: Step 10/10 (final step) of
`plans/2026-07-04_sendcloud-livraison-point-relais-tunnel-achat.md`. `webhookSendcloud()`
verifies the `sendcloud-signature` header via `hash_equals(hash_hmac('sha256', rawBody,
secretKey), header)` before anything else — mismatch logs and returns 200 without dispatching,
matching the plan's note that Sendcloud replays on non-200. Always logs a `WebhookLog`; only
calls `WebhookMapperEventName::execute()` when the configuration has webhooks enabled and the
type is recognized. `ParcelStatusChangedEvent` mirrors `PaymentReceiveEvent`'s
`WebhookHandlerInterface` shape exactly; confirmed via `debug:container --tag=app.webhook_handler`
that it's auto-tagged and picked up alongside the 3 existing eBay handlers — no extra wiring
needed (`#[AutoconfigureTag]` on the interface handles it). Verified: `lint:container`, `php -l`
on all 5 touched/new files, `doctrine:schema:validate` (mapping OK), `cache:clear`,
`debug:router` shows `webhook_sendcloud`. **Not verified**: no real Sendcloud webhook payload
sample was available to confirm the exact JSON shape/keys (`action`, `parcel.status.*`,
`timestamp`) match what Sendcloud actually sends — implemented per the source plan's spec.
Also couldn't fire a real HTTP request end-to-end since `sendcloud_configuration` table
doesn't exist yet (migrations not applied) — the controller would hit a DB error unrelated to
the webhook logic itself if tested against the current schema. This closes out all 10 steps of
the source plan; remaining before production: apply both migrations, get real Sendcloud test/
prod API keys, run the manual end-to-end scenario from the source plan's "Vérification"
section (sync methods, checkout with real service-point selection, label creation, webhook
delivery with a real signature).

## [2026-07-06 09:30] src-eurocommemo — Migrate Sendcloud integration from API v2 to API v3

**Target**: src-eurocommemo, branch `feature/sendcloud-service-point-checkout` (commits `cf06b7e`, `a809e5d`)
**Status**: SUCCESS
**Files affected**: `.env`, `migrations/Version20260705101512.php` (edited in place),
`src/Controller/Admin/Sendcloud/SendcloudShippingMethodCrudController.php`,
`src/Entity/Sendcloud/SendcloudParcel.php`, `src/Entity/Sendcloud/SendcloudShippingMethod.php`,
`src/Repository/Sendcloud/SendcloudShippingMethodRepository.php`,
`src/Service/Sendcloud/API/SendcloudApiClient.php`,
`src/Service/Sendcloud/SendcloudParcelService.php`,
`src/Service/Sendcloud/SendcloudShippingMethodSyncService.php`,
`src/Service/Webhook/DTO/Sendcloud/ParcelStatusChangedDTO.php`,
`src/Service/Webhook/Events/Sendcloud/ParcelStatusChangedEvent.php`
**Notes**: User asked to verify the Sendcloud shipping-methods retrieval against the real API
docs (`sendcloud.dev/api/v3`). Research (WebFetch against sendcloud.dev's docs index,
migration guide, and endpoint references) found that **API v2 — the version the entire
previous session's implementation was built against — entered maintenance mode in April 2026**
and is closed to new integrators; since this integration never authenticated with real keys,
it likely can't get v2 access at all. User confirmed via AskUserQuestion: migrate fully to v3
(shipping methods + the already-committed label creation/cancellation + webhook, not just the
literal "retrieval" ask), in one pass, using the same one-step-at-a-time pacing as before
(though steps 2/3/4/5 ended up bundled into a single commit since the renames are interdependent
— splitting them would have left broken intermediate commits with undefined method calls).
Key changes: base URL → `/api/v3/`; `SendcloudApiClient` rewritten around
`POST shipping-options`, `POST shipments/announce`, `POST shipments/{id}/cancel` (dropped the
unused `getParcel()`); `SendcloudShippingMethod.sendcloudId` (int) → `code` (string, v3 uses
string codes not numeric ids); `SendcloudParcel.statusId` (int) → `statusCode` (string, v3 has
no numeric status id) + new `shipmentId` (cancel operates on shipment id, not parcel id);
`SendcloudShippingMethodSyncService` redesigned to probe `shipping-options` per country used
by an active `Delivery` tariff (v3 has no static catalog endpoint — options are quoted
per-shipment-context only); `SendcloudParcelService::buildShipmentPayload()` restructured to
v3's nested `to_address`/`from_address`/`ship_with` shape (verified against a literal example
payload fetched from the docs). Also fixed a bug the sync-service redesign would otherwise
have missed: `SendcloudShippingMethodCrudController` still had an `IntegerField::new('sendcloudId', ...)`
that needed to become `TextField::new('code', ...)` — caught by grepping broadly, not by
`lint:container` (EasyAdmin field misconfigurations aren't caught by container linting).
**Important discovery**: both Sendcloud migrations (`Version20260705100348`,
`Version20260705101512`) had already been applied to the dev database by the user between
sessions (`doctrine:migrations:status` showed both as executed) — contradicting this plan's
initial assumption ("nothing has touched a real database yet"). Editing an already-executed
migration file in place does **not** retroactively change the database; Doctrine only tracks
that a version ran, not its content. **The user needs to roll back migration
`Version20260705101512` and reapply it** (`doctrine:migrations:migrate Version20260705100348`
then `doctrine:migrations:migrate`) for the DB to pick up the renamed columns — flagged
explicitly rather than left implicit. Verified: `lint:container`, `lint:yaml config`, `php -l`
on all touched files, `doctrine:schema:validate` (mapping OK), `cache:clear`, and cross-checked
the hand-edited migration against Doctrine's own `doctrine:schema:update --dump-sql` (read-only)
to confirm the diff matches exactly the intended renames. **Not verified**: still no live
Sendcloud test credentials, so none of the v3 calls were exercised against the real API — three
open questions flagged explicitly in the plan/commit message (service-point post-number
placement, shipment-id vs parcel-id relationship, incomplete shop `from_address` since
`Configuration` has no structured postal_code/city) need a sandbox check once keys exist.

## [2026-07-09 16:30] src-eurocommemo — Colonne "Service eBay sélectionné" sur les listings de commande admin

**Target**: src-eurocommemo @ current branch (uncommitted)
**Status**: SUCCESS
**Files affected**:
- `templates/admin/order/order_ebay_shipping_service.html.twig` (new) — cell showing `Order.shippingService.shippingService` with a Bootstrap tooltip (`Order.shippingService.description`), em-dash fallback when null
- `src/Controller/Admin/OrderCrudController.php` — `configureFields()`: inserted the new column after "Informations de réception" in both branches of the `delivery` param check, so it appears on all 4 index listing variants; `createIndexQueryBuilder()`: added `leftJoin('entity.shippingService', ...) + addSelect(...)` to avoid N+1 on the 500-row "prêtes à être expédiées" listing
**Notes**: Implements `plans/2026-07-09_colonne-service-ebay-livraison-listing-commandes.md`. No migration needed (`Order.shippingService` and `ShippingService.description` already existed). Verified: `php -l` on the controller, `bin/console lint:twig` on the new template, `bin/console cache:clear` — all OK inside `stack-orb_php83`. Not yet verified: manual browser check of the 4 listing screens and tooltip rendering (no admin session driven in this session).

## [2026-07-09 04:24] src-eurocommemo — Sendcloud API connector (list orders)

**Target**: src-eurocommemo @ current branch (uncommitted)
**Status**: SUCCESS
**Files affected**:
- `config/packages/eight_points_guzzle.yaml` — new `sendcloud_api` Guzzle client (`base_url: "%env(SENDCLOUD_BASE_URL)%/api/v3"`, Accept: application/json, timeout 15)
- `config/services.yaml` — new bind `$sendcloudApiClient: '@eight_points_guzzle.client.sendcloud_api'`
- `.env` — added committed default `SENDCLOUD_BASE_URL="https://panel.sendcloud.sc"` (was only in `.env.local`, needed for container compilation on CI/other machines)
- `src/Exceptions/ExternalSendcloudApiException.php` (new) — mirror of `ExternalEbayApiException`
- `src/Dto/Sendcloud/` (new) — typed nested DTOs: `SendcloudOrderDTO` (root) + `SendcloudOrderDetailsDTO`, `SendcloudOrderItemDTO`, `SendcloudPaymentDetailsDTO`, `SendcloudCustomerDetailsDTO`, `SendcloudAddressDTO` (shipping/billing), `SendcloudOrderStatusDTO`, `SendcloudPriceDTO`. `customs_details`/`shipping_details`/`service_point_details` exposed as raw arrays (not yet typed)
- `src/Service/Sendcloud/SendcloudApiClient.php` (new) — Guzzle client, HTTP Basic auth (publicKey/secretKey read from DB via `SendcloudConfigurationService`), `getOrders(?string $orderId = null): SendcloudOrderDTO[]`: `GET /orders`, optional `order_id` query filter, auto-follows RFC 5988 `Link` `rel="next"` header to aggregate all pages, throws `ExternalSendcloudApiException` on non-200 / not-configured
- `tests/Service/Sendcloud/SendcloudApiClientTest.php` (new) — FIRST test class in the repo; establishes the Guzzle `MockHandler` + `Middleware::history` convention. 6 tests: hydration, order_id filter present/absent, Link pagination aggregation, not-configured throw, non-200 throw
**Notes**: Implements `plans/2026-07-09_connecteur-api-sendcloud-orders.md`. Decisions validated with user: Guzzle (eightpoints, mirror eBay/PayPal) over Symfony HttpClient; fully typed nested DTOs; auto pagination. Verified inside `php-fpm-per83`: `php -l` on all 10 new files, `lint:yaml` (2 config files), `lint:container` (OK — `$sendcloudApiClient` resolves to `eight_points_guzzle.client.sendcloud_api`), `debug:autowiring SendcloudApiClient`, `cache:clear`, and `phpunit` (6 tests, 12 assertions, all green). **Not verified**: no live call against the real Sendcloud API (no exercised sandbox creds in this session) — the connector reads credentials from the `SendcloudConfiguration` DB row (not `.env`), so a configured row must exist for `getOrders()` to run end-to-end.

## [2026-07-11 00:00] src-eurocommemo — Sendcloud API connector re-implemented (after applying plan review)

**Target**: src-eurocommemo @ main (uncommitted)
**Status**: SUCCESS
**Files affected**:
- `config/packages/eight_points_guzzle.yaml` — new `sendcloud_api` Guzzle client (`base_url: "%env(SENDCLOUD_BASE_URL)%/api/v3"`, Accept: application/json, timeout 15)
- `config/services.yaml` — new bind `$sendcloudApiClient: '@eight_points_guzzle.client.sendcloud_api'`
- `src/Exceptions/ExternalSendcloudApiException.php` (new) — mirror of `ExternalEbayApiException`
- `src/Dto/Sendcloud/` (new, 8 files) — typed nested DTOs: `SendcloudOrderDTO` (root) + `SendcloudOrderDetailsDTO`, `SendcloudOrderItemDTO` (with `getImageUrl()` + deferred-fields docblock), `SendcloudPaymentDetailsDTO`, `SendcloudCustomerDetailsDTO`, `SendcloudAddressDTO`, `SendcloudOrderStatusDTO`, `SendcloudPriceDTO` (docblock: covers `price` + `costs-object`, `(float)` normalization). `customs_details`/`shipping_details`/`service_point_details` exposed as raw arrays
- `src/Service/Sendcloud/SendcloudApiClient.php` (new) — Guzzle client, HTTP Basic auth (publicKey/secretKey from DB via `SendcloudConfigurationService`), `getOrders(?string $orderId = null): SendcloudOrderDTO[]`: `GET /orders`, optional `order_id` filter, RFC 5988 `Link` `rel="next"` pagination, `ExternalSendcloudApiException` on non-200 / not-configured. `DEFAULT_PAGE_SIZE=100` (aligned to OpenAPI default, review #3)
- `tests/Service/Sendcloud/SendcloudApiClientTest.php` (new) — FIRST test class in the repo; Guzzle `MockHandler` + `Middleware::history` convention. 5 tests: without filter, with order_id filter, Link pagination aggregation, not-configured throw, non-200 throw
**Notes**: Implements `plans/2026-07-09_connecteur-api-sendcloud-orders.md` **after folding in the 6 points** from `...-review.md` (#1 deferred-fields doc + `getImageUrl()`, #2 all 5 test methods implemented, #3 page_size 100, #4 cache-wording, #5 SendcloudPriceDTO doc, #6 tests/ factual correction). **Reconciliation**: the earlier log entry [2026-07-09 04:24] describing this same connector was never committed and its files were absent from the working tree at session start (last commit = `e0f8256 feat(sendcloud): add backoffice configuration page`, config page only). This session re-created the files from scratch. Verified inside `php-fpm-per83`: `php -l` on all 10 new files, `lint:yaml config`, `lint:container` (OK — `$sendcloudApiClient` resolves), `debug:autowiring SendcloudApiClient`, `phpunit` (5 tests, 13 assertions, all green). Graphify graph refreshed (10 files re-extracted). **Not done / to decide**: unlike the orphaned prior entry, `.env` was NOT modified — `SENDCLOUD_BASE_URL` currently lives only in `.env.local`, so a fresh checkout without `.env.local` (CI / new dev) would compile the guzzle `base_url` as `/api/v3`. Recommend committing `SENDCLOUD_BASE_URL="https://panel.sendcloud.sc"` to `.env` (precedent: `BASE_URL_API_EBAY_TRADING` at `.env:73`). No live Sendcloud API call exercised.

## [2026-07-11 00:15] src-eurocommemo — Console command to store the Sendcloud order id on eBay orders

**Target**: src-eurocommemo @ main (uncommitted)
**Status**: SUCCESS
**Files affected**:
- `src/Command/SyncSendcloudOrderIdsCommand.php` (new) — command `app:sendcloud:sync-order-ids`. Iterates eBay orders (`Order.isEbay = true`), calls `SendcloudApiClient::getOrders($orderIdEbay)` per order, matches on Sendcloud `order_id` (fallback: single result), stores `SendcloudOrderDTO::getId()` (Sendcloud internal id) via `Order::setSendcloudOrderId()`. Options `--orderId` (`-o`, single eBay order) and `--force` (`-f`, reprocess already-filled). Single `flush()` at end (SyncEbayProductCommand pattern), `ProgressBar` + `writeln` (no `SymfonyStyle`), `ExternalSendcloudApiException` → `Command::FAILURE` with `<error>`.
- `src/Entity/Order.php` — new nullable property `sendcloudOrderId` (`#[ORM\Column(type: 'string', length: 255, nullable: true)]`, default `null`) mirroring `shippingServiceCode`, with fluent getter/setter (`getSendcloudOrderId()`/`setSendcloudOrderId(): Order`).
- `src/Repository/OrderRepository.php` — new methods `findEbayOrders(): array` and `findEbayOrdersMissingSendcloudId(): array` (QueryBuilder on `isEbay = true`, latter adds `sendcloudOrderId IS NULL`).
- `migrations/Version20260711001138.php` (new) — `ALTER TABLE orders ADD sendcloud_order_id VARCHAR(255) DEFAULT NULL` (`down()` drops it). Hand-cleaned: `make:migration` had also captured pre-existing schema drift (`DROP INDEX external_id ON orders`/`ON user`) unrelated to this change — removed to keep the migration atomic.
**Notes**: Implements `plans/2026-07-11_commande-sendcloud-order-id-commandes-ebay.md`. Matching decisions validated with user: `orderIdEbay` ↔ Sendcloud `order_id`; store `getId()`; one filtered API call per order. **Autowiring gotcha**: the constructor param originally named `$sendcloudApiClient` collided with the global bind `$sendcloudApiClient: '@eight_points_guzzle.client.sendcloud_api'` (config/services.yaml) and received the raw Guzzle `Client` instead of the service — `lint:container` caught it; renamed the param to `$apiClient`. Verified inside `php-fpm-per83`: `php -l` on the 3 touched/new PHP files, `doctrine:migrations:migrate` (applied OK), `doctrine:schema:validate` (mapping OK; DB "not in sync" is ONLY the pre-existing `external_id` index drift — `--dump-sql` shows no `sendcloud` line, confirming the new column is in sync), `lint:container` (OK after rename), `cache:clear`, `list` (command registered), `--help` (instantiates, proving autowiring). Graphify graph refreshed (4 files re-extracted). **Not verified**: no end-to-end run — `getOrders()` needs a configured `SendcloudConfiguration` DB row (public/secret key via backoffice); without it the command returns FAILURE with "Sendcloud API credentials are not configured." Also unconfirmed against a live payload whether Sendcloud's `order_id` actually carries the eBay order id (no push-to-Sendcloud code exists yet) — flagged for a sandbox check once credentials exist.

## [2026-07-11 00:40] src-eurocommemo — Sendcloud auth: explicit `Authorization: Basic` header

**Target**: src-eurocommemo @ main (uncommitted)
**Status**: SUCCESS
**Files affected**:
- `src/Service/Sendcloud/SendcloudApiClient.php` — `getOrders()` no longer relies on Guzzle's implicit `'auth' => [publicKey, secretKey]` option; it now builds an explicit request header `Authorization: Basic base64(publicKey:secretKey)` and passes it via `'headers'` on both the initial request and each RFC 5988 `next`-link follow-up.
- `tests/Service/Sendcloud/SendcloudApiClientTest.php` — added an assertion in `testGetOrdersWithoutFilter()` verifying the recorded request carries `Authorization: Basic base64('public-key:secret-key')`.
- `src/Command/SyncSendcloudOrderIdsCommand.php` — removed a leftover `dd($dtos);` debug line (added during a manual run) before the matching logic.
**Notes**: Implements the user request that Sendcloud auth be an explicit Basic Authorization header from the public/secret key. Functionally equivalent to the previous `auth` option (both send the same header) but explicit/controlled. Verified inside `php-fpm-per83`: `php -l` on the two touched PHP files, `phpunit tests/Service/Sendcloud/SendcloudApiClientTest.php` (5 tests, 14 assertions, all green — up from 13, the extra one being the new Authorization-header check). Graphify graph refreshed (3 files re-extracted). **Not verified**: still no live Sendcloud call (needs a configured `SendcloudConfiguration` DB row); the user was mid-run when adding `dd()`, so a real 401-vs-200 check against the sandbox is still pending credentials.

## [2026-07-11 02:30] src-eurocommemo — Sendcloud link in the "Service eBay sélectionné" orders-list column

**Target**: src-eurocommemo @ main (uncommitted)
**Status**: SUCCESS
**Files affected**:
- `templates/admin/order/order_ebay_shipping_service.html.twig` — after the existing shipping-service display block, added a conditional Sendcloud link inside the same EasyAdmin cell. Shown only when `entity.instance.sendcloudOrderId is not null and sendcloudOrderId != '0'` (the `"0"` sentinel is written by `SyncSendcloudOrderIdsCommand` when no Sendcloud match exists) and `entity.instance.orderIdEbay` is present. Link: `https://app.sendcloud.com/v2/shipping/list/orders?search={{ entity.instance.orderIdEbay|url_encode }}`, `target="_blank"`, label "Voir sur Sendcloud", classes `fw-bold text-primary` (mirroring the La Poste tracking link in `order_delivery_resume.html.twig:5`), wrapped in `<div class="mt-1">`.
**Notes**: Implements `plans/2026-07-11_lien-sendcloud-colonne-service-ebay.md`. Template-only change — no PHP/entity/controller/translation touched (column, `shippingService` relation and `sendcloudOrderId` already exposed via `entity.instance`). The eBay id (`orderIdEbay`, format `02-14852-44592`), not the Sendcloud id, is injected as the Sendcloud search term per the request. Verified: `bin/console lint:twig` on the template → "[OK] All 1 Twig files contain valid syntax" (run via `scripts/repo_exec.py`). **Not verified**: no end-to-end backoffice render (would need a running list with an eBay order whose `sendcloud_order_id` is set and ≠ "0").

## [2026-07-12 03:20] src-eurocommemo — Retroactive update of eBay order shipping fee & product prices

**Target**: src-eurocommemo @ main (uncommitted)
**Status**: SUCCESS
**Files affected**:
- `src/Service/Ebay/DTO/Output/Fulfillment/FulfillmentOrderDTO.php` — fixed `getDeliveryCost()`: the array key returned is now `value` (was `amount`) to match its only consumer `ImportFulfillmentOrderUseCase::defineOrderInformation()` which reads `$shippingCost['value']` — a load-bearing bug introduced by commit `3d9efc7` that silently dropped the shipping fee (null → coerced to 0) on the **create** path too. Also added null-safety on `$lineItem->getShippingCost()` (previously `->getValue()` unguarded → fatal if a line item has no `deliveryCost.shippingCost`) and a safe default currency (`'EUR'`) to avoid a currency conversion on `null`.
- `src/Service/Ebay/UseCase/UpdateEbayOrderPricingUseCase.php` (new) — re-syncs an already-imported eBay `Order` with the corrected Fulfillment payload: recomputes `amountLivraison` (summed per-line `deliveryCost.shippingCost`, currency-converted), unit prices of existing `OrderProducts` (`lineItemCost / quantity`, TTC/TGC/HT/lineTTC) matched to line items by product (`ebayId`=legacyItemId then `ebayTitle`, no `lineItemId` stored on `OrderProducts`), then `amountCmd`/`amountTva`. Mirrors formulas of `ImportFulfillmentOrderUseCase::defineOrderInformation()`/`defineOrderLine()`. Deliberately does NOT create/remove lines, touch stock (`StockManagementService`), or regenerate the invoice. Unmatched line items are logged and skipped. Quantity is realigned on the eBay payload (fallback to DB qty if eBay returns 0) to keep line totals coherent.
- `src/Command/GetEbayFulfillmentOrderCommand.php` — injected `UpdateEbayOrderPricingUseCase`; added option `--update-pricing` (`-p`); added the flag to the `import()` routing condition; in `handleExistingOrder()` the pricing update runs when `-p` is set, and the existing address-update branch is now gated on `--import`/`--update-addresses` so `-p` alone no longer triggers the address prompts. New order + `-p` alone falls through to the normal (now fixed) create path.
**Notes**: Implements `plans/2026-07-12_update-ebay-order-pricing.md`. Scope confirmed with user: single order via `--orderId`, new option on the existing import command (not a dedicated command), no invoice regeneration. Verified inside `php-fpm-per83` via `scripts/repo_exec.py`: `php -l` on the 3 files (OK), `lint:container` (OK — `UpdateEbayOrderPricingUseCase` autowires cleanly), `--help` shows `-p, --update-pricing`, `cache:clear` (OK), `phpunit` (5 tests / 14 assertions green — unchanged, no eBay use-case tests exist). Graphify graph refreshed (7 files re-extracted). **Not verified**: no live run against a real eBay order (`app:ebay:fulfillment-order -o <id> --update-pricing`) — needs a valid eBay Fulfillment API session + an already-imported order in DB; the optional unit test for the new use case (plan file #4) was not written.

## [2026-07-12 04:45] src-eurocommemo — Async Sendcloud order-id linking on eBay import

**Target**: src-eurocommemo @ `feature/sendcloud-async-order-link` (uncommitted)
**Status**: SUCCESS
**Files affected**:
- `src/Service/Sendcloud/SendcloudOrderLinker.php` (new) — shared `final` service extracting fetch+match from `SyncSendcloudOrderIdsCommand::findMatchingOrder()`: `matchSendcloudId(Order): ?string` calls `SendcloudApiClient::getOrders(orderIdEbay)`, matches on `order_id` (fallback: single result), returns the internal Sendcloud id or `null`. No mutation, no flush.
- `src/Messenger/Message/AssociateSendcloudOrderIdMessage.php` (new) — carries the DB `orderId` (mirrors `CreateEbayAsyncMessage`).
- `src/Exceptions/SendcloudOrderNotFoundException.php` (new) — thrown by the handler when the order is not on Sendcloud yet → triggers the Messenger retry.
- `src/Messenger/Handler/AssociateSendcloudOrderIdHandler.php` (new) — `#[AsMessageHandler]`: `find` → idempotence guard (`sendcloudOrderId !== null` returns early, covers already-linked and the `"0"` sentinel) → `matchSendcloudId` → set+flush, or throw `SendcloudOrderNotFoundException`.
- `src/EventSubscriber/SendcloudLinkFailureSubscriber.php` (new) — on `WorkerMessageFailedEvent` with `willRetry() === false` for this message type: sets `sendcloudOrderId = "0"`, flushes, logs a warning and sends the alert mail. No `failure_transport` needed.
- `templates/mail/sendcloud_link_failed.html.twig` (new) — minimal failure-alert body (eBay id + internal id + `"0"` note).
- `config/packages/messenger.yaml` — new transport `async_sendcloud` (`max_retries: 3`, `delay: 20000`, `multiplier: 1` for constant 20 s spacing → 4 attempts at t=0/+20/+40/+60 s) + routing for the new message.
- `src/Service/MailService.php` — added `sendSendcloudLinkFailure(Order $order)` (style aligned on `sendReportEbayNotificationCommand()`, `to` hard-coded to `morvan.aurelien@gmail.com` like the other eBay alerts).
- `src/Service/Ebay/UseCase/ImportFulfillmentOrderUseCase.php` — injected `MessageBusInterface`; dispatch `AssociateSendcloudOrderIdMessage` after flush + `generateInvoice()`, before `return $order`. Covers both the webhook and `app:ebay:fulfillment-order` (`GetEbayFulfillmentOrderCommand` delegates here) — no dispatch added to that command.
- `src/Command/ImportEbayOrderCommand.php` — legacy Trading-API command (`app:import:ebay-order`) persists inline; injected `MessageBusInterface`; dispatch after its own flush.
- `src/Command/SyncSendcloudOrderIdsCommand.php` — de-duplicated: dropped `SendcloudApiClient` + private `findMatchingOrder()` in favour of `SendcloudOrderLinker`; rewrote the loop; fixed the batch-flush guard `if ($cptProcess % 200)` → `if (0 === $cptProcess % 200)`. Behaviour (matched/notFound counters, `"0"` sentinel) unchanged.
- `cron.php` — added `async_sendcloud` to the `messenger:consume` transports.
- `tests/Service/Sendcloud/SendcloudOrderLinkerTest.php` (new, 4 tests) — Guzzle `MockHandler` through a real `SendcloudApiClient`: exact match, single-result fallback, empty → null, multiple non-matching → null.
- `tests/Messenger/Handler/AssociateSendcloudOrderIdHandlerTest.php` (new, 4 tests) — real `SendcloudOrderLinker` over a mocked `SendcloudApiClient` (the linker is `final`, so it is not mocked): success sets id + flushes, not-found throws + no flush, already-linked skips API + no flush, order-deleted no-op.
**Notes**: Implements `plans/2026-07-11_sendcloud-async-order-link.md`. Decisions: `max_retries: 3` (1 try + 3 retries), final failure → `"0"` + mail, shared `SendcloudOrderLinker`. The `--update-pricing` path (`UpdateEbayOrderPricingUseCase`) deliberately does NOT dispatch (existing order; idempotence guard would skip anyway). Verified inside `php-fpm-per83` via `scripts/repo_exec.py`: `php -l` on all 11 touched PHP files (OK), `lint:container` (OK — linker/handler/subscriber autowire), `lint:twig` (OK), `lint:yaml config/packages/messenger.yaml` (OK), `cache:clear` (OK), `debug:messenger` (message routed to its handler), `phpunit` full suite (13 tests / 27 assertions green, up from 5/14). Graphify graph refreshed (15 files re-extracted). **Not verified**: no live end-to-end run — needs a configured `SendcloudConfiguration` DB row + a real eBay order + a running `messenger:consume async_sendcloud` worker to observe the 4-attempt retry, the `"0"` sentinel and the alert mail. No commit made (awaiting explicit user instruction).

## [2026-07-12 05:20] src-eurocommemo — Widen Sendcloud link retry window (prod: order lands on Sendcloud after ~15 min)

**Target**: src-eurocommemo @ `feature/sendcloud-async-order-link` (uncommitted)
**Status**: SUCCESS
**Files affected**:
- `config/packages/messenger.yaml` — `async_sendcloud` `retry_strategy` widened from a 60 s window (`max_retries: 3`, `delay: 20000`, `multiplier: 1`) to ~42 min: `max_retries: 10`, `delay: 60000`, `multiplier: 2`, `max_delay: 300000` (exponential backoff capped at 5 min → attempts at ~0s/+1/+3/+7/+12/+17/+22/+27/+32/+37/+42 min). Fixes the prod bug where the order reaches Sendcloud only after ~15 min while the old window gave up after 1 min and wrongly set the `"0"` sentinel + sent an alert mail. Viable because the transport is Doctrine (`doctrine://default`, `.env:80`): delayed retries persist in `messenger_messages.available_at` and survive worker restarts.
- `templates/mail/sendcloud_link_failed.html.twig` — removed the now-false hard-coded "après 4 tentatives"; reworded to a count-independent "après épuisement des tentatives (~40 min d'attente)".
**Notes**: Implements `plans/2026-07-12_sendcloud-retry-window.md`. Handler (`AssociateSendcloudOrderIdHandler`) and subscriber (`SendcloudLinkFailureSubscriber`) unchanged — already correct (throw-to-retry until found; final `"0"`+mail only at `willRetry()===false`, now after ~42 min). Verified inside `php-fpm-per83` via `scripts/repo_exec.py`: `lint:yaml config/packages/messenger.yaml` (OK), `lint:twig` (OK), `cache:clear` (OK — container compiles, so `retry_strategy` keys valid), `debug:messenger` (message still routed to its handler). Graphify NOT refreshed: only a YAML + a Twig file changed, both excluded from AST extraction → graph unchanged. **Not verified**: no live run (needs Sendcloud credentials + a real late-arriving eBay order + a running worker to observe the ~17-min association and the ~42-min give-up). **Infra dependency (out of repo)**: the OVH cron invoking `cron.php` must relaunch `messenger:consume` regularly enough (≤ 30 min, given `--time-limit=1800`) so a message becoming available at +N min is consumed promptly — crontab not versioned, to confirm on prod. No commit made (awaiting explicit user instruction).

## [2026-07-12 11:45] src-eurocommemo — Feature: per-order "Sync Sendcloud" action on the admin orders list

**Target**: src-eurocommemo @ main (uncommitted)
**Status**: SUCCESS
**Files affected**:
- `src/Controller/Admin/OrderCrudController.php` — added a native EasyAdmin row action `syncSendcloud` (label "Sync Sendcloud", `fa fa-truck`) built with `linkToUrl()` so a CSRF token (`sendcloud_sync_<id>`) is appended as `_csrf_token` query param; `displayIf` shows it only for eBay orders whose `sendcloudOrderId` is `null` or `'0'`. Registered via `->add(Crud::PAGE_INDEX, $syncSendcloud)` and inserted in `->reorder([Action::EDIT, 'cancelOrder', 'syncSendcloud'])`. New handler `syncSendcloud(AdminContext): RedirectResponse`: validates CSRF (flash danger on mismatch), guards `getIsEbay()`, reuses `SendcloudOrderLinker::matchSendcloudId()` (catches `ExternalSendcloudApiException` → flash danger + log), then `setSendcloudOrderId($id ?? '0')` + flush + flash (success / warning) + redirect to referrer. Constructor gained 3 autowired deps: `SendcloudOrderLinker`, `CsrfTokenManagerInterface`, `LoggerInterface`; 4 new `use` imports.
**Notes**: Implements `plans/2026-07-12_bouton-sync-sendcloud-commandes.md` (Pattern A — native EasyAdmin action + CSRF, chosen over the AJAX pattern). No template / JS / Encore rebuild / migration — the `sendcloud_order_id` column and the `SendcloudOrderLinker` service already exist. Behaviour aligned with `app:sendcloud:sync-order-ids --orderId <n>` (`"0"` = not found sentinel, real id = match). Verified inside `php-fpm-per83` via `scripts/repo_exec.py`: `php -l` on `OrderCrudController.php` (OK), `cache:clear` (OK), `lint:container` (OK — the 3 new deps autowire). **Not verified**: no live end-to-end click (needs a configured `SendcloudConfiguration` row + a real eBay order with null/"0" id in the admin list to observe the flash + the column link flip). No commit made (awaiting explicit user instruction).

## [2026-07-12 17:10] src-eurocommemo — Feature: choose Sendcloud shipping method + service point (Shop2Shop) on awaiting-shipment orders

**Target**: src-eurocommemo @ `feature/sendcloud-shipping-method-service-point` (uncommitted)
**Status**: SUCCESS
**Files affected**:
- `src/Entity/Order.php` — added 3 nullable string columns `sendcloudShippingOptionCode`, `sendcloudServicePointId`, `sendcloudServicePointName` (+ getters/setters, `Order` fluent style) next to `sendcloudOrderId`; added `getTotalWeightKg(): float` (sum of `orderProduct.quantity * product.weight` grams ÷ 1000).
- `migrations/Version20260712000000.php` (new) — `ALTER TABLE orders ADD` the 3 columns; `down()` drops them.
- `src/Dto/Sendcloud/SendcloudShippingOptionDTO.php` (new) — read-only wrapper over a `POST /api/v3/shipping-options` option: `getCode/getName/getCarrierCode/getCarrierName/getLabel`, `requiresServicePoint()` reads `requirements.is_service_point_required`.
- `src/Dto/Sendcloud/SendcloudServicePointDTO.php` (new) — read-only wrapper over a `GET /api/v3/service-points` result: `getId` (Sendcloud id), `getCarrierServicePointId`, name/address getters, `getLabel()`.
- `src/Service/Sendcloud/SendcloudOrderShippingService.php` (new) — `applyShippingSelection(Order, code, ?spId, ?spName)`: guards Sendcloud association, calls `SendcloudApiClient::updateOrder()`, sets the 3 local fields (caller flushes).
- `src/Service/Sendcloud/SendcloudApiClient.php` — generalised private `request(string $method, …)` (was hard-coded `->get()` + `=== 200`; now `->request($method,…)` + 2xx range); adapted the existing `getOrders()` call to `request('GET', …)`; added `getShippingOptions()` (POST shipping-options, `from_address`/`to_address`/`parcels[].weight` kg, `calculate_quotes`), `getServicePoints()` (GET service-points, `country_code`+`carrier_code`+`address_postal_code`/`address_city`, reads `data.results`), `updateOrder()` (PATCH orders/{id}: `shipping_details.ship_with.shipping_option_code` + root `service_point_details.id` when a SP is given); 2 new DTO `use`, 2 new endpoint constants.
- `src/Controller/Admin/OrderCrudController.php` — injected `SendcloudApiClient` + `SendcloudOrderShippingService`; added `SENDCLOUD_FROM_COUNTRY = 'FR'`; 3 routes: `app_admin_order_sendcloud_shipping_options` (GET JSON, from delivery address + total weight), `app_admin_order_sendcloud_service_points` (GET JSON, `?carrier=` + delivery postal/city), `app_admin_order_sendcloud_apply_shipping` (POST, CSRF `sendcloud_shipping_<id>`, guards isEbay + VALID + not-shipped + associated, delegates to the service + flush).
- `templates/admin/order/order_delivery_action.html.twig` — inside the awaiting-shipment branch (`dateExpedition is null`), added a `.sendcloud-shipping-block` (shown only for eBay orders with a real `sendcloudOrderId`): shipping-method `<select>`, hidden service-point `<select>`, "Enregistrer sur Sendcloud" button carrying `data-csrf`, and a current-service-point line.
- `assets/back/js/back.js` — added a Sendcloud block: fetch + populate the method select, on change (or initial) load service points when `requiresServicePoint`, and a `$.ajax` POST to persist to Sendcloud with inline success/error feedback.
**Notes**: Implements `plans/2026-07-12_choix-service-livraison-point-relais-sendcloud.md`. Feature is scoped to eBay orders that are `statePayment == VALID`, `dateExpedition IS NULL` and Sendcloud-associated (`sendcloudOrderId ∉ {null,'0'}`) — i.e. the "En attente d'expédition"/"Prévente" statuses; UI lives in the `delivery=1` list cell. Push uses the vendored v3 spec (`specs/sendcloud-v3/{orders,shipping-options,service-points}/openapi.yaml`); all 3 endpoints share the existing `panel.sendcloud.sc` host + Guzzle client (no cross-host call). Verified inside `php-fpm-per83` via `scripts/repo_exec.py`: `php -l` on all 7 PHP files (OK), `lint:twig` (OK), `debug:router | grep sendcloud` (3 routes registered → controller DI compiles with the 2 new autowired deps), `doctrine:schema:validate --skip-sync` (mapping OK), `doctrine:migrations:migrate` (1 migration executed OK), post-migrate `schema:validate` shows only pre-existing unrelated drift (`DROP INDEX external_id ON user/orders` — my 3 columns are in sync). Front assets rebuilt on host via `npm run build` (Encore production, 62 files written, compiled successfully). **Not verified**: no live end-to-end run — needs a configured `SendcloudConfiguration` row + a real associated eBay order in the admin list to observe the method dropdown populating, the service-point dropdown appearing on a Shop2Shop option, and the PATCH reflecting in the Sendcloud panel. `SENDCLOUD_FROM_COUNTRY='FR'` hard-coded (métropole, per eBay SITEID 71) — to revisit if multi-origin. No commit made (awaiting explicit user instruction).

## [2026-07-12 17:26] src-eurocommemo — UI: split Sendcloud prep into its own admin column, distinct from "Expédition"

**Target**: src-eurocommemo @ `feature/sendcloud-shipping-method-service-point` (uncommitted)
**Status**: SUCCESS
**Files affected**:
- `templates/admin/order/order_sendcloud_action.html.twig` (new) — dedicated "Sendcloud" column template: the `.sendcloud-shipping-block` (method `<select>` + service-point `<select>` + "Enregistrer sur Sendcloud" button + current-SP line), made standalone with its own guard (`statePayment == VALID` and `dateExpedition IS NULL` and `isEbay` and `sendcloudOrderId ∉ {null,'0'}`).
- `templates/admin/order/order_delivery_action.html.twig` — removed the inlined Sendcloud block; the "Expédition" cell is back to N° suivi + eBay carrier `<select>` + "Confirmer l'expédition".
- `src/Controller/Admin/OrderCrudController.php` — in `configureFields()` (`delivery === 1` branch) inserted `Field::new('adminObject', "Sendcloud")->setTemplatePath('admin/order/order_sendcloud_action.html.twig')` **before** the "Expédition" field, so the list reads Sendcloud (prep) → Expédition (final confirm) left-to-right.
**Notes**: Follows the "Delta UI" section appended to `plans/2026-07-12_choix-service-livraison-point-relais-sendcloud.md` (user chose two distinct columns over a single-cell separator). Rationale: confirming shipment sets `dateExpedition` and drops the row from the `delivery=1` list, so the Sendcloud prep logically precedes it. `assets/back/js/back.js` unchanged — the JS targets `.sendcloud-shipping-block` by class, independent of the hosting cell. No migration, no asset rebuild. Verified inside `php-fpm-per83` via `scripts/repo_exec.py`: `php -l OrderCrudController.php` (OK), `lint:twig` on both templates (OK), `cache:clear` (OK). Graphify graph refreshed (2 files re-extracted). **Heads-up (pre-existing, user's edit)**: a leftover `dump($points);` remains in `OrderCrudController::sendcloudServicePoints()` (~line 483) — it will corrupt the JSON response in dev; to remove before commit. Also, `getServicePoints()` now sends free-text `address` (line1) **and** structured `address_postal_code`/`address_city`, which the Sendcloud v3 spec flags as mutually exclusive — may 400; to validate against the live API. **Not verified**: no live end-to-end run. No commit made (awaiting explicit user instruction).
