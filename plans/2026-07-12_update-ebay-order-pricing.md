# Plan — Mise à jour rétroactive des frais de port et prix produits des commandes eBay

## Contexte

Le dernier commit du repo `src-eurocommemo` (`3d9efc7` — *feat(ebay): refactor shipping cost
calculation*) a corrigé une **mauvaise interprétation de l'API eBay Fulfillment** :

- **Frais de port** : ils ne sont plus lus depuis `pricingSummary.deliveryCost` (niveau commande)
  mais **sommés depuis `deliveryCost.shippingCost` de chaque line item**.
- **Prix produit** : `lineItemCost` de l'API est le **total de ligne**, pas le prix unitaire ; le
  prix unitaire est désormais `lineItemCost.value / quantity`.

Deux problèmes en découlent :

1. **Bug bloquant introduit par le refactor** : `FulfillmentOrderDTO::getDeliveryCost()` renvoie un
   tableau clé `'amount'`, alors que son unique consommateur
   `ImportFulfillmentOrderUseCase::defineOrderInformation()` lit `$shippingCost['value']`
   (`ImportFulfillmentOrderUseCase.php:142`). Résultat : `$cost` vaut `null` →
   `setAmountLivraison(null)` → frais de port perdus (coercés à 0). Le chemin de **création** est
   donc lui aussi cassé aujourd'hui. Ce fix est un prérequis, indépendant du reste.

2. **Commandes déjà importées avec des montants erronés** : `ImportFulfillmentOrderUseCase::execute()`
   ne fait que **créer** (il lève `EbayOrderAlreadyImportedException` si la commande existe déjà,
   `ImportFulfillmentOrderUseCase.php:60-62`). Il n'existe aucun moyen de **re-synchroniser** les
   frais de port et les prix produits d'une commande eBay déjà en base avec le calcul corrigé.

**Objectif** : permettre, via la commande d'import `GetEbayFulfillmentOrderCommand`, de mettre à
jour les frais de livraison et les prix produits d'une commande eBay **déjà importée**, à partir du
payload eBay recalculé — sans recréer la commande, sans toucher au stock, sans régénérer la facture.

**Décisions cadrées avec le demandeur** :
- **Portée** : une seule commande à la fois, via l'option existante `--orderId`.
- **Emplacement** : nouvelle option `--update-pricing` (`-p`) sur `GetEbayFulfillmentOrderCommand`,
  avec un nouveau use case dédié `UpdateEbayOrderPricingUseCase`.
- **Facture** : **pas** de régénération du PDF ; on met uniquement à jour les montants en base
  (`amountLivraison`, prix des `OrderProducts`, `amountCmd`, `amountTva`).

