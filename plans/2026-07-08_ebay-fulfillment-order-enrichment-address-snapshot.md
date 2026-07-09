# Plan — Migrate eBay order enrichment from Trading API to Fulfillment API + OrderAddress snapshot (delivery/billing) (2026-07-08)

**Repo** : src-eurocommemo (`~/OrbStack/docker/volumes/src-eurocommemo`) · **Risk** : medium · **Complexité** : moderate

## Contexte

eBay order import currently relies entirely on **EbayTradingAPI** (SOAP/XML): a webhook
`/ebay/notification` (Platform Notifications, XML) triggers `PaymentReceiveEvent::handle()`
(`src/Service/Webhook/Events/Ebay/PaymentReceiveEvent.php`), which calls
`EbayTradingAPI::getOrder()` (`GetOrders`) to enrich the order (line items, shipping cost,
discount), then persists `Order`/`User`.

A **Fulfillment API** integration (REST/JSON) was started in parallel
(`FulfillmentApiV1::getOrder()`, DTOs under `src/Service/Ebay/DTO/Output/Fulfillment/`) — see
`plans/2026-07-08_consommation-api-ebay-fulfillment-detail-commande.md` for how it was built. It
remains **read-only / inspection-only** today (`GetEbayFulfillmentOrderCommand`, with a debug
`dd()` left in place at line 35) — no persistence code uses it yet.

**Scope validated with the user** (clarification loop, one question at a time):
- Replace **only the enrichment call** inside `PaymentReceiveEvent::handle()`:
  `EbayTradingAPI::getOrder()` → `FulfillmentApiV1::getOrder()`. The webhook trigger itself stays
  on Trading API XML (order id extraction, `Ack` check, de-duplication — all unchanged). Switching
  the notification mechanism to eBay's REST Notification API v2 is a separate, riskier project,
  out of scope here.
- Shipment confirmation (`EbayTradingAPI::completeSell()` / `CompleteSale`, called from
  `OrderCrudController::admin_delivery_validate()`) **does not change** — current behavior is kept
  as-is. `EbayTradingAPI` also stays in use for everything that isn't order-related (categories,
  stock, product listing) since the Fulfillment API doesn't cover listings.
- **Addresses**: the Fulfillment API exposes two genuinely different addresses (confirmed by a
  real payload the user pasted from their own eBay account):
  `fulfillmentStartInstructions[0].shippingStep.shipTo` (delivery) and
  `buyer.buyerRegistrationAddress` (billing / eBay account registration address) — whereas the
  Trading API only exposes a single `ShippingAddress`. At import time, snapshot both addresses so
  they're immutable and independent from the `User` account (which can be edited later — today the
  address only lives on `User`, mutable, so historical orders silently change if the buyer edits
  their address afterwards).
- **Address modeling**: the user asked for a **dedicated `OrderAddress` entity** rather than 14
  flat columns duplicated on `Order` (delivery/billing). Single table, a `type` discriminant
  column (`delivery`/`billing`), `Order` 1—N `OrderAddress` relation. This is a deliberate
  departure from the project's current convention (no address entity/embeddable exists elsewhere —
  `User` stores its address as flat columns), but avoids duplicating 7 fields × 2 and keeps the
  model extensible if a third address type shows up later.

Real Fulfillment API `getOrder` sample provided by the user (trimmed), showing the two distinct
addresses:
```json
{
  "buyer": {
    "buyerRegistrationAddress": {
      "fullName": "Christophe Baudry",
      "contactAddress": { "addressLine1": "28 Rue de Bel Ébat", "city": "Loches", "postalCode": "37600", "countryCode": "FR" },
      "primaryPhone": { "phoneNumber": "769718482" },
      "email": "011dbe83a9210ab92046@members.ebay.com"
    }
  },
  "fulfillmentStartInstructions": [{
    "shippingStep": {
      "shipTo": {
        "fullName": "Christophe Baudry",
        "contactAddress": { "addressLine1": "30 AVENUE DE LA CLOUTIERE", "addressLine2": "9608S", "city": "PERRUSSON", "postalCode": "37600", "countryCode": "FR" },
        "primaryPhone": { "phoneNumber": "769718482" }
      },
      "shippingCarrierCode": "Chronopost",
      "shippingServiceCode": "FR_Shop2Shop"
    }
  }]
}
```

