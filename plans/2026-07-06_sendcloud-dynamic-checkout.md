# Plan — Sendcloud Dynamic Checkout integration

**Date**: 2026-07-06
**Repo**: `src-eurocommemo` (Symfony e-commerce site, resolved via `workspace.yaml` → `${REPOS_ROOT}/src-eurocommemo`)
**Branch target**: new branch `feature/sendcloud-dynamic-checkout`, cut directly from `main` → `main`

## Context

The client asked to add the Sendcloud **Dynamic Checkout** widget to the checkout funnel; the Sendcloud panel-side configuration (carriers, rates, checkout rules) is already done, so this is purely a website-side integration.

Exploration turned up an older, unmerged branch (`feature/sendcloud-service-point-checkout`) with Sendcloud plumbing for a *different* feature (the client-side Service Point Picker widget). **The user confirmed that branch is to be ignored** — this plan builds directly on `main` and reuses none of its code.

Two things shape the whole design:

1. **Dynamic Checkout is not a JS widget.** Unlike the Service Point Picker (a `<script>` embed a browser can call with just a public key), Dynamic Checkout is a **server-to-server REST API**: `POST /checkout/delivery-options` on Sendcloud's public API v3 (confirmed against the live OpenAPI spec at `sendcloud.dev/.openapi/v3/dynamic-checkout/openapi.yaml`; still labelled **beta** by Sendcloud, so re-verify the request/response shape against `sendcloud.dev/docs/dynamic-checkout` right before implementing). It returns a live, priced, multi-carrier list of delivery options, each with a `checkout_identifier.value` (a shipping-option code, e.g. `dhl:complete/standard`) used later to book a shipment. The call must be signed with the account's public **and secret** key (HTTP Basic Auth) so it cannot run in browser JS — it's a Symfony controller action + Guzzle call + Twig radio list, nothing more.
2. **Reference pattern to mirror**: the codebase's one clean, currently-active external-API integration — PayPal (`src/Service/PaypalApiConnector.php`, `src/Dto/Paypal/*DTO.php`, env-based secrets in `.env`, Guzzle client in `config/packages/eight_points_guzzle.yaml`, bound in `config/services.yaml`'s `_defaults.bind`). This plan copies that shape exactly for Sendcloud (env vars for credentials — no new admin entity).

**Scope boundary**: this plan covers **selecting and persisting** a Dynamic Checkout option at checkout. It does **not** book the shipment (Sendcloud Shipments API / admin label UI) — the captured `checkout_identifier` is what a future booking step would need.

**Scope reduction**: a `service_point_delivery` option is surfaced like any other (carrier/title/price), without a specific-point picker (see Open question).

**Fallback**: Dynamic Checkout is an **additional** delivery choice next to the existing weight/zone `Delivery` price grid — if the API call fails, checkout falls back transparently to the grid.

**Notable existing-code detail found while exploring**: the "pickup in store" radio in `templates/order/delivery.html.twig` is currently commented out (`{# ... #}`, lines 51–54) — today only a single, hardcoded `checked` static-grid radio is rendered. Adding more radios means the `checked` attribute logic on the existing radio must become conditional (see the template section below) instead of unconditionally hardcoded.

---

## 1. `.env` — new Sendcloud credentials block

Add after the existing `### Ebay ###` block:

```dotenv
### Sendcloud ###
SENDCLOUD_BASE_URL="https://panel.sendcloud.sc/api/v3/"
SENDCLOUD_PUBLIC_KEY=
SENDCLOUD_SECRET_KEY=
### Sendcloud ###
```

Same shape as the existing `### Paypal ###` block (`.env:67-71`: `PAYPAL_URL`, `PAYPAL_CLIENT_ID`, `PAYPAL_CLIENT_SECRET`). Real values go in `.env.local` (gitignored), never committed.

## 2. `config/packages/eight_points_guzzle.yaml` — new Guzzle client

Add a `sendcloud_api` entry under `eight_points_guzzle.clients`, alongside `api_paypal`:

```yaml
        sendcloud_api:
            base_url: "%env(SENDCLOUD_BASE_URL)%"
            options:
                headers:
                    Accept: "application/json"
                timeout: 30
```

## 3. `config/services.yaml` — bind the client + credentials

Add to the existing `_defaults.bind` map (`config/services.yaml:20-27`), next to the `$paypalApiClient`/`$paypalClientId`/`$paypalClientSecret` lines:

```yaml
            $sendcloudApiClient: '@eight_points_guzzle.client.sendcloud_api'
            $sendcloudPublicKey: '%env(SENDCLOUD_PUBLIC_KEY)%'
            $sendcloudSecretKey: '%env(SENDCLOUD_SECRET_KEY)%'
```

These become available as constructor-promoted, autowired arguments by name in any service under `src/`, exactly like `$paypalApiClient` is consumed by `PaypalApiConnector::__construct()`.

## 4. New file — `src/Dto/Sendcloud/SendcloudDeliveryOptionDTO.php`

Mirrors `src/Dto/Paypal/PaypalOrderResponseDTO.php`'s array-hydration constructor style. One instance per entry of the API response's `delivery_options[]` array.

```php
<?php

namespace App\Dto\Sendcloud;

class SendcloudDeliveryOptionDTO
{
    private string $identifierType;
    private string $identifierValue;
    private string $carrierCode;
    private string $carrierName;
    private string $title;
    private string $methodType;
    private ?string $shippingRate;

    public function __construct(array $option)
    {
        $this->identifierType  = $option['checkout_identifier']['type'] ?? 'shipping_option_code';
        $this->identifierValue = $option['checkout_identifier']['value'];
        $this->carrierCode     = $option['carrier']['code'] ?? '';
        $this->carrierName     = $option['carrier']['name'] ?? '';
        $this->title           = $option['title'] ?? '';
        $this->methodType      = $option['delivery_method_type'] ?? 'standard_delivery';
        $this->shippingRate    = $option['shipping_rate']['value'] ?? null;
    }

    public function getIdentifierType(): string { return $this->identifierType; }
    public function getIdentifierValue(): string { return $this->identifierValue; }
    public function getCarrierCode(): string { return $this->carrierCode; }
    public function getCarrierName(): string { return $this->carrierName; }
    public function getTitle(): string { return $this->title; }
    public function getMethodType(): string { return $this->methodType; }
    public function getShippingRate(): ?string { return $this->shippingRate; }
}
```

Deliberately a plain hydration DTO (no setters) — same spirit as `PaypalOrderResponseDTO`. Kept serializable (scalars only) since it will be round-tripped through the session between the GET and POST of `/order/delivery`.

## 5. New file — `src/Service/SendcloudApiConnector.php`

Mirrors `src/Service/PaypalApiConnector.php` (constants for URLs, constructor-promoted Guzzle client + credential strings, one public method per API call).

```php
<?php

namespace App\Service;

use App\Dto\Sendcloud\SendcloudDeliveryOptionDTO;
use GuzzleHttp\Client;

class SendcloudApiConnector
{
    private const URL_DELIVERY_OPTIONS = 'checkout/delivery-options';
    private const SHOP_COUNTRY_CODE = 'FR';

    public function __construct(
        private readonly Client $sendcloudApiClient,
        private readonly string $sendcloudPublicKey,
        private readonly string $sendcloudSecretKey
    ) {
    }

    /**
     * @return SendcloudDeliveryOptionDTO[]
     * @throws \GuzzleHttp\Exception\GuzzleException
     */
    public function getDynamicCheckoutDeliveryOptions(
        ?string $toCountryCode,
        ?string $toPostalCode,
        float $totalWeightGrams,
        float $totalPrice
    ): array {
        $payload = [
            'total_weight' => [
                'value' => (string) max((int) round($totalWeightGrams), 1),
                'unit' => 'g',
            ],
            'total_price' => [
                'value' => number_format($totalPrice, 2, '.', ''),
            ],
            'from_address' => [
                'country_code' => self::SHOP_COUNTRY_CODE,
            ],
            'to_address' => array_filter([
                'country_code' => $toCountryCode,
                'postal_code' => $toPostalCode,
            ]),
        ];

        $response = $this->sendcloudApiClient->post(self::URL_DELIVERY_OPTIONS, [
            'auth' => [$this->sendcloudPublicKey, $this->sendcloudSecretKey],
            'json' => $payload,
        ]);

        $content = json_decode($response->getBody()->getContents(), true);

        return array_map(
            static fn (array $option): SendcloudDeliveryOptionDTO => new SendcloudDeliveryOptionDTO($option),
            $content['delivery_options'] ?? []
        );
    }
}
```

