# Plan — Import d'une commande eBay en base depuis `GetEbayFulfillmentOrderCommand` (Fulfillment API) (2026-07-08)

**Repo** : src-eurocommemo (`~/OrbStack/docker/volumes/src-eurocommemo`) · **Risk** : medium · **Complexité** : moderate

## Contexte

`GetEbayFulfillmentOrderCommand` (`app:ebay:fulfillment-order`) est aujourd'hui **en lecture
seule** : elle récupère une commande via `FulfillmentApiV1::getOrder()` (REST/JSON) et affiche un
résumé ou le payload brut. L'objectif est qu'elle puisse aussi **persister la commande en base**,
comme le fait `ImportEbayOrderCommand` (`app:import:ebay-order`) avec la Trading API — en notant
que `ImportEbayOrderCommand` est actuellement cassée comme référence (debug `dd()` +
`file_put_contents` en `src/Command/ImportEbayOrderCommand.php:74-75`, contrôle de doublon
commenté).

Constat clé de l'exploration : depuis la migration du 2026-07-08
(`plans/2026-07-08_ebay-fulfillment-order-enrichment-address-snapshot.md`), le handler webhook
`PaymentReceiveEvent` (`src/Service/Webhook/Events/Ebay/PaymentReceiveEvent.php`) **contient déjà
un import complet basé sur la Fulfillment API** : rapprochement/création de l'acheteur, mapping
`Order` + `OrderProducts`, snapshots `OrderAddress` (livraison/facturation), service de
livraison, remise, totaux, décrément de stock, génération de facture. Sa seule dépendance externe
est le payload webhook (`PaymentReceiveEventDTO`) pour l'email / prénom / nom de l'acheteur et la
date de notification.

**Décisions validées avec l'utilisateur** :
- L'import est déclenché par une nouvelle **option `--import`** sur `app:ebay:fulfillment-order` ;
  le comportement actuel (affichage / `--raw`) est inchangé quand l'option est absente.
- La logique d'import est **extraite dans un service partagé** (`ImportFulfillmentOrderUseCase`)
  utilisé à la fois par le handler webhook et par la commande — une seule source de vérité, pas de
  troisième copie du mapping. `ImportEbayOrderCommand` (Trading) n'est pas touchée.

Les données acheteur absentes du contexte webhook sont sourcées depuis le payload Fulfillment
lui-même : `fulfillmentStartInstructions[0].shippingStep.shipTo` (nom complet, adresse, téléphone,
parfois email) et `buyer.buyerRegistrationAddress` (nom complet, email, téléphone). Le nom complet
est découpé en prénom/nom ; la valeur de masquage eBay `"Invalid Request"` (renvoyée pour les
téléphones/emails masqués) est normalisée en `null`.

Deltas de comportement acceptés côté webhook (tous deux bénins) :
- L'appel Fulfillment API a désormais lieu **avant** le contrôle du pays (auparavant après) : une
  notification avec pays inconnu coûte un appel API supplémentaire.
- Les contrôles pays / doublon / produits sont déplacés dans le use case et remontés sous forme
  d'exceptions typées ; le handler conserve son contrôle de doublon précoce pour éviter des appels
  API inutiles et envoie exactement les mêmes mails de rapport.

## Fichiers concernés

Tous dans **src-eurocommemo**.

### Nouveaux

| Fichier | Rôle |
|---------|------|
| `src/Exceptions/EbayOrderAlreadyImportedException.php` | Garde typée : commande déjà en base |
| `src/Exceptions/EbayProductsMissingException.php` | Garde typée : des lignes ne matchent aucun produit |
| `src/Service/Ebay/DTO/Input/ImportBuyerDTO.php` | Infos acheteur normalisées, 2 factories (payload webhook / payload Fulfillment) |
| `src/Service/Ebay/UseCase/ImportFulfillmentOrderUseCase.php` | Logique d'import partagée, extraite de `PaymentReceiveEvent` |

#### `src/Exceptions/EbayOrderAlreadyImportedException.php`

Même style minimal que `CountryNotFoundException` :

```php
<?php

namespace App\Exceptions;

class EbayOrderAlreadyImportedException extends \Exception
{
    public function __construct(string $orderId)
    {
        parent::__construct(sprintf('eBay order "%s" is already imported.', $orderId));
    }
}
```

