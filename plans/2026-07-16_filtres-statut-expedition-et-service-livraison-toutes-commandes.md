# Plan — Filtres « statut d'expédition » et « service de livraison » sur la page Toutes les commandes

## Contexte

La page **« Toutes les commandes »** du backoffice (repo `src-eurocommemo`, stack Symfony 7 +
EasyAdmin 4.11.1) est servie par `OrderCrudController` sur l'action index d'EasyAdmin, sans
paramètre `state` (menu `submenuIndex=4`, cf. `DashboardController::configureMenuItems`). Elle
affiche aujourd'hui une colonne « Statut » (badges Prévente / En attente d'expédition / Expédiée /
Annulée / En attente de paiement) et une colonne « Infos livraison » (service de livraison eBay),
mais **aucun filtre** ne permet de restreindre la liste sur ces deux dimensions.

On veut ajouter à cette vue deux filtres dans le panneau « Filtres » d'EasyAdmin :

1. **Statut d'expédition** — filtre sur le statut *dérivé* affiché dans la colonne « Statut ».
2. **Service de livraison** — filtre sur l'`ShippingService` (`App\Entity\Ebay\ShippingService`)
   associé à la commande, alimenté par tous les services présents en base.

Point clé : le statut d'expédition **n'est pas une colonne** de l'entité `Order`. Il est calculé à
partir de trois éléments (voir `templates/admin/order/order_state.html.twig`) :
- `Order::$statePayment` (int, constantes de `GlobalConstants`),
- `Order::$dateExpedition` (nullable),
- la présence d'un produit en prévente parmi les `orderProducts` (`Product::$presale`).

Le filtre statut doit donc reproduire cette logique dérivée en SQL, et non filtrer une colonne
unique. Le service de livraison, lui, est une association `ManyToOne` déjà mappée
(`Order::$shippingService`) et déjà jointe dans la requête d'index — il se filtre nativement.

Contrainte de cohérence : la vue « Toutes les commandes » restreint déjà la requête
(`OrderCrudController::createIndexQueryBuilder`, lignes 106-111) à
`statePayment IN (VALID, CANCEL)` + `WAITING_RECEIPT` payé par chèque/virement. Les deux nouveaux
filtres s'ajoutent par `andWhere` par-dessus cette base, sans la contredire.

## Fichiers concernés

### Nouveaux

#### `src/Filter/OrderShippingStatusFilter.php`

Filtre EasyAdmin personnalisé (le statut étant dérivé, aucun `ChoiceFilter` natif ne convient car
son `apply()` génère `entity.shippingStatus IN (...)` sur une propriété inexistante). On implémente
`FilterInterface` + `FilterTrait` en réutilisant le formulaire `ChoiceFilterType`, et on surcharge
`apply()` pour traduire chaque statut sélectionné en clauses `WHERE` dérivées.

