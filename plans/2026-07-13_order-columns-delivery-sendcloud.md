# Plan — Colonnes « Infos livraison » et « Sendcloud » par écran de commandes

## Contexte

L'admin EasyAdmin expose trois listings de commandes, tous servis par le même
`OrderCrudController`, différenciés par les query params du menu
(`src/Controller/Admin/DashboardController.php:121-123`) :

| Écran | Query params |
|---|---|
| Commandes en attente de paiement | `state = WAITING_RECEIPT` |
| Commandes prêtes à être expédiées | `state = VALID`, `delivery = 1`, `ready = 1` |
| Toutes les commandes | *(aucun `state`)* |

État actuel des colonnes construites par `configureFields()` :

- **En attente de paiement** : passe par la branche `else` (lignes 258-263) → affiche
  « Infos livraison ». ❌ Non désiré.
- **Prêtes à être expédiées** : « Infos livraison » en position 3 (ligne 255, branche
  `delivery === 1`), « Sendcloud » bien plus loin (ligne 294). ❌ Mauvais positionnement.
- **Toutes les commandes** : « Infos livraison » apparaît **deux fois** (ligne 261 via la
  branche `else`, puis ligne 268 via le bloc `!has('state')`). ❌ Doublon.

Objectif :
1. « Infos livraison » **uniquement** sur *prêtes à être expédiées* et *toutes les commandes*.
2. « Sendcloud » **uniquement** sur *prêtes à être expédiées* (déjà le cas — à préserver).
3. Sur *prêtes à être expédiées* : « Infos livraison » **juste avant** « Sendcloud ».
4. Sur *toutes les commandes* : « Infos livraison » **juste avant** « N° Commande eBay ».

## Fichiers concernés

### Modifiés

#### `src/Controller/Admin/OrderCrudController.php` — méthode `configureFields()` (lignes 248-312)

Trois modifications ponctuelles, toutes dans cette méthode. Aucune autre méthode, aucun
template, aucune entité, aucune migration n'est touché.

**Modification 1 — Retirer « Infos livraison » de la branche `else`** (satisfait besoins 1 et 4).

La branche `else` (lignes 258-263) sert *En attente de paiement* **et** *Toutes les commandes*.
Retirer sa ligne « Infos livraison » (ligne 261) l'enlève de l'écran *en attente de paiement*
et supprime le doublon sur *toutes les commandes* (qui conserve son occurrence ligne 268).

```php
// AVANT (lignes 258-263)
} else {
    $return[] = Field::new('adminObject', "Commande")->setTemplatePath('admin/order/order_id.html.twig');
    $return[] = Field::new('adminObject', "Informations de contact")->setTemplatePath('admin/order/order_contact.html.twig');
    $return[] = Field::new('adminObject', "Informations de réception")->setTemplatePath('admin/order/order_delivery.html.twig');
    $return[] = Field::new('adminObject', "Infos livraison")->setTemplatePath('admin/order/order_ebay_shipping_service.html.twig')->addCssClass('text-center')->setTextAlign('center');
    $return[] = Field::new('adminObject', "Informations paiement")->setTemplatePath('admin/order/order_state_payment.html.twig');
}

// APRÈS
} else {
    $return[] = Field::new('adminObject', "Commande")->setTemplatePath('admin/order/order_id.html.twig');
    $return[] = Field::new('adminObject', "Informations de contact")->setTemplatePath('admin/order/order_contact.html.twig');
    $return[] = Field::new('adminObject', "Informations de réception")->setTemplatePath('admin/order/order_delivery.html.twig');
    $return[] = Field::new('adminObject', "Informations paiement")->setTemplatePath('admin/order/order_state_payment.html.twig');
}
```

**Modification 2 — Retirer « Infos livraison » de la branche `delivery === 1`** (prépare le besoin 3).

Dans la branche `delivery === 1` (lignes 252-256), retirer la ligne « Infos livraison »
(ligne 255) pour pouvoir la replacer juste avant « Sendcloud ».

```php
// AVANT (lignes 252-256)
if ((int)$this->requestStack->getCurrentRequest()->query->get('delivery') === 1 ) {
    $return[] = Field::new('adminObject', "Informations de contact")->setTemplatePath('admin/order/order_contact.html.twig');
    $return[] = Field::new('adminObject', "Informations de réception")->setTemplatePath('admin/order/order_delivery.html.twig');
    $return[] = Field::new('adminObject', "Infos livraison")->setTemplatePath('admin/order/order_ebay_shipping_service.html.twig')->addCssClass('text-center')->setTextAlign('center');
    $return[] = Field::new('adminObject', "Informations paiement")->setTemplatePath('admin/order/order_state_payment.html.twig');
} else {

// APRÈS
if ((int)$this->requestStack->getCurrentRequest()->query->get('delivery') === 1 ) {
    $return[] = Field::new('adminObject', "Informations de contact")->setTemplatePath('admin/order/order_contact.html.twig');
    $return[] = Field::new('adminObject', "Informations de réception")->setTemplatePath('admin/order/order_delivery.html.twig');
    $return[] = Field::new('adminObject', "Informations paiement")->setTemplatePath('admin/order/order_state_payment.html.twig');
} else {
```

