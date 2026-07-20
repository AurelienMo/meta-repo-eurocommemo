# Plan — Création de la commande Sendcloud post-paiement (livraison point relais)

## Contexte

Aujourd'hui, quand un client choisit une livraison en **point relais** dans le tunnel d'achat,
seule la sélection est **persistée en local** sur l'entité `Order` (`sendcloudShippingOptionCode`,
`sendcloudServicePointId`, `sendcloudServicePointName`, `amountLivraison`, adresse de livraison =
adresse du point). **Aucune commande n'est créée sur Sendcloud** : toute la machinerie d'écriture
Sendcloud (liaison, étiquette, suivi) est verrouillée derrière `getIsEbay()` et n'est nourrie que
par l'import eBay — pour les commandes web, rien n'est poussé, ni automatiquement ni manuellement.

Objectif : **après un paiement validé** pour une commande web (non-eBay) en point relais, **créer
la commande sur Sendcloud** (endpoint v3 `POST /api/v3/orders`, en asynchrone via Messenger),
stocker l'`id` Sendcloud retourné sur l'`Order`, puis **débrider le back-office** pour que ces
commandes soient gérables comme les commandes eBay (générer l'étiquette, récupérer le suivi).

Faits techniques vérifiés (exploration + doc API) :
- **API Sendcloud v3 création** : `POST https://panel.sendcloud.sc/api/v3/orders`. Le corps est un
  **tableau** d'objets order. Réponse `201` : `{ "data": [ { "id": <int>, "order_id": "...",
  "order_number": "..." } ] }`. Champs requis par order : `order_id`, `order_number`,
  `order_details` (`integration.id`, `status.code`, `order_created_at`, `order_items[]` avec
  `name`/`quantity`/`total_price`), `payment_details` (`total_price`, `status.code`),
  `shipping_address` (`name`, `address_line_1`, `postal_code`, `city`, `country_code`). Le point
  relais s'attache via `service_point_details.id` et la méthode via
  `shipping_details.ship_with = { type: "shipping_option_code", properties: { shipping_option_code }}`.
  (Source : doc API Sendcloud v3 — https://sendcloud.dev/api/v3/orders/create-update-orders-in-batch.md)
- Le client `SendcloudApiClient` n'a **aucune** méthode de création (uniquement getOrders / updateOrder
  PATCH / createLabelSync / getServicePoints / getShippingOptions / getParcel / downloadLabelPdf).
  Le pattern d'écriture à recopier est `updateOrder()` (`SendcloudApiClient.php:291-312`) via le
  builder central `request()` (`:379-408`, auth Basic depuis `SendcloudConfiguration`, `http_errors=>false`,
  lève `ExternalSendcloudApiException` sur non-2xx).
- `integration_id` : `SendcloudConfigurationService::getConfiguration()->getIntegrationId(): ?int`.
- Tous les champs Sendcloud nécessaires **existent déjà** sur `Order` (`Order.php:104-125`) →
  **aucune migration**.
- Poids : `Order::getTotalWeightKg()` existe déjà (`Order.php:546-555`, poids `Product` en grammes).
- Point d'ancrage post-paiement : le **listener Doctrine centralisé** `OrderListener::onFlush()`
  (`src/EventListener/OrderListener.php:69-88`) qui réagit déjà à la transition `statePayment → VALID`
  pour **les 4 méthodes** (CB, PayPal, **chèque, virement**) et y régénère la référence + envoie le
  mail de confirmation. C'est le seul point traversé par toutes les validations, quelle que soit la
  méthode :
  - CB → `VALID` dans `PaymentController::donePaymentCBAction()` (IPN Payzen) ;
  - PayPal → `VALID` via `OrderHelper::validPayment()` dans `PaymentController` (capture) ;
  - **chèque/virement** → créés en `CONST_STATE_PAYMENT_WAITING_RECEIPT` au tunnel
    (`OrderController.php:335-351`), puis passés à `VALID` **manuellement en back-office** par
    l'opérateur via `OrderCrudController::admin_payment_validate()`
    (route `app_admin_order_payment_validate`, `:520-531`).
  Toutes ces validations déclenchent un `flush()` → `OrderListener::onFlush()`. Dispatcher la
  création Sendcloud depuis ce hook (en **`postFlush`**, pour ne pas insérer le message en plein
  `onFlush`) couvre donc automatiquement CB, PayPal ET chèque/virement.
- Constantes utiles (`src/Utilities/GlobalConstants.php:22-32`) : méthodes
  `CONST_METHOD_PAYMENT_CHEQUE=1`, `VIREMENT=2`, `PAYPAL=3`, `CB=4` ; états
  `CONST_STATE_PAYMENT_PROCESS=0`, `VALID=1`, `WAITING_RECEIPT=2`, `CANCEL=3`, `FAILED=4`.
- Template Messenger existant à copier : `AssociateSendcloudOrderIdMessage` +
  `AssociateSendcloudOrderIdHandler` (transport `async_sendcloud`, retry 10× backoff exp.,
  `config/packages/messenger.yaml`).

Décision de conception :
- **Identifiant externe Sendcloud** (`order_id`) : les commandes web n'ont pas d'`orderIdEbay`.
  On introduit `Order::getSendcloudExternalOrderId(): ?string` = `orderIdEbay ?? reference`. Il est
  utilisé à la fois pour la création (`order_id` du payload) et dans `SendcloudLabelService`
  (aujourd'hui codé en dur sur `getOrderIdEbay()`), sans changer le comportement eBay
  (`orderIdEbay` non nul) tout en activant le web (`reference`).
- **Déclenchement centralisé sur la transition VALID** : le dispatch se fait dans `OrderListener`
  (hook unique pour CB/PayPal/chèque/virement), et **non** dans `PaymentController` (qui ne couvre
  que les paiements en ligne et raterait chèque/virement). Filtres au déclenchement : commande
  **web** (`!getIsEbay()`), **point relais** (`null !== getSendcloudServicePointId()`), et **pas
  déjà créée** (`sendcloudOrderId ∈ {null, '0'}`). Conséquence attendue :
  - CB / PayPal → créée sur Sendcloud dès la validation du paiement en ligne ;
  - **chèque / virement → créée sur Sendcloud au moment où l'opérateur confirme la réception du
    paiement en back-office** (pas avant : la commande est en attente jusque-là).
  Extensible plus tard à la livraison Sendcloud à domicile (retirer le filtre point relais).
- **Gestion back-office** : on remplace le verrou `getIsEbay()` par un nouveau
  `Order::isSendcloudManaged(): bool` = `getIsEbay() || null !== getSendcloudOrderId()`. Une
  commande web devient gérable dès qu'elle a reçu son `sendcloudOrderId` (après création async).
- **Devise** : `EUR` (opération FR→FR, cf. quotes point relais existants). ⚠ Si la boutique
  facture en XPF/TGC, l'enum Sendcloud (`EUR|GBP|USD`) refusera — à confirmer côté métier
  (voir Vérification). Isolée dans une constante `SendcloudOrderCreator::CURRENCY`.

## Fichiers concernés

Tous dans le repo **`src-eurocommemo`**.

### Nouveaux

#### `src/Messenger/Message/CreateSendcloudOrderMessage.php`

Message asynchrone (copie stricte de `AssociateSendcloudOrderIdMessage`).

```php
<?php

