# Plan — Bouton admin : mise à jour asynchrone du suivi Sendcloud des commandes expédiées

## Contexte

Une action unitaire « Récupérer le suivi Sendcloud » existe déjà par ligne dans l'admin
(`OrderCrudController::resolveSendcloudTracking`, appelant `BackfillSendcloudTrackingUseCase`), et
une commande CLI `app:sendcloud:backfill-tracking` traite en masse toutes les commandes retournées
par `OrderRepository::findEbayOrdersShippedMissingTracking()`.

Le besoin : offrir depuis la **page de liste des commandes** un bouton global qui déclenche ce
traitement de masse **sans bloquer l'admin**, et informer l'opérateur que le traitement est lancé.
La commande CLL actuelle est synchrone et **abandonne tout le run à la première erreur API Sendcloud**
(`BackfillSendcloudTrackingCommand.php:77-84`) — inadapté à un clic depuis l'interface.

Solution retenue : **fan-out Symfony Messenger**. Le clic déclenche une action EasyAdmin qui charge la
liste des IDs concernés et **dispatche un message par commande** sur le transport `async_sendcloud`
(déjà configuré avec un retry exponentiel adapté à l'API Sendcloud). Un handler recharge chaque commande,
appelle le use case existant, flush, et laisse remonter `ExternalSendcloudApiException` pour bénéficier
du retry par-commande. Un flash `info` confirme le lancement. Ce pattern réplique exactement l'existant
`AssociateSendcloudOrderIdMessage` / `AssociateSendcloudOrderIdHandler`.

L'admin est bâti sur **EasyAdmin** (Symfony 6.4) : il n'y a pas de template Twig autonome de liste ; la
liste est la page `index` générée par `OrderCrudController`, et les boutons globaux sont déclarés via
`Action::createAsGlobalAction()`. Aucun template Twig n'est à modifier (les flash s'affichent déjà via
`templates/admin/layout.html.twig:114-116`).

## Fichiers concernés

Repo : `src-eurocommemo` (`/Users/aurelienmorvan/OrbStack/docker/volumes/src-eurocommemo`).

### Nouveaux

#### `src/Messenger/Message/BackfillSendcloudTrackingMessage.php`

DTO immuable porteur d'un `orderId` scalaire — mirror exact de `AssociateSendcloudOrderIdMessage.php`.

```php
<?php

namespace App\Messenger\Message;

class BackfillSendcloudTrackingMessage
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

#### `src/Messenger/Handler/BackfillSendcloudTrackingHandler.php`

Handler `#[AsMessageHandler]` — mirror de `AssociateSendcloudOrderIdHandler.php` (recharge l'entité,
garde d'idempotence, appelle le use case, flush). Contrairement à la commande CLI, il **ne capture pas**
`ExternalSendcloudApiException` : la laisser remonter déclenche le retry exponentiel du transport
`async_sendcloud`. Le cas `not_found` (aucun colis) écrit le sentinel `'0'` et est terminal — pas de retry.

