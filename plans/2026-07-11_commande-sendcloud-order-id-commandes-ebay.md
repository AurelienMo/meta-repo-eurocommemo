# Plan — Commande Symfony : récupérer l'id Sendcloud des commandes eBay

## Contexte

Le projet Eurocommemorative dispose depuis peu d'un connecteur Sendcloud en lecture seule
(`SendcloudApiClient::getOrders()`), mais aucun code ne relie encore les commandes locales
aux commandes Sendcloud. On souhaite une commande console qui :

1. parcourt **l'intégralité des commandes eBay** stockées en base (`Order.isEbay = true`) ;
2. pour chaque commande, interroge l'API Sendcloud filtrée par l'id de commande eBay
   (`order_id`) ;
3. **stocke l'id interne Sendcloud** (`SendcloudOrderDTO::getId()`) sur la commande locale
   dans une nouvelle colonne, afin de pouvoir ensuite créer un colis / suivre l'expédition.

Décisions validées avec l'utilisateur :

- **Clé d'appariement** : `Order.orderIdEbay` ↔ Sendcloud `order_id`
  (l'API filtre déjà sur `order_id`, c'est la clé naturelle).
- **Valeur stockée** : `SendcloudOrderDTO::getId()` (id interne Sendcloud).
- **Stratégie d'appels** : un appel filtré par commande (`getOrders($orderIdEbay)`).

État confirmé par exploration :

- `Order` est mappé en **attributs PHP 8**, table `orders`
  (`src/Entity/Order.php:17-18`) ; l'id eBay est déjà stocké dans
  `orderIdEbay` (`#[ORM\Column(type: 'string', nullable: true)]`, `Order.php:106-107`).
- **Aucune** colonne Sendcloud n'existe encore sur `orders` (grep confirmé).
- Les commandes vivent dans `src/Command/`, `extends Command`, `#[AsCommand(...)]`,
  injection par promotion `readonly`, **pas de `SymfonyStyle`** (on utilise
  `OutputInterface::writeln` + `ProgressBar`), retour `Command::SUCCESS`/`FAILURE`.
- `SendcloudApiClient::getOrders(?string $orderId)` renvoie `SendcloudOrderDTO[]` et lève
  `ExternalSendcloudApiException` si les identifiants Sendcloud ne sont pas configurés
  (`src/Service/Sendcloud/SendcloudApiClient.php:30`).
- Les migrations : namespace `DoctrineMigrations`, `Version<YYYYMMDDHHMMSS>`, **pas de
  garde `abortIf`**, `ALTER TABLE orders ADD <col> ... DEFAULT NULL` (précédent exact :
  `migrations/Version20250327213452.php:22` qui a ajouté `order_id_ebay VARCHAR(255) DEFAULT NULL`).

---

## Fichiers concernés

### Nouveaux

#### `src/Command/SyncSendcloudOrderIdsCommand.php`

Commande console. Namespace `App\Command`, `extends Command`. Nom
`app:sendcloud:sync-order-ids`. Pour chaque commande eBay, appelle
`getOrders($orderIdEbay)`, apparie sur `order_id`, stocke `getId()`.