#### `src/Exceptions/EbayProductsMissingException.php`

```php
<?php

namespace App\Exceptions;

class EbayProductsMissingException extends \Exception
{
}
```

#### `src/Service/Ebay/DTO/Input/ImportBuyerDTO.php`

Normalise les champs acheteur consommés par `getBuyer()` / `defineOrderInformation()` afin que le
use case ne dépende plus de `PaymentReceiveEventDTO`. Miroir champ à champ des clés de
`PaymentReceiveEventDTO::getShippingAddress()`
(`src/Service/Webhook/DTO/Ebay/PaymentReceiveEventDTO.php:33-46`).

```php
<?php

namespace App\Service\Ebay\DTO\Input;

use App\Service\Ebay\DTO\Output\Fulfillment\FulfillmentOrderDTO;
use App\Service\Webhook\DTO\Ebay\PaymentReceiveEventDTO;

class ImportBuyerDTO
{
    private const EBAY_MASKED_VALUE = 'Invalid Request';

    public function __construct(
        private readonly ?string $firstName,
        private readonly ?string $lastName,
        private readonly ?string $email,
        private readonly ?string $name,        // display name used for user matching + userNameEbay
        private readonly ?string $street1,
        private readonly ?string $street2,
        private readonly ?string $city,
        private readonly ?string $zipcode,
        private readonly ?string $countryCode, // ISO code matched against Country::codeIso
        private readonly ?string $phone,
    ) {
    }

    public static function fromPaymentReceiveEvent(PaymentReceiveEventDTO $eventDto): self
    {
        $address = $eventDto->getShippingAddress();

        return new self(
            firstName: $eventDto->getBuyerFirstname(),
            lastName: $eventDto->getBuyerLastname(),
            email: $eventDto->getBuyerEmail(),
            name: $eventDto->getName(),
            street1: $address['street1'],
            street2: $address['street2'],
            city: $address['city'],
            zipcode: $address['zipcode'],
            countryCode: $address['country'],
            phone: $address['phone'],
        );
    }

    public static function fromFulfillmentOrder(FulfillmentOrderDTO $order): self
    {
        $shipTo = $order->getShipTo();
        $registration = $order->getBuyerRegistrationAddress();
        $fullName = $shipTo?->getFullName() ?? $registration?->getFullName();
        [$firstName, $lastName] = self::splitFullName($fullName);

        return new self(
            firstName: $firstName,
            lastName: $lastName,
            email: self::maskedToNull($shipTo?->getEmail() ?? $registration?->getEmail()),
            name: $fullName,
            street1: $shipTo?->getAddressLine1(),
            street2: $shipTo?->getAddressLine2(),
            city: $shipTo?->getCity(),
            zipcode: $shipTo?->getPostalCode(),
            countryCode: $shipTo?->getCountryCode(),
            phone: self::maskedToNull($shipTo?->getPhoneNumber() ?? $registration?->getPhoneNumber()),
        );
    }

    /**
     * @return array{0: ?string, 1: ?string}
     */
    private static function splitFullName(?string $fullName): array
    {
        if ($fullName === null || trim($fullName) === '') {
            return [null, null];
        }
        $parts = explode(' ', trim($fullName), 2);

        return [$parts[0], $parts[1] ?? $parts[0]];
    }

    private static function maskedToNull(?string $value): ?string
    {
        return $value === self::EBAY_MASKED_VALUE ? null : $value;
    }

    // one getter per property:
    public function getFirstName(): ?string { /* ... */ }
    public function getLastName(): ?string { /* ... */ }
    public function getEmail(): ?string { /* ... */ }
    public function getName(): ?string { /* ... */ }
    public function getStreet1(): ?string { /* ... */ }
    public function getStreet2(): ?string { /* ... */ }
    public function getCity(): ?string { /* ... */ }
    public function getZipcode(): ?string { /* ... */ }
    public function getCountryCode(): ?string { /* ... */ }
    public function getPhone(): ?string { /* ... */ }
}
```

Notes :
- Le filtrage de `"Invalid Request"` reprend `ImportEbayOrderCommand.php:100` (téléphone) et
  l'étend à l'email, car eBay masque les données personnelles de l'acheteur sur les commandes
  anciennes.