```php
<?php

namespace App\Messenger\Handler;

use App\Entity\Order;
use App\Exceptions\ExternalSendcloudApiException;
use App\Messenger\Message\BackfillSendcloudTrackingMessage;
use App\Repository\OrderRepository;
use App\Service\Sendcloud\UseCase\BackfillSendcloudTrackingUseCase;
use Doctrine\ORM\EntityManagerInterface;
use Psr\Log\LoggerInterface;
use Symfony\Component\Messenger\Attribute\AsMessageHandler;

#[AsMessageHandler]
class BackfillSendcloudTrackingHandler
{
    public function __construct(
        private readonly OrderRepository $orderRepository,
        private readonly BackfillSendcloudTrackingUseCase $backfillTracking,
        private readonly EntityManagerInterface $entityManager,
        private readonly LoggerInterface $logger,
    ) {
    }

    /**
     * @throws ExternalSendcloudApiException API/config error → retried by the async_sendcloud transport
     */
    public function __invoke(BackfillSendcloudTrackingMessage $message): void
    {
        $order = $this->orderRepository->find($message->getOrderId());
        if (!$order instanceof Order) {
            return; // order deleted meanwhile
        }

        // Idempotent: the three tracking columns are already set (resolved or "0" sentinel),
        // so this order no longer matches findEbayOrdersShippedMissingTracking().
        if (null !== $order->getSendcloudParcelId()
            && null !== $order->getSendcloudTrackingNumber()
            && null !== $order->getSendcloudTrackingUrl()) {
            return;
        }

        $result = $this->backfillTracking->execute($order);
        $this->entityManager->flush();

        $this->logger->info('Sendcloud tracking backfilled (async)', [
            'orderId'     => $order->getId(),
            'orderIdEbay' => $order->getOrderIdEbay(),
            'status'      => $result['status'],
        ]);
    }
}
```

### Modifiés

#### `config/packages/messenger.yaml` (routing, après la ligne 34)

Router le nouveau message sur le transport `async_sendcloud` existant (retry exponentiel déjà en place).
Sans cette ligne, Messenger le traiterait **en synchrone** — ce qui bloquerait l'admin.

```yaml
        routing:
            'App\Messenger\Message\CreateEbayAsyncMessage': async_create_ebay
            'App\Messenger\Message\AssociateSendcloudOrderIdMessage': async_sendcloud
            'App\Messenger\Message\BackfillSendcloudTrackingMessage': async_sendcloud
```

#### `src/Repository/OrderRepository.php` (nouvelle méthode, après `findEbayOrdersShippedMissingTracking` ligne 136)

Variante légère renvoyant uniquement les IDs (scalaires) pour le fan-out, afin de ne pas hydrater N
entités `Order` complètes juste pour dispatcher les messages. Mêmes critères que
`findEbayOrdersShippedMissingTracking` (lignes 120-136).

```php
/**
 * Ids of eBay orders already shipped and linked to Sendcloud, but missing at least one tracking field.
 * Lightweight variant of findEbayOrdersShippedMissingTracking() used to fan-out async backfill
 * messages without hydrating full Order entities.
 *
 * @return int[]
 */
public function findEbayOrderIdsShippedMissingTracking(): array
{
    $qb = $this->createQueryBuilder('o');

    $rows = $qb
        ->select('o.id')
        ->where('o.isEbay = true')
        ->andWhere('o.sendcloudOrderId IS NOT NULL')
        ->andWhere("o.sendcloudOrderId != '0'")
        ->andWhere('o.dateExpedition IS NOT NULL')
        ->andWhere($qb->expr()->orX(
            'o.sendcloudParcelId IS NULL',
            'o.sendcloudTrackingNumber IS NULL',
            'o.sendcloudTrackingUrl IS NULL'
        ))
        ->getQuery()
        ->getScalarResult();

    return array_map('intval', array_column($rows, 'id'));
}
```

#### `src/Controller/Admin/OrderCrudController.php`

**a) Imports** (bloc `use` en tête de fichier) — ajouter :

```php
use App\Messenger\Message\BackfillSendcloudTrackingMessage;
use App\Repository\OrderRepository;
use Symfony\Component\Messenger\MessageBusInterface;
```

**b) Constructeur** (lignes 57-70) — injecter le bus et le repository :

```php
    public function __construct(
        private readonly RequestStack $requestStack,
        private readonly EntityManagerInterface $em,
        private readonly OrderHelper $orderHelper,
        private readonly AdminUrlGenerator $adminUrlGenerator,
        private readonly SendcloudOrderLinker $linker,
        private readonly SendcloudApiClient $apiClient,
        private readonly SendcloudOrderShippingService $sendcloudShippingService,
        private readonly SendcloudLabelService $labelService,
        private readonly BackfillSendcloudTrackingUseCase $backfillTracking,
        private readonly CsrfTokenManagerInterface $csrfTokenManager,
        private readonly LoggerInterface $logger,
        private readonly MessageBusInterface $messageBus,
        private readonly OrderRepository $orderRepository,
    ) {
    }
```