```php
<?php

namespace App\Command;

use App\Dto\Sendcloud\SendcloudOrderDTO;
use App\Entity\Order;
use App\Exceptions\ExternalSendcloudApiException;
use App\Repository\OrderRepository;
use App\Service\Sendcloud\SendcloudApiClient;
use Doctrine\ORM\EntityManagerInterface;
use Psr\Log\LoggerInterface;
use Symfony\Component\Console\Attribute\AsCommand;
use Symfony\Component\Console\Command\Command;
use Symfony\Component\Console\Helper\ProgressBar;
use Symfony\Component\Console\Input\InputInterface;
use Symfony\Component\Console\Input\InputOption;
use Symfony\Component\Console\Output\OutputInterface;

#[AsCommand(
    name: 'app:sendcloud:sync-order-ids',
    description: 'Fetch the Sendcloud order id for every eBay order and store it locally'
)]
class SyncSendcloudOrderIdsCommand extends Command
{
    public function __construct(
        private readonly OrderRepository $orderRepository,
        private readonly SendcloudApiClient $sendcloudApiClient,
        private readonly EntityManagerInterface $entityManager,
        private readonly LoggerInterface $logger
    ) {
        parent::__construct();
    }

    protected function configure()
    {
        $this
            ->addOption(
                'orderId',
                'o',
                InputOption::VALUE_REQUIRED,
                'Restrict the sync to a single eBay order id (orderIdEbay)'
            )
            ->addOption(
                'force',
                'f',
                InputOption::VALUE_NONE,
                'Re-fetch even orders that already have a Sendcloud order id'
            );
    }

    protected function execute(InputInterface $input, OutputInterface $output): int
    {
        $orderId = $input->getOption('orderId');
        $force = (bool) $input->getOption('force');

        if (null !== $orderId && '' !== $orderId) {
            $order = $this->orderRepository->findOneBy(['orderIdEbay' => $orderId, 'isEbay' => true]);
            $orders = $order instanceof Order ? [$order] : [];
        } else {
            $orders = $force
                ? $this->orderRepository->findEbayOrders()
                : $this->orderRepository->findEbayOrdersMissingSendcloudId();
        }

        $output->writeln(count($orders).' eBay order(s) to process');

        if (0 === count($orders)) {
            return Command::SUCCESS;
        }

        $progressBar = new ProgressBar($output, count($orders));
        $progressBar->start();

        $matched = 0;
        $notFound = 0;

        foreach ($orders as $order) {
            try {
                $dtos = $this->sendcloudApiClient->getOrders($order->getOrderIdEbay());
            } catch (ExternalSendcloudApiException $e) {
                // Not-configured / API error: abort the whole run — nothing else will succeed.
                $progressBar->finish();
                $output->writeln('');
                $output->writeln('<error>'.$e->getMessage().'</error>');

                return Command::FAILURE;
            }

            $match = $this->findMatchingOrder($dtos, $order->getOrderIdEbay());

            if (null === $match || null === $match->getId()) {
                ++$notFound;
                $this->logger->warning('No Sendcloud order found for eBay order', [
                    'orderIdEbay' => $order->getOrderIdEbay(),
                ]);
                $progressBar->advance();
                continue;
            }

            $order->setSendcloudOrderId($match->getId());
            ++$matched;
            $progressBar->advance();
        }

        $progressBar->finish();
        $this->entityManager->flush();

        $output->writeln('');
        $output->writeln(sprintf('%d matched, %d not found', $matched, $notFound));

        return Command::SUCCESS;
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

        // Fallback: the API already filtered on order_id, so a single result is the match.
        return 1 === count($dtos) ? $dtos[0] : null;
    }
}
```

Notes de style respectées : promotion `readonly`, `parent::__construct()`, `configure()`
sans `: void`, options via `addOption(..., VALUE_REQUIRED / VALUE_NONE)` (comme
`ImportEbayOrderCommand.php:59-60` et `GetEbayFulfillmentOrderCommand.php:35-42`),
`ProgressBar` + `writeln` (pas de `SymfonyStyle`), **un seul `flush()` en fin de boucle**
(pattern (a) de `SyncEbayProductCommand.php:28-41`), `<error>...</error>` comme
`GetEbayFulfillmentOrderCommand.php:44-55`.

#### `migrations/Version<YYYYMMDDHHMMSS>.php`

Ajout de la colonne `sendcloud_order_id` sur la table `orders`. **Générer le nom de
fichier via `bin/console make:migration`** (ou `doctrine:migrations:generate`) — ne pas
inventer le timestamp. Le corps attendu (calqué sur `Version20250327213452.php:22` et
`Version20260708224710.php`) :

```php
<?php

declare(strict_types=1);

namespace DoctrineMigrations;

use Doctrine\DBAL\Schema\Schema;
use Doctrine\Migrations\AbstractMigration;

final class Version<YYYYMMDDHHMMSS> extends AbstractMigration
{
    public function getDescription(): string
    {
        return 'Add sendcloud_order_id column to orders (Sendcloud internal order id)';
    }

    public function up(Schema $schema): void
    {
        $this->addSql('ALTER TABLE orders ADD sendcloud_order_id VARCHAR(255) DEFAULT NULL');
    }

    public function down(Schema $schema): void
    {
        $this->addSql('ALTER TABLE orders DROP sendcloud_order_id');
    }
}
```

### Modifiés

#### `src/Entity/Order.php`

Ajouter la propriété `sendcloudOrderId` (calquée sur `shippingServiceCode`,
`Order.php:104-105` / `431-440` : `length: 255`, `nullable: true`, défaut `= null`,
setter fluent `: Order`). Placer la propriété près des autres champs eBay/livraison
(vers `Order.php:104-109`).

Propriété (à insérer après `shippingServiceCode`, ~ligne 105) :

```php
    #[ORM\Column(type: 'string', length: 255, nullable: true)]
    private ?string $sendcloudOrderId = null;
```

Getter/setter (à insérer près des accesseurs eBay, ~ligne 440) :

