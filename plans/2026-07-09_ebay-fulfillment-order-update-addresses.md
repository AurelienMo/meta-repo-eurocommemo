# Plan — Mise à jour des adresses d'une commande eBay existante via `app:ebay:fulfillment-order`

## Contexte

La commande console `app:ebay:fulfillment-order` (`GetEbayFulfillmentOrderCommand`) récupère une
commande depuis l'API Fulfillment d'eBay et, avec l'option `--import`, la persiste en base via
`ImportFulfillmentOrderUseCase`.

Aujourd'hui, si la commande existe déjà (`orderIdEbay` + `isEbay = true`), le use case lève
`EbayOrderAlreadyImportedException` et la commande se contente d'afficher `Order already imported`
puis retourne `SUCCESS`. Aucune donnée n'est rafraîchie, alors que l'acheteur peut avoir corrigé son
adresse de livraison ou de facturation côté eBay après la création de la commande en base.

**Objectif** : quand la commande existe déjà, proposer à l'opérateur de mettre à jour les adresses
de la commande (`OrderAddress` de type `delivery` et `billing`) à partir des données redescendues de
l'API eBay. Décisions validées avec l'utilisateur :

- **Granularité** : afficher, pour chaque adresse, l'existante en base vs celle d'eBay (diff), puis
  demander une confirmation **séparée** par adresse (on peut n'accepter que la livraison, par ex.).
- **Cron-safe** : une option `--update-addresses` (`-u`) applique la mise à jour **sans prompt** ;
  en exécution non interactive sans ce flag, aucune adresse n'est modifiée.
- **Périmètre** : uniquement les entités `OrderAddress` de la commande. L'adresse portée par
  l'entité `User` rattachée n'est **pas** touchée.

Contraintes du projet observées à respecter :

- Interaction console via `QuestionHelper` (`$this->getHelper('question')`), **pas de `SymfonyStyle`**.
  Pas de `ConfirmationQuestion` utilisé aujourd'hui : on l'introduit (idiomatique, basé sur le même
  `QuestionHelper` — cohérent avec `CreateUserCommand` / `DebugCommand`).
- Le mapping DTO eBay → entité adresse existe déjà : `OrderAddress::fromDto(?FulfillmentShipToDTO)`.
- La persistance des adresses passe par `Order::setDeliveryAddress()` / `setBillingAddress()`, qui
  gèrent le remplacement (`orphanRemoval` + `cascade: persist`) — un simple `flush()` suffit.
- La logique métier/persistance vit dans un *UseCase* (`src/Service/Ebay/UseCase/`) ; la commande
  reste fine et porte la présentation/interaction.

## Fichiers concernés

Repo : `src-eurocommemo` (chemin réel : `/Users/aurelienmorvan/OrbStack/docker/volumes/src-eurocommemo/`).
Chemins ci-dessous relatifs à la racine de ce repo.

### Nouveaux

#### `src/Service/Ebay/UseCase/UpdateEbayOrderAddressesUseCase.php`

Nouveau use case dédié : localiser une commande eBay existante et remplacer une de ses adresses
depuis le DTO eBay. Ne touche que `OrderAddress`.

```php
<?php

namespace App\Service\Ebay\UseCase;

use App\Entity\Order;
use App\Entity\OrderAddress;
use App\Repository\OrderRepository;
use App\Service\Ebay\DTO\Output\Fulfillment\FulfillmentShipToDTO;
use Doctrine\ORM\EntityManagerInterface;

class UpdateEbayOrderAddressesUseCase
{
    public function __construct(
        private readonly OrderRepository $orderRepository,
        private readonly EntityManagerInterface $entityManager,
    ) {
    }

    /**
     * Same lookup criteria as ImportFulfillmentOrderUseCase::execute().
     */
    public function findExistingEbayOrder(string $orderId): ?Order
    {
        return $this->orderRepository->findOneBy(['orderIdEbay' => $orderId, 'isEbay' => true]);
    }

    /**
     * Replace the address of the given type ("delivery" | "billing") with the eBay one.
     * setDeliveryAddress/setBillingAddress remove the previous address (orphanRemoval)
     * and attach the new one (cascade persist); flush() is therefore enough.
     */
    public function replaceAddress(Order $order, string $type, FulfillmentShipToDTO $dto): void
    {
        $address = OrderAddress::fromDto($dto);

        if ($type === OrderAddress::TYPE_DELIVERY) {
            $order->setDeliveryAddress($address);
        } else {
            $order->setBillingAddress($address);
        }

        $this->entityManager->flush();
    }
}
```

> Autowiring : `src/Service/` est déjà couvert par `config/services.yaml` (les autres UseCases eBay
> sont injectés sans déclaration explicite). Vérifier tout de même que `App\Service\` est bien dans
> le `App\:` `resource: '../src/'` autowire/autoconfigure — si oui, aucune déclaration à ajouter.

### Modifiés

#### `src/Command/GetEbayFulfillmentOrderCommand.php`

État actuel — voir `GetEbayFulfillmentOrderCommand.php:19-114`. Modifications :

**1. Imports (après ligne 12, `use App\Service\Ebay\UseCase\ImportFulfillmentOrderUseCase;`)** — ajouter :

```php
use App\Entity\Order;
use App\Entity\OrderAddress;
use App\Service\Ebay\DTO\Output\Fulfillment\FulfillmentShipToDTO;
use App\Service\Ebay\UseCase\UpdateEbayOrderAddressesUseCase;
use Symfony\Component\Console\Question\ConfirmationQuestion;
```

**2. Constructeur (`GetEbayFulfillmentOrderCommand.php:22-27`)** — injecter le nouveau use case :

```php
public function __construct(
    private readonly FulfillmentApiV1 $fulfillmentApi,
    private readonly ImportFulfillmentOrderUseCase $importFulfillmentOrder,
    private readonly UpdateEbayOrderAddressesUseCase $updateOrderAddresses,
) {
    parent::__construct();
}
```

**3. `configure()` (`GetEbayFulfillmentOrderCommand.php:29-35`)** — ajouter l'option cron-safe :

```php
protected function configure()
{
    $this
        ->addOption("orderId", "o", InputOption::VALUE_REQUIRED, "eBay order ID (e.g. 02-14852-44592)")
        ->addOption("raw", "r", InputOption::VALUE_NONE, "Dump the raw JSON payload")
        ->addOption("import", "i", InputOption::VALUE_NONE, "Persist the order into the database (like app:import:ebay-order)")
        ->addOption("update-addresses", "u", InputOption::VALUE_NONE, "If the order already exists, update its addresses from eBay without prompting");
}
```

**4. `execute()` — branchement (`GetEbayFulfillmentOrderCommand.php:55-57`)** — `-u` doit aussi
déclencher le chemin d'import/mise à jour, et on passe désormais `$input` à `import()` :

```php
if ($input->getOption("import") || $input->getOption("update-addresses")) {
    return $this->import($order, $input, $output);
}
```

**5. `import()` (`GetEbayFulfillmentOrderCommand.php:80-113`)** — nouvelle signature + court-circuit
sur commande existante **avant** le contrôle d'email (l'email n'est requis que pour la création) :

```php
private function import(FulfillmentOrderDTO $order, InputInterface $input, OutputInterface $output): int
{
    $existing = $this->updateOrderAddresses->findExistingEbayOrder($order->getOrderId());
    if ($existing instanceof Order) {
        return $this->handleExistingOrder($existing, $order, $input, $output);
    }

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

> Le `catch (EbayOrderAlreadyImportedException)` devient un filet de sécurité (course concurrente) :
> le court-circuit `findExistingEbayOrder()` gère le cas normal.

**6. Nouvelles méthodes privées** — à ajouter à la fin de la classe (après `import()`) :

```php
private function handleExistingOrder(
    Order $existing,
    FulfillmentOrderDTO $ebayOrder,
    InputInterface $input,
    OutputInterface $output
): int {
    $output->writeln(sprintf(
        "Order already imported (id: %d, reference: %s)",
        $existing->getId(),
        $existing->getReference()
    ));

    $force = (bool) $input->getOption("update-addresses");

    $this->maybeUpdateAddress(
        $existing,
        OrderAddress::TYPE_DELIVERY,
        $existing->getDeliveryAddress(),
        $ebayOrder->getShipTo(),
        $force,
        $input,
        $output
    );
    $this->maybeUpdateAddress(
        $existing,
        OrderAddress::TYPE_BILLING,
        $existing->getBillingAddress(),
        $ebayOrder->getBuyerRegistrationAddress(),
        $force,
        $input,
        $output
    );

    return Command::SUCCESS;
}

private function maybeUpdateAddress(
    Order $order,
    string $type,
    ?OrderAddress $current,
    ?FulfillmentShipToDTO $ebayDto,
    bool $force,
    InputInterface $input,
    OutputInterface $output
): void {
    $output->writeln("");
    $output->writeln(sprintf("=== %s address ===", ucfirst($type)));

    if ($ebayDto === null) {
        $output->writeln("No address of this type in the eBay payload — skipped.");

        return;
    }

    $ebayAddress = OrderAddress::fromDto($ebayDto);
    $output->writeln("Current (DB): " . $this->formatAddress($current));
    $output->writeln("eBay:         " . $this->formatAddress($ebayAddress));

    if (!$force) {
        if (!$input->isInteractive()) {
            $output->writeln("Non-interactive and --update-addresses not set — left unchanged.");

            return;
        }

        $question = new ConfirmationQuestion(
            sprintf("Update the %s address from eBay? [y/N] ", $type),
            false
        );
        if (!$this->getHelper('question')->ask($input, $output, $question)) {
            $output->writeln("Left unchanged.");

            return;
        }
    }

    $this->updateOrderAddresses->replaceAddress($order, $type, $ebayDto);
    $output->writeln(sprintf("%s address updated.", ucfirst($type)));
}

private function formatAddress(?OrderAddress $address): string
{
    if ($address === null) {
        return "(none)";
    }

    return trim(sprintf(
        "%s | %s %s | %s %s (%s) | tel: %s",
        $address->getFullName() ?? '',
        $address->getLine1() ?? '',
        $address->getLine2() ?? '',
        $address->getPostalCode() ?? '',
        $address->getCity() ?? '',
        $address->getCountryCode() ?? '',
        $address->getPhone() ?? ''
    ));
}
```

## Étapes

1. **Créer `UpdateEbayOrderAddressesUseCase`** (`src/Service/Ebay/UseCase/UpdateEbayOrderAddressesUseCase.php`)
   avec `findExistingEbayOrder()` et `replaceAddress()`. Vérifier l'autowiring (aucune déclaration
   manuelle attendue dans `config/services.yaml`).
2. **Modifier `GetEbayFulfillmentOrderCommand`** : ajouter les imports, injecter le use case,
   ajouter l'option `--update-addresses/-u`.
3. Dans `execute()`, brancher `import()` aussi sur `--update-addresses` et lui passer `$input`.
4. Réécrire `import()` : court-circuit `findExistingEbayOrder()` en tête → `handleExistingOrder()` ;
   sinon chemin de création inchangé (email → execute → try/catch).
5. Ajouter `handleExistingOrder()`, `maybeUpdateAddress()`, `formatAddress()`.
6. **Journaliser** l'action dans `logs/src-eurocommemo.md` (règle *action-logging*) après implémentation.
7. **Rafraîchir le graphify** du repo après modification du code (règle graphify du CLAUDE.md) :
   `graphify extract` + `graphify cluster-only --no-label` sur `docs/src-eurocommemo`.

## Vérification

Exécuter les commandes du repo via `scripts/repo_exec.py` (jamais d'appel direct), conformément au
CLAUDE.md.

1. **Lint PHP** de la commande et du nouveau use case :
   `scripts/repo_exec.py src-eurocommemo -- php -l src/Command/GetEbayFulfillmentOrderCommand.php`
   `scripts/repo_exec.py src-eurocommemo -- php -l src/Service/Ebay/UseCase/UpdateEbayOrderAddressesUseCase.php`
2. **Conteneur / DI** : `scripts/repo_exec.py src-eurocommemo -- php bin/console lint:container`
   (confirme que `UpdateEbayOrderAddressesUseCase` est bien autowiré et injecté dans la commande).
3. **Commande absente de la liste des options** : `... php bin/console app:ebay:fulfillment-order --help`
   doit afficher la nouvelle option `--update-addresses` (`-u`).
4. **Scénario commande existante, interactif** (adresse déjà en base) :
   `... php bin/console app:ebay:fulfillment-order -o <existing-order-id> --import`
   → affiche `Order already imported (...)`, puis pour chaque adresse le bloc
   `=== Delivery address ===` / `=== Billing address ===` avec `Current (DB)` vs `eBay`, et une
   question `Update the ... address from eBay? [y/N]`. Répondre `y` sur l'une, `N` sur l'autre, puis
   vérifier en base (`order_address`) que seule l'adresse confirmée a changé.
5. **Scénario cron-safe (non interactif)** :
   `... php bin/console app:ebay:fulfillment-order -o <existing-order-id> --update-addresses --no-interaction`
   → met à jour les deux adresses sans prompt.
   Sans `--update-addresses` en `--no-interaction` → aucune modification (message
   `Non-interactive and --update-addresses not set — left unchanged.`).
6. **Non-régression création** : `... -o <new-order-id> --import` sur une commande absente en base
   → import normal inchangé (`Order imported (id: ..., reference: ...)`).

> Note : le projet ne possède aucune suite de tests de commande (`tests/` ne contient que
> `bootstrap.php`, pas de `CommandTester`). L'ajout d'un test automatisé nécessiterait de
> bootstrapper `KernelTestCase` + `CommandTester` — hors périmètre de cette demande ; la
> vérification est manuelle via les scénarios ci-dessus.