namespace App\Messenger\Message;

class CreateSendcloudOrderMessage
{
    public function __construct(private readonly int $orderId)
    {
    }

    public function getOrderId(): int
    {
        return $this->orderId;
    }
}
```

#### `src/Messenger/Handler/CreateSendcloudOrderHandler.php`

Handler idempotent (calqué sur `AssociateSendcloudOrderIdHandler`). Refetch, garde si déjà créé,
délègue la construction du payload + l'appel API à `SendcloudOrderCreator`, log. Toute exception
remonte → retries `async_sendcloud`.

```php
<?php

namespace App\Messenger\Handler;

use App\Entity\Order;
use App\Messenger\Message\CreateSendcloudOrderMessage;
use App\Repository\OrderRepository;
use App\Service\Sendcloud\SendcloudOrderCreator;
use Psr\Log\LoggerInterface;
use Symfony\Component\Messenger\Attribute\AsMessageHandler;

#[AsMessageHandler]
class CreateSendcloudOrderHandler
{
    public function __construct(
        private readonly OrderRepository $orderRepository,
        private readonly SendcloudOrderCreator $creator,
        private readonly LoggerInterface $logger,
    ) {
    }

    public function __invoke(CreateSendcloudOrderMessage $message): void
    {
        $order = $this->orderRepository->find($message->getOrderId());
        if (!$order instanceof Order) {
            return;
        }
        // Idempotent: already created on Sendcloud.
        if (!in_array($order->getSendcloudOrderId(), [null, '0'], true)) {
            return;
        }
        // Only relay (service point) web orders are in scope for now.
        if (null === $order->getSendcloudServicePointId()) {
            return;
        }

        $this->creator->createForOrder($order);

        $this->logger->info('[Sendcloud] Web relay order created', [
            'orderId' => $order->getId(),
            'sendcloudOrderId' => $order->getSendcloudOrderId(),
        ]);
    }
}
```

#### `src/Service/Sendcloud/SendcloudOrderCreator.php`

Service dédié à la construction du payload v3 et à l'écriture retour sur l'`Order` (le handler ne
flush pas lui-même : le creator flush via l'EntityManager, comme le fait le back-office ; on injecte
l'EM pour rester cohérent avec les autres services Sendcloud qui laissent le caller flusher — ici on
flush dans le creator car le handler n'a pas d'EM). Miroir structurel de `SendcloudOrderShippingService`.

```php
<?php