**Modification 3 — Insérer « Infos livraison » juste avant « Sendcloud »** (satisfait besoin 3).

Dans le bloc `delivery === 1` de fin de méthode (lignes 293-297), ajouter la colonne
« Infos livraison » comme **première** entrée, immédiatement avant « Sendcloud ». Ce bloc ne
s'exécute que pour l'écran *prêtes à être expédiées* (seul écran avec `delivery = 1`), ce qui
garantit aussi que « Sendcloud » reste exclusif à cet écran (besoin 2, déjà satisfait — préservé).

```php
// AVANT (lignes 293-297)
if ((int)$this->requestStack->getCurrentRequest()->query->get('delivery') === 1 ) {
    $return[] = Field::new('adminObject', "Sendcloud")->setTemplatePath('admin/order/order_sendcloud_action.html.twig');
    $return[] = Field::new('adminObject', "Expédition")->setTemplatePath('admin/order/order_delivery_action.html.twig');
    $return[] = Field::new('adminObject', "Commande")->setTemplatePath('admin/order/order_id.html.twig');
}

// APRÈS
if ((int)$this->requestStack->getCurrentRequest()->query->get('delivery') === 1 ) {
    $return[] = Field::new('adminObject', "Infos livraison")->setTemplatePath('admin/order/order_ebay_shipping_service.html.twig')->addCssClass('text-center')->setTextAlign('center');
    $return[] = Field::new('adminObject', "Sendcloud")->setTemplatePath('admin/order/order_sendcloud_action.html.twig');
    $return[] = Field::new('adminObject', "Expédition")->setTemplatePath('admin/order/order_delivery_action.html.twig');
    $return[] = Field::new('adminObject', "Commande")->setTemplatePath('admin/order/order_id.html.twig');
}
```

## Résultat attendu (ordre des colonnes après modifications)

- **En attente de paiement** : Commande · Contact · Réception · Paiement · *(valid_payment)*
  → plus de « Infos livraison ». ✅
- **Prêtes à être expédiées** : Contact · Réception · Paiement · Préparation · Facture ·
  N° Commande eBay · N° Fake Facture · **Infos livraison** · **Sendcloud** · Expédition · Commande
  → « Infos livraison » juste avant « Sendcloud ». ✅
- **Toutes les commandes** : Commande · Contact · Réception · Paiement · Statut · Éligible compta. ·
  **Infos livraison** · Facture · **N° Commande eBay** · …
  → une seule « Infos livraison », juste avant « N° Commande eBay ». ✅

## Étapes

1. Ouvrir `src/Controller/Admin/OrderCrudController.php`, méthode `configureFields()`.
2. Appliquer **Modification 1** (supprimer « Infos livraison » de la branche `else`).
3. Appliquer **Modification 2** (supprimer « Infos livraison » de la branche `delivery === 1`).
4. Appliquer **Modification 3** (insérer « Infos livraison » avant « Sendcloud » dans le bloc
   `delivery === 1` final).
5. Vérifier qu'aucun `$return[]` ne référence deux fois `order_ebay_shipping_service.html.twig`
   pour un même écran.

## Vérification

- **Lint / syntaxe PHP** : `php -l src/Controller/Admin/OrderCrudController.php` (via
  `scripts/repo_exec.py` selon la config du repo).
- **Manuel** — se connecter à l'admin et vérifier les 3 menus (DashboardController lignes 121-123) :
  - *Commandes en attente de paiement* → colonne « Infos livraison » **absente**.
  - *Commandes prêtes à être expédiées* → « Infos livraison » présente **immédiatement à gauche**
    de « Sendcloud » ; « Sendcloud » toujours présente.
  - *Toutes les commandes* → « Infos livraison » présente **une seule fois**, immédiatement à
    gauche de « N° Commande eBay » ; « Sendcloud » **absente**.
- **Non-régression** : les contenus des colonnes déplacées sont inchangés (mêmes templates
  `order_ebay_shipping_service.html.twig` et `order_sendcloud_action.html.twig`).

---

*Note : conformément au skill `plan-writer` et à la convention projet (CLAUDE.md), après
approbation ce plan sera aussi persisté dans le meta-repo sous
`plans/2026-07-13_order-columns-delivery-sendcloud.md`.*
