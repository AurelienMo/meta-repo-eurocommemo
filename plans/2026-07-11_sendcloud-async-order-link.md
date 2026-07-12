# Plan — Association asynchrone de l'ID Sendcloud à l'import d'une commande eBay (2026-07-11)

**Run** : — · **Ticket** : — · **Repo(s)** : src-eurocommemo · **Branche** : `feature/sendcloud-async-order-link` → `main` · **Risk** : medium · **Complexité** : moderate

> Repo applicatif monté sous `/Users/aurelienmorvan/OrbStack/docker/volumes/src-eurocommemo/` — Symfony 6.4 LTS, `symfony/messenger` 6.4.19, transport Doctrine (`messenger_messages`). Les chemins des sections ci-dessous sont relatifs à la racine de ce repo.

## Contexte

Quand une commande eBay est importée en base (webhook temps réel **ou** commande console de rattrapage), le champ `Order::$sendcloudOrderId` reste `NULL`. Il n'est renseigné qu'ultérieurement, en masse, par la commande cron `app:sendcloud:sync-order-ids`, qui interroge l'API Sendcloud (`GET /orders?order_id={orderIdEbay}`) pour retrouver l'ID interne de la commande côté Sendcloud.

Problème : au moment précis de l'import, la commande n'est pas forcément encore présente côté Sendcloud (Sendcloud la reçoit via sa propre intégration eBay, avec un délai variable). On veut donc, **dès l'import**, déclencher une association asynchrone qui **réessaie plusieurs fois** pour laisser à Sendcloud le temps de recevoir la commande.

Objectif : à chaque import eBay (par tout moyen existant), dispatcher un message sur le bus Symfony Messenger qui tente d'associer l'ID Sendcloud à la commande, avec **1 tentative initiale + 3 re-essais espacés de 20 secondes** (`max_retries: 3` au sens strict Symfony, 4 passages au total à t=0, +20s, +40s, +60s). Après épuisement sans correspondance : poser la sentinelle `"0"` (déjà comprise par le template backoffice qui masque alors le lien « Voir sur Sendcloud ») **et envoyer un mail** d'alerte.

Décisions validées :
- **Tentatives** : `max_retries: 3` → 1 tentative + 3 re-essais.
- **Échec final** : `sendcloudOrderId = "0"` + mail.
- **Refacto** : extraire un service partagé `SendcloudOrderLinker` mutualisant fetch + matching, réutilisé par le nouveau handler **et** par `SyncSendcloudOrderIdsCommand`.
- **Chemin `--update-pricing`** : le chemin `UpdateEbayOrderPricingUseCase` (via `GetEbayFulfillmentOrderCommand::handleExistingOrder()`) ne passe **pas** par `ImportFulfillmentOrderUseCase::execute()` et ne dispatche donc **pas** le message d'association : la commande existe déjà (le garde d'idempotence du handler la sauterait de toute façon).

## Fichiers concernés

### Nouveaux
| Fichier | Rôle |
|---------|------|
| `src/Service/Sendcloud/SendcloudOrderLinker.php` | Service partagé : fetch API + matching, renvoie l'ID interne Sendcloud ou `null`. |
| `src/Messenger/Message/AssociateSendcloudOrderIdMessage.php` | Message portant l'`id` BDD de la commande. |
| `src/Messenger/Handler/AssociateSendcloudOrderIdHandler.php` | Handler `#[AsMessageHandler]` : associe l'ID, ou lève l'exception de retry. |
| `src/Exceptions/SendcloudOrderNotFoundException.php` | Exception « pas encore trouvée » → déclenche le retry Messenger. |
| `src/EventSubscriber/SendcloudLinkFailureSubscriber.php` | À l'épuisement des retries : pose `"0"` + mail. |
| `templates/mail/sendcloud_link_failed.html.twig` | Corps du mail d'alerte d'échec. |
| `tests/Service/Sendcloud/SendcloudOrderLinkerTest.php` | Test unitaire du service de matching. |
| `tests/Messenger/Handler/AssociateSendcloudOrderIdHandlerTest.php` | Test unitaire du handler. |