namespace App\Service\Sendcloud;

use App\Entity\Order;
use App\Exceptions\ExternalSendcloudApiException;
use Doctrine\ORM\EntityManagerInterface;

class SendcloudOrderCreator
{
    private const CURRENCY = 'EUR';
    private const ORDER_STATUS_CODE = 'fulfilled';   // ⚠ à confirmer (cf. Vérification)
    private const PAYMENT_STATUS_CODE = 'paid';

    public function __construct(
        private readonly SendcloudApiClient $apiClient,
        private readonly SendcloudConfigurationService $configurationService,
        private readonly EntityManagerInterface $entityManager,
    ) {
    }

    /**
     * Create the order on Sendcloud (v3), store the returned id + selection on the local Order.
     *
     * @throws ExternalSendcloudApiException
     * @throws \InvalidArgumentException
     */
    public function createForOrder(Order $order): void
    {
        $integrationId = $this->configurationService->getConfiguration()->getIntegrationId();
        if (null === $integrationId) {
            throw new \InvalidArgumentException('Sendcloud integration_id non configuré.');
        }

        $externalId = $order->getSendcloudExternalOrderId();
        if (null === $externalId) {
            throw new \InvalidArgumentException('Commande sans identifiant externe Sendcloud.');
        }

        $dto = $this->apiClient->createOrder($this->buildPayload($order, $integrationId, $externalId));

        $order->setSendcloudOrderId((string) $dto->getId());
        $this->entityManager->flush();
    }