Vérifié en amont : `ChoiceConfigurator` ne s'applique qu'au FQCN `ChoiceFilter::class` (donc ne
s'exécute pas ici), et `CommonConfigurator` ne touche la propriété que pour le libellé — une
propriété non mappée (`shippingStatus`) ne provoque donc **aucun** accès aux métadonnées Doctrine.

```php
<?php

declare(strict_types=1);

namespace App\Filter;

use App\Entity\Order;
use App\Utilities\GlobalConstants;
use Doctrine\ORM\QueryBuilder;
use EasyCorp\Bundle\EasyAdminBundle\Contracts\Filter\FilterInterface;
use EasyCorp\Bundle\EasyAdminBundle\Dto\EntityDto;
use EasyCorp\Bundle\EasyAdminBundle\Dto\FieldDto;
use EasyCorp\Bundle\EasyAdminBundle\Dto\FilterDataDto;
use EasyCorp\Bundle\EasyAdminBundle\Filter\FilterTrait;
use EasyCorp\Bundle\EasyAdminBundle\Form\Filter\Type\ChoiceFilterType;

final class OrderShippingStatusFilter implements FilterInterface
{
    use FilterTrait;

    public const STATUS_WAITING_PAYMENT  = 'waiting_payment';
    public const STATUS_CANCELLED        = 'cancelled';
    public const STATUS_SHIPPED          = 'shipped';
    public const STATUS_PRESALE          = 'presale';
    public const STATUS_WAITING_SHIPMENT = 'waiting_shipment';

    public static function new(string $propertyName, $label = null): self
    {
        return (new self())
            ->setFilterFqcn(__CLASS__)
            ->setProperty($propertyName)
            ->setLabel($label)
            ->setFormType(ChoiceFilterType::class)
            ->setFormTypeOption('translation_domain', 'EasyAdminBundle')
            // Multi-sélection : l'opérateur peut cocher plusieurs statuts.
            ->setFormTypeOption('value_type_options.multiple', true)
            ->setFormTypeOption('value_type_options.choices', [
                'En attente de paiement'  => self::STATUS_WAITING_PAYMENT,
                'Annulée'                 => self::STATUS_CANCELLED,
                'Expédiée'                => self::STATUS_SHIPPED,
                'Prévente'                => self::STATUS_PRESALE,
                "En attente d'expédition" => self::STATUS_WAITING_SHIPMENT,
            ]);
    }

    public function apply(QueryBuilder $queryBuilder, FilterDataDto $filterDataDto, ?FieldDto $fieldDto, EntityDto $entityDto): void
    {
        $alias      = $filterDataDto->getEntityAlias(); // "entity"
        $comparison = $filterDataDto->getComparison();  // "IN" ou "NOT IN"
        $value      = $filterDataDto->getValue();

        if (null === $value) {
            return;
        }

        $statuses = \is_array($value) ? $value : [$value];
        if ([] === $statuses) {
            return;
        }

        // Sous-requête « commandes contenant au moins un produit en prévente ».
        // Mirroir de la logique du bloc `ready` de OrderCrudController::createIndexQueryBuilder.
        $presaleSubDql = sprintf(
            'SELECT o2.id FROM %s o2 JOIN o2.orderProducts op2 JOIN op2.product p2 WHERE p2.presale = true',
            Order::class
        );

        $orX = $queryBuilder->expr()->orX();
        foreach ($statuses as $status) {
            switch ($status) {
                case self::STATUS_WAITING_PAYMENT:
                    $orX->add(sprintf('%s.statePayment = %d', $alias, GlobalConstants::CONST_STATE_PAYMENT_WAITING_RECEIPT));
                    break;
                case self::STATUS_CANCELLED:
                    $orX->add(sprintf('%s.statePayment = %d', $alias, GlobalConstants::CONST_STATE_PAYMENT_CANCEL));
                    break;
                case self::STATUS_SHIPPED:
                    $orX->add(sprintf(
                        '(%1$s.statePayment = %2$d AND (%1$s.delivery IS NOT NULL OR %1$s.isEbay = true) AND %1$s.dateExpedition IS NOT NULL)',
                        $alias,
                        GlobalConstants::CONST_STATE_PAYMENT_VALID
                    ));
                    break;
                case self::STATUS_PRESALE:
                    $orX->add(sprintf(
                        '(%1$s.statePayment = %2$d AND (%1$s.delivery IS NOT NULL OR %1$s.isEbay = true) AND %1$s.dateExpedition IS NULL AND %1$s.id IN (%3$s))',
                        $alias,
                        GlobalConstants::CONST_STATE_PAYMENT_VALID,
                        $presaleSubDql
                    ));
                    break;
                case self::STATUS_WAITING_SHIPMENT:
                    $orX->add(sprintf(
                        '(%1$s.statePayment = %2$d AND (%1$s.delivery IS NOT NULL OR %1$s.isEbay = true) AND %1$s.dateExpedition IS NULL AND %1$s.id NOT IN (%3$s))',
                        $alias,
                        GlobalConstants::CONST_STATE_PAYMENT_VALID,
                        $presaleSubDql
                    ));
                    break;
            }
        }

        if (0 === $orX->count()) {
            return;
        }

        // Respecte le sélecteur de comparaison IN / NOT IN du ChoiceFilterType.
        if ('NOT IN' === $comparison) {
            $queryBuilder->andWhere($queryBuilder->expr()->not($orX));
        } else {
            $queryBuilder->andWhere($orX);
        }
    }
}
```

Correspondance statut ↔ badge (source : `templates/admin/order/order_state.html.twig`, lignes 1-21) :

| Statut (constante)         | Badge Twig                | Condition SQL dérivée |
|----------------------------|---------------------------|------------------------|
| `STATUS_WAITING_PAYMENT`   | En attente de paiement    | `statePayment = 2` (WAITING_RECEIPT) |
| `STATUS_CANCELLED`         | Annulée                   | `statePayment = 3` (CANCEL) |
| `STATUS_SHIPPED`           | Expédiée                  | `statePayment = 1 AND (delivery IS NOT NULL OR isEbay) AND dateExpedition IS NOT NULL` |
| `STATUS_PRESALE`           | Prévente                  | `... = 1 AND (...) AND dateExpedition IS NULL AND id IN (sous-requête prévente)` |
| `STATUS_WAITING_SHIPMENT`  | En attente d'expédition   | `... = 1 AND (...) AND dateExpedition IS NULL AND id NOT IN (sous-requête prévente)` |

### Modifiés

#### `src/Controller/Admin/OrderCrudController.php`

**a) Imports** — ajouter en tête (bloc `use`, à côté des filtres existants lignes 22/37/51) :

```php
use App\Filter\OrderShippingStatusFilter;
use EasyCorp\Bundle\EasyAdminBundle\Filter\EntityFilter;
```

**b) `configureFilters()` (lignes 77-100)** — ajouter les deux filtres, gardés sur la vue
« Toutes les commandes » (absence du paramètre `state`, même garde que lignes 106/253/294).
Version complète de la méthode après modification :