Patterns de référence réutilisés : `SyncSendcloudOrderIdsCommand` (structure de commande d'update),
`UpdateEbayOrderAddressesUseCase` (use case d'update d'une commande existante),
`ImportFulfillmentOrderUseCase::defineOrderInformation()` / `::defineOrderLine()` (formules exactes
de conversion de devise, prix unitaire, TVA/TGC, totaux).

## Fichiers concernés

### Modifiés (repo `src-eurocommemo`)

#### 1. `src/Service/Ebay/DTO/Output/Fulfillment/FulfillmentOrderDTO.php`

Corriger `getDeliveryCost()` (`FulfillmentOrderDTO.php:62-75`) : aligner la **clé** sur ce que lit
le consommateur (`'value'`, cohérent avec `FulfillmentAmountDTO::getPayload()` qui utilise `value`),
ajouter la **null-safety** sur `getShippingCost()` (aujourd'hui `->getShippingCost()->getValue()`
sans garde → fatal si un line item n'a pas de `deliveryCost.shippingCost`), et fixer une devise par
défaut sûre pour éviter une conversion sur `currency = null`.

Avant (`FulfillmentOrderDTO.php:62-75`) :

```php
public function getDeliveryCost(): array
{
    $amount = 0;
    $currency = null;
    foreach ($this->getLineItems() as $lineItem) {
        $amount += $lineItem->getShippingCost()->getValue();
        $currency = $lineItem->getShippingCost()->getCurrency();
    }

    return [
        'currency' => $currency,
        'amount' => $amount
    ];
}
```

Après :

```php
public function getDeliveryCost(): array
{
    $amount = 0.0;
    $currency = 'EUR';
    foreach ($this->getLineItems() as $lineItem) {
        $shippingCost = $lineItem->getShippingCost();
        if ($shippingCost === null) {
            continue;
        }
        $amount += $shippingCost->getValue();
        $currency = $shippingCost->getCurrency() ?? $currency;
    }

    return [
        'currency' => $currency,
        'value' => $amount,
    ];
}
```

> Impact : corrige simultanément le chemin de **création**
> (`ImportFulfillmentOrderUseCase::defineOrderInformation()` lit désormais la bonne clé `value`) et
> le nouveau chemin d'**update**. Aucun autre appelant de `getDeliveryCost()` (seul consommateur :
> `ImportFulfillmentOrderUseCase.php:79`).

#### 2. `src/Command/GetEbayFulfillmentOrderCommand.php`

Ajouter l'option `--update-pricing`, injecter le nouveau use case, router le flag vers `import()`,
et déclencher la mise à jour des montants dans `handleExistingOrder()`.

**a. Constructeur** (`GetEbayFulfillmentOrderCommand.php:27-33`) — injecter le use case :

```php
public function __construct(
    private readonly FulfillmentApiV1 $fulfillmentApi,
    private readonly ImportFulfillmentOrderUseCase $importFulfillmentOrder,
    private readonly UpdateEbayOrderAddressesUseCase $updateOrderAddresses,
    private readonly UpdateEbayOrderPricingUseCase $updateOrderPricing,
) {
    parent::__construct();
}
```

Import à ajouter en tête de fichier (après la ligne 16) :

```php
use App\Service\Ebay\UseCase\UpdateEbayOrderPricingUseCase;
```

**b. `configure()`** (`GetEbayFulfillmentOrderCommand.php:35-42`) — ajouter l'option :

```php
->addOption("update-addresses", "u", InputOption::VALUE_NONE, "If the order already exists, update its addresses from eBay without prompting")
->addOption("update-pricing", "p", InputOption::VALUE_NONE, "If the order already exists, re-sync shipping fee and product prices from eBay");
```

**c. Routing dans `execute()`** (`GetEbayFulfillmentOrderCommand.php:62`) — ajouter le flag à la
condition existante :

```php
if ($input->getOption("import") || $input->getOption("update-addresses") || $input->getOption("update-pricing")) {
    return $this->import($order, $input, $output);
}
```

**d. `handleExistingOrder()`** (`GetEbayFulfillmentOrderCommand.php:127-161`) — traiter le pricing et
ne déclencher la logique d'adresses que si les flags adresses/import sont présents (pour que
`--update-pricing` seul ne provoque pas les prompts d'adresses) :

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

    if ($input->getOption("update-pricing")) {
        $this->updateOrderPricing->execute($existing, $ebayOrder);
        $output->writeln(sprintf(
            "Pricing updated — shipping: %s €, order total: %s €",
            $existing->getAmountLivraison(),
            $existing->getAmountCmd()
        ));
    }

    if ($input->getOption("import") || $input->getOption("update-addresses")) {
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
    }

    return Command::SUCCESS;
}
```

> Note : si la commande ciblée n'existe **pas** encore en base et que seul `--update-pricing` est
> passé, `import()` retombe sur le chemin de création normal (`ImportFulfillmentOrderUseCase::execute`),
> qui produit désormais des montants corrects grâce au fix du DTO. Comportement acceptable ; on ne le
> bloque pas.

### Nouveaux (repo `src-eurocommemo`)

#### 3. `src/Service/Ebay/UseCase/UpdateEbayOrderPricingUseCase.php`

Nouveau use case, calqué sur `UpdateEbayOrderAddressesUseCase` (mêmes conventions) et sur les
formules de `ImportFulfillmentOrderUseCase`. Il **met à jour** une commande existante : frais de
port, prix unitaires des `OrderProducts` déjà présents (appariés par produit), puis recalcule les
totaux `amountTva` et `amountCmd`. Il **ne crée pas** de nouvelles lignes, **ne décrémente pas** le
stock (contrairement à l'import — sinon double décompte), **ne régénère pas** la facture.

Enregistrement DI : autowiring Symfony standard (`services.yaml` par convention `App\` →
`src/`), aucune déclaration manuelle nécessaire (comme `UpdateEbayOrderAddressesUseCase`).

```php
<?php

namespace App\Service\Ebay\UseCase;

use App\Entity\Order;
use App\Entity\OrderProducts;
use App\Entity\Product;
use App\Repository\ProductRepository;
use App\Service\CurrencyConverter;
use App\Service\Ebay\DTO\Output\Fulfillment\FulfillmentLineItemDTO;
use App\Service\Ebay\DTO\Output\Fulfillment\FulfillmentOrderDTO;
use Doctrine\ORM\EntityManagerInterface;
use Psr\Log\LoggerInterface;

class UpdateEbayOrderPricingUseCase
{
    public function __construct(
        private readonly EntityManagerInterface $entityManager,
        private readonly CurrencyConverter $currencyConverter,
        private readonly ProductRepository $productRepository,
        private readonly LoggerInterface $logger,
    ) {
    }