    /**
     * @return array<string, mixed> a single Sendcloud v3 order object
     */
    private function buildPayload(Order $order, int $integrationId, string $externalId): array
    {
        $address = $order->getDeliveryAddress();
        if (null === $address) {
            throw new \InvalidArgumentException('Commande sans adresse de livraison.');
        }
        $user = $order->getUser();

        $items = [];
        foreach ($order->getOrderProducts() as $line) {
            $product = $line->getProduct();
            $item = [
                'name' => (string) $product->getTitle(),
                'quantity' => (int) $line->getQuantity(),
                'total_price' => [
                    'value' => (float) $line->getAmountProductVenteLineTTC(),
                    'currency' => self::CURRENCY,
                ],
                'unit_price' => [
                    'value' => (float) $line->getAmountProductVenteUnitTTC(),
                    'currency' => self::CURRENCY,
                ],
            ];
            if (null !== $product->getReference()) {
                $item['sku'] = (string) $product->getReference();
            }
            if (null !== $product->getWeight()) {
                $item['measurement'] = ['weight' => ['value' => (int) $product->getWeight(), 'unit' => 'g']];
            }
            $items[] = $item;
        }

        return [
            'order_id' => $externalId,
            'order_number' => (string) $order->getReference(),
            'order_details' => [
                'integration' => ['id' => $integrationId],
                'status' => ['code' => self::ORDER_STATUS_CODE, 'message' => 'Fulfilled'],
                'order_created_at' => $order->getCreatedAt()->format(\DateTimeInterface::ATOM),
                'order_items' => $items,
            ],
            'payment_details' => [
                'total_price' => ['value' => (float) $order->getAmountCmd(), 'currency' => self::CURRENCY],
                'status' => ['code' => self::PAYMENT_STATUS_CODE, 'message' => 'Paid'],
            ],
            'shipping_address' => array_filter([
                'name' => (string) $address->getFullName(),
                'address_line_1' => $address->getLine1(),
                'address_line_2' => $address->getLine2(),
                'postal_code' => $address->getPostalCode(),
                'city' => $address->getCity(),
                'country_code' => $address->getCountryCode(),
                'phone_number' => $address->getPhone(),
                'email' => $user->getEmail(),
            ], static fn ($v) => null !== $v && '' !== $v),
            'customer_details' => array_filter([
                'name' => trim($user->getFirstName().' '.$user->getLastName()),
                'email' => $user->getEmail(),
                'phone_number' => $address->getPhone() ?: $user->getPhone(),
            ], static fn ($v) => null !== $v && '' !== $v),
            'shipping_details' => [
                'measurement' => ['weight' => ['value' => $order->getTotalWeightKg(), 'unit' => 'kg']],
                'ship_with' => [
                    'type' => 'shipping_option_code',
                    'properties' => ['shipping_option_code' => (string) $order->getSendcloudShippingOptionCode()],
                ],
            ],
            'service_point_details' => ['id' => (string) $order->getSendcloudServicePointId()],
        ];
    }
}
```

> ✔ **Signatures vérifiées dans le code réel** : `User::getEmail()` (`User.php:121`),
> `getFirstName()` (`:193`), `getLastName()` (`:202`), `getPhone()` (`:211`) ;
> `Product::getTitle()` (`:497`, via `translate('fr')->getTitle()`), `getReference()` (`:123`),
> `getWeight()` (`:230`) ; `OrderProducts::getAmountProductVenteLineTTC()` (`:96`),
> `getAmountProductVenteUnitTTC()` (`:87`) ; `Order::getAmountCmd()` (`:212`), `getReference()`
> (`:302`), `getCreatedAt()` (trait `TimestampableTrait`).

### Modifiés

#### `src/Service/Sendcloud/SendcloudApiClient.php`

Ajouter la méthode `createOrder()` après `updateOrder()` (`:312`), en réutilisant la constante
`ENDPOINT_ORDERS` (`:17`) et le builder `request()`. Le body de l'API est un **tableau** → on
enveloppe l'objet dans `[$order]` et on lit `data[0]`. Retour typé `SendcloudOrderDTO` (déjà importé
`:5`).

```php
    /**
     * Create a single order on Sendcloud (v3 batch endpoint, wrapped in a 1-element array).
     *
     * @param array<string, mixed> $order a Sendcloud v3 order object
     *
     * @throws ExternalSendcloudApiException
     */
    public function createOrder(array $order): SendcloudOrderDTO
    {
        $response = $this->request('POST', self::PREFIX_URL.self::ENDPOINT_ORDERS, [
            'json' => [$order],
            'http_errors' => false,
        ]);
        $decoded = json_decode($response->getBody()->getContents(), true) ?? [];
        $data = $decoded['data'][0] ?? null;
        if (null === $data || !isset($data['id'])) {
            throw new ExternalSendcloudApiException('Invalid Sendcloud create-order response: '.json_encode($decoded));
        }

        return new SendcloudOrderDTO($data);
    }
```

#### `src/Entity/Order.php`

Deux helpers, à placer près des getters Sendcloud (après `getSendcloudLabelGeneratedAt`/`getTotalWeightKg`,
`:544-555`).

```php
    /** External id used as Sendcloud `order_id`: eBay id when present, else the local reference. */
    public function getSendcloudExternalOrderId(): ?string
    {
        return $this->orderIdEbay ?? $this->reference;
    }

    /** True when the order is managed on Sendcloud (eBay order, or a Sendcloud order already created). */
    public function isSendcloudManaged(): bool
    {
        return true === $this->isEbay || !in_array($this->sendcloudOrderId, [null, '0'], true);
    }
```

#### `src/Service/Sendcloud/SendcloudLabelService.php`

Rendre `generateLabel()` agnostique eBay : remplacer l'usage de `getOrderIdEbay()` (`:39`) par le
nouvel identifiant externe. Avant/après :

```php
// AVANT (SendcloudLabelService.php:39)
$result = $this->apiClient->createLabelSync((string) $order->getOrderIdEbay(), $integrationId);

