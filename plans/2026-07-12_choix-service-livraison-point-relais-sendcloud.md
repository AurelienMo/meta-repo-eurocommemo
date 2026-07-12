# Plan — Choix du service de livraison et du point relais Sendcloud (commandes en attente d'expédition)

## Contexte

Aujourd'hui l'intégration Sendcloud du repo `src-eurocommemo` est **en lecture seule** : les commandes eBay
sont ingérées nativement par Sendcloud (via sa propre intégration eBay), et l'application se contente
d'appeler `GET /api/v3/orders` pour retrouver et stocker l'`sendcloudOrderId` sur la commande locale
(cf. `SendcloudApiClient::getOrders()` + `SendcloudOrderLinker::matchSendcloudId()`). Aucune écriture vers
Sendcloud, aucun listing de méthodes de livraison, aucune gestion de point relais n'existe.

Objectif : depuis l'admin, pour une commande **associée à Sendcloud**, permettre à l'opérateur de
**choisir la méthode de livraison** (shipping option Sendcloud), et — quand la méthode choisie est une
livraison en point relais (Shop2Shop, Mondial Relay, etc.) — de **choisir le point relais**. La sélection
est **poussée vers Sendcloud** via `PATCH /api/v3/orders/{id}`, et mémorisée localement pour affichage.

Contrainte métier : action possible **uniquement** pour les commandes au statut « En attente d'expédition »
ou « Prévente ». Ces deux statuts correspondent tous deux à
`statePayment == CONST_STATE_PAYMENT_VALID (1)` **et** `dateExpedition IS NULL` **et**
(`delivery` non nul **ou** `isEbay`) — la seule différence étant la présence d'un produit en prévente
(cf. `templates/admin/order/order_state.html.twig`). Comme l'association Sendcloud n'existe que pour les
commandes eBay, la condition effective d'affichage est :

```
isEbay == true
&& statePayment == CONST_STATE_PAYMENT_VALID
&& dateExpedition IS NULL
&& sendcloudOrderId not in (null, '0')
```

Décisions produit validées avec le demandeur :
- **Emplacement UI** : cellule « Expédition » de la liste (`order_delivery_action.html.twig`), sur la vue
  « commandes en attente de livraison » (`delivery=1`), qui héberge déjà le `<select>` transporteur eBay.
- **Sélection du point relais** : dropdown custom alimenté par un endpoint interne relayant l'API Service
  Points Sendcloud (pas de widget JS externe).
- **Déclencheur du picker point relais** : toute méthode de livraison qui requiert un point relais
  (`requirements.is_service_point_required == true` dans la réponse shipping-options) — générique.

### Contrat API Sendcloud v3 (source : `specs/sendcloud-v3/*/openapi.yaml`, vendored dans le meta-repo)

Les trois endpoints sont sur **le même host** que l'existant (`SENDCLOUD_BASE_URL` = `https://panel.sendcloud.sc`,
préfixe `/api/v3`), donc réutilisables via le client Guzzle `sendcloud_api` déjà câblé — aucun appel cross-host.

1. **Lister les méthodes de livraison** — `POST /api/v3/shipping-options`
   (`specs/sendcloud-v3/shipping-options/openapi.yaml:870`). Body (schéma `shipping-option-filter`) :
   ```json
   {
     "from_address": { "country_code": "FR", "postal_code": "…", "city": "…" },
     "to_address":   { "country_code": "…",  "postal_code": "…", "city": "…" },
     "parcels": [ { "weight": { "value": "2.000", "unit": "kg" } } ],
     "calculate_quotes": true
   }
   ```
   Réponse `data[]` de `shipping-option`, champs utiles :
   `code` (ex. `colissimo:standard`), `name`, `carrier: {code, name}`, `product: {code, name}`,
   `functionalities.last_mile` (`home_delivery` | `service_point` | …),
   `requirements.is_service_point_required` (bool — **déclencheur du picker**),
   `quotes[].price.total: {value, currency}`.