    /**
     * Re-sync shipping fee and product unit prices of an already-imported eBay order with the
     * (corrected) eBay Fulfillment payload. Does NOT create/remove line items, touch stock, or
     * regenerate the invoice. Order structure (which products, discounts) is left untouched.
     */
    public function execute(Order $order, FulfillmentOrderDTO $orderFromEbay): void
    {
        // 1. Shipping fee — mirrors ImportFulfillmentOrderUseCase::defineOrderInformation() (141-152)
        $shippingCost = $orderFromEbay->getDeliveryCost();
        $cost = (float) $shippingCost['value'];
        if ($shippingCost['currency'] !== null && $shippingCost['currency'] !== 'EUR') {
            $cost = $this->currencyConverter->convert($cost, $shippingCost['currency'], 'EUR');
        }
        $order->setAmountLivraison($cost);

        // 2. Product unit prices + order totals — mirrors execute() (92-107) & defineOrderLine()
        $sumAmountCmd = 0.0;
        $sumAmountTGC = 0.0;
        foreach ($orderFromEbay->getLineItems() as $item) {
            $this->updateOrderLine($order, $item, $sumAmountCmd, $sumAmountTGC);
        }

        if (!is_null($order->getAmountReduction())) {
            $sumAmountCmd = ($sumAmountCmd < $order->getAmountReduction())
                ? 0
                : $sumAmountCmd - $order->getAmountReduction();
        }
        $sumAmountCmd += $cost;

        $order->setAmountTva($sumAmountTGC);
        $order->setAmountCmd($sumAmountCmd);

        $this->entityManager->flush();
    }

    private function updateOrderLine(
        Order $order,
        FulfillmentLineItemDTO $item,
        float &$sumAmountCmd,
        float &$sumAmountTGC
    ): void {
        // Same product matching as ImportFulfillmentOrderUseCase::defineOrderLine() (218-221)
        $product = $this->productRepository->findOneBy(['ebayId' => $item->getLegacyItemId()]);
        if (!$product) {
            $product = $this->productRepository->findOneBy(['ebayTitle' => $item->getTitle()]);
        }
        if (!$product instanceof Product) {
            $this->logger->critical('[Eurocommemo] product not found on pricing update', [
                'orderEbay' => $order->getOrderIdEbay(),
                'product' => serialize($item),
            ]);

            return;
        }

        $orderProduct = $this->findOrderProductByProduct($order, $product);
        if (!$orderProduct instanceof OrderProducts) {
            $this->logger->warning('[Eurocommemo] no matching order line to update pricing', [
                'orderEbay' => $order->getOrderIdEbay(),
                'productId' => $product->getId(),
            ]);

            return;
        }

        $quantity = $item->getQuantity() > 0 ? $item->getQuantity() : $orderProduct->getQuantity();

        // Unit price — mirrors defineOrderLine() (226-229): lineItemCost is the LINE total.
        $lineCost = $item->getLineItemCost();
        $unitPrice = $lineCost && $lineCost->getCurrency() !== 'EUR'
            ? $this->currencyConverter->convert($lineCost->getValue() / $quantity, $lineCost->getCurrency(), 'EUR')
            : (($lineCost?->getValue() / $quantity) ?? 0.0);

        $orderProduct->setQuantity($quantity);
        $orderProduct->setAmountProductVenteUnitTTC($unitPrice);
        $orderProduct->setAmountProductVenteUnitTGC(
            round($unitPrice - ($unitPrice / (1 + ($product->getTva()->getAmount() / 100))), 2)
        );
        $orderProduct->setAmountProductVenteUnitHT($unitPrice - $orderProduct->getAmountProductVenteUnitTGC());
        $orderProduct->setAmountProductVenteLineTTC($quantity * $unitPrice);

        $sumAmountCmd += $orderProduct->getAmountProductVenteLineTTC();
        $sumAmountTGC += $orderProduct->getAmountProductVenteUnitTGC() * $quantity;
    }