```php
    public function getSendcloudOrderId(): ?string
    {
        return $this->sendcloudOrderId;
    }

    public function setSendcloudOrderId(?string $sendcloudOrderId): Order
    {
        $this->sendcloudOrderId = $sendcloudOrderId;

        return $this;
    }
```

#### `src/Repository/OrderRepository.php`

Ajouter deux méthodes de requête eBay (aucune n'existe aujourd'hui — seule
`findLastFakeNumEbay()` à `OrderRepository.php:82` filtre sur `isEbay`). Style calqué
sur les `createQueryBuilder('o')` existants.

```php
    /**
     * @return Order[]
     */
    public function findEbayOrders(): array
    {
        return $this->createQueryBuilder('o')
            ->where('o.isEbay = true')
            ->getQuery()
            ->getResult();
    }

    /**
     * @return Order[]
     */
    public function findEbayOrdersMissingSendcloudId(): array
    {
        return $this->createQueryBuilder('o')
            ->where('o.isEbay = true')
            ->andWhere('o.sendcloudOrderId IS NULL')
            ->getQuery()
            ->getResult();
    }
```

> Ajouter `use App\Entity\Order;` si absent (probable — déjà présent car
> `ServiceEntityRepository<Order>`).

---

## Étapes

1. **Entité** — Ajouter la propriété `sendcloudOrderId` + getter/setter dans
   `src/Entity/Order.php` (calqué sur `shippingServiceCode`).
   Vérif : `bin/console doctrine:schema:validate` (mapping) doit signaler la colonne
   manquante en base → normal avant migration.

2. **Migration** — Générer la migration (`bin/console make:migration`), vérifier qu'elle
   contient exactement `ALTER TABLE orders ADD sendcloud_order_id VARCHAR(255) DEFAULT NULL`
   (et le `DROP` en `down()`), puis l'appliquer
   (`bin/console doctrine:migrations:migrate`).

3. **Repository** — Ajouter `findEbayOrders()` et `findEbayOrdersMissingSendcloudId()`
   dans `src/Repository/OrderRepository.php`.

4. **Commande** — Créer `src/Command/SyncSendcloudOrderIdsCommand.php` selon le squelette
   ci-dessus (appariement sur `order_id`, stockage de `getId()`, options `--orderId` /
   `--force`, gestion `ExternalSendcloudApiException`, `flush()` unique).

5. **Auto-câblage** — Vérifier que la commande est bien enregistrée
   (`bin/console list | grep sendcloud`) et que ses dépendances s'autowirent
   (`SendcloudApiClient`, `OrderRepository`, `EntityManagerInterface`, `LoggerInterface`).

Toutes les commandes s'exécutent via `scripts/repo_exec.py` (conteneur `php-fpm-per83`),
jamais en appel direct — cf. CLAUDE.md.

---

## Vérification

- **Statique / mapping** :
  `bin/console lint:container`,
  `bin/console doctrine:schema:validate` (mapping OK après migration),
  `php -l` sur les 2 nouveaux fichiers PHP + `Order.php` + `OrderRepository.php`,
  `bin/console cache:clear`.
- **Enregistrement de la commande** :
  `bin/console list` doit lister `app:sendcloud:sync-order-ids` ;
  `bin/console debug:autowiring SendcloudApiClient` doit résoudre.
- **Migration** : `bin/console doctrine:migrations:status` (nouvelle version présente,
  non exécutée avant migrate), puis colonne `sendcloud_order_id` visible en base après
  `migrate`.
- **Bout en bout (nécessite des identifiants Sendcloud configurés en base via la page
  backoffice `SendcloudConfiguration`)** :
  - `bin/console app:sendcloud:sync-order-ids --orderId=<un_order_id_ebay_connu_de_sendcloud>`
    → doit afficher `1 matched, 0 not found` et renseigner `sendcloud_order_id` sur la
    ligne correspondante (vérifier en base ou dans l'admin).
  - `bin/console app:sendcloud:sync-order-ids` (sans option) → traite toutes les commandes
    eBay sans id Sendcloud ; relancer une 2ᵉ fois doit afficher `0 eBay order(s) to process`
    (idempotence, sauf `--force`).
  - Sans configuration Sendcloud → la commande retourne un code d'échec (`FAILURE`) avec
    le message `Sendcloud API credentials are not configured.`
- **Test unitaire (optionnel, si on suit le précédent `SendcloudApiClientTest`)** : un test
  de la commande avec `CommandTester` et un `SendcloudApiClient` mocké renvoyant un
  `SendcloudOrderDTO` dont `order_id` = `orderIdEbay`, vérifiant que
  `Order::getSendcloudOrderId()` vaut le `id` du DTO.
