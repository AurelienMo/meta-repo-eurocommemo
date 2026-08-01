# Plan — Mail « colis disponible en point relais » (webhook Sendcloud)

> Repo cible : `src-eurocommemo` · Chiffrage associé :
> `estimates/2026-08-01_mail-colis-dispo-point-relais.md` (~7,5 h)

## Contexte

Le webhook Sendcloud (`POST /sendcloud/notification`, `src/Controller/WebhookController.php:67`) ne
fait aujourd'hui **que du debug** : il filtre les emails eBay puis transfère le payload brut au
mainteneur via `MailService::sendSendcloudWebhookDebug()`. Aucun traitement métier.

Le client n'est prévenu qu'au **départ** du colis (`mail_delivery.html.twig`, envoyé par
`OrderListener` à la saisie de la date d'expédition). Quand son colis arrive en point relais, il ne
reçoit rien du site — d'où des retraits tardifs, voire des retours à l'expéditeur.

Contraintes validées : **commandes web uniquement** (eBay déjà exclu par le filtre
`@members.ebay.com`), **nouveau template dédié**, **envoi unique** avec garde anti-doublon.

### Ce qu'un payload de production a confirmé

Un vrai `parcel_status_changed` Chronopost Shop2Shop en statut « Awaiting customer pickup » a été
capturé. Il tranche trois incertitudes qui étaient ouvertes :

| Question | Réponse du payload |
|---|---|
| Forme du bloc `status` | `{"id": 12, "message": "Awaiting customer pickup"}` — **`id` numérique, pas de `code`**. Le webhook est en forme v2, alors que le catalogue interrogé (`code` + `message`) est en v3. |
| Nom du point relais | `to_address.address_line_2` = `"PRO ET CIE MORANDINI"` |
| Adresse du point relais | **Disponible en entier** dans `to_address` : `address_line_1`, `city`, `postal_code`, `country_code` |

Autres champs exploitables, tous présents : `parcel.id` (690794557), `tracking_number`
(`XM020261994TS`), `tracking_url`, `order_number` (`F-2026-1247`), `email` (client),
`carrier.name` (`Chronopost`), `to_service_point` (13201412).

**`order_number` = `Order::reference`** : `SendcloudOrderCreator::buildPayload()` envoie
`'order_number' => $order->getReference()`, et `OrderListener` écrase la référence par le numéro de
facture `F-YYYY-NNNN` à la validation du paiement (`OrderListener.php:99-100`,
`OrderHelper::incrementFullNumOrder()`). Le rapprochement par `order_number` est donc fiable.

**Aucun délai de retrait n'est transmis.** `date_cancel_before` concerne l'annulation de l'étiquette,
pas la rétention en point relais. Le mail n'affichera donc pas de date limite.

### Conséquences sur le plan

1. **La résolution du statut doit accepter `id`.** Le repli sur `message` seul aurait fonctionné,
   mais l'id observé en production (`12` → *Awaiting customer pickup*) est une clé plus sûre qu'un
   libellé susceptible d'être traduit. Ordre retenu : `code` (v3, futur) → `id` (uniquement les ids
   **observés**) → `message`.
   Prudence sur les ids : le payload de test présent dans `var/log/dev.log` utilisait `id: 3` pour
   « Ready to send », alors que la doc Sendcloud donne `3 → En route to sorting center`. On ne mappe
   donc **que** les ids réellement constatés.
2. **Le mail peut afficher l'adresse complète du point relais** — c'était un point ouvert chiffré à
   +0,75 h dans l'estimation ; il tombe, l'information est dans le payload.
3. **Un DTO devient utile** pour lire ce payload proprement, plutôt que de promener un tableau brut
   jusqu'au template. `src/Dto/Sendcloud/` en contient déjà 8 sur ce moule exact.

