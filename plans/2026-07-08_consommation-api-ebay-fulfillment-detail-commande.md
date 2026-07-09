# Plan — Consume eBay Fulfillment API to fetch order details by eBay order ID (2026-07-08)

**Repo** : src-eurocommemo (`~/OrbStack/docker/volumes/src-eurocommemo`) · **Risk** : low · **Complexité** : simple

## Contexte

Order retrieval currently goes through the legacy **Trading API** XML call `GetOrders`
(`src/Service/Ebay/API/EbayTradingAPI.php:283-316` → `OrderEbayResponseDTO`), consumed by
`ImportEbayOrderCommand`. The goal is to add the ability to consume the modern **Sell
Fulfillment API v1** (`GET /sell/fulfillment/v1/order/{orderId}`) so the order detail can be
fetched anywhere in the codebase from an eBay order ID (e.g. `02-14852-44592`), through a
**hydrated DTO that exposes every value of the API response** (typed getters for the main
fields + a generic dot-path accessor + raw payload).

Scope validated with the user: **API capability only** — the existing order import
(`ImportEbayOrderCommand` / Trading API) is not touched.

Everything needed already exists in the repo and is reused as-is:
- Guzzle client `ebay_json_api` (base `https://api.ebay.com` via `BASE_URL_API_EBAY_TRADING`,
  `.env:73`) declared in `config/packages/eight_points_guzzle.yaml:21-24` and bound as
  `$ebayJsonApi` in `config/services.yaml:28`.
- REST JSON call pattern with Bearer token: `src/Service/Ebay/API/AccoungApiV1.php` (headers
  `Accept` + `Authorization: Bearer <accessToken>` from `GetEbayConfigurationUseCase`, which
  auto-refreshes the OAuth token).
- Exception `App\Exceptions\ExternalEbayApiException`.
- DTO-wrapping-array style: `src/Service/Ebay/DTO/Output/OrderEbayResponseDTO.php`.

**Constraint (to verify at runtime, not in code)**: the Fulfillment API requires the OAuth scope
`https://api.ebay.com/oauth/api_scope/sell.fulfillment` in the user consent URL. That consent
URL is stored in DB (`EbayConfiguration.redirectUri`, sprintf template — `EbayConfiguration.php:140-143`)
and cannot be checked from the code. A `403 Insufficient permissions` on first call means the
scope must be added to the consent URL and the eBay account re-connected from
`/admin/ebay-configuration`.

The response field names below come from the public eBay Sell Fulfillment API v1 `getOrder`
documentation (not observable in the repo). The generic `get()` accessor guarantees access to
any value even for fields without a typed getter.

## Fichiers concernés

Tous dans `src-eurocommemo`. **Aucun fichier modifié** (client Guzzle et binding déjà en place) — uniquement des nouveaux.

### Nouveaux

#### `src/Service/Ebay/DTO/Output/Fulfillment/FulfillmentAmountDTO.php`

Wraps eBay `Amount` objects (`{"value": "43.50", "currency": "EUR"}`).

```php
<?php

namespace App\Service\Ebay\DTO\Output\Fulfillment;

class FulfillmentAmountDTO
{
    public function __construct(
        private array $payload
    ) {
    }

    public function getValue(): float
    {
        return (float) ($this->payload['value'] ?? 0.0);
    }

    public function getCurrency(): ?string
    {
        return $this->payload['currency'] ?? null;
    }

    public function getPayload(): array
    {
        return $this->payload;
    }
}
```

#### `src/Service/Ebay/DTO/Output/Fulfillment/FulfillmentShipToDTO.php`

Wraps `fulfillmentStartInstructions[0].shippingStep.shipTo`.

```php
<?php

namespace App\Service\Ebay\DTO\Output\Fulfillment;

class FulfillmentShipToDTO
{
    public function __construct(
        private array $payload
    ) {
    }

    public function getFullName(): ?string
    {
        return $this->payload['fullName'] ?? null;
    }

    public function getAddressLine1(): ?string
    {
        return $this->payload['contactAddress']['addressLine1'] ?? null;
    }

    public function getAddressLine2(): ?string
    {
        return $this->payload['contactAddress']['addressLine2'] ?? null;
    }

    public function getCity(): ?string
    {
        return $this->payload['contactAddress']['city'] ?? null;
    }

    public function getStateOrProvince(): ?string
    {
        return $this->payload['contactAddress']['stateOrProvince'] ?? null;
    }

    public function getPostalCode(): ?string
    {
        return $this->payload['contactAddress']['postalCode'] ?? null;
    }

    public function getCountryCode(): ?string
    {
        return $this->payload['contactAddress']['countryCode'] ?? null;
    }

    public function getPhoneNumber(): ?string
    {
        return $this->payload['primaryPhone']['phoneNumber'] ?? null;
    }

    public function getEmail(): ?string
    {
        return $this->payload['email'] ?? null;
    }

    public function getPayload(): array
    {
        return $this->payload;
    }
}
```