Note: unlike `PaypalApiConnector`, this method does **not** wrap the Guzzle call in a redundant `try { ... } catch (GuzzleException $e) { throw $e; }` (that pattern in `PaypalApiConnector` adds nothing — it rethrows unchanged). Exceptions bubble to the caller (`OrderController::delivery()`), which is the single place that decides to log-and-fall-back. `SHOP_COUNTRY_CODE = 'FR'` mirrors the same hardcoded-shop-origin convention already implied by this codebase's other carrier-adjacent code (e.g. `Configuration` has no structured origin address, only free text).

## 6. Migration — new `orders` columns

Generate with `bin/console make:migration` after step 7's entity change; expected `up()`/`down()` (matches the style of existing migrations, e.g. `ALTER TABLE orders ADD ...` seen in this repo's migration history):

```php
public function up(Schema $schema): void
{
    $this->addSql(<<<'SQL'
        ALTER TABLE orders
            ADD sendcloud_checkout_identifier_type VARCHAR(255) DEFAULT NULL,
            ADD sendcloud_checkout_identifier_value VARCHAR(255) DEFAULT NULL,
            ADD sendcloud_carrier_code VARCHAR(255) DEFAULT NULL,
            ADD sendcloud_carrier_name VARCHAR(255) DEFAULT NULL,
            ADD sendcloud_method_title VARCHAR(255) DEFAULT NULL,
            ADD sendcloud_method_type VARCHAR(255) DEFAULT NULL,
            ADD sendcloud_shipping_rate VARCHAR(255) DEFAULT NULL
    SQL);
}

public function down(Schema $schema): void
{
    $this->addSql(<<<'SQL'
        ALTER TABLE orders
            DROP sendcloud_checkout_identifier_type,
            DROP sendcloud_checkout_identifier_value,
            DROP sendcloud_carrier_code,
            DROP sendcloud_carrier_name,
            DROP sendcloud_method_title,
            DROP sendcloud_method_type,
            DROP sendcloud_shipping_rate
    SQL);
}
```

## 7. `src/Entity/Order.php` — new fields

Add next to the existing `fakeOrderIdEbay` field (`src/Entity/Order.php:102-103`), same flat nullable-column style:

```php
#[ORM\Column(type: 'string', nullable: true)]
private ?string $sendcloudCheckoutIdentifierType = null;
#[ORM\Column(type: 'string', nullable: true)]
private ?string $sendcloudCheckoutIdentifierValue = null;
#[ORM\Column(type: 'string', nullable: true)]
private ?string $sendcloudCarrierCode = null;
#[ORM\Column(type: 'string', nullable: true)]
private ?string $sendcloudCarrierName = null;
#[ORM\Column(type: 'string', nullable: true)]
private ?string $sendcloudMethodTitle = null;
#[ORM\Column(type: 'string', nullable: true)]
private ?string $sendcloudMethodType = null;
#[ORM\Column(type: 'string', nullable: true)]
private ?string $sendcloudShippingRate = null;
```

Getters/setters (matching `getFakeOrderIdEbay()`/`setFakeOrderIdEbay()` style at `src/Entity/Order.php:446-455`, fluent setters returning `Order`):

```php
public function getSendcloudCheckoutIdentifierType(): ?string { return $this->sendcloudCheckoutIdentifierType; }
public function setSendcloudCheckoutIdentifierType(?string $v): Order { $this->sendcloudCheckoutIdentifierType = $v; return $this; }

public function getSendcloudCheckoutIdentifierValue(): ?string { return $this->sendcloudCheckoutIdentifierValue; }
public function setSendcloudCheckoutIdentifierValue(?string $v): Order { $this->sendcloudCheckoutIdentifierValue = $v; return $this; }

public function getSendcloudCarrierCode(): ?string { return $this->sendcloudCarrierCode; }
public function setSendcloudCarrierCode(?string $v): Order { $this->sendcloudCarrierCode = $v; return $this; }

public function getSendcloudCarrierName(): ?string { return $this->sendcloudCarrierName; }
public function setSendcloudCarrierName(?string $v): Order { $this->sendcloudCarrierName = $v; return $this; }

public function getSendcloudMethodTitle(): ?string { return $this->sendcloudMethodTitle; }
public function setSendcloudMethodTitle(?string $v): Order { $this->sendcloudMethodTitle = $v; return $this; }

public function getSendcloudMethodType(): ?string { return $this->sendcloudMethodType; }
public function setSendcloudMethodType(?string $v): Order { $this->sendcloudMethodType = $v; return $this; }

public function getSendcloudShippingRate(): ?string { return $this->sendcloudShippingRate; }
public function setSendcloudShippingRate(?string $v): Order { $this->sendcloudShippingRate = $v; return $this; }

public function hasSendcloudDynamicCheckout(): bool
{
    return $this->sendcloudCheckoutIdentifierValue !== null;
}
```