## Fichiers concernés

### Nouveaux
| Fichier | Rôle |
|---|---|
| `src/Entity/OrderAddress.php` | Address snapshot entity, discriminated by `type` (`delivery`/`billing`) |
| `src/Repository/OrderAddressRepository.php` | Standard `ServiceEntityRepository` |
| `migrations/Version20260708XXXXXX.php` | Creates `order_address` table + FK to `orders` |

### Modifiés
| Fichier | Changement |
|---|---|
| `src/Service/Ebay/DTO/Output/Fulfillment/FulfillmentOrderDTO.php` | + `getBuyerRegistrationAddress(): ?FulfillmentShipToDTO` |
| `src/Entity/Order.php` | + `OneToMany` relation to `OrderAddress` + `getDeliveryAddress()`/`getBillingAddress()`/`setDeliveryAddress()`/`setBillingAddress()` accessors |
| `src/Service/Webhook/Events/Ebay/PaymentReceiveEvent.php` | `EbayTradingAPI` → `FulfillmentApiV1` for enrichment only; snapshot both `OrderAddress` records |
| `src/Command/GetEbayFulfillmentOrderCommand.php` | Remove the debug `dd($order)` (line 35) — needed to manually validate the new call before touching the production webhook |

**Out of scope** (confirmed with the user): `OrderCrudController::admin_delivery_validate()`,
`EbayTradingAPI::completeSell()`, `OrderProducts` (no `ebayLineItemId` field), `ImportEbayOrderCommand`
(separate debug command, not touched by this plan — keeps using `EbayTradingAPI` as-is).

## Détail des modifications

### 1. `FulfillmentOrderDTO.php` — expose the billing address

Real payload confirmed by the user: `buyer.buyerRegistrationAddress` has the exact same shape as
`shipTo` (fullName, contactAddress{addressLine1,city,postalCode,countryCode,...}, primaryPhone,
email) → reuse `FulfillmentShipToDTO` as-is, no new DTO class needed.

```php
// add after getShipTo() (line 77)
public function getBuyerRegistrationAddress(): ?FulfillmentShipToDTO
{
    $address = $this->payload['buyer']['buyerRegistrationAddress'] ?? null;

    return $address !== null ? new FulfillmentShipToDTO($address) : null;
}
```

### 2. `src/Entity/OrderAddress.php` — new entity

Style: matches the project's simple entities (`OrderProducts`) — `#[Column]`/`#[ORM\Column]`,
fluent setters returning `self`/the entity, no promoted properties.