2. **Lister les points relais** — `GET /api/v3/service-points`
   (`specs/sendcloud-v3/service-points/openapi.yaml:20`). Query :
   `country_code` (requis, ISO-2), `carrier_code` (tableau, ex. `carrier_code=colissimo`),
   point de référence via `address_postal_code` + `address_city` (structuré, sans house_number = autorisé),
   `limit`. Réponse : `data.results[]` de `ServicePoint`, champs utiles :
   `id` (int, id Sendcloud), `carrier_service_point_id`, `name`, `carrier: {code, name}`,
   `address: {street, house_number, postal_code, city, country_code}`,
   `position: {latitude, longitude}`, `distance`.

3. **Pousser la sélection** — `PATCH /api/v3/orders/{id}`
   (`specs/sendcloud-v3/orders/openapi.yaml:1338`, schéma `order-partial-update`, mise à jour partielle).
   `{id}` = id interne Sendcloud (= `Order::sendcloudOrderId`). Body :
   ```json
   {
     "shipping_details": {
       "ship_with": {
         "type": "shipping_option_code",
         "properties": { "shipping_option_code": "colissimo:standard" }
       }
     },
     "service_point_details": { "id": "10875349" }
   }
   ```
   `shipping_details.ship_with` (schéma `ship-with`, `specs/…/orders/openapi.yaml:659`) est toujours envoyé.
   `service_point_details` est **au niveau racine** de l'ordre (sibling de `shipping_details`,
   `specs/…/orders/openapi.yaml:2402`), envoyé **uniquement** pour une livraison en point relais ; on utilise
   la clé `id` (id Sendcloud du point relais) — l'alternative `carrier_service_point_id` existe aussi.

Tous les chemins ci-dessous sont relatifs au repo `src-eurocommemo`
(`/Users/aurelienmorvan/OrbStack/docker/volumes/src-eurocommemo`).

## Fichiers concernés

### Nouveaux

#### `src/Dto/Sendcloud/SendcloudShippingOptionDTO.php`
Wrapper lecture seule d'une shipping option renvoyée par `POST /api/v3/shipping-options`, dans le style des
DTO existants (`__construct(private readonly array $payload)`).

```php
<?php

namespace App\Dto\Sendcloud;

class SendcloudShippingOptionDTO
{
    public function __construct(private readonly array $payload)
    {
    }

    public function getCode(): ?string
    {
        return $this->payload['code'] ?? null;
    }

    public function getName(): ?string
    {
        return $this->payload['name'] ?? null;
    }

    /** Code transporteur, utilisé pour filtrer les points relais (ex. "colissimo", "mondial_relay"). */
    public function getCarrierCode(): ?string
    {
        return $this->payload['carrier']['code'] ?? null;
    }

    public function getCarrierName(): ?string
    {
        return $this->payload['carrier']['name'] ?? null;
    }

    /** Libellé lisible pour le <select>. */
    public function getLabel(): string
    {
        return $this->getName()
            ?? trim(sprintf('%s %s', (string) $this->getCarrierName(), (string) $this->getCode()));
    }

    /** True si l'option exige un point relais (Shop2Shop, Mondial Relay, casier…). */
    public function requiresServicePoint(): bool
    {
        return (bool) ($this->payload['requirements']['is_service_point_required'] ?? false);
    }

    public function getPayload(): array
    {
        return $this->payload;
    }
}
```

#### `src/Dto/Sendcloud/SendcloudServicePointDTO.php`
Wrapper lecture seule d'un point relais renvoyé par `GET /api/v3/service-points` (`data.results[]`).

```php
<?php

namespace App\Dto\Sendcloud;

class SendcloudServicePointDTO
{
    public function __construct(private readonly array $payload)
    {
    }

    /** Id Sendcloud (celui à renvoyer dans service_point_details.id du PATCH). */
    public function getId(): ?int
    {
        return $this->payload['id'] ?? null;
    }

    public function getCarrierServicePointId(): ?string
    {
        return $this->payload['carrier_service_point_id'] ?? null;
    }

    public function getName(): ?string
    {
        return $this->payload['name'] ?? null;
    }

    public function getStreet(): ?string
    {
        return $this->payload['address']['street'] ?? null;
    }

    public function getHouseNumber(): ?string
    {
        return $this->payload['address']['house_number'] ?? null;
    }

    public function getPostalCode(): ?string
    {
        return $this->payload['address']['postal_code'] ?? null;
    }

    public function getCity(): ?string
    {
        return $this->payload['address']['city'] ?? null;
    }

    public function getDistance(): ?int
    {
        return $this->payload['distance'] ?? null;
    }

    /** Libellé lisible : "NAME — 12 Rue X, 75001 Paris". */
    public function getLabel(): string
    {
        $address = trim(sprintf(
            '%s %s, %s %s',
            (string) $this->getHouseNumber(),
            (string) $this->getStreet(),
            (string) $this->getPostalCode(),
            (string) $this->getCity()
        ));

        return trim(sprintf('%s — %s', (string) $this->getName(), $address), ' —');
    }
}
```