**c) `configureActions()` (lignes 159-248)** — déclarer une action **globale** (bouton en haut de la
liste) protégée par un token CSRF fixe et une confirmation `confirm()`, sur le modèle CSRF de
`resolveSendcloudTracking` (lignes 201-227) et du pattern global action de
`ProductCrudController.php:100-106,141`. À insérer juste avant `$batchPrintPdfTodayGlobal` (ligne 229) :

```php
        $backfillTrackingAll = Action::new('backfillTrackingAll', 'Mettre à jour les suivis Sendcloud')
            ->setIcon('fa fa-barcode')
            ->linkToUrl(function () {
                $token = $this->csrfTokenManager
                    ->getToken('sendcloud_tracking_all')
                    ->getValue();

                return $this->adminUrlGenerator
                    ->setController(self::class)
                    ->setAction('backfillTrackingAll')
                    ->set('_csrf_token', $token)
                    ->includeReferrer()
                    ->generateUrl();
            })
            ->createAsGlobalAction()
            ->addCssClass('btn btn-primary')
            ->setHtmlAttributes([
                'onclick' => "return confirm('Lancer la mise à jour du suivi Sendcloud pour toutes les commandes expédiées concernées ?')",
            ]);
```

Puis l'enregistrer dans le `return $actions` (lignes 234-247) via un `->add(Crud::PAGE_INDEX, $backfillTrackingAll)` :

```php
        return $actions
            ->disable(Action::NEW)
            ->disable(Action::DELETE)
            ->add(Crud::PAGE_INDEX, $cancelOrder)
            ->add(Crud::PAGE_INDEX, $syncSendcloud)
            ->add(Crud::PAGE_INDEX, $resolveSendcloudTracking)
            ->add(Crud::PAGE_INDEX, $backfillTrackingAll)
            ->addBatchAction($batchPrintPdfTodayGlobal)
            ->update(Crud::PAGE_INDEX, Action::EDIT, function (Action $action) {
                return $action->displayIf(function(Order $order) {
                    return $order->getStatePayment() !== GlobalConstants::CONST_STATE_PAYMENT_CANCEL;
                });
            })
            ->reorder(Crud::PAGE_INDEX, [Action::EDIT, 'cancelOrder', 'syncSendcloud', 'resolveSendcloudTracking'])
        ;
```

> Note : le `reorder` (ligne 246) ne concerne que les actions **par ligne** ; l'action globale n'y figure
> pas et apparaîtra automatiquement dans la barre d'actions de page.

**d) Méthode d'action `backfillTrackingAll()`** — à ajouter à côté de `resolveSendcloudTracking`
(après la ligne 457). Valide le CSRF (mirror `resolveSendcloudTracking` lignes 417-421), récupère les IDs,
dispatche un message par commande, puis flash `info` de confirmation. Aucune requête API Sendcloud n'est
faite ici : seul un `SELECT o.id` + N `dispatch` (insertion en table `messenger_messages`), donc réponse
quasi instantanée.

