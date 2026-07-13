# Plan — Mise à jour du service de livraison depuis `GetEbayFulfillmentOrderCommand`

## Contexte

La commande `app:ebay:fulfillment-order` (`GetEbayFulfillmentOrderCommand`) sait déjà, pour une
commande eBay **déjà importée**, resynchroniser depuis eBay :

- le pricing (`--update-pricing` → `UpdateEbayOrderPricingUseCase`),
- les adresses (`--update-addresses` → `UpdateEbayOrderAddressesUseCase`).

En revanche, le **service de livraison choisi** (`Order.shippingServiceCode` + relation
`Order.shippingService`) n'est écrit **qu'au moment de l'import initial** — bloc de 3 lignes dans
`ImportFulfillmentOrderUseCase::execute()` (lignes 90-93). Si l'acheteur change de mode de livraison
sur eBay après l'import, la commande locale reste figée sur l'ancien service.

**Objectif** : ajouter à la commande une option dédiée `-s / --update-shipping` qui, sur une commande
déjà importée, resynchronise `shippingServiceCode` + `shippingService` depuis le payload Fulfillment,
en réutilisant **exactement** la logique de mapping de l'import. Application directe (sans
confirmation interactive), à l'image de `--update-pricing`. Décision UX validée avec l'utilisateur.

La logique de mapping cible (identique à l'import) est :

```php
if ($shippingServiceToken = $orderFromEbay->getShippingServiceCode()) {
    $order->setShippingServiceCode($shippingServiceToken);
    $order->setShippingService($this->shippingServiceRepository->findOneByToken($shippingServiceToken));
}
```

Source du token : `FulfillmentOrderDTO::getShippingServiceCode()` →
`fulfillmentStartInstructions[0].shippingStep.shippingServiceCode`. Le lookup
`ShippingServiceRepository::findOneByToken()` retourne `null` si le token n'est pas au catalogue
(table alimentée par `app:ebay:list-shipping-services`) — comportement conservé tel quel.

---

## Fichiers concernés

Tous les chemins sont relatifs au repo `src-eurocommemo`
(`/Users/aurelienmorvan/OrbStack/docker/volumes/src-eurocommemo/`).

### Nouveaux

#### `src/Service/Ebay/UseCase/UpdateEbayOrderShippingServiceUseCase.php`

Nouveau use case, calqué sur `UpdateEbayOrderPricingUseCase` (même dossier, mêmes conventions :
constructeur `readonly`, `execute(Order, FulfillmentOrderDTO): void`, `flush()` en fin). Il isole
la mise à jour du service de livraison sans toucher au pricing ni aux adresses. Renvoie l'ancien et
le nouveau token pour permettre à la commande d'afficher un feedback lisible.

```php
<?php

namespace App\Service\Ebay\UseCase;

use App\Entity\Order;
use App\Repository\Ebay\ShippingServiceRepository;
use App\Service\Ebay\DTO\Output\Fulfillment\FulfillmentOrderDTO;
use Doctrine\ORM\EntityManagerInterface;

class UpdateEbayOrderShippingServiceUseCase
{
    public function __construct(
        private readonly EntityManagerInterface $entityManager,
        private readonly ShippingServiceRepository $shippingServiceRepository,
    ) {
    }

    /**
     * Re-sync the chosen shipping service of an already-imported eBay order with the eBay
     * Fulfillment payload. Mirrors the shipping-service mapping performed at import time in
     * ImportFulfillmentOrderUseCase::execute() (90-93). Leaves pricing, addresses and line
     * items untouched.
     *
     * @return array{previousCode: ?string, newCode: ?string} tokens before/after the update
     */
    public function execute(Order $order, FulfillmentOrderDTO $orderFromEbay): array
    {
        $previousCode = $order->getShippingServiceCode();

        $shippingServiceToken = $orderFromEbay->getShippingServiceCode();
        if ($shippingServiceToken !== null) {
            $order->setShippingServiceCode($shippingServiceToken);
            $order->setShippingService(
                $this->shippingServiceRepository->findOneByToken($shippingServiceToken)
            );
            $this->entityManager->flush();
        }

        return [
            'previousCode' => $previousCode,
            'newCode' => $order->getShippingServiceCode(),
        ];
    }
}
```

> Note d'ancrage : `ShippingServiceRepository` vit sous `App\Repository\Ebay` (confirmé par l'import
> `App\Repository\Ebay\ShippingServiceRepository` et la méthode
> `findOneByToken(string $token): ?ShippingService` en `ShippingServiceRepository.php:16-19`). La
> signature de `getShippingServiceCode()` est bien `?string` (`FulfillmentOrderDTO.php:100-103`).
> `setShippingServiceCode(?string)` et `setShippingService(?ShippingService)` existent tels quels sur
> `Order` (`Order.php:436-456`).

### Modifiés

#### `src/Command/GetEbayFulfillmentOrderCommand.php`

Trois modifications ponctuelles, dans le style des dépendances / options / feedback existants.

**a) Import + dépendance constructeur** (après la ligne 17 `use ...\UpdateEbayOrderPricingUseCase;`
et dans le constructeur lignes 28-35) :

```php
use App\Service\Ebay\UseCase\UpdateEbayOrderShippingServiceUseCase; // nouvel import
```

```php
public function __construct(
    private readonly FulfillmentApiV1 $fulfillmentApi,
    private readonly ImportFulfillmentOrderUseCase $importFulfillmentOrder,
    private readonly UpdateEbayOrderAddressesUseCase $updateOrderAddresses,
    private readonly UpdateEbayOrderPricingUseCase $updateOrderPricing,
    private readonly UpdateEbayOrderShippingServiceUseCase $updateOrderShippingService, // nouveau
) {
    parent::__construct();
}
```