#### `src/Service/Sendcloud/SendcloudOrderShippingService.php`
Service applicatif orchestrant la mise à jour Sendcloud d'une commande + la persistance locale. Ne flush
pas (le contrôleur flush), met à jour les champs entité.

```php
<?php

namespace App\Service\Sendcloud;

use App\Entity\Order;
use App\Exceptions\ExternalSendcloudApiException;

class SendcloudOrderShippingService
{
    public function __construct(
        private readonly SendcloudApiClient $apiClient,
    ) {
    }

    /**
     * Pousse la méthode de livraison (+ point relais éventuel) vers la commande Sendcloud,
     * puis met à jour les champs locaux de l'Order (l'appelant flush).
     *
     * @throws ExternalSendcloudApiException
     * @throws \InvalidArgumentException si la commande n'a pas d'association Sendcloud exploitable
     */
    public function applyShippingSelection(
        Order $order,
        string $shippingOptionCode,
        ?string $servicePointId,
        ?string $servicePointName
    ): void {
        $sendcloudOrderId = $order->getSendcloudOrderId();
        if (null === $sendcloudOrderId || '0' === $sendcloudOrderId) {
            throw new \InvalidArgumentException('Order has no Sendcloud association.');
        }

        $this->apiClient->updateOrder($sendcloudOrderId, $shippingOptionCode, $servicePointId);

        $order->setSendcloudShippingOptionCode($shippingOptionCode);
        $order->setSendcloudServicePointId($servicePointId);
        $order->setSendcloudServicePointName($servicePointName);
    }
}
```

#### `migrations/VersionYYYYMMDDHHMMSS.php`
Migration Doctrine ajoutant trois colonnes à `orders`. `up()`/`down()` complets (respecter le format des
migrations existantes du repo — vendor MySQL) :

```php
public function up(Schema $schema): void
{
    $this->addSql('ALTER TABLE orders
        ADD sendcloud_shipping_option_code VARCHAR(255) DEFAULT NULL,
        ADD sendcloud_service_point_id VARCHAR(255) DEFAULT NULL,
        ADD sendcloud_service_point_name VARCHAR(255) DEFAULT NULL');
}

public function down(Schema $schema): void
{
    $this->addSql('ALTER TABLE orders
        DROP sendcloud_shipping_option_code,
        DROP sendcloud_service_point_id,
        DROP sendcloud_service_point_name');
}
```

### Modifiés

#### `src/Entity/Order.php`
Ajouter trois champs (près du champ `sendcloudOrderId`, lignes 106-107) + getters/setters dans le style
existant (`get*(): ?string` / `set*(?string): Order`).

```php
#[ORM\Column(type: 'string', length: 255, nullable: true)]
private ?string $sendcloudShippingOptionCode = null;

#[ORM\Column(type: 'string', length: 255, nullable: true)]
private ?string $sendcloudServicePointId = null;

#[ORM\Column(type: 'string', length: 255, nullable: true)]
private ?string $sendcloudServicePointName = null;
```

```php
public function getSendcloudShippingOptionCode(): ?string { return $this->sendcloudShippingOptionCode; }
public function setSendcloudShippingOptionCode(?string $v): Order { $this->sendcloudShippingOptionCode = $v; return $this; }

public function getSendcloudServicePointId(): ?string { return $this->sendcloudServicePointId; }
public function setSendcloudServicePointId(?string $v): Order { $this->sendcloudServicePointId = $v; return $this; }

public function getSendcloudServicePointName(): ?string { return $this->sendcloudServicePointName; }
public function setSendcloudServicePointName(?string $v): Order { $this->sendcloudServicePointName = $v; return $this; }
```