## 8. `src/Service/CartHelper.php` — new method + `cartToOrder()` change

**New method** `getTotalAmountCart(): float`, extracting the `sumCart` computation currently duplicated inline in `templates/order/delivery.html.twig:24-26` (cart-line total) and `:126-128` (code-reduction applied), so the controller can pass a correct `total_price` to Sendcloud without duplicating that logic a third time:

```php
public function getTotalAmountCart(): float
{
    $sumCart = 0;
    /** @var User $user */
    $user = $this->tokenStorageInterface->getToken()?->getUser();
    if ($user instanceof User) {
        foreach ($user->getCarts() as $cart) {
            $sumCart += $cart->getAmountCartLine();
        }
    }

    $codeReduction = $this->requestStack->getSession()->get('codeReduction');
    if ($codeReduction) {
        $sumCart = ($codeReduction->getMontantReduction() > $sumCart)
            ? 0
            : $sumCart - $codeReduction->getMontantReduction();
    }

    return $sumCart;
}
```

(Mirrors the exact twig logic at `templates/order/delivery.html.twig:126-128`; `Cart::getAmountCartLine()` at `src/Entity/Cart.php:66` has no return type, treated as float here.)

**`cartToOrder()` change** (`src/Service/CartHelper.php:255-273`) — add an `elseif` next to the existing `if($session->get('delivery'))` block:

```php
/*** Livraison ***/
$order->setAmountLivraison(0);
if ($session->get('delivery')) {
    /** @var Delivery $delivery */
    $delivery = $this->em->getRepository(Delivery::class)->find($session->get('delivery'));

    $order->setDelivery($delivery);

    $amountDelivery = $delivery->getPrice();
    if ($delivery->getFreeCartCondition() && $delivery->getFreeCartCondition() <= $sumAmountCmd) {
        $amountDelivery = 0;
    }
    $order->setAmountLivraison($amountDelivery);
    $sumAmountCmd += $amountDelivery;
} elseif ($session->get('selectedSendcloudOption')) {
    /** @var \App\Dto\Sendcloud\SendcloudDeliveryOptionDTO $option */
    $option = $session->get('selectedSendcloudOption');

    $order->setSendcloudCheckoutIdentifierType($option->getIdentifierType())
        ->setSendcloudCheckoutIdentifierValue($option->getIdentifierValue())
        ->setSendcloudCarrierCode($option->getCarrierCode())
        ->setSendcloudCarrierName($option->getCarrierName())
        ->setSendcloudMethodTitle($option->getTitle())
        ->setSendcloudMethodType($option->getMethodType())
        ->setSendcloudShippingRate($option->getShippingRate());

    $amountDelivery = (float) ($option->getShippingRate() ?? 0);
    $order->setAmountLivraison($amountDelivery);
    $sumAmountCmd += $amountDelivery;
}
```