// APRÈS
$result = $this->apiClient->createLabelSync((string) $order->getSendcloudExternalOrderId(), $integrationId);
```

#### `src/EventListener/OrderListener.php`

**Point de déclenchement unique.** Ce listener réagit déjà à la transition `statePayment → VALID`
pour les 4 méthodes (`OrderListener.php:69-88`). On y ajoute la collecte des commandes web point
relais à créer sur Sendcloud, puis on dispatche en **`postFlush`** (jamais en plein `onFlush` : un
`MessageBusInterface::dispatch()` insère dans la table `messenger_messages` via le transport
`doctrine://default`, ce qui n'est pas sûr pendant l'`onFlush` en cours).

1. Imports (après `:12`) et constructeur (`:20-25`) :

```php
use App\Messenger\Message\CreateSendcloudOrderMessage;
use Doctrine\ORM\Event\PostFlushEventArgs;
use Symfony\Component\Messenger\MessageBusInterface;

// constructeur — ajouter le paramètre
private readonly MailService $mailService,
private readonly MessageBusInterface $messageBus,
```

2. Nouvelle propriété tampon (les ids collectés pendant `onFlush`, dispatchés en `postFlush`) :

```php
    /** @var int[] Web relay order ids that just became VALID, to create on Sendcloud after flush. */
    private array $sendcloudOrdersToCreate = [];
```

3. Dans le bloc « Order payment validate » (`onFlush`, à l'intérieur du `if` `:70-73`, après l'envoi
   du mail `:87`), collecter les commandes éligibles :

```php
                    // ... après le bloc "Send Email Confirmation order" existant
                    if (!$entity->getIsEbay()
                        && null !== $entity->getSendcloudServicePointId()
                        && in_array($entity->getSendcloudOrderId(), [null, '0'], true)) {
                        $this->sendcloudOrdersToCreate[] = $entity->getId();
                    }
```

4. Nouvelle méthode `postFlush()` qui vide le tampon et dispatche (post-commit) :

```php
    public function postFlush(PostFlushEventArgs $args): void
    {
        if ([] === $this->sendcloudOrdersToCreate) {
            return;
        }

        $orderIds = $this->sendcloudOrdersToCreate;
        $this->sendcloudOrdersToCreate = [];

        foreach ($orderIds as $orderId) {
            $this->messageBus->dispatch(new CreateSendcloudOrderMessage($orderId));
        }
    }
```

> Couverture : CB/PayPal passent `VALID` + flush via `PaymentController` → `onFlush`/`postFlush` ;
> chèque/virement passent `VALID` + flush via `OrderCrudController::admin_payment_validate()` →
> mêmes hooks. **Aucune modification de `PaymentController` ni de `OrderCrudController`** n'est
> nécessaire pour le déclenchement (le listener capte toutes les validations). `$entity->getId()`
> est défini (commande persistée au tunnel).

#### `config/services.yaml`

Enregistrer le nouvel événement `postFlush` sur `OrderListener` (bloc `:48-50`, à côté du tag
`onFlush` existant) :

```yaml
    App\EventListener\OrderListener:
        tags:
            - { name: doctrine.event_listener, event: onFlush, entity: 'App\Entity\Order'}
            - { name: doctrine.event_listener, event: postFlush }
```

#### `config/packages/messenger.yaml`

Router le nouveau message vers `async_sendcloud` (bloc `routing:`, à côté des deux autres) :

```yaml
        routing:
            'App\Messenger\Message\CreateEbayAsyncMessage': async_create_ebay
            'App\Messenger\Message\AssociateSendcloudOrderIdMessage': async_sendcloud
            'App\Messenger\Message\BackfillSendcloudTrackingMessage': async_sendcloud
            'App\Messenger\Message\CreateSendcloudOrderMessage': async_sendcloud
```

#### `src/Controller/Admin/OrderCrudController.php`

Débrider les actions Sendcloud pour les commandes web point relais en remplaçant le verrou
`!$order->getIsEbay()` (ou `$entity->getIsEbay()`) par `!$order->isSendcloudManaged()` /
`$entity->isSendcloudManaged()` là où le point relais web doit être géré. Détail par emplacement :