Ajouter aussi un helper de poids total en kg — le body shipping-options attend un poids par colis en kg ;
`OrderProducts::getQuantity(): ?int` (`src/Entity/OrderProducts.php:59`) et `Product::getWeight(): ?int`
(`src/Entity/Product.php:230`, poids en **grammes**) existent déjà :

```php
/** Poids total de la commande en kilogrammes (weight Product en grammes). */
public function getTotalWeightKg(): float
{
    $grams = 0;
    foreach ($this->orderProducts as $orderProduct) {
        $grams += (int) $orderProduct->getQuantity() * (int) $orderProduct->getProduct()->getWeight();
    }

    return $grams / 1000;
}
```

#### `src/Service/Sendcloud/SendcloudApiClient.php`
Généraliser `request()` pour accepter un verbe HTTP + un body JSON, et ajouter trois méthodes publiques.
`request()` actuel (lignes 61-85) appelle `->get()` en dur et exige un statut `=== 200` ; le refactoriser en
`->request($method, …)` avec une plage 2xx (le PATCH renvoie 200, le POST shipping-options 200, mais rester
tolérant). Ajouter les `use` : `App\Dto\Sendcloud\SendcloudShippingOptionDTO;` et
`App\Dto\Sendcloud\SendcloudServicePointDTO;`.

Nouvelles constantes :
```php
private const ENDPOINT_SHIPPING_OPTIONS = '/shipping-options';
private const ENDPOINT_SERVICE_POINTS = '/service-points';
```