    private function findOrderProductByProduct(Order $order, Product $product): ?OrderProducts
    {
        foreach ($order->getOrderProducts() as $orderProduct) {
            if ($orderProduct->getProduct() === $product) {
                return $orderProduct;
            }
        }

        return null;
    }
}
```

Points d'attention ancrés dans le code réel :

- **Appariement ligne eBay ↔ `OrderProducts`** : aucun `lineItemId` eBay n'est stocké sur
  `OrderProducts` (l'entité ne référence qu'un `Product`, cf. `OrderProducts.php:21-22`). On
  réapparie donc par **produit**, avec la même résolution que l'import (`ebayId` = `getLegacyItemId()`
  puis `ebayTitle` = `getTitle()`). Si une ligne eBay n'a pas d'`OrderProducts` correspondant en
  base (produit ajouté/retiré depuis l'import), elle est **loggée et ignorée** — ce use case met à
  jour le pricing, il ne restructure pas la commande.
- **Quantité** : réalignée sur le payload eBay pour garder un total de ligne cohérent
  (`ligne = quantité × prix unitaire`), en repli sur la quantité en base si eBay renvoie 0.
- **Totaux** : `amountCmd` et `amountTva` recalculés exactement comme à la création
  (`ImportFulfillmentOrderUseCase.php:92-107`) : somme des lignes TTC, moins la réduction existante,
  plus les frais de port. La réduction (`amountReduction`) et le stock ne sont pas retouchés.

### (Optionnel) 4. `tests/Service/Ebay/UseCase/UpdateEbayOrderPricingUseCaseTest.php`

Le repo n'a qu'une suite de tests unitaires (`tests/Service/Sendcloud/SendcloudApiClientTest.php`) —
aucun test sur les use cases eBay. Test recommandé (non bloquant) sur le même style : monter un
`Order` avec un `OrderProducts`, un `FulfillmentOrderDTO` factice, mocker `CurrencyConverter` /
`ProductRepository` / `EntityManagerInterface` / `LoggerInterface`, et asserter `amountLivraison`,
`amountProductVenteUnitTTC` et `amountCmd` après `execute()`.

## Étapes

1. **Fix DTO (prérequis)** — corriger `FulfillmentOrderDTO::getDeliveryCost()` (fichier #1) : clé
   `value`, null-safety `getShippingCost()`, devise par défaut `'EUR'`. Vérifie que le chemin de
   création repose désormais bien sur `$shippingCost['value']`.
2. **Créer le use case** — ajouter `UpdateEbayOrderPricingUseCase` (fichier #3) avec `execute()`,
   `updateOrderLine()`, `findOrderProductByProduct()`.
3. **Câbler la commande** — dans `GetEbayFulfillmentOrderCommand` (fichier #2) : import + injection
   du use case, option `--update-pricing`, ajout du flag au routing `execute()`, branche pricing +
   garde adresses dans `handleExistingOrder()`.
4. **(Optionnel) Test unitaire** — ajouter le test du use case (fichier #4).
5. **Rafraîchir le graphe graphify** du repo après modification (cf. CLAUDE.md § graphify).

## Vérification

Toutes les commandes passent par `scripts/repo_exec.py` (jamais d'appel direct), cf. CLAUDE.md.

1. **Lint / analyse statique** (si configurés dans le repo) :
   ```sh
   scripts/repo_exec.py src-eurocommemo -- vendor/bin/php-cs-fixer fix --dry-run --diff
   scripts/repo_exec.py src-eurocommemo -- vendor/bin/phpstan analyse src/Service/Ebay src/Command
   ```

2. **Aide de la commande** — l'option apparaît :
   ```sh
   scripts/repo_exec.py src-eurocommemo -- bin/console app:ebay:fulfillment-order --help
   ```
   Attendu : `--update-pricing (-p)` listée.

3. **Dry sur une vraie commande eBay déjà importée** — relever d'abord en base
   (`amountLivraison`, `amountCmd`, `order_products.amount_product_vente_unit_ttc` /
   `_line_ttc`) pour un `orderIdEbay` connu, puis :
   ```sh
   scripts/repo_exec.py src-eurocommemo -- bin/console app:ebay:fulfillment-order -o 02-14852-44592 --update-pricing
   ```
   Attendu :
   - sortie `Pricing updated — shipping: <montant> €, order total: <montant> €` ;
   - en base, `amountLivraison` = somme des `deliveryCost.shippingCost` du payload (converti EUR) ;
   - chaque `OrderProducts.amountProductVenteUnitTTC` = `lineItemCost / quantity` (converti EUR),
     `_line_ttc` = `quantité × unitTTC` ;
   - `amountCmd` = Σ lignes TTC − réduction + frais de port ; `amountTva` cohérent ;
   - **aucune** nouvelle ligne `order_products` créée, stock **inchangé**, **aucun** nouveau PDF.

4. **Comparer au payload brut** pour valider les montants attendus :
   ```sh
   scripts/repo_exec.py src-eurocommemo -- bin/console app:ebay:fulfillment-order -o 02-14852-44592 --raw
   ```
   Recouper `deliveryCost.shippingCost` (par ligne) et `lineItemCost` / `quantity` avec les valeurs
   persistées.

5. **Non-régression création** — sur une commande eBay **non** importée, `--import` produit
   désormais des frais de port non nuls (validation du fix DTO) :
   ```sh
   scripts/repo_exec.py src-eurocommemo -- bin/console app:ebay:fulfillment-order -o <nouvelle-commande> --import
   ```

6. **(Optionnel) Tests unitaires** :
   ```sh
   scripts/repo_exec.py src-eurocommemo -- vendor/bin/phpunit tests/Service/Ebay
   ```