```php
<?php

namespace App\Entity;

use App\Repository\OrderAddressRepository;
use App\Service\Ebay\DTO\Output\Fulfillment\FulfillmentShipToDTO;
use Doctrine\ORM\Mapping as ORM;
use Doctrine\ORM\Mapping\Column;

#[ORM\Entity(repositoryClass: OrderAddressRepository::class)]
#[ORM\Table(name: "order_address")]
class OrderAddress
{
    public const TYPE_DELIVERY = 'delivery';
    public const TYPE_BILLING = 'billing';

    #[ORM\Id]
    #[ORM\GeneratedValue]
    #[Column(type: 'integer')]
    private ?int $id = null;

    #[ORM\ManyToOne(targetEntity: Order::class, inversedBy: 'addresses')]
    #[ORM\JoinColumn(name: "order_id", referencedColumnName: "id", nullable: false, onDelete: "CASCADE")]
    private Order $order;

    #[ORM\Column(type: 'string', length: 20)]
    private string $type;

    #[ORM\Column(type: 'string', length: 255, nullable: true)]
    private ?string $fullName = null;

    #[ORM\Column(type: 'string', length: 255, nullable: true)]
    private ?string $line1 = null;

    #[ORM\Column(type: 'string', length: 255, nullable: true)]
    private ?string $line2 = null;

    #[ORM\Column(type: 'string', length: 255, nullable: true)]
    private ?string $city = null;

    #[ORM\Column(type: 'string', length: 20, nullable: true)]
    private ?string $postalCode = null;

    #[ORM\Column(type: 'string', length: 2, nullable: true)]
    private ?string $countryCode = null;

    #[ORM\Column(type: 'string', length: 50, nullable: true)]
    private ?string $phone = null;

    public function getId(): ?int
    {
        return $this->id;
    }

    public function getOrder(): Order
    {
        return $this->order;
    }
    public function setOrder(Order $order): OrderAddress
    {
        $this->order = $order;
        return $this;
    }

    public function getType(): string
    {
        return $this->type;
    }
    public function setType(string $type): OrderAddress
    {
        $this->type = $type;
        return $this;
    }

    public function getFullName(): ?string
    {
        return $this->fullName;
    }
    public function setFullName(?string $fullName): OrderAddress
    {
        $this->fullName = $fullName;
        return $this;
    }

    public function getLine1(): ?string
    {
        return $this->line1;
    }
    public function setLine1(?string $line1): OrderAddress
    {
        $this->line1 = $line1;
        return $this;
    }

    public function getLine2(): ?string
    {
        return $this->line2;
    }
    public function setLine2(?string $line2): OrderAddress
    {
        $this->line2 = $line2;
        return $this;
    }

    public function getCity(): ?string
    {
        return $this->city;
    }
    public function setCity(?string $city): OrderAddress
    {
        $this->city = $city;
        return $this;
    }

    public function getPostalCode(): ?string
    {
        return $this->postalCode;
    }
    public function setPostalCode(?string $postalCode): OrderAddress
    {
        $this->postalCode = $postalCode;
        return $this;
    }

    public function getCountryCode(): ?string
    {
        return $this->countryCode;
    }
    public function setCountryCode(?string $countryCode): OrderAddress
    {
        $this->countryCode = $countryCode;
        return $this;
    }

    public function getPhone(): ?string
    {
        return $this->phone;
    }
    public function setPhone(?string $phone): OrderAddress
    {
        $this->phone = $phone;
        return $this;
    }

    public static function fromDto(?FulfillmentShipToDTO $dto): ?self
    {
        if ($dto === null) {
            return null;
        }

        return (new self())
            ->setFullName($dto->getFullName())
            ->setLine1($dto->getAddressLine1())
            ->setLine2($dto->getAddressLine2())
            ->setCity($dto->getCity())
            ->setPostalCode($dto->getPostalCode())
            ->setCountryCode($dto->getCountryCode())
            ->setPhone($dto->getPhoneNumber());
    }
}
```

### 3. `src/Repository/OrderAddressRepository.php` — new, standard boilerplate

```php
<?php

namespace App\Repository;

use App\Entity\OrderAddress;
use Doctrine\Bundle\DoctrineBundle\Repository\ServiceEntityRepository;
use Doctrine\Persistence\ManagerRegistry;

/**
 * @extends ServiceEntityRepository<OrderAddress>
 *
 * @method OrderAddress|null find($id, $lockMode = null, $lockVersion = null)
 * @method OrderAddress|null findOneBy(array $criteria, array $orderBy = null)
 * @method OrderAddress[]    findAll()
 * @method OrderAddress[]    findBy(array $criteria, array $orderBy = null, $limit = null, $offset = null)
 */
class OrderAddressRepository extends ServiceEntityRepository
{
    public function __construct(ManagerRegistry $registry)
    {
        parent::__construct($registry, OrderAddress::class);
    }
}
```

### 4. `Order.php` — relation to `OrderAddress`

Add the property after `$orderProducts` (line 62), following the same `OneToMany`/`Collection`
style already used for `orderProducts`:

```php
/**
 * @var Collection<int, OrderAddress>
 */
#[ORM\OneToMany(mappedBy: 'order', targetEntity: OrderAddress::class, cascade: ["persist", "remove"], orphanRemoval: true)]
private Collection $addresses;
```

Initialize in the constructor (lines 105-107, next to `orderProducts`):

```php
#[Pure] public function __construct() {
    $this->orderProducts = new ArrayCollection();
    $this->addresses = new ArrayCollection();
}
```