### Modifiés
| Fichier | Changement |
|---------|-----------|
| `config/packages/messenger.yaml` | Nouveau transport `async_sendcloud` (retry 20s ×3, `multiplier: 1`) + routing du message. |
| `src/Service/Ebay/UseCase/ImportFulfillmentOrderUseCase.php` | Inject `MessageBusInterface` + dispatch après le flush (`:116`) — couvre le webhook **et** `app:ebay:fulfillment-order` (`GetEbayFulfillmentOrderCommand`), tous deux passant par ce use case. |
| `src/Command/ImportEbayOrderCommand.php` | Inject `MessageBusInterface` + dispatch après le flush (`:155-156`) — chemin console **legacy** (`app:import:ebay-order`, Trading API, persistance inline hors use case). |
| `src/Command/SyncSendcloudOrderIdsCommand.php` | Remplacer `SendcloudApiClient` + `findMatchingOrder` par `SendcloudOrderLinker` (dé-duplication). |
| `src/Service/MailService.php` | Ajouter `sendSendcloudLinkFailure(Order $order)`. |
| `cron.php` | Ajouter `async_sendcloud` à la commande `messenger:consume`. |

---

### `src/Service/Sendcloud/SendcloudOrderLinker.php` (nouveau)

Extrait la logique de matching aujourd'hui dans `SyncSendcloudOrderIdsCommand::findMatchingOrder()` (`:125-135`). Ne mute pas l'entité, ne flush pas.

```php
<?php

namespace App\Service\Sendcloud;

use App\Dto\Sendcloud\SendcloudOrderDTO;
use App\Entity\Order;
use App\Exceptions\ExternalSendcloudApiException;

final class SendcloudOrderLinker
{
    public function __construct(
        private readonly SendcloudApiClient $apiClient,
    ) {
    }

    /**
     * Fetch the Sendcloud order matching the given eBay order and return its
     * internal Sendcloud id, or null when the order is not (yet) on Sendcloud.
     *
     * @throws ExternalSendcloudApiException
     */
    public function matchSendcloudId(Order $order): ?string
    {
        $dtos  = $this->apiClient->getOrders($order->getOrderIdEbay());
        $match = $this->findMatchingOrder($dtos, $order->getOrderIdEbay());

        return $match?->getId();
    }

    /**
     * @param SendcloudOrderDTO[] $dtos
     */
    private function findMatchingOrder(array $dtos, ?string $orderIdEbay): ?SendcloudOrderDTO
    {
        foreach ($dtos as $dto) {
            if ($dto->getOrderId() === $orderIdEbay) {
                return $dto;
            }
        }

        // API already filtered on order_id: a single result is the match.
        return 1 === count($dtos) ? $dtos[0] : null;
    }
}
```

### `src/Messenger/Message/AssociateSendcloudOrderIdMessage.php` (nouveau)

Même style que `CreateEbayAsyncMessage` (`src/Messenger/Message/CreateEbayAsyncMessage.php`).

```php
<?php

namespace App\Messenger\Message;

class AssociateSendcloudOrderIdMessage
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

### `src/Exceptions/SendcloudOrderNotFoundException.php` (nouveau)

Sur le modèle de `ExternalSendcloudApiException` (`extends \Exception`).

```php
<?php

namespace App\Exceptions;

class SendcloudOrderNotFoundException extends \Exception
{
    public function __construct(?string $orderIdEbay)
    {
        parent::__construct(sprintf('No Sendcloud order found yet for eBay order "%s".', $orderIdEbay));
    }
}
```

### `src/Messenger/Handler/AssociateSendcloudOrderIdHandler.php` (nouveau)

Même pattern que `CreateEbayAsyncHandler` (`#[AsMessageHandler]`, `__invoke`).

```php
<?php

namespace App\Messenger\Handler;

use App\Entity\Order;
use App\Exceptions\SendcloudOrderNotFoundException;
use App\Messenger\Message\AssociateSendcloudOrderIdMessage;
use App\Repository\OrderRepository;
use App\Service\Sendcloud\SendcloudOrderLinker;
use Doctrine\ORM\EntityManagerInterface;
use Psr\Log\LoggerInterface;
use Symfony\Component\Messenger\Attribute\AsMessageHandler;

#[AsMessageHandler]
class AssociateSendcloudOrderIdHandler
{
    public function __construct(
        private readonly OrderRepository $orderRepository,
        private readonly SendcloudOrderLinker $linker,
        private readonly EntityManagerInterface $entityManager,
        private readonly LoggerInterface $logger,
    ) {
    }

    /**
     * @throws SendcloudOrderNotFoundException      not on Sendcloud yet → Messenger retries in 20s
     * @throws \App\Exceptions\ExternalSendcloudApiException  API/config error → also retried
     */
    public function __invoke(AssociateSendcloudOrderIdMessage $message): void
    {
        $order = $this->orderRepository->find($message->getOrderId());
        if (!$order instanceof Order) {
            return; // order deleted meanwhile
        }

        // Idempotent: already linked, or already marked "0" by a previous failure.
        if (null !== $order->getSendcloudOrderId()) {
            return;
        }

        $sendcloudId = $this->linker->matchSendcloudId($order);

        if (null === $sendcloudId) {
            throw new SendcloudOrderNotFoundException($order->getOrderIdEbay());
        }

        $order->setSendcloudOrderId($sendcloudId);
        $this->entityManager->flush();

        $this->logger->info('Sendcloud order id linked', [
            'orderIdEbay'     => $order->getOrderIdEbay(),
            'sendcloudId'     => $sendcloudId,
        ]);
    }
}
```