L'adresse est par ailleurs déjà en base : `CartHelper` (`CartHelper.php:271-279`) enregistre
l'adresse de livraison via `OrderAddress::fromServicePoint()` (`OrderAddress.php:171-183`), qui place
le nom du relais en `line2` et sa rue en `line1` — même structure que `to_address`. Le payload reste
prioritaire (il reflète l'endroit où le colis se trouve réellement), la commande sert de repli.

## Fichiers concernés

Repo : `src-eurocommemo` (Symfony 6, PHP 8, Doctrine ORM, EasyAdmin).

### Nouveaux

#### `src/Dto/Sendcloud/SendcloudParcelDTO.php`

Même moule que `src/Dto/Sendcloud/SendcloudServicePointDTO.php` : wrapper immuable sur le tableau du
payload, getters tolérants aux clés absentes.

```php
<?php

namespace App\Dto\Sendcloud;

/**
 * Read-only view over the `parcel` block of a Sendcloud webhook payload.
 * Service point data is read from `to_address`, where Sendcloud puts the pickup point:
 * `address_line_2` carries its name, `address_line_1` its street.
 */
class SendcloudParcelDTO
{
    public function __construct(private readonly array $payload)
    {
    }

    public function getId(): ?string
    {
        return isset($this->payload['id']) ? (string) $this->payload['id'] : null;
    }

    public function getEmail(): ?string
    {
        return $this->payload['email'] ?? $this->payload['to_address']['email'] ?? null;
    }

    public function getTrackingNumber(): ?string
    {
        return $this->payload['tracking_number'] ?? null;
    }

    public function getTrackingUrl(): ?string
    {
        return $this->payload['tracking_url'] ?? null;
    }

    /** Sendcloud `order_number` — equals Order::getReference() for orders created by this app. */
    public function getOrderNumber(): ?string
    {
        return $this->payload['order_number'] ?? null;
    }

    /** @return array<string, mixed> The raw `status` block, fed to SendcloudParcelStatusEnum. */
    public function getStatus(): array
    {
        return is_array($this->payload['status'] ?? null) ? $this->payload['status'] : [];
    }

    public function getCarrierName(): ?string
    {
        return $this->payload['carrier']['name'] ?? null;
    }

    public function getServicePointId(): ?string
    {
        $id = $this->payload['to_service_point'] ?? $this->payload['to_address']['service_point'] ?? null;

        return null !== $id ? (string) $id : null;
    }

    public function getServicePointName(): ?string
    {
        return $this->nonEmpty($this->payload['to_address']['address_line_2'] ?? null)
            ?? $this->nonEmpty($this->payload['address_2'] ?? null);
    }

    public function getServicePointStreet(): ?string
    {
        return $this->nonEmpty($this->payload['to_address']['address_line_1'] ?? null)
            ?? $this->nonEmpty($this->payload['address'] ?? null);
    }

    public function getServicePointPostalCode(): ?string
    {
        return $this->nonEmpty($this->payload['to_address']['postal_code'] ?? null)
            ?? $this->nonEmpty($this->payload['postal_code'] ?? null);
    }

    public function getServicePointCity(): ?string
    {
        return $this->nonEmpty($this->payload['to_address']['city'] ?? null)
            ?? $this->nonEmpty($this->payload['city'] ?? null);
    }

    /** "12 RUE DU GENERAL LECLERC, 57390 AUDUN LE TICHE" — empty string when nothing is known. */
    public function getServicePointFullAddress(): string
    {
        $cityLine = trim(sprintf('%s %s', (string) $this->getServicePointPostalCode(), (string) $this->getServicePointCity()));

        return trim(implode(', ', array_filter([$this->getServicePointStreet(), $cityLine])), ', ');
    }

    private function nonEmpty(mixed $value): ?string
    {
        return is_string($value) && '' !== trim($value) ? trim($value) : null;
    }
}
```

#### `src/Entity/Enum/SendcloudParcelStatusEnum.php`

Backed enum sur le `code` v3, avec la table des messages et la table (partielle) des ids observés.
Le dossier ne contient aujourd'hui que `WebhookLogTypeEnum.php` (constantes + `match`) ; on passe ici
à un vrai backed enum.

Les 35 cas du catalogue sont figés — pas seulement celui utile — pour distinguer « statut connu mais
non déclencheur » de « statut hors catalogue », ce dernier méritant un log.

```php
<?php

namespace App\Entity\Enum;

/**
 * Sendcloud normalises every carrier's tracking events into a single catalogue of statuses:
 * there is no per-carrier list, the same values apply to Chronopost Shop2Shop, Mondial Relay, etc.
 * Source: GET {SENDCLOUD_BASE_URL}/parcels/statuses on the project account (2026-08-01).
 */
enum SendcloudParcelStatusEnum: string
{
    case READY_TO_SEND            = 'READY_TO_SEND';
    case ANNOUNCING               = 'ANNOUNCING';
    case ANNOUNCED                = 'ANNOUNCED';
    case ANNOUNCED_UNCOLLECTED    = 'ANNOUNCED_UNCOLLECTED';
    case ANNOUNCEMENT_FAILED      = 'ANNOUNCEMENT_FAILED';
    case NO_LABEL                 = 'NO_LABEL';
    case PICKED_UP_BY_DRIVER      = 'PICKED_UP_BY_DRIVER';
    case COLLECT_ERROR            = 'COLLECT_ERROR';
    case TO_SORTING               = 'TO_SORTING';
    case AT_SORTING_CENTRE        = 'AT_SORTING_CENTRE';
    case SORTING                  = 'SORTING';
    case SORTED                   = 'SORTED';
    case UNSORTED                 = 'UNSORTED';
    case AT_CUSTOMS               = 'AT_CUSTOMS';
    case SHIPMENT_ON_ROUTE        = 'SHIPMENT_ON_ROUTE';
    case DRIVER_ON_ROUTE          = 'DRIVER_ON_ROUTE';
    case DELAYED                  = 'DELAYED';
    case DELIVERY_DATE_CHANGED    = 'DELIVERY_DATE_CHANGED';
    case DELIVERY_ADDRESS_CHANGED = 'DELIVERY_ADDRESS_CHANGED';
    case DELIVERY_METHOD_CHANGED  = 'DELIVERY_METHOD_CHANGED';
    case AWAITING_CUSTOMER_PICKUP = 'AWAITING_CUSTOMER_PICKUP';
    case COLLECTED_BY_CUSTOMER    = 'COLLECTED_BY_CUSTOMER';
    case DELIVERED                = 'DELIVERED';
    case DELIVERY_FAILED          = 'DELIVERY_FAILED';
    case UNDELIVERABLE            = 'UNDELIVERABLE';
    case REFUSED_BY_RECIPIENT     = 'REFUSED_BY_RECIPIENT';
    case RETURNED_TO_SENDER       = 'RETURNED_TO_SENDER';
    case ADDRESS_INVALID          = 'ADDRESS_INVALID';
    case CANCELLING               = 'CANCELLING';
    case CANCELLING_UPSTREAM      = 'CANCELLING_UPSTREAM';
    case CANCELLED                = 'CANCELLED';
    case CANCELLED_UPSTREAM       = 'CANCELLED_UPSTREAM';
    case CANCELLATION_FAILED      = 'CANCELLATION_FAILED';
    case EXCEPTION                = 'EXCEPTION';
    case UNKNOWN                  = 'UNKNOWN';

    /**
     * Legacy numeric ids carried by the v2 webhook shape. Sendcloud does not publish this mapping,
     * so ONLY ids observed on real production payloads are listed here — never guessed ones.
     * 12 => "Awaiting customer pickup", observed 2026-07-29 on a Chronopost Shop2Shop parcel.
     */
    private const OBSERVED_IDS = [
        12 => self::AWAITING_CUSTOMER_PICKUP,
    ];

    /** Human message returned by Sendcloud, used as a resolution key when `code` is absent. */
    public function message(): string
    {
        return match ($this) {
            self::READY_TO_SEND            => 'Ready to send',
            self::ANNOUNCING               => 'Being announced',
            self::ANNOUNCED                => 'Announced',
            self::ANNOUNCED_UNCOLLECTED    => 'Announced: not collected',
            self::ANNOUNCEMENT_FAILED      => 'Announcement failed',
            self::NO_LABEL                 => 'No label',
            self::PICKED_UP_BY_DRIVER      => 'Shipment picked up by driver',
            self::COLLECT_ERROR            => 'Error collecting',
            self::TO_SORTING               => 'En route to sorting center',
            self::AT_SORTING_CENTRE        => 'At sorting centre',
            self::SORTING                  => 'Being sorted',
            self::SORTED                   => 'Sorted',
            self::UNSORTED                 => 'Not sorted',
            self::AT_CUSTOMS               => 'At Customs',
            self::SHIPMENT_ON_ROUTE        => 'Parcel en route',
            self::DRIVER_ON_ROUTE          => 'Driver en route',
            self::DELAYED                  => 'Delivery delayed',
            self::DELIVERY_DATE_CHANGED    => 'Delivery date changed',
            self::DELIVERY_ADDRESS_CHANGED => 'Delivery address changed',
            self::DELIVERY_METHOD_CHANGED  => 'Delivery method changed',
            self::AWAITING_CUSTOMER_PICKUP => 'Awaiting customer pickup',
            self::COLLECTED_BY_CUSTOMER    => 'Shipment collected by customer',
            self::DELIVERED                => 'Delivered',
            self::DELIVERY_FAILED          => 'Delivery attempt failed',
            self::UNDELIVERABLE            => 'Unable to deliver',
            self::REFUSED_BY_RECIPIENT     => 'Refused by recipient',
            self::RETURNED_TO_SENDER       => 'Returned to sender',
            self::ADDRESS_INVALID          => 'Address invalid',
            self::CANCELLING               => 'Cancellation requested',
            self::CANCELLING_UPSTREAM      => 'Submitting cancellation request',
            self::CANCELLED                => 'Cancelled',
            self::CANCELLED_UPSTREAM       => 'Cancelled upstream',
            self::CANCELLATION_FAILED      => 'Parcel cancellation failed.',
            self::EXCEPTION                => 'Exception',
            self::UNKNOWN                  => 'Unknown status - check carrier track & trace page for more insights',
        };
    }

    /**
     * Resolve the status from a webhook `parcel.status` block, most reliable key first:
     * `code` (v3 shape), then the observed numeric `id` (v2 shape, what production sends today),
     * then the human `message` carried by both.
     *
     * @param array<string, mixed> $status
     */
    public static function tryFromPayload(array $status): ?self
    {
        $code = $status['code'] ?? null;
        if (is_string($code) && null !== $resolved = self::tryFrom(strtoupper(trim($code)))) {
            return $resolved;
        }

        $id = $status['id'] ?? null;
        if (is_numeric($id) && isset(self::OBSERVED_IDS[(int) $id])) {
            return self::OBSERVED_IDS[(int) $id];
        }

        $message = $status['message'] ?? null;
        if (!is_string($message)) {
            return null;
        }

        $normalised = strtolower(trim($message));
        foreach (self::cases() as $case) {
            if (strtolower($case->message()) === $normalised) {
                return $case;
            }
        }

        return null;
    }

    /** True for the only status meaning "the parcel is waiting for the customer at a service point". */
    public function isAwaitingCustomerPickup(): bool
    {
        return self::AWAITING_CUSTOMER_PICKUP === $this;
    }
}
```

#### `src/Service/Sendcloud/UseCase/NotifyServicePointPickupUseCase.php`

Le contrôleur reste fin ; la logique va dans un use case, comme
`src/Service/Sendcloud/UseCase/BackfillSendcloudTrackingUseCase.php`. Différence avec ce dernier : il
**flushe**, n'ayant pas d'appelant transactionnel (le webhook est un point d'entrée terminal).

```php
<?php

namespace App\Service\Sendcloud\UseCase;

use App\Dto\Sendcloud\SendcloudParcelDTO;
use App\Entity\Order;
use App\Repository\OrderRepository;
use App\Service\MailService;
use Doctrine\ORM\EntityManagerInterface;
use Psr\Log\LoggerInterface;

final class NotifyServicePointPickupUseCase
{
    public function __construct(
        private readonly OrderRepository $orderRepository,
        private readonly MailService $mailService,
        private readonly EntityManagerInterface $entityManager,
        private readonly LoggerInterface $logger,
    ) {
    }

    /**
     * Send the "your parcel is waiting at the pickup point" email for the parcel carried by an
     * AWAITING_CUSTOMER_PICKUP webhook. Idempotent: an order already stamped is never notified twice.
     *
     * @return 'sent'|'already_notified'|'order_not_found'|'ebay_order'|'send_failed'
     */
    public function execute(SendcloudParcelDTO $parcel): string
    {
        $order = $this->orderRepository->findOneByParcelIdentifiers(
            $parcel->getId(),
            $parcel->getTrackingNumber(),
            $parcel->getOrderNumber()
        );

        if (null === $order) {
            $this->logger->info('[Webhook][Sendcloud] Pickup notification: no matching order', [
                'parcelId'       => $parcel->getId(),
                'trackingNumber' => $parcel->getTrackingNumber(),
                'orderNumber'    => $parcel->getOrderNumber(),
            ]);

            return 'order_not_found';
        }

        // Defensive: the controller already filters @members.ebay.com, but an eBay order could be
        // matched through parcel id / tracking number without carrying that email.
        if (true === $order->getIsEbay()) {
            return 'ebay_order';
        }

        if (null !== $order->getSendcloudPickupNotifiedAt()) {
            return 'already_notified';
        }

        if (!$this->mailService->sendMailServicePointPickup($order, $parcel)) {
            $this->logger->warning('[Webhook][Sendcloud] Pickup notification could not be sent', [
                'orderId'   => $order->getId(),
                'reference' => $order->getReference(),
                'email'     => $order->getUser()->getEmail(),
            ]);

            return 'send_failed';
        }

        // Backfill the pickup point name when the order predates it (eg. imported orders).
        if (null === $order->getSendcloudServicePointName() && null !== $parcel->getServicePointName()) {
            $order->setSendcloudServicePointName($parcel->getServicePointName());
        }

        $order->setSendcloudPickupNotifiedAt(new \DateTime());
        $this->entityManager->flush();

        $this->logger->info('[Webhook][Sendcloud] Pickup notification sent', [
            'orderId'   => $order->getId(),
            'reference' => $order->getReference(),
        ]);

        return 'sent';
    }
}
```

Note : `Order::getSendcloudParcelId()` peut valoir la sentinelle `'0'`
(`BackfillSendcloudTrackingUseCase::NO_PARCEL_SENTINEL`) — le finder l'exclut explicitement.

#### `templates/mail/mail_service_point_pickup.html.twig`

Même squelette et mêmes styles inline que `mail_delivery.html.twig`. Le nom et l'adresse du relais
viennent du payload (`parcel`), avec repli sur la commande — dont l'adresse de livraison **est** déjà
celle du point relais (`OrderAddress::fromServicePoint()` : `line2` = nom, `line1` = rue).

```twig
{% extends 'mail/base.html.twig' %}

{% block title %}Votre colis vous attend en point relais !{% endblock %}

{% block content %}
    <div class="pt-4 p-3" style="background-color: #FCFCFC">
        <div class="fw-bold ff-ovo text-center" style="color: #000000">
            Votre colis est disponible en point relais !
        </div>

        <div class="w100 mx-0 p-4 mt-4 mb-2 text-center" style="background-color: #f5f5f5; font-size: 13px !important;">
            <div class="mt-3">
                Votre commande #{{ order.reference }} est arrivée en point relais et vous y attend.

                {% set pointName = parcel.servicePointName ?? order.sendcloudServicePointName %}
                {% set pointAddress = parcel.servicePointFullAddress %}

                {% if pointName or pointAddress %}
                    <div class="mt-4">
                        {% if pointName %}
                            <b>{{ pointName }}</b><br>
                        {% endif %}
                        {% if pointAddress %}
                            {{ pointAddress }}<br>
                        {% endif %}
                        {% if parcel.carrierName %}
                            <span style="font-size: 12px !important;">Transporteur : {{ parcel.carrierName }}</span>
                        {% endif %}
                    </div>
                {% endif %}

                {% set trackingNumber = parcel.trackingNumber ?? order.sendcloudTrackingNumber %}
                {% if trackingNumber %}
                    <div class="mt-4">
                        Votre numéro de suivi : <b>{{ trackingNumber }}</b>
                    </div>
                {% endif %}

                {% set trackingUrl = parcel.trackingUrl ?? order.sendcloudTrackingUrl %}
                {% if trackingUrl %}
                    <div class="text-center">
                        <a class="btn btn-primary mt-4 text-dark" href="{{ trackingUrl }}" style="color: #fff !important;padding: 6px 12px; border-radius: 5px; background-color: #193A61; border: 1px solid #193A61; font-size: 13px !important;">
                            Suivre ma commande
                        </a>
                    </div>
                {% endif %}

                <div class="mt-4">
                    Pensez à vous munir d'une pièce d'identité pour le retrait.
                </div>
            </div>
        </div>

        <div class="mt-3" style="font-size: 13px !important;">
            Merci pour votre confiance
            <br />Votre équipe EuroCommemorative
        </div>
    </div>
{% endblock %}
```

Pas de date limite de retrait : le payload n'en transmet aucune (`date_cancel_before` concerne
l'annulation de l'étiquette, pas la rétention en relais).

#### `migrations/Version20260801120000.php`

Même forme que `migrations/Version20260712120000.php` :

```php
<?php

declare(strict_types=1);

namespace DoctrineMigrations;

use Doctrine\DBAL\Schema\Schema;
use Doctrine\Migrations\AbstractMigration;

final class Version20260801120000 extends AbstractMigration
{
    public function getDescription(): string
    {
        return 'Add sendcloud_pickup_notified_at to orders (service point pickup email guard)';
    }

    public function up(Schema $schema): void
    {
        $this->addSql('ALTER TABLE orders ADD sendcloud_pickup_notified_at DATETIME DEFAULT NULL');
    }

    public function down(Schema $schema): void
    {
        $this->addSql('ALTER TABLE orders DROP sendcloud_pickup_notified_at');
    }
}
```

#### `tests/Entity/Enum/SendcloudParcelStatusEnumTest.php`

Nouveau dossier `tests/Entity/Enum/` (l'arbo `tests/` contient `EventListener`, `Messenger`,
`Service`). `PHPUnit\Framework\TestCase` pur, comme les tests existants.

```php
public function testResolvesFromObservedNumericId(): void;      // ['id' => 12, 'message' => 'Awaiting customer pickup'] → AWAITING_CUSTOMER_PICKUP
public function testResolvesFromV3Code(): void;                 // ['code' => 'AWAITING_CUSTOMER_PICKUP'] → même cas
public function testResolvesFromMessageWhenIdUnknown(): void;   // ['id' => 999, 'message' => 'Delivered'] → DELIVERED
public function testIgnoresUnmappedNumericId(): void;           // ['id' => 3, 'message' => 'Ready to send'] → READY_TO_SEND (par le message, pas par l'id)
public function testReturnsNullForUnknownStatus(): void;        // ['code' => 'FOO'] → null
public function testOnlyAwaitingCustomerPickupTriggers(): void; // DELIVERED / UNDELIVERABLE → isAwaitingCustomerPickup() === false
```

#### `tests/Dto/Sendcloud/SendcloudParcelDTOTest.php`

Alimenté avec le **payload de production réel** (fixture inline ou
`tests/fixtures/sendcloud_parcel_awaiting_pickup.json`) :

```php
public function testReadsServicePointNameFromToAddressLine2(): void; // 'PRO ET CIE MORANDINI'
public function testBuildsFullServicePointAddress(): void;           // '12 RUE DU GENERAL LECLERC, 57390 AUDUN LE TICHE'
public function testReadsTrackingAndOrderNumber(): void;             // 'XM020261994TS' / 'F-2026-1247'
public function testFallsBackOnRootLevelKeys(): void;                // to_address absent → address_2 / address / postal_code / city
public function testReturnsNullOnEmptyStrings(): void;               // company_name-like empty values → null
```

#### `tests/Service/Sendcloud/UseCase/NotifyServicePointPickupUseCaseTest.php`

Mêmes conventions que `tests/Service/Sendcloud/SendcloudTrackingResolverTest.php` (namespace
`App\Tests\Service\Sendcloud\UseCase`, mocks PHPUnit, fabrique privée d'`Order`).

```php
public function testSendsMailAndStampsOrder(): void;             // 'sent' + setSendcloudPickupNotifiedAt + flush
public function testBackfillsServicePointNameWhenMissing(): void;// name null en base → hydraté depuis le payload
public function testDoesNotSendTwice(): void;                    // déjà tamponnée → 'already_notified', mailService jamais appelé
public function testReturnsOrderNotFoundWhenNoMatch(): void;     // repository → null → 'order_not_found'
public function testSkipsEbayOrders(): void;                     // getIsEbay() true → 'ebay_order'
public function testDoesNotStampWhenSendFails(): void;           // mail false → 'send_failed', pas de flush
```

### Modifiés

#### `src/Entity/Order.php`

Nouveau champ, déclaré juste après `sendcloudLabelGeneratedAt` (`Order.php:122`), dans le style des
champs voisins :

```php
#[ORM\Column(type: 'datetime', nullable: true)]
private ?\DateTime $sendcloudPickupNotifiedAt = null;
```

Accesseurs après `setSendcloudLabelGeneratedAt()` (`Order.php:541-546`), setter fluide comme ses
voisins :

```php
public function getSendcloudPickupNotifiedAt(): ?\DateTime
{
    return $this->sendcloudPickupNotifiedAt;
}

public function setSendcloudPickupNotifiedAt(?\DateTime $sendcloudPickupNotifiedAt): Order
{
    $this->sendcloudPickupNotifiedAt = $sendcloudPickupNotifiedAt;

    return $this;
}
```

#### `src/Repository/OrderRepository.php`

Nouveau finder, après `findEbayOrderIdsShippedMissingTracking()` (`OrderRepository.php:145-165`) :

```php
/**
 * Match a Sendcloud webhook parcel to a local order, most specific key first:
 * parcel id, then tracking number, then `order_number` — which SendcloudOrderCreator sends as
 * Order::getReference() (the F-YYYY-NNNN invoice number set by OrderListener on payment).
 *
 * The '0' sentinel written by BackfillSendcloudTrackingUseCase is excluded so that
 * "no parcel on Sendcloud" orders never match.
 */
public function findOneByParcelIdentifiers(
    ?string $parcelId,
    ?string $trackingNumber,
    ?string $orderNumber
): ?Order {
    foreach ([
        ['sendcloudParcelId', $parcelId],
        ['sendcloudTrackingNumber', $trackingNumber],
    ] as [$field, $value]) {
        if (null === $value || '' === $value || '0' === $value) {
            continue;
        }

        $order = $this->createQueryBuilder('o')
            ->where(sprintf('o.%s = :value', $field))
            ->setParameter('value', $value)
            ->orderBy('o.id', 'DESC')
            ->setMaxResults(1)
            ->getQuery()
            ->getOneOrNullResult();

        if (null !== $order) {
            return $order;
        }
    }

    if (null === $orderNumber || '' === $orderNumber) {
        return null;
    }

    return $this->createQueryBuilder('o')
        ->where('o.orderIdEbay = :value OR o.reference = :value')
        ->setParameter('value', $orderNumber)
        ->orderBy('o.id', 'DESC')
        ->setMaxResults(1)
        ->getQuery()
        ->getOneOrNullResult();
}
```

`setMaxResults(1)` évite une `NonUniqueResultException` si deux commandes portent par accident le
même numéro de suivi.

#### `src/Service/MailService.php`

Nouvelle méthode publique après `sendMailExpeditionOrder()` (`MailService.php:156-177`), dont elle
reprend le contrat `bool` — utile pour ne tamponner la commande qu'en cas de succès.

**Écart assumé** avec les autres mails clients : le sujet n'utilise **pas**
`requestStack->getCurrentRequest()->attributes->get('seo')->getTitle()`. `ConfigurationListener`
alimente bien cet attribut sur toutes les requêtes, webhook compris, mais uniquement si une ligne
`Configuration` existe ; un appel en chaîne sur `null` produirait une erreur fatale dans un point
d'entrée qui doit toujours répondre 200. On utilise le littéral `'EuroCommemorative'`, comme
`sendSendcloudLinkFailure()` (`MailService.php:247`).

Import à ajouter : `use App\Dto\Sendcloud\SendcloudParcelDTO;`

```php
/**
 * Notify the buyer that their parcel is waiting at the pickup point. Pickup point name/address are
 * read from the webhook parcel, which reflects where the parcel actually landed; the order is only
 * a fallback.
 *
 * @return bool true when the email was handed over to the transport, false when the buyer has no
 *              valid email address or when rendering/sending failed (error is logged).
 */
public function sendMailServicePointPickup(Order $order, SendcloudParcelDTO $parcel): bool
{
    if (!filter_var($order->getUser()->getEmail(), FILTER_VALIDATE_EMAIL)) {
        return false;
    }

    try {
        $message = (new Email())
            ->subject('EuroCommemorative - Votre colis est disponible en point relais')
            ->from(new Address($this->params->get('mailer_from'), 'EuroCommemorative'))
            ->to(new Address($order->getUser()->getEmail()))
            ->html($this->templating->render('mail/mail_service_point_pickup.html.twig', [
                'order'        => $order,
                'parcel'       => $parcel,
                'absolute_url' => $this->params->get('absolute_url'),
            ]));

        $this->mailer->send($message);
    } catch (Exception $e) {
        $this->logger->critical("Erreur lors de l'envoie de l'email : ".$e->getMessage());

        return false;
    }

    return true;
}
```

#### `src/Controller/WebhookController.php`

Modification de `webhookSendcloud()` (`WebhookController.php:67-100`). Le corps s'arrête aujourd'hui
après le mail de debug ; on insère la détection **après** le filtre eBay et **avant** le `return`, en
conservant l'envoi de debug tel quel (décision de chiffrage).

Imports à ajouter :

```php
use App\Dto\Sendcloud\SendcloudParcelDTO;
use App\Entity\Enum\SendcloudParcelStatusEnum;
use App\Service\Sendcloud\UseCase\NotifyServicePointPickupUseCase;
```

Nouvelle signature (2 arguments injectés en plus ; `$sendcloudConfigurationService` est conservé, il
est déjà appelé en tête de méthode) :

```php
#[Route("/sendcloud/notification", name: 'webhook_sendcloud', methods: ['POST'])]
public function webhookSendcloud(
    Request $request,
    MailService $mailService,
    SendcloudConfigurationService $sendcloudConfigurationService,
    NotifyServicePointPickupUseCase $notifyServicePointPickup,
    LoggerInterface $logger
): JsonResponse {
```

Bloc à insérer entre `$mailService->sendSendcloudWebhookDebug(...)` (ligne 97) et le `return` final
(ligne 99) :

```php
if ('parcel_status_changed' !== $action) {
    return new JsonResponse(null, 200);
}

$parcelDto = new SendcloudParcelDTO($parcel);
$status = SendcloudParcelStatusEnum::tryFromPayload($parcelDto->getStatus());

if (null === $status) {
    $logger->info('[Webhook][Sendcloud] Unrecognised parcel status', [
        'status'   => $parcelDto->getStatus(),
        'parcelId' => $parcelDto->getId(),
    ]);

    return new JsonResponse(null, 200);
}

if ($status->isAwaitingCustomerPickup()) {
    $notifyServicePointPickup->execute($parcelDto);
}

return new JsonResponse(null, 200);
```

Le use case ne lève pas : toute anomalie est journalisée et le webhook répond 200, pour que Sendcloud
ne rejoue pas indéfiniment la notification.

### Non modifiés (vérifié)

- `config/services.yaml` — l'autowiring/autoconfigure couvre `src/` ; aucun câblage explicite requis.
- `src/EventListener/OrderListener.php` — le mail d'expédition reste inchangé.
- `src/Controller/Admin/OrderCrudController.php` — pas d'action de renvoi manuel (hors périmètre,
  chiffrée en option à ~0,5 h).

## Étapes

1. **DTO du payload** — créer `src/Dto/Sendcloud/SendcloudParcelDTO.php` et
   `tests/Dto/Sendcloud/SendcloudParcelDTOTest.php` alimenté par le payload de production réel.
   Vérifiable isolément, sans base ni HTTP.

2. **Enum des statuts** — créer `src/Entity/Enum/SendcloudParcelStatusEnum.php` (35 cas, `message()`,
   `OBSERVED_IDS`, `tryFromPayload()`, `isAwaitingCustomerPickup()`) et
   `tests/Entity/Enum/SendcloudParcelStatusEnumTest.php`.

3. **Champ de traçabilité** — ajouter `sendcloudPickupNotifiedAt` + accesseurs dans
   `src/Entity/Order.php`, puis `migrations/Version20260801120000.php`.

4. **Finder** — ajouter `OrderRepository::findOneByParcelIdentifiers()`.

5. **Mail** — créer `templates/mail/mail_service_point_pickup.html.twig` puis
   `MailService::sendMailServicePointPickup()`.

6. **Use case** — créer `src/Service/Sendcloud/UseCase/NotifyServicePointPickupUseCase.php`, qui
   assemble les étapes 3 à 5, puis son test.

7. **Branchement webhook** — modifier `webhookSendcloud()` (imports, signature, bloc de détection).

8. **Recette locale** — rejouer le payload réel en curl (voir Vérification), contrôler le mail dans le
   catcher local et l'absence de second envoi.

## Vérification

Toutes les commandes passent par `scripts/repo_exec.py` (repo en `compose`, service `php-fpm-per83`,
workdir `/var/www/eurocommemo`) — jamais d'appel direct à `php`/`composer`.

### Tests automatisés

```sh
scripts/repo_exec.py src-eurocommemo -- php bin/phpunit tests/Dto/Sendcloud/SendcloudParcelDTOTest.php
scripts/repo_exec.py src-eurocommemo -- php bin/phpunit tests/Entity/Enum/SendcloudParcelStatusEnumTest.php
scripts/repo_exec.py src-eurocommemo -- php bin/phpunit tests/Service/Sendcloud/UseCase/NotifyServicePointPickupUseCaseTest.php
scripts/repo_exec.py src-eurocommemo -- php bin/phpunit
```

### Migration

```sh
scripts/repo_exec.py src-eurocommemo -- php bin/console doctrine:migrations:migrate --no-interaction
scripts/repo_exec.py src-eurocommemo -- php bin/console doctrine:schema:validate
```

`schema:validate` doit être vert sur le mapping (le champ ajouté ne doit pas générer de diff).

### Scénario manuel — déclenchement nominal (payload réel)

Enregistrer le payload de production fourni dans
`tests/fixtures/sendcloud_parcel_awaiting_pickup.json`, puis, sur une commande web de test dont
`sendcloud_parcel_id` / `reference` correspondent et `sendcloud_pickup_notified_at` est `NULL` :

```sh
curl -s -o /dev/null -w '%{http_code}\n' -X POST \
  'https://eurocommemo.orb.local/fr/sendcloud/notification' \
  -H 'Content-Type: application/json' \
  --data-binary @tests/fixtures/sendcloud_parcel_awaiting_pickup.json
```

Attendu : `200` ; mail « Votre colis est disponible en point relais » dans le catcher local, affichant
`PRO ET CIE MORANDINI`, `12 RUE DU GENERAL LECLERC, 57390 AUDUN LE TICHE`, `Chronopost` et
`XM020261994TS` ; `sendcloud_pickup_notified_at` renseigné en base.

### Scénario manuel — anti-doublon

Rejouer la même commande. Attendu : `200`, aucun second mail, la date en base inchangée, et aucune
nouvelle ligne `Pickup notification sent` dans `var/log/dev.log`.

### Scénario manuel — résolution par le message et par le code

Rejouer le payload en remplaçant `"status"` par `{"message":"Awaiting customer pickup"}` (sans `id`),
puis par `{"code":"AWAITING_CUSTOMER_PICKUP"}`, sur deux autres commandes éligibles. Attendu : mail
envoyé dans les deux cas — ce sont les chemins de repli et de compatibilité v3.

### Scénario manuel — statuts non déclencheurs

Rejouer avec `{"id":11,"message":"Delivered"}` puis `{"id":777,"message":"Totally unknown"}`. Attendu
dans les deux cas : `200`, aucun mail client. Pour le second, une ligne
`[Webhook][Sendcloud] Unrecognised parcel status` dans `var/log/dev.log`.

### Vérification en production (post-déploiement)

- Sur la première expédition Chronopost Shop2Shop réelle, confirmer la séquence complète : mail reçu
  au bon moment, contenu correct, pas de doublon sur les notifications suivantes.
- Surveiller les lignes `Unrecognised parcel status` : elles révéleraient un id non mappé dont le
  message aurait aussi changé — le seul scénario qui casserait la détection.

## Journalisation (règle du meta-repo)

Après implémentation, ajouter une entrée dans `logs/src-eurocommemo.md` au format imposé par
`.claude/rules/action-logging.md` (date, cible + branche, statut, fichiers touchés, notes).