Accessors (append at the end of the class, after `setFakeOrderIdEbay`, lines 451-455):

```php
public function getAddresses(): Collection
{
    return $this->addresses;
}

public function getDeliveryAddress(): ?OrderAddress
{
    return $this->findAddressByType(OrderAddress::TYPE_DELIVERY);
}

public function getBillingAddress(): ?OrderAddress
{
    return $this->findAddressByType(OrderAddress::TYPE_BILLING);
}

public function setDeliveryAddress(?OrderAddress $address): Order
{
    return $this->replaceAddress(OrderAddress::TYPE_DELIVERY, $address);
}

public function setBillingAddress(?OrderAddress $address): Order
{
    return $this->replaceAddress(OrderAddress::TYPE_BILLING, $address);
}

private function findAddressByType(string $type): ?OrderAddress
{
    foreach ($this->addresses as $address) {
        if ($address->getType() === $type) {
            return $address;
        }
    }

    return null;
}

private function replaceAddress(string $type, ?OrderAddress $address): Order
{
    if ($existing = $this->findAddressByType($type)) {
        $this->addresses->removeElement($existing);
    }
    if ($address !== null) {
        $address->setType($type)->setOrder($this);
        $this->addresses->add($address);
    }

    return $this;
}
```

`use App\Entity\OrderAddress;` is not needed (same `App\Entity` namespace).

### 5. Doctrine migration

Name it following the existing convention (`Version<YYYYMMDDHHMMSS>.php`) — generate it via
`doctrine:migrations:generate` at implementation time (the exact FK constraint name, e.g.
`FK_xxxxx`, will be whatever the generator produces — not fixed here):

```php
<?php

declare(strict_types=1);

namespace DoctrineMigrations;

use Doctrine\DBAL\Schema\Schema;
use Doctrine\Migrations\AbstractMigration;

final class Version20260708XXXXXX extends AbstractMigration
{
    public function getDescription(): string
    {
        return 'Create order_address table (delivery/billing snapshot per order)';
    }

    public function up(Schema $schema): void
    {
        $this->addSql('CREATE TABLE order_address (id INT AUTO_INCREMENT NOT NULL, order_id INT NOT NULL, type VARCHAR(20) NOT NULL, full_name VARCHAR(255) DEFAULT NULL, line1 VARCHAR(255) DEFAULT NULL, line2 VARCHAR(255) DEFAULT NULL, city VARCHAR(255) DEFAULT NULL, postal_code VARCHAR(20) DEFAULT NULL, country_code VARCHAR(2) DEFAULT NULL, phone VARCHAR(50) DEFAULT NULL, INDEX IDX_ORDER_ADDRESS_ORDER (order_id), PRIMARY KEY(id)) DEFAULT CHARACTER SET utf8mb4 COLLATE `utf8mb4_unicode_ci` ENGINE = InnoDB');
        $this->addSql('ALTER TABLE order_address ADD CONSTRAINT FK_ORDER_ADDRESS_ORDER FOREIGN KEY (order_id) REFERENCES orders (id) ON DELETE CASCADE');
    }

    public function down(Schema $schema): void
    {
        $this->addSql('ALTER TABLE order_address DROP FOREIGN KEY FK_ORDER_ADDRESS_ORDER');
        $this->addSql('DROP TABLE order_address');
    }
}
```

### 6. `PaymentReceiveEvent.php` — switch enrichment to the Fulfillment API

Replace the `EbayTradingAPI $tradingApi` injection (line 39) with `FulfillmentApiV1 $fulfillmentApi`
(`use App\Service\Ebay\API\FulfillmentApiV1;` replaces `use App\Service\Ebay\API\EbayTradingAPI;`).
Also replace the `ItemSoldDTO`/`ShippingCostDTO` imports with
`FulfillmentLineItemDTO`/`FulfillmentAmountDTO`, and add `use App\Entity\OrderAddress;`.

**`handle()` (lines 60-139)** — the XML webhook stays the trigger (order id, `Ack` check,
de-duplication unchanged); only enrichment changes:

```php
// line 88 — before
$orderFromEbay = $this->tradingApi->getOrder($eventDto->getOrderId());

// after
$orderFromEbay = $this->fulfillmentApi->getOrder($eventDto->getOrderId());
```

```php
// lines 95-104 — before
$order = new Order();
$this->defineOrderInformation(
    $order,
    $eventDto,
    $country,
    $dateNotification,
    $orderFromEbay->getShippingDetails(),
    $orderFromEbay->getNameBuyer(),
    $orderFromEbay->getDiscountAmount(),
);

// after
$order = new Order();
$this->defineOrderInformation(
    $order,
    $eventDto,
    $country,
    $dateNotification,
    $orderFromEbay->getDeliveryCost(),
    $orderFromEbay->getShipTo()?->getFullName() ?? $eventDto->getName(),
    $orderFromEbay->getAdjustment()?->getPayload() ?? ['currency' => 'EUR', 'value' => 0.0],
);
$order->setDeliveryAddress(OrderAddress::fromDto($orderFromEbay->getShipTo()));
$order->setBillingAddress(OrderAddress::fromDto($orderFromEbay->getBuyerRegistrationAddress()));
```

```php
// lines 106-109 — before
if ($shippingServiceToken = $orderFromEbay->getShippingService()) {
    $order->setShippingServiceCode($shippingServiceToken);
    $order->setShippingService($this->shippingServiceRepository->findOneByToken($shippingServiceToken));
}

// after
if ($shippingServiceToken = $orderFromEbay->getShippingServiceCode()) {
    $order->setShippingServiceCode($shippingServiceToken);
    $order->setShippingService($this->shippingServiceRepository->findOneByToken($shippingServiceToken));
}
```

**`defineOrderInformation()` (lines 160-196)** — change the type of the 5th parameter:

```php
private function defineOrderInformation(
    Order &$order,
    PaymentReceiveEventDTO $eventDto,
    Country $country,
    \DateTime $dateNotification,
    ?FulfillmentAmountDTO $shippingCostDTO,   // was ?ShippingCostDTO
    string $buyerName,
    array $discountAmount = [],
): void {
    // ...
    if (!is_null($shippingCostDTO)) {
        $costShippingCurrency = $shippingCostDTO->getCurrency();   // was getShippingCurrencyId()
        $cost = $shippingCostDTO->getValue();
        // rest unchanged
    }
    // rest unchanged
}
```

**`allItemsIsPresent()` (lines 243-254)** and **`defineOrderLine()` (lines 256-286)** — change the
item type (product matching unchanged: `ebayId` then fallback to `ebayTitle`):

```php
/**
 * @param FulfillmentLineItemDTO[] $items
 */
private function allItemsIsPresent(array $items): bool
{
    $listEbayTitles = array_map(fn (FulfillmentLineItemDTO $item) => $item->getTitle(), $items);
    $productsIds = $this->productRepository->findByEbayTitles($listEbayTitles);

    return count($productsIds) === count($items);
}

private function defineOrderLine(Order &$order, FulfillmentLineItemDTO $item, float &$sumAmountCmd, float &$sumAmountTGC)
{
    $product = $this->productRepository->findOneBy(['ebayId' => $item->getLegacyItemId()]);
    if (!$product) {
        $product = $this->productRepository->findOneBy(['ebayTitle' => $item->getTitle()]);
    }
    if (!$product) {
        $this->logger->critical('[Eurocommemo] product not found', ['orderEbay' => $order->getOrderIdEbay(), 'product' => serialize($item)]);
    }
    if ($item->getQuantity() > 0 && $product instanceof Product) {
        $lineCost = $item->getLineItemCost();
        $unitPrice = $lineCost && $lineCost->getCurrency() !== 'EUR'
            ? $this->currencyConverter->convert($lineCost->getValue(), $lineCost->getCurrency(), 'EUR')
            : ($lineCost?->getValue() ?? 0.0);
        $orderProduct = new OrderProducts();
        $orderProduct
            ->setQuantity($item->getQuantity())
            ->setProduct($product);
        $orderProduct->setAmountProductVenteUnitTTC($unitPrice);
        $orderProduct->setAmountProductVenteUnitTGC(round($unitPrice - ($unitPrice / (1 + ($product->getTva()->getAmount() / 100))), 2));
        $orderProduct->setAmountProductVenteUnitHT($unitPrice - $orderProduct->getAmountProductVenteUnitTGC());
        $orderProduct->setAmountProductVenteLineTTC($orderProduct->getQuantity() * $orderProduct->getAmountProductVenteUnitTTC());

        $sumAmountCmd += $orderProduct->getAmountProductVenteLineTTC();
        $sumAmountTGC += $orderProduct->getAmountProductVenteUnitTGC() * $orderProduct->getQuantity();
        $order->addOrderProduct($orderProduct);

        $this->stockManagementService->execute(
            platformName: StockManagementService::PLATFORM_EBAY,
            product: $product,
            quantity: $item->getQuantity(),
        );
    }
}
```

