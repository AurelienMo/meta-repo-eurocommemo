# Mise à jour canBeCreateOnDelcampe et canBeBoostOnDelcampe — 2026-06-16

## Contexte

Les changements introduits sur la branche `feature/boost-delcampe` imposent deux nouvelles règles métier :
- **Annonce unique** sur Delcampe (1 catégorie par rotation country → thèmes)
- **Délai configurable** de N jours (défaut 100) entre deux créations/boosts, tracé via `lastBoostDelcampeAt`

Les méthodes `canBeCreateOnDelcampe()` et `canBeBoostOnDelcampe()` sur `Product` pilotent la visibilité des boutons EasyAdmin et le filtre des produits éligibles dans `BoostAutoDelcampeCommand`. Elles doivent refléter ces nouvelles règles.

## Fichiers concernés

| Fichier | Action |
|---|---|
| `src/Entity/Product.php` | Modifier `canBeCreateOnDelcampe()` et `canBeBoostOnDelcampe()` |

## Problèmes actuels

**`canBeCreateOnDelcampe()`** (ligne ~1413) :
- Condition `count($lastCategories) > $this->getProductsDelcampe()->count()` présuppose le multi-catégorie
- Avec la règle annonce unique : dès qu'une annonce existe → création impossible (utiliser le boost)

**`canBeBoostOnDelcampe()`** (ligne ~1700) :
- Délai hardcodé à **15 jours** → doit être N jours configurable (défaut 100)
- Date de référence = `ProductDelcampe.startedAt` le plus ancien → doit prioriser `lastBoostDelcampeAt`

## Appelants (5 points — aucun changement de signature requis)

- `src/Command/Delcampe/BoostAutoDelcampeCommand.php:78`
- `src/Controller/Admin/ProductBCCrudController.php:359` (bouton Créer)
- `src/Controller/Admin/ProductBCCrudController.php:375` (bouton Boost)
- `src/Entity/Product.php:~1718` (appel récursif interne)
- `src/Repository/ProductRepository.php:162`

## Étapes d'implémentation

### 1. `canBeCreateOnDelcampe()` — simplification

Remplacer la condition multi-catégorie par `productsDelcampe.count() === 0` :

```php
public function canBeCreateOnDelcampe(array $lastCategoriesId): bool
{
    if ($this->excludeDelcampe || $this->productImages->count() === 0) {
        return false;
    }

    $lastCategories = $this->getAllCategoriesLastChild($lastCategoriesId);

    return $this->stock > 0
        && $this->shop
        && !is_null($lastCategories)
        && count($lastCategories) > 0
        && $this->productsDelcampe->count() === 0;
}
```

### 2. `canBeBoostOnDelcampe()` — `lastBoostDelcampeAt` + délai configurable

Ajouter `$boostDelayDays = 100` (rétrocompat totale) et utiliser `lastBoostDelcampeAt` en priorité :

```php
public function canBeBoostOnDelcampe(array $lastCategoriesId, int $boostDelayDays = 100): bool
{
    if ($this->excludeDelcampe) {
        return false;
    }

    if ($this->productsDelcampe->count() === 0) {
        return $this->canBeCreateOnDelcampe($lastCategoriesId);
    }

    $reference = $this->lastBoostDelcampeAt;
    if ($reference === null) {
        foreach ($this->productsDelcampe as $productDelcampe) {
            $started = $productDelcampe->getStartedAt();
            if ($started !== null && ($reference === null || $started < $reference)) {
                $reference = $started;
            }
        }
    }

    if ($reference === null) {
        return false;
    }

    $lastCategories = $this->getAllCategoriesLastChild($lastCategoriesId);
    $interval = $reference->diff(new \DateTime());

    return $this->stock > 0
        && !is_null($lastCategories)
        && count($lastCategories) > 0
        && $interval->days >= $boostDelayDays;
}
```

> Le bypass "vendu Delcampe → pas de délai" est géré à la couche application (`DelcampeBoostPolicy`), pas ici.

## Vérification

1. Produit sans annonce → `canBeCreate` : `true`, `canBeBoost` : délègue → `true`
2. Produit avec 1 annonce, `lastBoostDelcampeAt` < 100j → `canBeCreate` : `false`, `canBeBoost` : `false`
3. Produit avec 1 annonce, `lastBoostDelcampeAt` ≥ 100j → `canBeCreate` : `false`, `canBeBoost` : `true`
4. Boutons EasyAdmin et `BoostAutoDelcampeCommand` se comportent correctement