### `config/packages/messenger.yaml` (modifié)

Ajouter le transport `async_sendcloud` sous `transports:` et l'entrée de routing. `multiplier: 1` est **impératif** pour un espacement constant de 20s (sinon backoff ×2 par défaut).

```yaml
framework:
    messenger:
        reset_on_message: true

        transports:
            async_create_ebay:
                dsn: "%env(MESSENGER_TRANSPORT_DSN)%"
                options:
                    auto_setup: true
                    queue_name: async_create_ebay
                retry_strategy:
                    max_retries: 3
                    delay: 1000
                    max_delay: 0
            async_sendcloud:
                dsn: "%env(MESSENGER_TRANSPORT_DSN)%"
                options:
                    auto_setup: true
                    queue_name: async_sendcloud
                retry_strategy:
                    max_retries: 3
                    delay: 20000      # 20 s between attempts
                    multiplier: 1     # constant delay (no exponential backoff)
                    max_delay: 0

        routing:
            'App\Messenger\Message\CreateEbayAsyncMessage': async_create_ebay
            'App\Messenger\Message\AssociateSendcloudOrderIdMessage': async_sendcloud
```

### `src/EventSubscriber/SendcloudLinkFailureSubscriber.php` (nouveau)

Écoute `WorkerMessageFailedEvent` ; à l'épuisement des re-essais (`willRetry() === false`), pose `"0"` + mail. Aucun `failure_transport` requis : l'événement est émis même sans transport d'échec configuré.

```php
<?php

namespace App\EventSubscriber;

use App\Entity\Order;
use App\Messenger\Message\AssociateSendcloudOrderIdMessage;
use App\Repository\OrderRepository;
use App\Service\MailService;
use Doctrine\ORM\EntityManagerInterface;
use Psr\Log\LoggerInterface;
use Symfony\Component\EventDispatcher\EventSubscriberInterface;
use Symfony\Component\Messenger\Event\WorkerMessageFailedEvent;

class SendcloudLinkFailureSubscriber implements EventSubscriberInterface
{
    public function __construct(
        private readonly OrderRepository $orderRepository,
        private readonly EntityManagerInterface $entityManager,
        private readonly MailService $mailService,
        private readonly LoggerInterface $logger,
    ) {
    }

    public static function getSubscribedEvents(): array
    {
        return [
            WorkerMessageFailedEvent::class => 'onMessageFailed',
        ];
    }

    public function onMessageFailed(WorkerMessageFailedEvent $event): void
    {
        if ($event->willRetry()) {
            return; // more retries pending
        }

        $message = $event->getEnvelope()->getMessage();
        if (!$message instanceof AssociateSendcloudOrderIdMessage) {
            return;
        }

        $order = $this->orderRepository->find($message->getOrderId());
        if (!$order instanceof Order) {
            return;
        }

        $order->setSendcloudOrderId('0');
        $this->entityManager->flush();

        $this->logger->warning('Sendcloud order id association exhausted, marked "0"', [
            'orderIdEbay' => $order->getOrderIdEbay(),
            'error'       => $event->getThrowable()->getMessage(),
        ]);

        $this->mailService->sendSendcloudLinkFailure($order);
    }
}
```

### `src/Service/MailService.php` (modifié)

Ajouter la méthode (style aligné sur `sendReportEbayNotificationCommand()`, `:212-236`, et `sendAlertRefreshTokenEbayExpired()`, `:170-187`).