**b) Nouvelle option** (dans `configure()`, après la ligne 44 `--update-pricing`) :

```php
->addOption("update-shipping", "s", InputOption::VALUE_NONE, "If the order already exists, re-sync the chosen shipping service (code + relation) from eBay");
```

**c) Déclencheur `execute()`** — la commande route vers `import()` dès qu'une option d'action est
posée. Ajouter `update-shipping` à la condition (ligne 65) :

```php
if (
    $input->getOption("import")
    || $input->getOption("update-addresses")
    || $input->getOption("update-pricing")
    || $input->getOption("update-shipping")
) {
    return $this->import($order, $input, $output);
}
```

**d) Appel dans `handleExistingOrder()`** — insérer un bloc juste après le bloc `--update-pricing`
(après la ligne 149, avant le bloc adresses ligne 151), en miroir de son feedback :

```php
if ($input->getOption("update-shipping")) {
    $result = $this->updateOrderShippingService->execute($existing, $ebayOrder);
    $matched = $existing->getShippingService() !== null ? 'matched in catalogue' : 'no catalogue match';
    $output->writeln(sprintf(
        "Shipping service updated — %s → %s (%s)",
        $result['previousCode'] ?? '(none)',
        $result['newCode'] ?? '(none)',
        $matched
    ));
}
```

> Remarque : le cas « commande inexistante » (branche `import()` complète, lignes 97-127) n'a pas
> besoin d'être modifié — l'import initial pose déjà `shippingServiceCode` + `shippingService` via
> `ImportFulfillmentOrderUseCase`. `--update-shipping` ne concerne que le chemin
> `handleExistingOrder()`.

#### Enregistrement du service (à vérifier, probablement aucun changement)

`UpdateEbayOrderPricingUseCase` et `UpdateEbayOrderAddressesUseCase` sont injectés sans configuration
explicite : l'autowiring Symfony par défaut (`services.yaml`, `App\` → `src/`, `autowire: true`,
`autoconfigure: true`) couvre le nouveau use case. Vérifier qu'aucun `services.yaml` n'exclut
`src/Service/Ebay/UseCase/` ; si l'exclusion existe, ajouter une déclaration explicite calquée sur
celle de `UpdateEbayOrderPricingUseCase`. **Par défaut : aucun fichier de config à modifier.**

---

## Étapes

1. **Créer le use case** `src/Service/Ebay/UseCase/UpdateEbayOrderShippingServiceUseCase.php` avec la
   classe ci-dessus (constructeur `EntityManagerInterface` + `ShippingServiceRepository`, méthode
   `execute()` renvoyant `{previousCode, newCode}`).

2. **Modifier `GetEbayFulfillmentOrderCommand.php`** — 4 sous-étapes (a→d ci-dessus) :
   import + dépendance constructeur, option `--update-shipping`, ajout à la condition de routage
   `execute()`, bloc d'appel + feedback dans `handleExistingOrder()`.

3. **Vérifier l'autowiring** — s'assurer que `config/services.yaml` n'exclut pas
   `src/Service/Ebay/UseCase/` ; sinon déclarer le service explicitement.

4. **Journaliser l'action** dans `logs/src-eurocommemo.md` (règle `action-logging`) : entrée datée
   listant le fichier créé + le fichier modifié.

5. **Rafraîchir le graphe graphify** du repo après modification (règle `graphify` du CLAUDE.md) :
   `graphify extract` puis `graphify cluster-only` sur `docs/src-eurocommemo`.

---

## Vérification

Exécution des commandes du repo **via `scripts/repo_exec.py`** (jamais d'appel direct), conformément
au CLAUDE.md.

1. **Lint / analyse statique** — lancer le linter PHP / PHPStan du repo sur les deux fichiers touchés
   pour confirmer types et signatures (aucune erreur d'autowiring, `array{previousCode,newCode}`
   cohérent).

2. **Sanity CLI** — `php bin/console app:ebay:fulfillment-order --help` doit afficher la nouvelle
   option `-s, --update-shipping`.

3. **Scénario nominal (commande déjà importée, service changé sur eBay)** :
   `php bin/console app:ebay:fulfillment-order -o <orderId> --update-shipping`
   - Attendu : ligne `Shipping service updated — <ancien> → <nouveau> (matched in catalogue)`.
   - Vérifier en base que `orders.shipping_service_code` et `orders.shipping_service_id` reflètent le
     nouveau token (`shipping_service_id` = id du `ShippingService` dont
     `shipping_service` == token, ou `NULL` si hors catalogue).

4. **Cas token hors catalogue** — sur une commande dont le token eBay n'existe pas dans la table
   `ShippingService` : `shipping_service_code` est mis à jour, `shipping_service_id` passe à `NULL`,
   feedback `(no catalogue match)`. Aucune exception.

5. **Cas payload sans shippingStep** — si `getShippingServiceCode()` renvoie `null`, aucune écriture,
   aucun `flush()` inutile ; l'ordre reste inchangé (feedback `(none) → (none)`).

6. **Non-régression** — vérifier que `--update-pricing` et `--update-addresses` fonctionnent
   toujours seuls et se combinent proprement avec `--update-shipping` (ex.
   `-o <id> --update-pricing --update-shipping`), et que l'import initial d'une commande **non**
   existante continue de poser correctement le service de livraison (chemin `import()` inchangé).