- Heuristique de découpe du nom : premier token = prénom, reste = nom (un nom à token unique donne
  la même valeur aux deux champs, comme côté Trading où les deux champs existent toujours).

#### `src/Service/Ebay/UseCase/ImportFulfillmentOrderUseCase.php`

Extraction de la logique d'import privée de `PaymentReceiveEvent` (lignes 62–291), avec
`PaymentReceiveEventDTO` remplacé par `ImportBuyerDTO`. Placé dans le dossier existant
`src/Service/Ebay/UseCase/` (pattern : `GetEbayConfigurationUseCase`, etc.). Autowiré — aucun
changement dans `services.yaml`.

```php
<?php

namespace App\Service\Ebay\UseCase;

use App\Entity\Country;
use App\Entity\Order;
use App\Entity\OrderAddress;
use App\Entity\OrderProducts;
use App\Entity\Product;
use App\Entity\User;
use App\Exceptions\CountryNotFoundException;
use App\Exceptions\EbayOrderAlreadyImportedException;
use App\Exceptions\EbayProductsMissingException;
use App\Repository\CountryRepository;
use App\Repository\Ebay\ShippingServiceRepository;
use App\Repository\OrderRepository;
use App\Repository\ProductRepository;
use App\Repository\UserRepository;
use App\Service\CurrencyConverter;
use App\Service\Ebay\DiscountService;
use App\Service\Ebay\DTO\Input\ImportBuyerDTO;
use App\Service\Ebay\DTO\Output\Fulfillment\FulfillmentAmountDTO;
use App\Service\Ebay\DTO\Output\Fulfillment\FulfillmentLineItemDTO;
use App\Service\Ebay\DTO\Output\Fulfillment\FulfillmentOrderDTO;
use App\Service\OrderHelper;
use App\Service\RandomService;
use App\Service\StockManagementService;
use App\Utilities\GlobalConstants;
use Doctrine\ORM\EntityManagerInterface;
use Psr\Log\LoggerInterface;
use Symfony\Component\PasswordHasher\Hasher\UserPasswordHasherInterface;

class ImportFulfillmentOrderUseCase
{
    public function __construct(
        private readonly OrderRepository $orderRepository,
        private readonly CountryRepository $countryRepository,
        private readonly UserRepository $userRepository,
        private readonly EntityManagerInterface $entityManager,
        private readonly CurrencyConverter $currencyConverter,
        private readonly RandomService $randomService,
        private readonly ProductRepository $productRepository,
        private readonly DiscountService $discountService,
        private readonly StockManagementService $stockManagementService,
        private readonly OrderHelper $orderHelper,
        private readonly UserPasswordHasherInterface $userPasswordHasher,
        private readonly LoggerInterface $logger,
        private readonly ShippingServiceRepository $shippingServiceRepository,
    ) {
    }

    /**
     * @throws EbayOrderAlreadyImportedException
     * @throws CountryNotFoundException
     * @throws EbayProductsMissingException
     */
    public function execute(FulfillmentOrderDTO $orderFromEbay, ImportBuyerDTO $buyer, \DateTime $dateNotification): Order
    {
        $orderId = $orderFromEbay->getOrderId();
        if ($this->orderRepository->findOneBy(['orderIdEbay' => $orderId, 'isEbay' => true]) instanceof Order) {
            throw new EbayOrderAlreadyImportedException($orderId);
        }

        $country = $this->getCountry($buyer->getCountryCode());

        $items = $orderFromEbay->getLineItems();
        if (!$this->allItemsIsPresent($items)) {
            throw new EbayProductsMissingException(
                sprintf('Some line items of eBay order "%s" match no product (ebayId / ebayTitle).', $orderId)
            );
        }

        $order = new Order();
        $this->defineOrderInformation(
            $order,
            $buyer,
            $country,
            $dateNotification,
            $orderFromEbay->getDeliveryCost(),
            $orderFromEbay->getShipTo()?->getFullName() ?? $buyer->getName(),
            $orderFromEbay->getAdjustment()?->getPayload() ?? ['currency' => 'EUR', 'value' => 0.0],
        );
        $order->setOrderIdEbay($orderId);
        $order->setDeliveryAddress(OrderAddress::fromDto($orderFromEbay->getShipTo()));
        $order->setBillingAddress(OrderAddress::fromDto($orderFromEbay->getBuyerRegistrationAddress()));

        if ($shippingServiceToken = $orderFromEbay->getShippingServiceCode()) {
            $order->setShippingServiceCode($shippingServiceToken);
            $order->setShippingService($this->shippingServiceRepository->findOneByToken($shippingServiceToken));
        }

        $sumAmountCmd = 0;
        $sumAmountTGC = 0;
        foreach ($items as $item) {
            $this->defineOrderLine($order, $item, $sumAmountCmd, $sumAmountTGC);
        }

        if (!is_null($order->getAmountReduction())) {
            $sumAmountCmd = ($sumAmountCmd < $order->getAmountReduction()) ? 0 : $sumAmountCmd - $order->getAmountReduction();
        }
        $order->setFakeOrderIdEbay($this->orderHelper->incrementFakeNumEbay());

        $sumAmountCmd += $order->getAmountLivraison();

        $order->setAmountTva($sumAmountTGC);
        $order->setAmountCmd($sumAmountCmd);
        $order->setAmountLivraison($order->getAmountLivraison() ?? 0);
        $this->entityManager->persist($order);
        $this->entityManager->flush();

        $this->orderHelper->generateInvoice($order);

        return $order;
    }

    private function getCountry(?string $codeIso): Country
    {
        $country = $this->countryRepository->findOneBy(['codeIso' => $codeIso]);
        if (!$country) {
            throw new CountryNotFoundException();
        }

        return $country;
    }

    private function defineOrderInformation(
        Order &$order,
        ImportBuyerDTO $buyer,
        Country $country,
        \DateTime $dateNotification,
        ?FulfillmentAmountDTO $shippingCostDTO,
        string $buyerName,
        array $discountAmount = [],
    ): void {
        // body moved verbatim from PaymentReceiveEvent::defineOrderInformation (lines 162-199),
        // with two substitutions:
        //   $eventDto->getOrderId()  -> removed (setOrderIdEbay is done in execute())
        //   $this->getBuyer($eventDto, $country, $buyerName) -> $this->getBuyer($buyer, $country, $buyerName)
    }

    private function getBuyer(ImportBuyerDTO $buyer, Country $country, string $buyerName): User
    {
        // body moved verbatim from PaymentReceiveEvent::getBuyer (lines 201-244), with:
        //   $eventDto->getShippingAddress()['zipcode'] -> $buyer->getZipcode()
        //   $eventDto->getShippingAddress()['city']    -> $buyer->getCity()
        //   $eventDto->getBuyerEmail()                 -> $buyer->getEmail()
        //   $eventDto->getBuyerFirstname()             -> $buyer->getFirstName()
        //   $eventDto->getBuyerLastname()              -> $buyer->getLastName()
        //   $eventDto->getName()                       -> $buyer->getName()
        //   $eventDto->getShippingAddress()['street2'] -> $buyer->getStreet2()
        //   $eventDto->getShippingAddress()['street1'] -> $buyer->getStreet1()
        //   $eventDto->getShippingAddress()['phone']   -> $buyer->getPhone()
    }

    /**
     * @param FulfillmentLineItemDTO[] $items
     */
    private function allItemsIsPresent(array $items): bool
    {
        // moved verbatim from PaymentReceiveEvent::allItemsIsPresent (lines 246-252)
    }

    private function defineOrderLine(Order &$order, FulfillmentLineItemDTO $item, float &$sumAmountCmd, float &$sumAmountTGC): void
    {
        // moved verbatim from PaymentReceiveEvent::defineOrderLine (lines 254-290):
        // product lookup by ebayId=legacyItemId then ebayTitle, critical log if absent,
        // unit price from lineItemCost with EUR conversion, TTC/TGC/HT amounts,
        // stockManagementService->execute(PLATFORM_EBAY, ...)
    }
}
```