#### `src/Service/Ebay/DTO/Output/Fulfillment/FulfillmentLineItemDTO.php`

Wraps one entry of `lineItems[]`.

```php
<?php

namespace App\Service\Ebay\DTO\Output\Fulfillment;

class FulfillmentLineItemDTO
{
    public function __construct(
        private array $payload
    ) {
    }

    public function getLineItemId(): ?string
    {
        return $this->payload['lineItemId'] ?? null;
    }

    public function getLegacyItemId(): ?string
    {
        return $this->payload['legacyItemId'] ?? null;
    }

    public function getSku(): ?string
    {
        return $this->payload['sku'] ?? null;
    }

    public function getTitle(): ?string
    {
        return $this->payload['title'] ?? null;
    }

    public function getQuantity(): int
    {
        return (int) ($this->payload['quantity'] ?? 0);
    }

    public function getLineItemCost(): ?FulfillmentAmountDTO
    {
        return isset($this->payload['lineItemCost']) ? new FulfillmentAmountDTO($this->payload['lineItemCost']) : null;
    }

    public function getTotal(): ?FulfillmentAmountDTO
    {
        return isset($this->payload['total']) ? new FulfillmentAmountDTO($this->payload['total']) : null;
    }

    public function getShippingCost(): ?FulfillmentAmountDTO
    {
        return isset($this->payload['deliveryCost']['shippingCost']) ? new FulfillmentAmountDTO($this->payload['deliveryCost']['shippingCost']) : null;
    }

    public function getLineItemFulfillmentStatus(): ?string
    {
        return $this->payload['lineItemFulfillmentStatus'] ?? null;
    }

    public function getPayload(): array
    {
        return $this->payload;
    }
}
```

#### `src/Service/Ebay/DTO/Output/Fulfillment/FulfillmentOrderDTO.php`

Main hydrated object — wraps the full `getOrder` response. Typed getters for the main fields,
`getPayload()` for the raw response, and `get('a.b.c')` dot-path accessor so **any** value of
the response is reachable even without a dedicated getter.

```php
<?php

namespace App\Service\Ebay\DTO\Output\Fulfillment;

class FulfillmentOrderDTO
{
    public function __construct(
        private array $payload
    ) {
    }

    public function getOrderId(): string
    {
        return $this->payload['orderId'];
    }

    public function getLegacyOrderId(): ?string
    {
        return $this->payload['legacyOrderId'] ?? null;
    }

    public function getCreationDate(): ?\DateTimeImmutable
    {
        return isset($this->payload['creationDate']) ? new \DateTimeImmutable($this->payload['creationDate']) : null;
    }

    public function getLastModifiedDate(): ?\DateTimeImmutable
    {
        return isset($this->payload['lastModifiedDate']) ? new \DateTimeImmutable($this->payload['lastModifiedDate']) : null;
    }

    public function getOrderFulfillmentStatus(): ?string
    {
        return $this->payload['orderFulfillmentStatus'] ?? null;
    }

    public function getOrderPaymentStatus(): ?string
    {
        return $this->payload['orderPaymentStatus'] ?? null;
    }

    public function getBuyerUsername(): ?string
    {
        return $this->payload['buyer']['username'] ?? null;
    }

    public function getSalesRecordReference(): ?string
    {
        return $this->payload['salesRecordReference'] ?? null;
    }

    public function getTotal(): ?FulfillmentAmountDTO
    {
        return isset($this->payload['pricingSummary']['total']) ? new FulfillmentAmountDTO($this->payload['pricingSummary']['total']) : null;
    }

    public function getPriceSubtotal(): ?FulfillmentAmountDTO
    {
        return isset($this->payload['pricingSummary']['priceSubtotal']) ? new FulfillmentAmountDTO($this->payload['pricingSummary']['priceSubtotal']) : null;
    }

    public function getDeliveryCost(): ?FulfillmentAmountDTO
    {
        return isset($this->payload['pricingSummary']['deliveryCost']) ? new FulfillmentAmountDTO($this->payload['pricingSummary']['deliveryCost']) : null;
    }

    public function getAdjustment(): ?FulfillmentAmountDTO
    {
        return isset($this->payload['pricingSummary']['adjustment']) ? new FulfillmentAmountDTO($this->payload['pricingSummary']['adjustment']) : null;
    }

    public function getShipTo(): ?FulfillmentShipToDTO
    {
        $shipTo = $this->payload['fulfillmentStartInstructions'][0]['shippingStep']['shipTo'] ?? null;

        return $shipTo !== null ? new FulfillmentShipToDTO($shipTo) : null;
    }

    public function getShippingServiceCode(): ?string
    {
        return $this->payload['fulfillmentStartInstructions'][0]['shippingStep']['shippingServiceCode'] ?? null;
    }

    public function getShippingCarrierCode(): ?string
    {
        return $this->payload['fulfillmentStartInstructions'][0]['shippingStep']['shippingCarrierCode'] ?? null;
    }

    /**
     * @return FulfillmentLineItemDTO[]
     */
    public function getLineItems(): array
    {
        return array_map(
            static fn (array $lineItem): FulfillmentLineItemDTO => new FulfillmentLineItemDTO($lineItem),
            $this->payload['lineItems'] ?? []
        );
    }

    /**
     * Generic accessor: reach any value of the raw response with a dot path,
     * e.g. get('paymentSummary.payments.0.paymentStatus').
     */
    public function get(string $path, mixed $default = null): mixed
    {
        $value = $this->payload;
        foreach (explode('.', $path) as $segment) {
            if (!is_array($value) || !array_key_exists($segment, $value)) {
                return $default;
            }
            $value = $value[$segment];
        }

        return $value;
    }

    public function getPayload(): array
    {
        return $this->payload;
    }
}
```