```php
    public function backfillTrackingAll(AdminContext $context): RedirectResponse
    {
        $request = $this->requestStack->getCurrentRequest();

        if (!$this->isCsrfTokenValid('sendcloud_tracking_all', $request->query->get('_csrf_token'))) {
            $this->addFlash('danger', 'Token CSRF invalide.');

            return $this->redirect($context->getReferrer());
        }

        $orderIds = $this->orderRepository->findEbayOrderIdsShippedMissingTracking();

        if ([] === $orderIds) {
            $this->addFlash('info', 'Aucune commande à mettre à jour : tous les suivis Sendcloud sont déjà renseignés.');

            return $this->redirect($context->getReferrer());
        }

        foreach ($orderIds as $orderId) {
            $this->messageBus->dispatch(new BackfillSendcloudTrackingMessage($orderId));
        }

        $this->logger->info('Sendcloud tracking backfill dispatched from admin', [
            'count' => count($orderIds),
        ]);

        $this->addFlash('info', sprintf(
            'Mise à jour du suivi Sendcloud lancée pour %d commande(s). Le traitement s\'effectue en arrière-plan ; les suivis apparaîtront progressivement.',
            count($orderIds)
        ));

        return $this->redirect($context->getReferrer());
    }
```

## Étapes

1. **Message** — créer `src/Messenger/Message/BackfillSendcloudTrackingMessage.php` (mirror de
   `AssociateSendcloudOrderIdMessage`).
2. **Routing** — ajouter la ligne de routing dans `config/packages/messenger.yaml` (transport
   `async_sendcloud`). Indispensable pour l'asynchronisme.
3. **Handler** — créer `src/Messenger/Handler/BackfillSendcloudTrackingHandler.php` (recharge + garde
   d'idempotence + `BackfillSendcloudTrackingUseCase::execute()` + `flush()`, sans capturer
   `ExternalSendcloudApiException`).
4. **Repository** — ajouter `findEbayOrderIdsShippedMissingTracking(): int[]` dans `OrderRepository.php`.
5. **Controller** — dans `OrderCrudController.php` : ajouter les 3 imports, injecter `MessageBusInterface`
   et `OrderRepository` au constructeur, déclarer l'action globale `backfillTrackingAll` dans
   `configureActions()` et l'enregistrer, puis implémenter la méthode `backfillTrackingAll()`.
6. **Graphe graphify** — après modifications, rafraîchir le graphe du repo (cf. CLAUDE.md § graphify).
7. **Log** — consigner l'action dans `logs/src-eurocommemo.md` (règle action-logging).

## Vérification

- **Statique** : `scripts/repo_exec.py` pour lint/analyse du repo (`php -l` sur les nouveaux fichiers,
  PHPStan/CS si configurés). Vérifier l'autowiring : `bin/console debug:messenger` doit lister
  `BackfillSendcloudTrackingMessage` routé vers `async_sendcloud` et le handler
  `BackfillSendcloudTrackingHandler`.
- **Routing Messenger** : `bin/console debug:messenger` → confirmer la présence du nouveau message/handler.
- **Worker requis** : le traitement suppose un consumer actif du transport `async_sendcloud`
  (`bin/console messenger:consume async_sendcloud`). À confirmer côté infra (le même worker consomme déjà
  `AssociateSendcloudOrderIdMessage`). Sans worker, les messages restent en attente en base.
- **Manuel (bout en bout)** :
  1. Ouvrir la page de liste des commandes de l'admin → le bouton « Mettre à jour les suivis Sendcloud »
     apparaît dans la barre d'actions de page.
  2. Cliquer → confirmation `confirm()` → au retour, flash `info` « Mise à jour … lancée pour N commande(s) … ».
  3. Vérifier en base `messenger_messages` (queue `async_sendcloud`) que N messages sont enfilés.
  4. Lancer le worker et vérifier que les colonnes `sendcloudParcelId` / `sendcloudTrackingNumber` /
     `sendcloudTrackingUrl` se remplissent (ou passent au sentinel `'0'` si aucun colis), et que les
     lignes ne matchent plus `findEbayOrdersShippedMissingTracking()`.
  5. Re-cliquer sans nouvelles commandes éligibles → flash `info` « Aucune commande à mettre à jour … ».
- **Idempotence / retry** : relancer un message déjà traité doit être un no-op (garde du handler) ; une
  `ExternalSendcloudApiException` doit déclencher le retry exponentiel du transport (jusqu'à 10 tentatives).