- `resolveSendcloudTracking` action `displayIf` (`:223`) : `getIsEbay()` → `isSendcloudManaged()`.
- `resolveSendcloudTracking()` méthode, garde `:449` : `!$order->getIsEbay()` → `!$order->isSendcloudManaged()`.
- `sendcloudShippingOptionsBatch()` boucle `:594` : `!$order->getIsEbay()` → `!$order->isSendcloudManaged()`.
- `sendcloudShippingOptions()` `:641` : `!$order->getIsEbay()` → `!$order->isSendcloudManaged()`.
- `sendcloudApplyShipping()` `:700` : `!$order->getIsEbay()` → `!$order->isSendcloudManaged()`
  (les 3 autres conditions — statePayment VALID, dateExpedition null, sendcloudOrderId présent —
  restent inchangées).
- `sendcloudGenerateLabel()` `:739` : idem `:700`.

Laisser **inchangé** :
- `syncSendcloud` (action `displayIf` `:201` + garde `:398`) : spécifique eBay (lie via
  `SendcloudOrderLinker::matchSendcloudId()` sur l'id eBay). Les commandes web sont créées
  directement, elles n'ont pas besoin du sync → rester `getIsEbay()`.
- Les gardes `admin_delivery_validate()` (`:542/548/555`) : flux de confirmation d'expédition eBay,
  hors périmètre de cette feature.

Exemple avant/après (`sendcloudApplyShipping`, `:700-703`) :

```php
// AVANT
if (!$order->getIsEbay()
    || $order->getStatePayment() !== GlobalConstants::CONST_STATE_PAYMENT_VALID
    || null !== $order->getDateExpedition()
    || in_array($order->getSendcloudOrderId(), [null, '0'], true)) {

// APRÈS
if (!$order->isSendcloudManaged()
    || $order->getStatePayment() !== GlobalConstants::CONST_STATE_PAYMENT_VALID
    || null !== $order->getDateExpedition()
    || in_array($order->getSendcloudOrderId(), [null, '0'], true)) {
```

#### `templates/admin/order/order_sendcloud_action.html.twig`

Le panneau entier est gardé par `and entity.instance.isEbay` (`:3`). Remplacer par le helper pour
afficher aussi le panneau des commandes web gérées sur Sendcloud :

```twig
{% if entity.instance.statePayment == constant('App\\Utilities\\GlobalConstants::CONST_STATE_PAYMENT_VALID')
    and entity.instance.dateExpedition is null
    and entity.instance.isSendcloudManaged
    and entity.instance.sendcloudOrderId is not null
    and entity.instance.sendcloudOrderId != '0' %}
```

Le reste du template (selects, boutons `.btn-sendcloud-apply` / `.btn-sendcloud-generate-label`,
bloc suivi) et `assets/back/js/back.js` **ne changent pas** : le JS lit les routes via `data-*` et
n'a aucun test eBay ; les services `SendcloudOrderShippingService` / `SendcloudLabelService` sont
déjà agnostiques.

#### `templates/admin/order/order_ebay_shipping_service.html.twig`

Le lien « Voir sur Sendcloud » (`:19`) est conditionné à `entity.instance.orderIdEbay` et pointe une
recherche Sendcloud par id eBay — inopérant pour une commande web. Élargir la condition et l'URL à
l'identifiant externe générique :

```twig
{% set sendcloudSearch = entity.instance.orderIdEbay ?? entity.instance.reference %}
{% if sendcloudOrderId is not null and sendcloudOrderId != '0' and sendcloudSearch %}
    <div class="mt-1">
        <a href="https://app.sendcloud.com/v2/shipping/list/orders?search={{ sendcloudSearch|url_encode }}"
           class="fw-bold text-primary" target="_blank">Voir sur Sendcloud</a>
    </div>
{% endif %}
```

## Étapes

1. **Client API** — ajouter `SendcloudApiClient::createOrder()` (`src/Service/Sendcloud/SendcloudApiClient.php`).
2. **Entité** — ajouter `Order::getSendcloudExternalOrderId()` et `Order::isSendcloudManaged()`
   (`src/Entity/Order.php`).
3. **Étiquette** — basculer `SendcloudLabelService::generateLabel()` sur
   `getSendcloudExternalOrderId()` (`src/Service/Sendcloud/SendcloudLabelService.php`).
4. **Service de création** — créer `SendcloudOrderCreator` (`src/Service/Sendcloud/SendcloudOrderCreator.php`) ;
   vérifier au passage les getters `User` (email/first/last/phone) et `Product::getTitle()`.
5. **Messenger** — créer `CreateSendcloudOrderMessage` + `CreateSendcloudOrderHandler`, puis router
   le message dans `config/packages/messenger.yaml` (`async_sendcloud`).
6. **Déclenchement centralisé** — injecter `MessageBusInterface` dans `OrderListener`, collecter en
   `onFlush` les commandes web point relais qui passent `VALID` (filtres `!getIsEbay()` +
   `getSendcloudServicePointId() !== null` + `sendcloudOrderId ∈ {null,'0'}`) et dispatcher en
   `postFlush` ; enregistrer l'événement `postFlush` dans `config/services.yaml`. Couvre CB, PayPal,
   chèque et virement en un seul point (aucune modif de `PaymentController`/`OrderCrudController`
   pour le déclenchement).
7. **Back-office** — remplacer les 6 verrous `getIsEbay()` listés par `isSendcloudManaged()` dans
   `OrderCrudController`, et adapter les 2 templates Twig.
8. **Cache** — `cache:clear` pour recharger routing/services/messenger.

## Vérification

Commandes via `scripts/repo_exec.py . src-eurocommemo -- <cmd>` (stack compose).

1. **Lint & container** :
   ```sh
   python3 scripts/repo_exec.py . src-eurocommemo -- php -l src/Service/Sendcloud/SendcloudOrderCreator.php
   python3 scripts/repo_exec.py . src-eurocommemo -- php -l src/Messenger/Handler/CreateSendcloudOrderHandler.php
   python3 scripts/repo_exec.py . src-eurocommemo -- php -l src/EventListener/OrderListener.php
   python3 scripts/repo_exec.py . src-eurocommemo -- php bin/console lint:yaml config/services.yaml
   python3 scripts/repo_exec.py . src-eurocommemo -- php bin/console lint:container
   python3 scripts/repo_exec.py . src-eurocommemo -- php bin/console lint:twig templates/admin/order
   python3 scripts/repo_exec.py . src-eurocommemo -- php bin/console cache:clear
   ```
2. **Routing Messenger** — le message est bien routé :
   ```sh
   python3 scripts/repo_exec.py . src-eurocommemo -- php bin/console debug:messenger
   ```
   Attendu : `CreateSendcloudOrderMessage` listé, transport `async_sendcloud`.
3. **Schéma inchangé** (aucune migration) :
   ```sh
   python3 scripts/repo_exec.py . src-eurocommemo -- php bin/console doctrine:schema:validate --skip-sync
   ```
4. **Scénario fonctionnel end-to-end (humain, clés Sendcloud + `integration_id` réels)** :
   Lancer le worker : `php bin/console messenger:consume async_sendcloud -vv` (ou attendre le cron).
   - **CB / PayPal** : passer une commande web point relais, payer → paiement `AUTHORISED` →
     vérifier le log `[Sendcloud] Web relay order created` et `orders.sendcloud_order_id` renseigné.
   - **Chèque / virement (cas ajouté par ce changement)** : passer une commande web point relais en
     choisissant « chèque » ou « virement » → la commande est en `WAITING_RECEIPT`, **aucune** création
     Sendcloud à ce stade. Puis, en back-office, cliquer **« Confirmer la réception du paiement »** →
     la commande passe `VALID` → vérifier que la création Sendcloud se déclenche alors
     (`orders.sendcloud_order_id` renseigné).
   - Vérifier dans le panneau Sendcloud que la commande apparaît **avec** le transporteur et le point
     relais pré-sélectionnés.
   - Back-office → liste commandes `?delivery=1` : le panneau Sendcloud s'affiche pour la commande
     web ; cliquer « Générer l'étiquette » → parcel + n° de suivi + URL stockés ; « Suivre le colis »
     fonctionne.
5. **Points à confirmer côté métier / API avant prod** :
   - **Devise** : si la boutique n'est pas en EUR, l'enum Sendcloud (`EUR|GBP|USD`) rejettera →
     ajuster `SendcloudOrderCreator::CURRENCY`.
   - **`order_details.status.code`** : valeur `fulfilled` reprise de l'exemple de doc ; confirmer
     qu'elle est acceptée pour une commande payée non expédiée (sinon `processing`/`open`) — observable
     via le corps d'erreur remonté par `ExternalSendcloudApiException` au premier appel réel.
   - **Non-régression eBay** : une commande eBay génère toujours son étiquette (le changement
     `getOrderIdEbay()` → `getSendcloudExternalOrderId()` renvoie l'id eBay quand présent).