#### `src/Service/Ebay/API/FulfillmentApiV1.php`

Mirrors `AccoungApiV1` (same constructor signature/bindings, same Bearer-token pattern).
`'http_errors' => false` is required so the status-code check is reachable on 4xx (same flag
as `EbayApiConnector.php:55`; without it Guzzle throws `ClientException` before the check).

**Route appelée** : `GET https://api.ebay.com/sell/fulfillment/v1/order/{orderId}` — headers
`Accept: application/json`, `Authorization: Bearer <accessToken>`. Réponses : `200` + JSON order,
`404` order inconnu, `403` scope `sell.fulfillment` absent du consentement OAuth.

```php
<?php

namespace App\Service\Ebay\API;

use App\Exceptions\ExternalEbayApiException;
use App\Service\Ebay\DTO\Output\Fulfillment\FulfillmentOrderDTO;
use App\Service\Ebay\UseCase\GetEbayConfigurationUseCase;
use GuzzleHttp\Client;

class FulfillmentApiV1
{
    private const BASE_URL_FULFILLMENT = '/sell/fulfillment/v1';

    public function __construct(
        private readonly Client $ebayJsonApi,
        private readonly GetEbayConfigurationUseCase $ebayConfigurationUseCase
    ) {
    }

    public function getOrder(string $orderId): FulfillmentOrderDTO
    {
        $configuration = $this->ebayConfigurationUseCase->execute();
        $headers = [
            'Accept' => 'application/json',
            'Authorization' => 'Bearer ' . $configuration->getAccessToken(),
        ];

        $response = $this->ebayJsonApi->get(
            sprintf('%s/order/%s', self::BASE_URL_FULFILLMENT, $orderId),
            [
                'headers' => $headers,
                'http_errors' => false,
            ]
        );

        $content = $response->getBody()->getContents();

        if ($response->getStatusCode() !== 200) {
            throw new ExternalEbayApiException($content);
        }

        return new FulfillmentOrderDTO(json_decode($content, true));
    }
}
```

#### `src/Command/GetEbayFulfillmentOrderCommand.php`

Console command to exercise the service end-to-end (manual verification + ops usage).
Same style as `ImportEbayOrderCommand` (`#[AsCommand]`, promoted readonly dependencies).