```php
public function sendSendcloudLinkFailure(Order $order): void
{
    $message = (new Email())
        ->subject('[Sendcloud][Order] Association introuvable pour la commande eBay : '.$order->getOrderIdEbay())
        ->from(new Address($this->params->get('mailer_from'), 'EuroCommemorative'))
        ->to(new Address('morvan.aurelien@gmail.com'))
        ->html(
            $this->templating->render(
                'mail/sendcloud_link_failed.html.twig',
                [
                    'orderIdEbay' => $order->getOrderIdEbay(),
                    'id'          => $order->getId(),
                ]
            )
        );

    try {
        $this->mailer->send($message);
    } catch (\Exception $e) {
        $this->logger->critical("Erreur lors de l'envoie de l'email : ".$e->getMessage());
    }
}
```

### `templates/mail/sendcloud_link_failed.html.twig` (nouveau)

Gabarit minimal sur le modèle de `templates/mail/order_ebay.html.twig`.

```twig
<p>Aucune commande Sendcloud n'a pu être associée après 4 tentatives.</p>
<ul>
    <li>Commande eBay : {{ orderIdEbay }}</li>
    <li>Commande interne : #{{ id }}</li>
</ul>
<p>Le champ <code>sendcloudOrderId</code> a été marqué « 0 » (traité, introuvable).</p>
```

### `src/Service/Ebay/UseCase/ImportFulfillmentOrderUseCase.php` (modifié) — chemin partagé

Injecter `MessageBusInterface` dans le constructeur (`:35-50`) et dispatcher après le flush (`:116`), en pratique juste avant le `return $order;` (`:120`), après `generateInvoice()` (`:118`). L'`id` est disponible dès le flush (`persist :115`, `flush :116`).

Ce point de dispatch **couvre tous les appelants** du use case : le webhook **et** la commande moderne `app:ebay:fulfillment-order` (`GetEbayFulfillmentOrderCommand::import()` → `execute()` à `:110`). Ne **pas** ajouter de dispatch redondant dans `GetEbayFulfillmentOrderCommand`.

```php
// constructeur — ajouter l'argument :
private readonly \Symfony\Component\Messenger\MessageBusInterface $messageBus,

// execute(), après $this->entityManager->flush(); (l.116) et generateInvoice() (l.118),
// juste avant return $order; (l.120) :
$this->messageBus->dispatch(new \App\Messenger\Message\AssociateSendcloudOrderIdMessage($order->getId()));
```

### `src/Command/ImportEbayOrderCommand.php` (modifié) — chemin console legacy

Commande **legacy** Trading API (`app:import:ebay-order`) : elle instancie et persiste l'`Order` inline (`new Order()`, `persist`/`flush` `:155-156`, `generateInvoice()` `:158`), hors du use case partagé — d'où un dispatch propre. Injecter `MessageBusInterface` dans le constructeur et dispatcher après le flush (`:155-156`), avant `generateInvoice()` (`:158`).

```php
// constructeur — ajouter l'argument :
private readonly \Symfony\Component\Messenger\MessageBusInterface $messageBus,

// execute(), après $this->entityManager->flush(); (l.156) :
$this->messageBus->dispatch(new \App\Messenger\Message\AssociateSendcloudOrderIdMessage($order->getId()));
```

### `src/Command/SyncSendcloudOrderIdsCommand.php` (modifié) — dé-duplication

Remplacer la dépendance `SendcloudApiClient` (`:27`) par `SendcloudOrderLinker`, supprimer la méthode privée `findMatchingOrder()` (`:125-135`), et réécrire la boucle (`:79-111`) pour consommer le service. Comportement inchangé (compteurs `matched`/`notFound`, sentinelle `"0"`).

```php
// constructeur : remplacer
//   private readonly SendcloudApiClient $apiClient,
// par
private readonly SendcloudOrderLinker $linker,

// dans la boucle foreach ($orders as $order) :
try {
    $sendcloudId = $this->linker->matchSendcloudId($order);
} catch (ExternalSendcloudApiException $e) {
    $progressBar->finish();
    $output->writeln('');
    $output->writeln('<error>'.$e->getMessage().'</error>');

    return Command::FAILURE;
}

if (null === $sendcloudId) {
    ++$notFound;
    $this->logger->warning('No Sendcloud order found for eBay order', [
        'orderIdEbay' => $order->getOrderIdEbay(),
    ]);
    $order->setSendcloudOrderId('0');
} else {
    $order->setSendcloudOrderId($sendcloudId);
    ++$matched;
}

$progressBar->advance();
```

> Note : profiter de la réécriture pour corriger le flush par batch bogué `if ($cptProcess % 200)` (`:108-110`) → `if (0 === $cptProcess % 200)`, ou simplifier en un unique flush final (`:114`). À valider avec l'équipe.

### `cron.php` (modifié)

