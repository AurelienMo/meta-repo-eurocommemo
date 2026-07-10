# Plan — Connecteur API Sendcloud : récupération des commandes

## Contexte

Le repo `src-eurocommemo` (Symfony 6.4, PHP ≥ 8.3) dispose déjà d'une **configuration
Sendcloud persistée en base** (entité `SendcloudConfiguration` avec `publicKey` / `secretKey`,
son repository `findFirst()`, le service `SendcloudConfigurationService::getConfiguration()`,
un formulaire, un contrôleur d'admin et une migration). Le commentaire de l'entité
(`SendcloudConfiguration.php:80`) annonce explicitement ces credentials comme « utile pour un
futur connecteur API ».

Ce connecteur n'existe pas encore : `src/Service/Sendcloud/UseCase/` et `src/Dto/Sendcloud/`
sont **vides**. L'objectif est de créer le client HTTP du connecteur Sendcloud, authentifié en
**HTTP Basic** (`publicKey` = user, `secretKey` = password) avec les credentials lus en base,
**mis en cache par le service** (mémoïsation dans `SendcloudConfigurationService::getConfiguration()`),
et d'y implémenter une méthode de **récupération de la liste des commandes**
avec un **filtre optionnel `order_id`**.

Ancrage API (source : `specs/sendcloud-v3/orders/openapi.yaml`, doc archivée localement) :

- **Serveur** : `https://panel.sendcloud.sc/api/v3` (env `SENDCLOUD_BASE_URL="https://panel.sendcloud.sc"` déjà présent en `.env.local`).
- **Endpoint** : `GET /orders` (`operationId: sc-public-v3-orders-get-list_orders`).
- **Auth** : `security: [{ HTTPBasicAuth: [] }]` → Basic Auth `publicKey:secretKey`.
- **Filtre** : paramètre query `order_id` (`type: string`, insensible à la casse).
- **Réponse `200`** : `{ "data": [ <order>, ... ] }` + **header `Link`** (RFC 5988) portant les
  liens `next` / `prev` pour la pagination.
- **Erreurs** : `400` / `404` au format JSON:API `{ "errors": [ { status, code, title, detail, source } ] }`.

**Décisions de conception validées avec l'utilisateur :**
1. **Client HTTP** : Guzzle via `eightpoints/guzzle-bundle` (convention dominante des connecteurs
   externes — mirror de `src/Service/Ebay/API/FulfillmentApiV1.php` et `src/Service/PaypalApiConnector.php`).
2. **DTO** : DTOs typés imbriqués (un DTO par sous-objet), pas un simple payload-array.
3. **Pagination** : suivi automatique du header `Link` (`next`) en boucle pour agréger toutes les pages.

## Fichiers concernés

### Nouveaux — repo `src-eurocommemo`

#### `config/packages/eight_points_guzzle.yaml` — déclarer le client Guzzle Sendcloud

Ajouter un client `sendcloud_api` à côté des clients `api_paypal` / `ebay_json_api` existants.
Le `base_url` inclut le préfixe `/api/v3` (les credentials NE sont PAS bakés ici — ils sont lus
en base et passés par requête via l'option `auth`).

```yaml
eight_points_guzzle:
    clients:
        # ... clients existants (api_paypal, ebay_api_trading, ebay_json_api) ...
        sendcloud_api:
            base_url: "%env(SENDCLOUD_BASE_URL)%/api/v3"
            options:
                headers:
                    Accept: "application/json"
                timeout: 15
```

> Vérifier que la concaténation `%env(...)%/api/v3` est acceptée par la version du bundle
> (`eightpoints/guzzle-bundle: ^8.5`). Si non, ajouter une variable dédiée
> `SENDCLOUD_API_BASE_URL="https://panel.sendcloud.sc/api/v3"` en `.env` / `.env.local` et
> référencer `base_url: "%env(SENDCLOUD_API_BASE_URL)%"`.

#### `config/services.yaml` — binder le client Guzzle

Ajouter le bind nommé dans `_defaults.bind` (mirror exact des binds `$paypalApiClient` /
`$ebayJsonApi` existants aux lignes 21-28) :

```yaml
services:
    _defaults:
        autowire: true
        autoconfigure: true
        bind:
            # ... binds existants ...
            $sendcloudApiClient: '@eight_points_guzzle.client.sendcloud_api'
```

Aucune définition de service manuelle n'est nécessaire au-delà : `App\` est auto-enregistré
(`resource: '../src/'`), donc le connecteur et les DTOs sont câblés par autowiring.

#### `src/Exceptions/ExternalSendcloudApiException.php` — exception dédiée

Mirror exact de `src/Exceptions/ExternalEbayApiException.php` (corps vide).

```php
<?php

namespace App\Exceptions;

class ExternalSendcloudApiException extends \Exception
{
}
```

#### `src/Dto/Sendcloud/SendcloudPriceDTO.php` — value object monétaire réutilisable

Correspond au schéma `price` (et `costs-object`) : `{ value: number, currency: string }`.
Réutilisé par les prix des items et des paiements.

```php
<?php

namespace App\Dto\Sendcloud;

/**
 * Value object monétaire couvrant DEUX schémas OpenAPI :
 *  - `price`        → `value` de type `number`
 *  - `costs-object` → `value` de type `[string, 'null']` (pattern décimal `[\d]+(\.[\d]+)?`)
 * Le cast `(float)` normalise volontairement les deux formes (précision suffisante pour
 * l'affichage des montants). Pas de DTO séparé.
 */
class SendcloudPriceDTO
{
    public function __construct(private readonly array $payload)
    {
    }

    public function getValue(): ?float
    {
        return isset($this->payload['value']) ? (float) $this->payload['value'] : null;
    }

    public function getCurrency(): ?string
    {
        return $this->payload['currency'] ?? null;
    }
}
```

#### `src/Dto/Sendcloud/SendcloudAddressDTO.php` — adresse (shipping / billing)

Correspond au schéma `address` (partagé par `shipping-address` et `billing-address`).
Champs : `name, company_name, address_line_1, address_line_2, house_number, postal_code, city,
po_box, state_province_code, country_code, email, phone_number`.

```php
<?php

namespace App\Dto\Sendcloud;

class SendcloudAddressDTO
{
    public function __construct(private readonly array $payload)
    {
    }

    public function getName(): ?string { return $this->payload['name'] ?? null; }
    public function getCompanyName(): ?string { return $this->payload['company_name'] ?? null; }
    public function getAddressLine1(): ?string { return $this->payload['address_line_1'] ?? null; }
    public function getAddressLine2(): ?string { return $this->payload['address_line_2'] ?? null; }
    public function getHouseNumber(): ?string { return $this->payload['house_number'] ?? null; }
    public function getPostalCode(): ?string { return $this->payload['postal_code'] ?? null; }
    public function getCity(): ?string { return $this->payload['city'] ?? null; }
    public function getPoBox(): ?string { return $this->payload['po_box'] ?? null; }
    public function getStateProvinceCode(): ?string { return $this->payload['state_province_code'] ?? null; }
    public function getCountryCode(): ?string { return $this->payload['country_code'] ?? null; }
    public function getEmail(): ?string { return $this->payload['email'] ?? null; }
    public function getPhoneNumber(): ?string { return $this->payload['phone_number'] ?? null; }
}
```

#### `src/Dto/Sendcloud/SendcloudOrderStatusDTO.php` — statut (`{ code, message }`)

Utilisé par `order_details.status` et `payment_details.status`.

```php
<?php

namespace App\Dto\Sendcloud;

class SendcloudOrderStatusDTO
{
    public function __construct(private readonly array $payload)
    {
    }

    public function getCode(): ?string { return $this->payload['code'] ?? null; }
    public function getMessage(): ?string { return $this->payload['message'] ?? null; }
}
```

#### `src/Dto/Sendcloud/SendcloudOrderItemDTO.php` — ligne de commande

Correspond aux items de `order-items`. Champs principaux : `item_id, product_id, variant_id,
image_url, name, description, quantity, sku, hs_code, country_of_origin, unit_price (price),
total_price (price), ean`.

```php
<?php

namespace App\Dto\Sendcloud;

/**
 * Champs volontairement différés (non requis par la demande, à typer si besoin métier) :
 * properties, measurement, delivery_dates, mid_code, material_content, intended_use,
 * manufacturer_product_id, manufacturer_product_id_std, dangerous_goods.
 */
class SendcloudOrderItemDTO
{
    public function __construct(private readonly array $payload)
    {
    }

    public function getItemId(): ?string { return $this->payload['item_id'] ?? null; }
    public function getProductId(): ?string { return $this->payload['product_id'] ?? null; }
    public function getVariantId(): ?string { return $this->payload['variant_id'] ?? null; }
    public function getImageUrl(): ?string { return $this->payload['image_url'] ?? null; }
    public function getName(): ?string { return $this->payload['name'] ?? null; }
    public function getDescription(): ?string { return $this->payload['description'] ?? null; }
    public function getQuantity(): ?int { return isset($this->payload['quantity']) ? (int) $this->payload['quantity'] : null; }
    public function getSku(): ?string { return $this->payload['sku'] ?? null; }
    public function getHsCode(): ?string { return $this->payload['hs_code'] ?? null; }
    public function getCountryOfOrigin(): ?string { return $this->payload['country_of_origin'] ?? null; }
    public function getEan(): ?string { return $this->payload['ean'] ?? null; }

    public function getUnitPrice(): ?SendcloudPriceDTO
    {
        return isset($this->payload['unit_price']) ? new SendcloudPriceDTO($this->payload['unit_price']) : null;
    }

    public function getTotalPrice(): ?SendcloudPriceDTO
    {
        return isset($this->payload['total_price']) ? new SendcloudPriceDTO($this->payload['total_price']) : null;
    }
}
```

#### `src/Dto/Sendcloud/SendcloudOrderDetailsDTO.php` — nœud `order_details`

Champs : `integration.id (int), status (status), order_created_at, order_updated_at,
order_items[] (order-item), notes, tags[]`.

```php
<?php

namespace App\Dto\Sendcloud;

class SendcloudOrderDetailsDTO
{
    public function __construct(private readonly array $payload)
    {
    }

    public function getIntegrationId(): ?int
    {
        return isset($this->payload['integration']['id']) ? (int) $this->payload['integration']['id'] : null;
    }

    public function getStatus(): ?SendcloudOrderStatusDTO
    {
        return isset($this->payload['status']) ? new SendcloudOrderStatusDTO($this->payload['status']) : null;
    }

    public function getOrderCreatedAt(): ?string { return $this->payload['order_created_at'] ?? null; }
    public function getOrderUpdatedAt(): ?string { return $this->payload['order_updated_at'] ?? null; }
    public function getNotes(): ?string { return $this->payload['notes'] ?? null; }

    /** @return string[] */
    public function getTags(): array { return $this->payload['tags'] ?? []; }

    /** @return SendcloudOrderItemDTO[] */
    public function getOrderItems(): array
    {
        return array_map(
            static fn (array $item): SendcloudOrderItemDTO => new SendcloudOrderItemDTO($item),
            $this->payload['order_items'] ?? []
        );
    }
}
```

#### `src/Dto/Sendcloud/SendcloudPaymentDetailsDTO.php` — nœud `payment_details`

Champs : `is_cash_on_delivery (bool), total_price / subtotal_price / estimated_shipping_price /
estimated_tax_price (price), status (status), invoice_date, discount_granted / insurance_costs /
freight_costs / other_costs (costs-object → price)`.

```php
<?php

namespace App\Dto\Sendcloud;

class SendcloudPaymentDetailsDTO
{
    public function __construct(private readonly array $payload)
    {
    }

    public function isCashOnDelivery(): ?bool { return $this->payload['is_cash_on_delivery'] ?? null; }
    public function getInvoiceDate(): ?string { return $this->payload['invoice_date'] ?? null; }

    public function getStatus(): ?SendcloudOrderStatusDTO
    {
        return isset($this->payload['status']) ? new SendcloudOrderStatusDTO($this->payload['status']) : null;
    }

    public function getTotalPrice(): ?SendcloudPriceDTO { return $this->price('total_price'); }
    public function getSubtotalPrice(): ?SendcloudPriceDTO { return $this->price('subtotal_price'); }
    public function getEstimatedShippingPrice(): ?SendcloudPriceDTO { return $this->price('estimated_shipping_price'); }
    public function getEstimatedTaxPrice(): ?SendcloudPriceDTO { return $this->price('estimated_tax_price'); }
    public function getDiscountGranted(): ?SendcloudPriceDTO { return $this->price('discount_granted'); }
    public function getInsuranceCosts(): ?SendcloudPriceDTO { return $this->price('insurance_costs'); }
    public function getFreightCosts(): ?SendcloudPriceDTO { return $this->price('freight_costs'); }
    public function getOtherCosts(): ?SendcloudPriceDTO { return $this->price('other_costs'); }

    private function price(string $key): ?SendcloudPriceDTO
    {
        return isset($this->payload[$key]) && is_array($this->payload[$key])
            ? new SendcloudPriceDTO($this->payload[$key])
            : null;
    }
}
```

#### `src/Dto/Sendcloud/SendcloudCustomerDetailsDTO.php` — nœud `customer_details`

```php
<?php

namespace App\Dto\Sendcloud;

class SendcloudCustomerDetailsDTO
{
    public function __construct(private readonly array $payload)
    {
    }

    public function getName(): ?string { return $this->payload['name'] ?? null; }
    public function getPhoneNumber(): ?string { return $this->payload['phone_number'] ?? null; }
    public function getEmail(): ?string { return $this->payload['email'] ?? null; }
}
```

#### `src/Dto/Sendcloud/SendcloudOrderDTO.php` — DTO racine

Top-level (schéma `order`) : `id, order_id, order_number, created_at, modified_at,
order_details, payment_details, customs_details, customer_details, billing_address,
shipping_address, shipping_details, service_point_details`. Les sous-nœuds sont exposés via
leurs DTOs typés. `customs_details`, `shipping_details` et `service_point_details` sont exposés
en accès brut (`array`) dans une première version — à typer ultérieurement si besoin métier
(indiqué explicitement pour ne pas sur-spécifier des nœuds non requis par la demande).

```php
<?php

namespace App\Dto\Sendcloud;

class SendcloudOrderDTO
{
    public function __construct(private readonly array $payload)
    {
    }

    public function getId(): ?string { return $this->payload['id'] ?? null; }
    public function getOrderId(): ?string { return $this->payload['order_id'] ?? null; }
    public function getOrderNumber(): ?string { return $this->payload['order_number'] ?? null; }
    public function getCreatedAt(): ?string { return $this->payload['created_at'] ?? null; }
    public function getModifiedAt(): ?string { return $this->payload['modified_at'] ?? null; }

    public function getOrderDetails(): ?SendcloudOrderDetailsDTO
    {
        return isset($this->payload['order_details']) ? new SendcloudOrderDetailsDTO($this->payload['order_details']) : null;
    }

    public function getPaymentDetails(): ?SendcloudPaymentDetailsDTO
    {
        return isset($this->payload['payment_details']) ? new SendcloudPaymentDetailsDTO($this->payload['payment_details']) : null;
    }

    public function getCustomerDetails(): ?SendcloudCustomerDetailsDTO
    {
        return isset($this->payload['customer_details']) ? new SendcloudCustomerDetailsDTO($this->payload['customer_details']) : null;
    }

    public function getShippingAddress(): ?SendcloudAddressDTO
    {
        return isset($this->payload['shipping_address']) ? new SendcloudAddressDTO($this->payload['shipping_address']) : null;
    }

    public function getBillingAddress(): ?SendcloudAddressDTO
    {
        return isset($this->payload['billing_address']) ? new SendcloudAddressDTO($this->payload['billing_address']) : null;
    }

    /** Raw nodes not yet typed (customs / shipping / service point). */
    public function getCustomsDetails(): ?array { return $this->payload['customs_details'] ?? null; }
    public function getShippingDetails(): ?array { return $this->payload['shipping_details'] ?? null; }
    public function getServicePointDetails(): ?array { return $this->payload['service_point_details'] ?? null; }

    public function getPayload(): array { return $this->payload; }
}
```

#### `src/Service/Sendcloud/SendcloudApiClient.php` — le connecteur

Client Guzzle injecté par bind `$sendcloudApiClient`, credentials lus en base et mis en cache par
`SendcloudConfigurationService::getConfiguration()`. Méthode `getOrders(?string $orderId = null): array` qui :
- vérifie que la config est renseignée (`isConfigured()`), sinon lève `ExternalSendcloudApiException` ;
- appelle `GET /orders` en Basic Auth (`'auth' => [$publicKey, $secretKey]`), avec le filtre
  `order_id` ajouté à `query` uniquement s'il est fourni ;
- vérifie le status (pattern eBay : `http_errors => false` + contrôle manuel), lève l'exception dédiée sinon ;
- agrège les pages en suivant le header `Link` (`rel="next"`) jusqu'à épuisement ;
- retourne un tableau de `SendcloudOrderDTO`.

```php
<?php

namespace App\Service\Sendcloud;

use App\Dto\Sendcloud\SendcloudOrderDTO;
use App\Exceptions\ExternalSendcloudApiException;
use GuzzleHttp\Client;
use GuzzleHttp\Exception\GuzzleException;
use Psr\Http\Message\ResponseInterface;

class SendcloudApiClient
{
    private const ENDPOINT_ORDERS = '/orders';
    private const DEFAULT_PAGE_SIZE = 100; // OpenAPI default (min 1, max 200)

    public function __construct(
        private readonly Client $sendcloudApiClient,
        private readonly SendcloudConfigurationService $configurationService,
    ) {
    }

    /**
     * Retrieve the list of Sendcloud orders, optionally filtered by external order id.
     * Follows the RFC 5988 `Link` header to aggregate every page.
     *
     * @return SendcloudOrderDTO[]
     *
     * @throws ExternalSendcloudApiException
     */
    public function getOrders(?string $orderId = null): array
    {
        $configuration = $this->configurationService->getConfiguration();
        if (!$configuration->isConfigured()) {
            throw new ExternalSendcloudApiException('Sendcloud API credentials are not configured.');
        }

        $auth = [$configuration->getPublicKey(), $configuration->getSecretKey()];

        $query = ['page_size' => self::DEFAULT_PAGE_SIZE];
        if (null !== $orderId && '' !== $orderId) {
            $query['order_id'] = $orderId;
        }

        $orders = [];
        $url = self::ENDPOINT_ORDERS;
        $options = ['auth' => $auth, 'query' => $query, 'http_errors' => false];

        while (null !== $url) {
            $response = $this->request($url, $options);
            $decoded = json_decode($response->getBody()->getContents(), true) ?? [];

            foreach ($decoded['data'] ?? [] as $order) {
                $orders[] = new SendcloudOrderDTO($order);
            }

            // The `next` link already carries the cursor/query params → drop `query` for it.
            $url = $this->extractNextLink($response);
            $options = ['auth' => $auth, 'http_errors' => false];
        }

        return $orders;
    }

    private function request(string $url, array $options): ResponseInterface
    {
        try {
            $response = $this->sendcloudApiClient->get($url, $options);
        } catch (GuzzleException $exception) {
            throw new ExternalSendcloudApiException($exception->getMessage(), (int) $exception->getCode(), $exception);
        }

        if ($response->getStatusCode() !== 200) {
            throw new ExternalSendcloudApiException($response->getBody()->getContents());
        }

        return $response;
    }

    /**
     * Parse the RFC 5988 `Link` header and return the absolute URL flagged `rel="next"`, or null.
     */
    private function extractNextLink(ResponseInterface $response): ?string
    {
        foreach ($response->getHeader('Link') as $header) {
            foreach (explode(',', $header) as $part) {
                if (preg_match('/<([^>]+)>\s*;\s*rel="?next"?/', trim($part), $matches) === 1) {
                    return $matches[1];
                }
            }
        }

        return null;
    }
}
```

> Note pagination : le lien `next` renvoyé par Sendcloud est une URL absolue contenant déjà le
> `cursor` (et donc le filtre `order_id` initial). Guzzle accepte une URL absolue passée à `get()`
> même quand le client a un `base_url` : elle remplace le base_url. On retire donc `query` des
> options pour les pages suivantes afin de ne pas dupliquer les paramètres.

### Nouveaux — tests (repo `src-eurocommemo`)

#### `tests/Service/Sendcloud/SendcloudApiClientTest.php` — test unitaire du connecteur

Aucun test n'existe encore dans le repo (`tests/` ne contient que `bootstrap.php` ; le dossier
`tests/Service/Sendcloud/` existe déjà mais est vide) et `MockHttpClient`/Guzzle `MockHandler` ne
sont utilisés nulle part — ce test **établit** la convention. Comme le client est Guzzle, mocker via `GuzzleHttp\Handler\MockHandler` +
`HandlerStack`, et un `SendcloudConfigurationService` stubbé retournant une config configurée.

Scénarios à couvrir :
- `getOrders()` sans filtre → hydrate correctement les DTOs depuis `data[]`.
- `getOrders('555413')` → ajoute bien `order_id` dans la query de la 1re requête.
- Réponse paginée (2 pages via header `Link` `rel="next"`) → agrège les deux pages.
- Config non renseignée → lève `ExternalSendcloudApiException`.
- Status ≠ 200 → lève `ExternalSendcloudApiException`.

```php
<?php

namespace App\Tests\Service\Sendcloud;

use App\Service\Sendcloud\SendcloudApiClient;
use App\Service\Sendcloud\SendcloudConfigurationService;
use App\Entity\Sendcloud\SendcloudConfiguration;
use GuzzleHttp\Client;
use GuzzleHttp\Handler\MockHandler;
use GuzzleHttp\HandlerStack;
use GuzzleHttp\Psr7\Response;
use PHPUnit\Framework\TestCase;

class SendcloudApiClientTest extends TestCase
{
    public function testGetOrdersWithoutFilter(): void
    {
        // MockHandler → one page with data[]. Assert DTOs hydrated and no order_id in the query.
    }

    public function testGetOrdersWithOrderIdFilter(): void
    {
        // getOrders('555413') → assert the first request query carries order_id=555413.
    }

    public function testGetOrdersAggregatesPaginatedResults(): void
    {
        // MockHandler with a first page carrying a Link: <...>; rel="next" header,
        // then a second page with no Link header. Assert 2 DTOs returned.
    }

    public function testGetOrdersThrowsWhenNotConfigured(): void
    {
        // Stub SendcloudConfigurationService->getConfiguration() to return a blank
        // SendcloudConfiguration (isConfigured() === false). Expect ExternalSendcloudApiException.
    }

    public function testGetOrdersThrowsOnNon200Status(): void
    {
        // MockHandler returns a 400/404 JSON:API error. Expect ExternalSendcloudApiException.
    }

    private function buildClient(MockHandler $mock, SendcloudConfiguration $config): SendcloudApiClient
    {
        $guzzle = new Client(['handler' => HandlerStack::create($mock)]);
        $service = $this->createMock(SendcloudConfigurationService::class);
        $service->method('getConfiguration')->willReturn($config);

        return new SendcloudApiClient($guzzle, $service);
    }
}
```

### Modifiés — repo `src-eurocommemo`

- `config/packages/eight_points_guzzle.yaml` — ajout du client `sendcloud_api` (cf. supra).
- `config/services.yaml` — ajout du bind `$sendcloudApiClient` (cf. supra).

## Étapes

1. **Client Guzzle & bind** — Ajouter le client `sendcloud_api` dans
   `config/packages/eight_points_guzzle.yaml` et le bind `$sendcloudApiClient` dans
   `config/services.yaml`. Vérifier avec `bin/console debug:container --parameters | grep -i sendcloud`
   et `bin/console lint:yaml config`.
2. **Exception** — Créer `src/Exceptions/ExternalSendcloudApiException.php` (mirror de `ExternalEbayApiException`).
3. **DTOs value objects** — Créer `SendcloudPriceDTO`, `SendcloudOrderStatusDTO`, `SendcloudAddressDTO`,
   `SendcloudCustomerDetailsDTO` sous `src/Dto/Sendcloud/`.
4. **DTOs composés** — Créer `SendcloudOrderItemDTO`, `SendcloudOrderDetailsDTO`,
   `SendcloudPaymentDetailsDTO`, puis le DTO racine `SendcloudOrderDTO`.
5. **Connecteur** — Créer `src/Service/Sendcloud/SendcloudApiClient.php` avec
   `getOrders(?string $orderId = null): array` (Basic Auth depuis la config DB, filtre `order_id`
   optionnel, suivi du header `Link`, mapping vers `SendcloudOrderDTO[]`).
6. **Tests** — Créer `tests/Service/Sendcloud/SendcloudApiClientTest.php` (Guzzle `MockHandler`)
   couvrant les 5 scénarios listés.
7. **Câblage & vérif statique** — `bin/console cache:clear`, `bin/console debug:autowiring SendcloudApiClient`,
   `php -l` sur chaque fichier créé.

## Vérification

Toutes les commandes sont exécutées **via `scripts/repo_exec.py`** (le repo est en `exec.mode: compose`,
service `php-fpm-per83`), conformément au CLAUDE.md — jamais d'appel direct.

- **Lint / syntaxe** :
  `python3 scripts/repo_exec.py src-eurocommemo -- php -l src/Service/Sendcloud/SendcloudApiClient.php`
  (et sur chaque DTO), `... -- bin/console lint:yaml config`.
- **Container** : `python3 scripts/repo_exec.py src-eurocommemo -- bin/console lint:container` —
  confirme que `$sendcloudApiClient` est résolu et l'autowiring de `SendcloudApiClient` OK.
- **Autowiring** : `... -- bin/console debug:autowiring SendcloudApiClient`.
- **Tests unitaires** :
  `python3 scripts/repo_exec.py src-eurocommemo -- vendor/bin/phpunit tests/Service/Sendcloud/SendcloudApiClientTest.php`
  → les 5 scénarios passent (mock Guzzle, aucune requête réseau réelle).
- **Test manuel end-to-end** (nécessite des credentials Sendcloud valides en base, saisis via le
  back-office existant) — via une commande console jetable ou `bin/console` custom :
  - `getOrders()` → renvoie une liste de `SendcloudOrderDTO` non vide ;
  - `getOrders('<order_id connu>')` → renvoie l'ordre ciblé (filtre appliqué) ;
  - config vidée → `ExternalSendcloudApiException` levée.
- **Point d'attention** : les credentials de `.env.local` sont des clés de dev ; le connecteur lit
  la config **en base** (`SendcloudConfiguration`), pas l'env. S'assurer qu'une config est bien
  persistée (le back-office Sendcloud crée une ligne vide au premier accès via
  `SendcloudConfigurationService::getConfiguration()`).
- **Graphify** : après implémentation, rafraîchir le graphe du repo
  (`graphify extract .../src-eurocommemo --out docs/src-eurocommemo ...` puis `cluster-only`).