```php
<?php

namespace App\Command;

use App\Exceptions\ExternalEbayApiException;
use App\Service\Ebay\API\FulfillmentApiV1;
use Symfony\Component\Console\Attribute\AsCommand;
use Symfony\Component\Console\Command\Command;
use Symfony\Component\Console\Input\InputInterface;
use Symfony\Component\Console\Input\InputOption;
use Symfony\Component\Console\Output\OutputInterface;

#[AsCommand("app:ebay:fulfillment-order")]
class GetEbayFulfillmentOrderCommand extends Command
{
    public function __construct(
        private readonly FulfillmentApiV1 $fulfillmentApi
    ) {
        parent::__construct();
    }

    protected function configure()
    {
        $this
            ->addOption("orderId", "o", InputOption::VALUE_REQUIRED, "eBay order ID (e.g. 02-14852-44592)")
            ->addOption("raw", "r", InputOption::VALUE_NONE, "Dump the raw JSON payload");
    }

    protected function execute(InputInterface $input, OutputInterface $output): int
    {
        $orderId = $input->getOption("orderId");

        try {
            $order = $this->fulfillmentApi->getOrder($orderId);
        } catch (ExternalEbayApiException $exception) {
            $output->writeln("<error>eBay API error: {$exception->getMessage()}</error>");

            return Command::FAILURE;
        }

        if ($input->getOption("raw")) {
            $output->writeln(json_encode($order->getPayload(), JSON_PRETTY_PRINT | JSON_UNESCAPED_UNICODE));

            return Command::SUCCESS;
        }

        $output->writeln("Order:      " . $order->getOrderId());
        $output->writeln("Status:     " . $order->getOrderFulfillmentStatus() . " / " . $order->getOrderPaymentStatus());
        $output->writeln("Created:    " . $order->getCreationDate()?->format('Y-m-d H:i:s'));
        $output->writeln("Buyer:      " . $order->getBuyerUsername());
        $output->writeln("Ship to:    " . $order->getShipTo()?->getFullName() . " — " . $order->getShipTo()?->getCity() . " (" . $order->getShipTo()?->getCountryCode() . ")");
        $output->writeln("Shipping:   " . $order->getShippingServiceCode());
        $output->writeln("Total:      " . $order->getTotal()?->getValue() . " " . $order->getTotal()?->getCurrency());
        foreach ($order->getLineItems() as $lineItem) {
            $output->writeln(sprintf(
                "  - %s x%d — %s %s (legacyItemId: %s)",
                $lineItem->getTitle(),
                $lineItem->getQuantity(),
                $lineItem->getTotal()?->getValue(),
                $lineItem->getTotal()?->getCurrency(),
                $lineItem->getLegacyItemId()
            ));
        }

        return Command::SUCCESS;
    }
}
```

### Modifiés

Aucun. Le client Guzzle `ebay_json_api` (`config/packages/eight_points_guzzle.yaml:21-24`), le
binding `$ebayJsonApi` (`config/services.yaml:28`) et la variable d'env
`BASE_URL_API_EBAY_TRADING` (`.env:73`) existent déjà ; l'autowiring `App\` couvre les
nouvelles classes.

## Étapes

1. Créer les 4 DTOs `src/Service/Ebay/DTO/Output/Fulfillment/` — `FulfillmentAmountDTO`,
   `FulfillmentShipToDTO`, `FulfillmentLineItemDTO`, puis `FulfillmentOrderDTO` (dépend des 3 premiers).
2. Créer le service `src/Service/Ebay/API/FulfillmentApiV1.php` (dépend de l'étape 1).
3. Créer la commande `src/Command/GetEbayFulfillmentOrderCommand.php` (dépend de l'étape 2).
4. Vérifier (section suivante), puis consigner l'entrée dans `logs/src-eurocommemo.md` (règle action-logging du meta-repo).

## Vérification

Commandes via `scripts/repo_exec.py` (exécution dans le conteneur `php-fpm-per83`,
`exec.mode: compose` — jamais d'appel direct) :

```sh
# Container is wired and the new services are autowirable
python3 scripts/repo_exec.py src-eurocommemo "php bin/console lint:container"

# End-to-end: fetch a real order (use a recent order ID, e.g. 02-14852-44592 from src/Command/ebay-order.json)
python3 scripts/repo_exec.py src-eurocommemo "php bin/console app:ebay:fulfillment-order -o 02-14852-44592"
python3 scripts/repo_exec.py src-eurocommemo "php bin/console app:ebay:fulfillment-order -o 02-14852-44592 --raw"
```

Critères :
- `lint:container` passe sans erreur.
- La commande affiche orderId, statuts, acheteur, adresse de livraison, total et lignes — cohérents
  avec la même commande vue côté Trading API (`app:import:ebay-order`) / back-office eBay.
- `--raw` dump le JSON complet ; vérifier qu'un chemin arbitraire est accessible via
  `FulfillmentOrderDTO::get()` (ex. `paymentSummary.payments.0.paymentStatus`).
- Cas d'erreur : un orderId inexistant → `ExternalEbayApiException` avec le corps d'erreur eBay
  (exit code failure, pas de fatal).
- Si `403 Insufficient permissions` : ajouter le scope
  `https://api.ebay.com/oauth/api_scope/sell.fulfillment` à l'URL de consentement stockée dans
  `EbayConfiguration.redirectUri` et reconnecter le compte depuis `/admin/ebay-configuration`
  (le refresh token existant ne porte pas les nouveaux scopes).

Pas de tests unitaires : le repo n'a pas d'infrastructure de tests exploitable (`tests/` ne
contient que `bootstrap.php`).