And `foreach ($orderFromEbay->getItems() as $item)` (line 114) → `foreach ($orderFromEbay->getLineItems() as $item)`.

`DiscountService::getDiscount(array $discountValueWithCurrency): float` (unchanged) already expects
`['currency' => ..., 'value' => ...]` — `FulfillmentAmountDTO::getPayload()` has exactly that shape,
no adaptation needed on `DiscountService`'s side.

`$this->entityManager->persist($order)` (line 129, unchanged) is enough to persist both
`OrderAddress` records thanks to the `cascade: ["persist", "remove"]` set in §4 — no extra
`persist()` call needed.

Note: `OrderCrudController::admin_delivery_validate()` keeps calling
`EbayTradingAPI::completeSell()` exactly as today — nothing this flow needs depends on this change
(the `ShippingProvider` is resolved from the admin HTTP request, not from the eBay order).

### 7. `GetEbayFulfillmentOrderCommand.php`

Remove line 35 (`dd($order);`) — debug code already flagged during exploration; needed to be able
to run this command and manually validate `getShipTo()`/`getBuyerRegistrationAddress()` on a real
order before switching the production webhook.

## Étapes d'implémentation

1. `FulfillmentOrderDTO::getBuyerRegistrationAddress()` (§1).
2. `OrderAddress` + `OrderAddressRepository` (§2, §3).
3. Relation + accessors on `Order` (§4), then the Doctrine migration (§5) — run through
   `scripts/repo_exec.py` (never `php bin/console` directly, per the meta-repo `CLAUDE.md`).
4. `GetEbayFulfillmentOrderCommand` (§7) — remove the `dd()` so §1 can be validated manually on a
   real order before touching the webhook.
5. `PaymentReceiveEvent` (§6) — the enrichment switch, core of this plan.

## Vérification

1. `scripts/repo_exec.py src-eurocommemo -- php bin/console doctrine:migrations:migrate --dry-run`
   then run the real migration on a dev environment.
2. `scripts/repo_exec.py src-eurocommemo -- php bin/console app:ebay:fulfillment-order -o <real order id>`
   (after removing the `dd()`) to confirm `getShipTo()`/`getBuyerRegistrationAddress()` return two
   genuinely distinct addresses on a real order.
3. Replay a test eBay webhook (or invoke `PaymentReceiveEvent::handle()` with a test payload) and
   check in the database that two `order_address` rows (type `delivery` and `billing`) get created
   for the order with the right values, and that `Order::getDeliveryAddress()`/`getBillingAddress()`
   return them correctly. Compare amounts/line items against what the old Trading API path would
   have produced, on 2-3 real orders (`EbayTradingAPI::getOrder()` vs `FulfillmentApiV1::getOrder()`
   on the same `orderId`), before considering the switch reliable.
4. Confirm the "confirm shipment" admin flow (`admin_delivery_validate`) still works exactly as
   before on an eBay order imported through the new path — not modified by this plan, but it
   depends on fields (`orderIdEbay`, `shippingProvider`) set by `PaymentReceiveEvent`.
5. `scripts/repo_exec.py src-eurocommemo -- <project lint/static-analysis command>` if available (not
   explicitly identified during exploration — check `composer.json` scripts).