`request()` refactoré (signature élargie, comportement identique pour l'appel existant) :
```php
/**
 * @throws ExternalSendcloudApiException
 */
private function request(string $method, string $url, array $options): ResponseInterface
{
    $configuration = $this->configurationService->getConfiguration();
    if (!$configuration->isConfigured()) {
        throw new ExternalSendcloudApiException('Sendcloud API credentials are not configured.');
    }
    $headers = [
        'Authorization' => 'Basic '.base64_encode(
            $configuration->getPublicKey().':'.$configuration->getSecretKey()
        ),
        'Content-Type' => 'application/json',
    ];

    try {
        $response = $this->sendcloudApiClient->request($method, $url, array_merge($options, ['headers' => $headers]));
    } catch (GuzzleException $exception) {
        throw new ExternalSendcloudApiException($exception->getMessage(), (int) $exception->getCode(), $exception);
    }

    $status = $response->getStatusCode();
    if ($status < 200 || $status >= 300) {
        throw new ExternalSendcloudApiException($response->getBody()->getContents());
    }

    return $response;
}
```
> Adapter l'appel existant dans `getOrders()` (ligne 43) : `$this->request('GET', $url, $options)`.

Nouvelles méthodes publiques :
```php
/**
 * @return SendcloudShippingOptionDTO[]
 * @throws ExternalSendcloudApiException
 */
public function getShippingOptions(
    string $fromCountryCode,
    ?string $fromPostalCode,
    string $toCountryCode,
    ?string $toPostalCode,
    ?string $toCity,
    float $weightKg
): array {
    $body = [
        'from_address' => array_filter([
            'country_code' => $fromCountryCode,
            'postal_code'  => $fromPostalCode,
        ]),
        'to_address' => array_filter([
            'country_code' => $toCountryCode,
            'postal_code'  => $toPostalCode,
            'city'         => $toCity,
        ]),
        'parcels' => [[
            'weight' => ['value' => number_format(max($weightKg, 0.001), 3, '.', ''), 'unit' => 'kg'],
        ]],
        'calculate_quotes' => true,
    ];

    $response = $this->request('POST', self::PREFIX_URL.self::ENDPOINT_SHIPPING_OPTIONS, [
        'json' => $body,
        'http_errors' => false,
    ]);
    $decoded = json_decode($response->getBody()->getContents(), true) ?? [];

    return array_map(
        static fn (array $o) => new SendcloudShippingOptionDTO($o),
        $decoded['data'] ?? []
    );
}

/**
 * @return SendcloudServicePointDTO[]
 * @throws ExternalSendcloudApiException
 */
public function getServicePoints(
    string $countryCode,
    string $carrierCode,
    ?string $postalCode = null,
    ?string $city = null
): array {
    $query = ['country_code' => $countryCode, 'carrier_code' => $carrierCode, 'limit' => 50];
    if (null !== $postalCode) { $query['address_postal_code'] = $postalCode; }
    if (null !== $city)       { $query['address_city'] = $city; }

    $response = $this->request('GET', self::PREFIX_URL.self::ENDPOINT_SERVICE_POINTS, [
        'query' => $query,
        'http_errors' => false,
    ]);
    $decoded = json_decode($response->getBody()->getContents(), true) ?? [];

    return array_map(
        static fn (array $sp) => new SendcloudServicePointDTO($sp),
        $decoded['data']['results'] ?? []
    );
}

/**
 * PATCH partiel de la commande Sendcloud : méthode de livraison + point relais éventuel.
 *
 * @throws ExternalSendcloudApiException
 */
public function updateOrder(
    string $sendcloudOrderId,
    string $shippingOptionCode,
    ?string $servicePointId = null
): void {
    $body = [
        'shipping_details' => [
            'ship_with' => [
                'type' => 'shipping_option_code',
                'properties' => ['shipping_option_code' => $shippingOptionCode],
            ],
        ],
    ];
    if (null !== $servicePointId) {
        $body['service_point_details'] = ['id' => $servicePointId];
    }

    $this->request('PATCH', self::PREFIX_URL.self::ENDPOINT_ORDERS.'/'.$sendcloudOrderId, [
        'json' => $body,
        'http_errors' => false,
    ]);
}
```

#### `src/Controller/Admin/OrderCrudController.php`
Injecter `SendcloudApiClient` + `SendcloudOrderShippingService` dans le constructeur (lignes 50-59), et
ajouter trois routes (style des `#[Route]` existants `app_admin_order_delivery_validate`, lignes 378-421).
Le pays expéditeur est FR (métropole) — cf. `X-EBAY-API-SITEID: 71` (eBay France) dans la config Guzzle ;
constante à confirmer avec le demandeur si multi-origine.

```php
use App\Service\Sendcloud\SendcloudApiClient;
use App\Service\Sendcloud\SendcloudOrderShippingService;
// constructeur : ajouter
private readonly SendcloudApiClient $sendcloudApiClient,
private readonly SendcloudOrderShippingService $sendcloudShippingService,
```

```php
private const SENDCLOUD_FROM_COUNTRY = 'FR';

#[Route('/admin/order/{id}/sendcloud/shipping-options', name: 'app_admin_order_sendcloud_shipping_options')]
public function sendcloudShippingOptions(Order $order): JsonResponse
{
    $address = $order->getDeliveryAddress();
    if (!$order->getIsEbay() || null === $address) {
        return new JsonResponse([]);
    }

    try {
        $options = $this->sendcloudApiClient->getShippingOptions(
            self::SENDCLOUD_FROM_COUNTRY,
            null,
            (string) $address->getCountryCode(),
            $address->getPostalCode(),
            $address->getCity(),
            $order->getTotalWeightKg()
        );
    } catch (ExternalSendcloudApiException $e) {
        return new JsonResponse(['error' => $e->getMessage()]);
    }

    return new JsonResponse(array_map(static fn ($o) => [
        'code' => $o->getCode(),
        'label' => $o->getLabel(),
        'carrierCode' => $o->getCarrierCode(),
        'requiresServicePoint' => $o->requiresServicePoint(),
    ], $options));
}

#[Route('/admin/order/{id}/sendcloud/service-points', name: 'app_admin_order_sendcloud_service_points')]
public function sendcloudServicePoints(Order $order, Request $request): JsonResponse
{
    $address = $order->getDeliveryAddress();
    $carrier = (string) $request->query->get('carrier');
    if (null === $address || '' === $carrier) {
        return new JsonResponse([]);
    }

    try {
        $points = $this->sendcloudApiClient->getServicePoints(
            (string) $address->getCountryCode(),
            $carrier,
            $address->getPostalCode(),
            $address->getCity()
        );
    } catch (ExternalSendcloudApiException $e) {
        return new JsonResponse(['error' => $e->getMessage()]);
    }

    return new JsonResponse(array_map(static fn ($sp) => [
        'id' => $sp->getId(),
        'label' => $sp->getLabel(),
    ], $points));
}

#[Route('/admin/order/{id}/sendcloud/apply-shipping', name: 'app_admin_order_sendcloud_apply_shipping', methods: ['POST'])]
public function sendcloudApplyShipping(Order $order, Request $request): JsonResponse
{
    if (!$this->isCsrfTokenValid('sendcloud_shipping_'.$order->getId(), (string) $request->request->get('_csrf_token'))) {
        return new JsonResponse(['state' => 0, 'message' => 'Token CSRF invalide.']);
    }
    if (!$order->getIsEbay()
        || $order->getStatePayment() !== GlobalConstants::CONST_STATE_PAYMENT_VALID
        || null !== $order->getDateExpedition()
        || in_array($order->getSendcloudOrderId(), [null, '0'], true)) {
        return new JsonResponse(['state' => 0, 'message' => "Action indisponible pour cette commande."]);
    }

    $code = (string) $request->request->get('shippingOptionCode');
    if ('' === $code) {
        return new JsonResponse(['state' => 0, 'message' => 'Méthode de livraison requise.']);
    }

    try {
        $this->sendcloudShippingService->applyShippingSelection(
            $order,
            $code,
            $request->request->get('servicePointId') ?: null,
            $request->request->get('servicePointName') ?: null
        );
        $this->em->flush();
    } catch (ExternalSendcloudApiException $e) {
        return new JsonResponse(['state' => 0, 'message' => 'Erreur API Sendcloud : '.$e->getMessage()]);
    } catch (\InvalidArgumentException $e) {
        return new JsonResponse(['state' => 0, 'message' => $e->getMessage()]);
    }

    return new JsonResponse([
        'state' => 1,
        'shippingLabel' => $code,
        'servicePointName' => $order->getSendcloudServicePointName(),
    ]);
}
```
> `Request` et `ExternalSendcloudApiException` sont déjà importés dans le fichier (lignes 5 et 38). Les deux
> endpoints de lecture restent sans CSRF (cohérent avec `_ebay_shipping_providers` /
> `app_admin_order_delivery_validate`) ; seul l'endpoint d'écriture `apply-shipping` porte le token CSRF
> (pattern `sendcloud_shipping_{id}`, aligné sur `syncSendcloud`).

#### `templates/admin/order/order_delivery_action.html.twig`
Dans la branche `elseif (entity.instance.delivery is not null or entity.instance.isEbay) and
entity.instance.dateExpedition is null` (lignes 9-17), sous le `<select>` transporteur eBay (lignes 12-14),
ajouter le bloc Sendcloud, affiché seulement si l'association existe :

```twig
{% set sendcloudId = entity.instance.sendcloudOrderId %}
{% if entity.instance.isEbay and sendcloudId is not null and sendcloudId != '0' %}
    <div class="sendcloud-shipping-block mt-2" data-order-id="{{ entity.instance.id }}">
        <select id="sendcloud-shipping-{{ entity.instance.id }}"
                class="form-select form-select-sm mb-1 small select-sendcloud-shipping"
                style="max-width: 240px; font-size: 12px"
                data-url="{{ path('app_admin_order_sendcloud_shipping_options', {id: entity.instance.id}) }}"
                data-current="{{ entity.instance.sendcloudShippingOptionCode }}">
        </select>

        <select id="sendcloud-servicepoint-{{ entity.instance.id }}"
                class="form-select form-select-sm mb-1 small select-sendcloud-servicepoint d-none"
                style="max-width: 240px; font-size: 12px"
                data-url="{{ path('app_admin_order_sendcloud_service_points', {id: entity.instance.id}) }}"
                data-current-id="{{ entity.instance.sendcloudServicePointId }}">
        </select>

        <button type="button"
                class="btn btn-outline-primary btn-sm btn-sendcloud-apply"
                data-path="{{ path('app_admin_order_sendcloud_apply_shipping', {id: entity.instance.id}) }}"
                data-order-id="{{ entity.instance.id }}"
                data-csrf="{{ csrf_token('sendcloud_shipping_' ~ entity.instance.id) }}">
            <small>Enregistrer sur Sendcloud</small>
        </button>

        {% if entity.instance.sendcloudServicePointName %}
            <div class="small text-muted mt-1">
                Point relais : <b>{{ entity.instance.sendcloudServicePointName }}</b>
            </div>
        {% endif %}
    </div>
{% endif %}
```

#### `assets/back/js/back.js`
Ajouter un bloc dédié Sendcloud, calqué sur le populator `.select-providers` (lignes 177-196) et le handler
`.btn-order-delivery-validate` (lignes 75-107). Comportement : charger les méthodes → si l'option requiert un
point relais, charger/afficher les points relais du transporteur → enregistrer vers Sendcloud.

```js
// --- Sendcloud shipping option + service point ---
document.querySelectorAll('.sendcloud-shipping-block').forEach(function (block) {
    const shippingSelect = block.querySelector('.select-sendcloud-shipping');
    const spSelect = block.querySelector('.select-sendcloud-servicepoint');

    // 1. Charger les méthodes de livraison
    fetch(shippingSelect.dataset.url)
        .then(r => r.json())
        .then(options => {
            if (!Array.isArray(options)) { return; }
            const current = shippingSelect.dataset.current;
            shippingSelect.innerHTML = '<option value="">— Choisir une méthode —</option>' +
                options.map(o =>
                    `<option value="${o.code}" data-requires-sp="${o.requiresServicePoint ? 1 : 0}" ` +
                    `data-carrier="${o.carrierCode || ''}" ${o.code === current ? 'selected' : ''}>${o.label}</option>`
                ).join('');
            maybeLoadServicePoints();
        });

    // 2. Afficher/charger les points relais si l'option l'exige
    function maybeLoadServicePoints() {
        const opt = shippingSelect.selectedOptions[0];
        if (!opt || opt.dataset.requiresSp !== '1') {
            spSelect.classList.add('d-none'); spSelect.innerHTML = ''; return;
        }
        const carrier = opt.dataset.carrier || '';
        fetch(spSelect.dataset.url + '?carrier=' + encodeURIComponent(carrier))
            .then(r => r.json())
            .then(points => {
                if (!Array.isArray(points)) { return; }
                const curId = spSelect.dataset.currentId;
                spSelect.innerHTML = '<option value="">— Choisir un point relais —</option>' +
                    points.map(p =>
                        `<option value="${p.id}" data-name="${p.label}" ` +
                        `${String(p.id) === curId ? 'selected' : ''}>${p.label}</option>`
                    ).join('');
                spSelect.classList.remove('d-none');
            });
    }
    shippingSelect.addEventListener('change', maybeLoadServicePoints);

    // 3. Enregistrer vers Sendcloud
    block.querySelector('.btn-sendcloud-apply').addEventListener('click', function () {
        const spOpt = spSelect.selectedOptions[0];
        $.ajax({
            url: this.dataset.path,
            type: 'POST',
            dataType: 'json',
            data: {
                shippingOptionCode: shippingSelect.value,
                servicePointId: spSelect.classList.contains('d-none') ? '' : spSelect.value,
                servicePointName: (spOpt && spOpt.dataset.name) || '',
                _csrf_token: this.dataset.csrf,
            },
            success: (data) => {
                const ok = data.state === 1;
                const msg = ok
                    ? 'Enregistré sur Sendcloud' + (data.servicePointName ? ' (' + data.servicePointName + ')' : '')
                    : (data.message || 'Erreur');
                block.querySelector('.sendcloud-feedback')?.remove();
                const el = document.createElement('div');
                el.className = 'sendcloud-feedback small mt-1 ' + (ok ? 'text-success' : 'text-danger');
                el.textContent = msg;
                block.appendChild(el);
            },
            error: () => console.log('Sendcloud apply request failed.'),
        });
    });
});
```

## Étapes

1. **Entité + migration** — Ajouter les 3 champs Sendcloud (+ getters/setters) et le helper
   `getTotalWeightKg()` dans `src/Entity/Order.php` ; écrire la migration
   `migrations/VersionYYYYMMDDHHMMSS.php` (colonnes `sendcloud_shipping_option_code`,
   `sendcloud_service_point_id`, `sendcloud_service_point_name`). Exécuter la migration en base de dev.
2. **DTOs** — Créer `SendcloudShippingOptionDTO` et `SendcloudServicePointDTO` dans `src/Dto/Sendcloud/`.
3. **Client API** — Dans `src/Service/Sendcloud/SendcloudApiClient.php` : refactorer `request()` pour prendre
   un verbe HTTP (+ plage 2xx), adapter l'appel existant en `GET`, ajouter les constantes et
   `getShippingOptions()`, `getServicePoints()`, `updateOrder()`.
4. **Service** — Créer `src/Service/Sendcloud/SendcloudOrderShippingService.php`
   (`applyShippingSelection()`), câblé par autowiring (aucune conf `services.yaml` requise : injection déjà
   autowirée pour `SendcloudOrderLinker`).
5. **Contrôleur** — Dans `OrderCrudController.php` : injecter `SendcloudApiClient` +
   `SendcloudOrderShippingService`, ajouter la constante `SENDCLOUD_FROM_COUNTRY` et les 3 routes
   (`shipping-options`, `service-points`, `apply-shipping`).
6. **Template** — Étendre `templates/admin/order/order_delivery_action.html.twig` avec le bloc Sendcloud
   conditionné à `isEbay && sendcloudOrderId ∉ {null,'0'}` (déjà dans la branche `dateExpedition is null`,
   donc statut « En attente d'expédition » / « Prévente » garanti).
7. **JS** — Ajouter le bloc Sendcloud dans `assets/back/js/back.js` ; recompiler les assets front via
   `scripts/repo_exec.py`.
8. **Rafraîchir le graphe** — après modif, relancer l'extraction graphify du repo
   (`docs/src-eurocommemo/graphify-out/`) conformément au CLAUDE.md.

## Vérification

- **Build/qualité** (via `scripts/repo_exec.py`) : lint PHP + `bin/console lint:twig templates/admin/order`,
  `bin/console doctrine:migrations:migrate` en dev, build des assets front.
- **Schéma** : `bin/console doctrine:schema:validate` — mapping ↔ base cohérent après migration.
- **Scénario manuel (nominal, méthode simple)** :
  1. Aller sur « Commandes prêtes à être expédiées » (`state=VALID&delivery=1&ready=1`).
  2. Sur une commande eBay avec `sendcloudOrderId` renseigné, la cellule « Expédition » affiche le
     `<select>` méthodes (peuplé par `POST /shipping-options`) sans `<select>` point relais.
  3. Choisir une méthode standard → « Enregistrer sur Sendcloud » → message succès ; vérifier via le lien
     « Voir sur Sendcloud » que la méthode est positionnée, et en base que `sendcloud_shipping_option_code`
     est renseigné.
- **Scénario manuel (Shop2Shop / point relais)** :
  1. Même cellule, choisir une méthode dont `requiresServicePoint == true` → le `<select>` point relais
     apparaît, peuplé par `GET /service-points?carrier=<code>` + code postal / ville de l'adresse de livraison.
  2. Choisir un point relais → « Enregistrer sur Sendcloud » → succès ; vérifier dans le panel Sendcloud que
     `service_point_details` est renseigné, et en base `sendcloud_service_point_id` / `_name`.
- **Contrôle de périmètre** : le bloc n'apparaît PAS pour une commande expédiée (`dateExpedition` non nul),
  non eBay, ou sans association Sendcloud ; l'endpoint `apply-shipping` refuse (state 0) une commande hors
  statut ou sans association (gardes serveur).
- **CSRF** : rejouer un POST `apply-shipping` avec un `_csrf_token` invalide → réponse `state:0`
  « Token CSRF invalide. ».
- **Robustesse API** : credentials Sendcloud vides → endpoints de lecture renvoient `[]`/`{error}` sans
  casser la page ; l'écriture renvoie un message d'erreur lisible.