```php
public function configureFilters(Filters $filters): Filters
{
    $request = $this->requestStack->getCurrentRequest();
    $state = $request->query->get('state');
    $ready = $request->query->get('ready');
    $delivery = $request->query->get('delivery');

    $filter = Filters::new();

    if ($state) {
        $filter->add(BooleanFilter::new('state'));
    }
    if ($ready) {
        $filter->add(BooleanFilter::new('ready'));
    }
    if ($delivery) {
        $filter->add(BooleanFilter::new('delivery'));
    }

    // Filtres propres à la vue « Toutes les commandes » (aucun paramètre `state`).
    if (!$request->query->has('state')) {
        $filter->add(OrderShippingStatusFilter::new('shippingStatus', "Statut d'expédition"));
        $filter->add(
            EntityFilter::new('shippingService', 'Service de livraison')
                // ShippingService n'a pas de __toString() : on affiche le nom du service
                // via choice_label (property path -> getShippingService()).
                ->setFormTypeOption('value_type_options.choice_label', 'shippingService')
        );
    }

    $filter->add(BooleanFilter::new('isEbay', 'Commande eBay'));
    $filter->add(NumericFilter::new('fakeOrderIdEbay', 'N° Fake facture'));

    return $filter;
}
```

Remarques d'ancrage :
- `EntityFilter` sur une association *to-one* génère `entity.shippingService IN (:param)` (branche
  `else` de `EntityFilter::apply()`, ligne ~72), **sans** ajouter de jointure — donc aucun conflit
  avec le `leftJoin('entity.shippingService', 'shippingService')` déjà présent à la ligne 104 de
  `createIndexQueryBuilder`.
- La liste déroulante du service est alimentée automatiquement par `EntityFilterType` depuis tous
  les `ShippingService` en base. `choice_label => 'shippingService'` évite d'ajouter un
  `__toString()` à l'entité (alternative possible mais plus intrusive).
- `createIndexQueryBuilder` n'a **pas** besoin d'être modifié : les filtres EasyAdmin sont appliqués
  après lui via leur `apply()`, sur le même `QueryBuilder` (alias `entity`).

## Étapes

1. **Créer le filtre statut** — ajouter `src/Filter/OrderShippingStatusFilter.php` avec le contenu
   ci-dessus. Vérifier que le namespace `App\Filter` est bien couvert par l'autoload PSR-4 de
   `composer.json` (préfixe `App\` → `src/`, standard Symfony ; sinon `composer dump-autoload`).
2. **Brancher les filtres dans le contrôleur** — modifier `OrderCrudController.php` : ajouter les
   deux `use`, puis remplacer le corps de `configureFilters()` par la version ci-dessus. Ne toucher
   à aucune autre méthode.
3. **Vérifier l'exécution** (voir section suivante) : le bouton « Filtres » de la vue
   « Toutes les commandes » expose les deux nouveaux filtres et chaque sélection restreint bien la
   liste, en cohérence avec les badges de la colonne « Statut » et le service affiché.

## Vérification

Toutes les commandes d'exécution passent par `scripts/repo_exec.py` (cf. CLAUDE.md).

1. **Sanity PHP / conteneur** : `php bin/console cache:clear` puis `php bin/console debug:container`
   ne renvoie aucune erreur (classe `App\Filter\OrderShippingStatusFilter` chargeable).
2. **Rendu du panneau** : se connecter au backoffice, ouvrir **« Toutes les commandes »**
   (`OrderCrudController` index, sans `state`), cliquer sur **Filtres**. Vérifier la présence de
   « Statut d'expédition » (5 choix, multi-sélection) et « Service de livraison » (déroulant listant
   les services de `ebay_shipping_service`, libellés lisibles via `getShippingService()`).
3. **Filtre statut — cohérence avec les badges** : pour chacun des 5 statuts, appliquer le filtre et
   confirmer que toutes les lignes affichées portent le badge correspondant dans la colonne
   « Statut » (ex. « Expédiée » → uniquement des commandes avec `dateExpedition` non nulle ;
   « Prévente » → uniquement des commandes VALID non expédiées contenant ≥ 1 produit `presale`).
   Tester une sélection multiple (ex. Prévente + En attente d'expédition) → union correcte.
4. **Filtre service** : choisir un service donné → seules les commandes reliées à ce
   `ShippingService` restent. Vérifier qu'aucune erreur de jointure/DQL n'apparaît (le join
   `shippingService` préexistant ne doit pas être dupliqué).
5. **Non-régression des autres vues** : ouvrir « Commandes en attente de paiement » (`state=2`) et
   « Commandes prêtes à être expédiées » (`state=1&delivery=1&ready=1`) et confirmer que les deux
   nouveaux filtres **n'apparaissent pas** (garde `!has('state')`) et que ces vues sont inchangées.
6. **Rafraîchir le graphe** après implémentation (cf. CLAUDE.md § graphify) :
   `graphify extract` + `graphify cluster-only` sur `docs/src-eurocommemo`.