No local free-shipping-threshold check is needed here (unlike the static grid's `freeCartCondition`) — Sendcloud's own Dynamic Checkout configuration in the panel already applies any such rule before returning `shipping_rate`.

## 9. `src/Controller/OrderController.php` — constructor + `delivery()`

**Constructor** (`src/Controller/OrderController.php:46-56`) — add two parameters:

```php
public function __construct(private readonly EntityManagerInterface $em,
                            private readonly UserPasswordHasherInterface $hasher,
                            private readonly CartHelper $cartHelper,
                            private readonly EventDispatcherInterface $eventDispatcher,
                            private readonly OrderHelper $orderHelper,
                            private readonly MailService $mailer,
                            private readonly TranslatorInterface $translator,
                            private readonly RandomService $random,
                            private readonly PaymentCbHelper $paymentCbHelper,
                            private readonly TokenStorageInterface $tokenStorage,
                            private readonly RequestStack $requestStack,
                            private readonly SendcloudApiConnector $sendcloudApiConnector,
                            private readonly \Psr\Log\LoggerInterface $logger) {
}
```

(`LoggerInterface` is autowired by Symfony by default — no new service registration needed; this controller currently has no logger injected.)

Add imports: `use App\Service\SendcloudApiConnector;`, `use App\Dto\Sendcloud\SendcloudDeliveryOptionDTO;`, `use GuzzleHttp\Exception\GuzzleException;`.

**`delivery()`** (`src/Controller/OrderController.php:161-192`), full replacement:

```php
#[Route('/order/delivery', name: 'order_delivery')]
#[IsGranted('ROLE_USER')]
public function delivery(Request $request): Response
{
    $bannerGenerale = $this->em->getRepository(Away::class)->findOneBy(['active' => true, 'orderProcess' => true]);
    $session = $request->getSession();

    /*** SUBMIT POST ***/
    if ($request->request->get('delivery')) {
        $rawDelivery = (string) $request->request->get('delivery');

        $session->set('delivery', null);
        $session->remove('selectedSendcloudOption');

        if (str_starts_with($rawDelivery, 'sendcloud:')) {
            $identifierValue = substr($rawDelivery, strlen('sendcloud:'));
            /** @var SendcloudDeliveryOptionDTO[] $options */
            $options = $session->get('sendcloudDeliveryOptions', []);
            $selected = null;
            foreach ($options as $option) {
                if ($option->getIdentifierValue() === $identifierValue) {
                    $selected = $option;
                    break;
                }
            }

            if ($selected === null) {
                $this->addFlash('danger', $this->translator->trans('shop.order.deliveryMissing', [], 'shop'));
                return $this->redirectToRoute('order_delivery');
            }

            $session->set('selectedSendcloudOption', $selected);
        } else {
            $deliveryId = ($rawDelivery === GlobalConstants::LIVRAISON_RETRAIT) ? null : (int) $rawDelivery;
            $session->set('delivery', $deliveryId);
        }

        return $this->redirectToRoute('order_payment');
    }

    /*** Remove item unavailable ***/
    $this->cartHelper->removeCartItemUnavailable();

    $weightCart = $this->cartHelper->getWeightCart();
    $arrayListAmountTva = $this->cartHelper->listAmountTvaByCart();

    /** @var User $user */
    $user = $this->getUser();
    $sendcloudDeliveryOptions = [];
    try {
        $sendcloudDeliveryOptions = $this->sendcloudApiConnector->getDynamicCheckoutDeliveryOptions(
            $user->getCountry()?->getCodeIso(),
            $user->getPostalCode(),
            (float) $weightCart,
            $this->cartHelper->getTotalAmountCart()
        );
    } catch (GuzzleException $e) {
        $this->logger->error('Sendcloud Dynamic Checkout call failed: '.$e->getMessage());
    }
    $session->set('sendcloudDeliveryOptions', $sendcloudDeliveryOptions);

    return $this->render('order/delivery.html.twig', [
        'arrayListAmountTva' => $arrayListAmountTva,
        'bannerGenerale' => $bannerGenerale,
        'weight' => $weightCart,
        'delivery' => $this->orderHelper->getDelivery($weightCart),
        'sendcloudDeliveryOptions' => $sendcloudDeliveryOptions,
        'selectedSendcloudIdentifier' => $session->get('selectedSendcloudOption')?->getIdentifierValue(),
    ]);
}
```

Security note baked into the design: the POST branch resolves the customer's choice by looking the submitted identifier up in the **session-stored** list fetched server-side on the prior GET — the price/carrier the customer ends up paying always comes from that trusted list, never from a client-supplied hidden field.

## 10. `templates/order/delivery.html.twig` — render the options

Replace the single hardcoded-`checked` static radio block (`templates/order/delivery.html.twig:55-65`) so `checked` becomes conditional, then add the Sendcloud loop:

```twig
{% if delivery %}
    {% set free = false %}
    {% if delivery.freeCartCondition and delivery.freeCartCondition <= sumCart %}
        {% set free = true %}
    {% endif %}

    <div class="radio mt-2 mx-0">
        <input id="delivery-{{ delivery.id }}" type="radio" name="delivery" value="{{ delivery.id }}"
               {% if selectedSendcloudIdentifier is null %}checked{% endif %}>
        <label for="delivery-{{ delivery.id }}" class="radio-label cursor-pointer text-dark fs-6">Je souhaiterai me faire livrer à mon adresse <b>({{ (free) ? "shop.order.free"|trans({}, "shop") : "+ "~delivery.price|number_format(2, '.', ' ')~" €" }})</b></label>
    </div>
{% endif %}

{% for option in sendcloudDeliveryOptions %}
    <div class="radio mt-2 mx-0">
        <input id="delivery-sendcloud-{{ loop.index }}" type="radio" name="delivery" value="sendcloud:{{ option.identifierValue }}"
               {% if selectedSendcloudIdentifier == option.identifierValue %}checked{% endif %}>
        <label for="delivery-sendcloud-{{ loop.index }}" class="radio-label cursor-pointer text-dark fs-6">
            {{ option.carrierName }} — {{ option.title }} <b>({{ option.shippingRate|number_format(2, '.', ' ') }} €)</b>
        </label>
    </div>
{% endfor %}
```

## 11. Mail templates — `templates/mail/mail_order.html.twig` and `templates/mail/mail_order_waiting_payment.html.twig`

The existing block at line 63 (both files) is:

```twig
{% if order.delivery is null and not order.isEbay %}
    <b>Commande à récupérer en magasin</b>
    ...
{% else %}
    <b>La commande sera expédiée à l'adresse</b>
    ...
{% endif %}
```

Add a branch before `{% else %}`:

```twig
{% if order.delivery is null and not order.isEbay and not order.hasSendcloudDynamicCheckout %}
    <b>Commande à récupérer en magasin</b>
    ...
{% elseif order.hasSendcloudDynamicCheckout %}
    <b>La commande sera expédiée via {{ order.sendcloudCarrierName }} — {{ order.sendcloudMethodTitle }}</b>
    <br />{{ order.user.firstName~" "~order.user.lastName }}
    <br />{{ order.user.fullAddress|raw }}
{% else %}
    <b>La commande sera expédiée à l'adresse</b>
    ...
{% endif %}
```

## 12. Translations

Add `shop.order.deliveryMissing: "Veuillez sélectionner un mode de livraison"` to `translations/shop.fr.yml` (used by the new flash-error branch in `delivery()`), plus `.en.yml`/`.de.yml` equivalents. Option titles/carrier names are not translated — they come verbatim from Sendcloud.

---

## Implementation steps

1. `.env` + `config/packages/eight_points_guzzle.yaml` + `config/services.yaml` (sections 1–3).
2. `src/Dto/Sendcloud/SendcloudDeliveryOptionDTO.php` (section 4).
3. `src/Service/SendcloudApiConnector.php` (section 5).
4. `src/Entity/Order.php` fields/getters/setters (section 7) → `bin/console make:migration` → apply migration (section 6).
5. `src/Service/CartHelper.php`: `getTotalAmountCart()` + `cartToOrder()` change (section 8).
6. `src/Controller/OrderController.php`: constructor + `delivery()` (section 9).
7. `templates/order/delivery.html.twig` (section 10).
8. Mail templates (section 11).
9. Translations (section 12).

## Open question

Does the Sendcloud account's Dynamic Checkout configuration include any `service_point_delivery` method? If yes, decide separately (out of scope here) whether/how to let the customer pick the exact point — this plan surfaces the method as a plain option (carrier + price) without a point picker.

## Verification

1. `scripts/repo_exec.py src-eurocommemo -- composer install --no-interaction` then `bin/console doctrine:migrations:migrate --no-interaction` — migration applies cleanly.
2. Set `SENDCLOUD_PUBLIC_KEY`/`SENDCLOUD_SECRET_KEY` in `.env.local` from the already-configured Sendcloud panel account.
3. Add a product to the cart, go through `/order/information` → `/order/delivery`: confirm Dynamic Checkout options render as radios with real carrier names/prices matching the Sendcloud panel's configuration for that destination/weight, and that the existing static-grid radio still renders correctly (`checked` logic).
4. Select a Dynamic Checkout option, complete payment (test/cheque method to avoid live PayPal), confirm on `/order/complete` and in the confirmation email that carrier/method/price match the selection.
5. Tamper the submitted `delivery` value client-side to a `sendcloud:` identifier not in the session-stored list — confirm the controller rejects it (flash error, redirect back).
6. Temporarily break the credentials (wrong secret key) and confirm checkout still works end-to-end via the static `Delivery` grid — no regression, failure visible in `var/log/`.
7. `scripts/repo_exec.py src-eurocommemo -- vendor/bin/phpunit` — no regressions.