Ajouter `async_sendcloud` à la commande consume (⚠️ chemin de prod OVH en dur).

```php
<?php
exec("/usr/local/php8.3/bin/php /homez.988/eurocos/www/eurocommemorative-v2/bin/console messenger:consume async_create_ebay async_sendcloud --time-limit=1800");
```

## Étapes d'implémentation

1. **Service partagé** — créer `SendcloudOrderLinker` (fetch + matching, sans mutation ni flush).
2. **Message + exception** — créer `AssociateSendcloudOrderIdMessage` et `SendcloudOrderNotFoundException`.
3. **Handler** — créer `AssociateSendcloudOrderIdHandler` (`find` → idempotence → match → set/flush ou throw).
4. **Transport + routing** — modifier `config/packages/messenger.yaml` (`async_sendcloud`, `delay: 20000`, `multiplier: 1`, routing).
5. **Échec final** — créer `SendcloudLinkFailureSubscriber` (`WorkerMessageFailedEvent`, `willRetry()===false` → `"0"` + mail), la méthode `MailService::sendSendcloudLinkFailure()` et le template `mail/sendcloud_link_failed.html.twig`.
6. **Dispatch import partagé** — injecter `MessageBusInterface` dans `ImportFulfillmentOrderUseCase` + dispatch après flush (couvre le webhook **et** `app:ebay:fulfillment-order`).
7. **Dispatch console legacy** — injecter `MessageBusInterface` dans `ImportEbayOrderCommand` (`app:import:ebay-order`, Trading API) + dispatch après flush.
8. **Dé-duplication** — brancher `SyncSendcloudOrderIdsCommand` sur `SendcloudOrderLinker`, supprimer `findMatchingOrder()`.
9. **Worker** — ajouter `async_sendcloud` au `messenger:consume` de `cron.php`.
10. **Tests** — `SendcloudOrderLinkerTest` (sur le modèle de `tests/Service/Sendcloud/SendcloudApiClientTest.php`, MockHandler Guzzle) + `AssociateSendcloudOrderIdHandlerTest` (mock `SendcloudOrderLinker` : succès → flush ; `null` → `SendcloudOrderNotFoundException`).

## DAG d'exécution

Résumé : DAG non produit par ce skill. Séquence linéaire recommandée 1 → 10, avec les étapes 6/7 (dispatch) parallélisables une fois l'étape 2 faite, et l'étape 10 (tests) après 1 et 3.

### Groupes parallélisables
- Groupe 1 : 1, 2 (fondations sans dépendance mutuelle)
- Groupe 2 : 3, 4, 5 (dépendent de 1/2)
- Groupe 3 : 6, 7, 8 (dépendent de 2 ; 8 dépend aussi de 1)
- Groupe 4 : 9, 10

### Stack / DoD par repo
- **src-eurocommemo** : PHP 8.3 · Composer · Symfony 6.4 · DoD : `cache:clear` OK, `debug:messenger` route le message, scénarios succès + retry/échec validés, suite PHPUnit verte. Exécution via `scripts/repo_exec.py`.

## Vérification

1. **Cache DI** : `php bin/console cache:clear` (via `scripts/repo_exec.py`) — valide l'autowiring du service, du handler et du subscriber.
2. **Routing Messenger** : `php bin/console debug:messenger` — confirme que `AssociateSendcloudOrderIdMessage` est routé vers `async_sendcloud` et le handler enregistré.
3. **Bout-en-bout — succès** : importer une commande eBay déjà présente côté Sendcloud, soit via la commande moderne `php bin/console app:ebay:fulfillment-order -o <orderId> --import` (chemin use case partagé), soit via la commande legacy `php bin/console app:import:ebay-order -o <orderId>` — les deux dispatchent le message. Lancer `php bin/console messenger:consume async_sendcloud -vv`, vérifier en base `orders.sendcloud_order_id` = ID interne attendu et l'apparition du lien « Voir sur Sendcloud » dans le backoffice.
4. **Bout-en-bout — retry + échec** : importer une commande absente de Sendcloud, consommer avec `-vv`, observer les 3 re-essais espacés de ~20s, puis vérifier `sendcloud_order_id = "0"` et la réception du mail d'alerte.
5. **Non-régression** : `php bin/console app:sendcloud:sync-order-ids -o <orderId>` produit le même résultat qu'avant la refacto (matched / not found).
6. **Tests** : `SendcloudOrderLinkerTest` + `AssociateSendcloudOrderIdHandlerTest` verts ; lancer la suite via `scripts/repo_exec.py`.