Note : dans le code webhook actuel, `setOrderIdEbay($eventDto->getOrderId())` utilise le
`ContainingOrder.OrderID` du webhook, qui est le même identifiant que celui interrogé sur la
Fulfillment API (`fulfillmentApi->getOrder($eventDto->getOrderId())` fonctionne aujourd'hui) —
basculer la valeur stockée vers `FulfillmentOrderDTO::getOrderId()` préserve donc le comportement
du webhook et est correct pour la commande.

### Modifiés

| Fichier | Changement |
|---------|-----------|
| `src/Command/GetEbayFulfillmentOrderCommand.php` | Nouvelle option `--import` déléguant au use case |
| `src/Service/Webhook/Events/Ebay/PaymentReceiveEvent.php` | Délègue au use case ; conserve le check Ack, le check doublon précoce, l'appel API et les mails de rapport |

#### `src/Command/GetEbayFulfillmentOrderCommand.php`

Le constructeur (ligne 16) reçoit le use case :

```php
public function __construct(
    private readonly FulfillmentApiV1 $fulfillmentApi,
    private readonly ImportFulfillmentOrderUseCase $importFulfillmentOrder,
) {
    parent::__construct();
}
```

`configure()` (lignes 22–27) gagne une option :

```php
->addOption("import", "i", InputOption::VALUE_NONE, "Persist the order into the database (like app:import:ebay-order)")
```

`execute()` (lignes 29–66) : après le fetch existant et la gestion de `--raw`, brancher avant
l'affichage du résumé :

```php
if ($input->getOption("import")) {
    return $this->import($order, $output);
}
```

Nouvelle méthode privée :

```php
private function import(FulfillmentOrderDTO $order, OutputInterface $output): int
{
    $buyer = ImportBuyerDTO::fromFulfillmentOrder($order);

    if ($buyer->getEmail() === null) {
        $output->writeln("<error>Buyer email is not exposed in the Fulfillment payload for this order — cannot match/create the user.</error>");

        return Command::FAILURE;
    }

    $createdAt = $order->getCreationDate() !== null
        ? \DateTime::createFromImmutable($order->getCreationDate())
        : new \DateTime();

    try {
        $imported = $this->importFulfillmentOrder->execute($order, $buyer, $createdAt);
    } catch (EbayOrderAlreadyImportedException) {
        $output->writeln("Order already imported");

        return Command::SUCCESS;
    } catch (CountryNotFoundException) {
        $output->writeln(sprintf("<error>Country not found: %s</error>", $buyer->getCountryCode() ?? 'null'));

        return Command::FAILURE;
    } catch (EbayProductsMissingException $exception) {
        $output->writeln(sprintf("<error>%s</error>", $exception->getMessage()));

        return Command::FAILURE;
    }

    $output->writeln(sprintf("Order imported (id: %d, reference: %s)", $imported->getId(), $imported->getReference()));

    return Command::SUCCESS;
}
```

Nouveaux imports : `App\Exceptions\CountryNotFoundException`,
`App\Exceptions\EbayOrderAlreadyImportedException`, `App\Exceptions\EbayProductsMissingException`,
`App\Service\Ebay\DTO\Input\ImportBuyerDTO`,
`App\Service\Ebay\DTO\Output\Fulfillment\FulfillmentOrderDTO`,
`App\Service\Ebay\UseCase\ImportFulfillmentOrderUseCase`.

`createdAt` utilise la `creationDate` Fulfillment afin qu'une commande importée manuellement garde
sa vraie date eBay (miroir de `ImportEbayOrderCommand.php:79` qui utilise le `CreatedDate` de la
transaction).

#### `src/Service/Webhook/Events/Ebay/PaymentReceiveEvent.php`

Le constructeur (lignes 37–55) se réduit aux dépendances réellement utilisées après délégation :

```php
public function __construct(
    private readonly OrderRepository $orderRepository,
    private readonly FulfillmentApiV1 $fulfillmentApi,
    private readonly MailService $mailService,
    private readonly ImportFulfillmentOrderUseCase $importFulfillmentOrder,
) {
}
```

`handle()` (lignes 62–141) devient :

```php
public function handle(array $webhookData, \DateTime $dateNotification): void
{
    if ($webhookData['Ack'] !== 'Success') {
        $this->sendReportMail(
            $webhookData['TransactionArray']['Transaction']['ContainingOrder']['OrderID'],
            'failure_webhook'
        );

        return;
    }

    $eventDto = new PaymentReceiveEventDTO($webhookData);
    // Early duplicate check kept: avoids a Fulfillment API call on webhook redeliveries.
    if ($this->orderRepository->findOneBy(['orderIdEbay' => $eventDto->getOrderId(), 'isEbay' => true])) {
        return;
    }

    $orderFromEbay = $this->fulfillmentApi->getOrder($eventDto->getOrderId());

    try {
        $order = $this->importFulfillmentOrder->execute(
            $orderFromEbay,
            ImportBuyerDTO::fromPaymentReceiveEvent($eventDto),
            $dateNotification
        );
    } catch (EbayOrderAlreadyImportedException) {
        return;
    } catch (CountryNotFoundException) {
        $this->sendReportMail(
            $eventDto->getOrderId(),
            'country_not_found',
            $eventDto->getShippingAddress()['country']
        );

        return;
    } catch (EbayProductsMissingException) {
        return; // current behavior: skip silently, a later notification retry may succeed
    }

    $this->sendReportMail($order->getOrderIdEbay(), 'success', internalId: $order->getId());
}
```

`sendReportMail()` (lignes 143–152) inchangée. Les méthodes privées déplacées (`getCountry`,
`defineOrderInformation`, `getBuyer`, `allItemsIsPresent`, `defineOrderLine`) et leurs imports
devenus inutiles sont supprimés. Sémantique préservée : mêmes mails de rapport, mêmes retours
silencieux, même résolution du nom acheteur (`shipTo fullName ?? eventDto name`, désormais dans le
use case), mêmes calculs remise/livraison/totaux.

## Étapes d'implémentation

1. Créer `src/Exceptions/EbayOrderAlreadyImportedException.php` et
   `src/Exceptions/EbayProductsMissingException.php`.
2. Créer `src/Service/Ebay/DTO/Input/ImportBuyerDTO.php` (les deux factories + getters).
3. Créer `src/Service/Ebay/UseCase/ImportFulfillmentOrderUseCase.php` en déplaçant la logique
   d'import hors de `PaymentReceiveEvent` (substitutions listées ci-dessus).
4. Refactorer `src/Service/Webhook/Events/Ebay/PaymentReceiveEvent.php` pour déléguer au use case
   (constructeur allégé + nouveau corps de `handle()`).
5. Ajouter le chemin `--import` dans `src/Command/GetEbayFulfillmentOrderCommand.php`.
6. Rafraîchir le knowledge graph (règle du meta-repo) :
   `graphify extract <repo-path> --out docs/src-eurocommemo --exclude '*.md' ...` puis
   `graphify cluster-only docs/src-eurocommemo --no-label`.
7. Ajouter l'entrée de log d'action dans `logs/src-eurocommemo.md` (règle du meta-repo).

Les étapes 1–2 sont indépendantes ; 3 dépend de 1–2 ; 4–5 dépendent de 3.

## DAG d'exécution

N/A — plan préalable produit par `/plan-writer` (pas de DAG). Lancer le skill `planner` si un DAG
machine est nécessaire.

## Vérification

Aucune suite de tests n'existe dans le repo (`tests/` ne contient que `bootstrap.php`) : la
vérification passe par le lint du conteneur + des scénarios manuels. Toutes les commandes passent
par `scripts/repo_exec.py` (mode compose, service `php-fpm-per83`), jamais `php`/`composer` en
direct sur l'hôte.

1. **Câblage du conteneur** : `php bin/console lint:container` (via `repo_exec.py`) — valide
   l'autowiring du nouveau use case et du handler webhook allégé.
2. **Non-régression lecture seule** : `php bin/console app:ebay:fulfillment-order -o <orderId>` et
   `--raw` — sortie identique à avant (sans `--import`).
3. **Import** : `php bin/console app:ebay:fulfillment-order -o <orderId> --import` sur une vraie
   commande sandbox/production **absente de la base**. Vérifier en base : une ligne `order`
   (`isEbay=1`, `orderIdEbay`, `fakeOrderIdEbay` incrémenté, montants TTC/TGC cohérents), lignes
   `order_products`, lignes `OrderAddress` livraison/facturation, `user` rapproché ou créé, stock
   décrémenté, facture générée.
4. **Idempotence** : relancer la même commande → `Order already imported`, code retour 0, pas de
   seconde ligne.
5. **Chemins d'erreur** : code ISO pays inconnu et titre produit inconnu → message d'erreur
   explicite, code retour 1, rien de persisté.
6. **Non-régression webhook** (staging) : rejouer une Platform Notification eBay → commande
   importée à l'identique, mail de rapport `success` envoyé ; redelivery de la même notification →
   skip silencieux.
