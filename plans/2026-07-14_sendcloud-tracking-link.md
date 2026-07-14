# Plan — Lien de suivi transporteur à la place de « Voir sur Sendcloud » (page Toutes les commandes)

> Note : conformément à la convention projet (CLAUDE.md § plans), la copie canonique de ce plan
> sera enregistrée à l'implémentation sous `plans/2026-07-14_sendcloud-tracking-link.md` à la
> racine du meta-repo. Le présent fichier est le plan de travail validé en plan-mode.

## Contexte

Sur la page admin EasyAdmin « Toutes les commandes » (`OrderCrudController`, colonne « Infos
livraison »), les commandes associées à Sendcloud affichent aujourd'hui un lien texte
**« Voir sur Sendcloud »** qui ouvre le back-office Sendcloud
(`https://app.sendcloud.com/v2/shipping/list/orders?search=<orderIdEbay>`).

Ce lien n'a d'intérêt que pour l'opérateur interne ; il ne permet pas de **suivre le colis**.
L'objectif est de le remplacer par un lien de **suivi du colis** pointant vers l'URL de tracking
fournie par le transporteur.

L'entité `Order` persiste déjà, après génération de l'étiquette Sendcloud, le champ
`sendcloudTrackingUrl` (alimenté depuis `parcel['tracking_url']` dans
`SendcloudLabelService::generateLabel()`, `src/Service/Sendcloud/SendcloudLabelService.php:49`).
Cette URL est la page de suivi Sendcloud qui redirige vers le suivi réel du transporteur — elle
répond donc directement au besoin **sans stockage ni mapping supplémentaire**.

Décisions validées avec le demandeur :
- **Source du suivi** : réutiliser `sendcloudTrackingUrl` déjà stocké (pas d'URL transporteur
  reconstruite, pas de nouveau champ carrier).
- **Cas sans suivi** (commande liée à Sendcloud mais étiquette non encore générée →
  `sendcloudTrackingUrl` null) : **ne rien afficher** (ni lien de suivi, ni ancien lien Sendcloud).

Portée : le lien « Voir sur Sendcloud » n'existe qu'à un seul endroit du repo, le template
`templates/admin/order/order_ebay_shipping_service.html.twig` (colonne « Infos livraison »),
rendu à la fois sur la vue « Toutes les commandes » (`OrderCrudController.php:266`) et sur la vue
« Prêtes à être expédiées » `delivery=1` (`OrderCrudController.php:292`). Le remplacement vaut donc
pour les deux vues, ce qui est cohérent (dans les deux cas on veut suivre le colis dès qu'un suivi
existe). Aucune modification de PHP, d'entité ou de migration n'est nécessaire.

## Fichiers concernés

### Modifiés

Repo `src-eurocommemo` (`/Users/aurelienmorvan/OrbStack/docker/volumes/src-eurocommemo`)

#### `templates/admin/order/order_ebay_shipping_service.html.twig`

Seul fichier touché. Remplacer le bloc actuel du lien Sendcloud (lignes 17-26) par un bloc
conditionné sur la présence de `sendcloudTrackingUrl`.

État actuel (lignes 17-26) :

```twig
    {% set sendcloudOrderId = entity.instance.sendcloudOrderId %}
    {% if sendcloudOrderId is not null and sendcloudOrderId != '0' and entity.instance.orderIdEbay %}
        <div class="mt-1">
            <a href="https://app.sendcloud.com/v2/shipping/list/orders?search={{ entity.instance.orderIdEbay|url_encode }}"
               class="fw-bold text-primary"
               target="_blank">
                Voir sur Sendcloud
            </a>
        </div>
    {% endif %}
```

Nouvelle version (remplace intégralement les lignes 17-26) :

```twig
    {% set sendcloudTrackingUrl = entity.instance.sendcloudTrackingUrl %}
    {% if sendcloudTrackingUrl %}
        <div class="mt-1">
            <a href="{{ sendcloudTrackingUrl }}"
               class="fw-bold text-primary"
               target="_blank"
               rel="noopener noreferrer">
                Suivre le colis
            </a>
        </div>
    {% endif %}
```

Notes :
- La partie haute du template (lignes 1-15, affichage de `shippingService`) reste **inchangée**.
- La condition passe de `sendcloudOrderId != '0' … and orderIdEbay` à la seule présence de
  `sendcloudTrackingUrl` : ce champ n'est renseigné qu'après génération d'étiquette Sendcloud,
  donc il n'existe que pour des commandes eBay effectivement expédiées via Sendcloud → il implique
  déjà l'association Sendcloud, aucune condition supplémentaire n'est requise.
- `sendcloudTrackingUrl` est une valeur texte simple (colonne `string(255)`,
  `src/Entity/Order.php:118-119`, getter `getSendcloudTrackingUrl()` `src/Entity/Order.php:524`) ;
  Twig auto-échappe l'attribut `href`. Ajout de `rel="noopener noreferrer"` (bonne pratique pour
  `target="_blank"`, absent de la version actuelle).
- Le texte « Suivre le colis » est du contenu d'UI opérateur en français : conforme à la règle
  `terminal-language` / domaine (l'anglais s'applique au code, pas aux libellés métier affichés).

## Étapes

1. Éditer `templates/admin/order/order_ebay_shipping_service.html.twig` : remplacer le bloc
   lignes 17-26 par la nouvelle version ci-dessus. Aucun autre fichier n'est modifié.

2. Vider le cache Twig/EasyAdmin si nécessaire pour la vérification (via
   `scripts/repo_exec.py`, cf. CLAUDE.md § pipeline — jamais d'appel direct).

3. Consigner l'action dans `logs/src-eurocommemo.md` (règle `action-logging`) : fichier modifié,
   statut, notes.

## Vérification

Aucune logique PHP modifiée → pas de test unitaire à ajouter. Vérification manuelle en admin :

1. **Commande avec étiquette générée** (`sendcloudTrackingUrl` renseigné) : sur la page
   « Toutes les commandes » et sur « Prêtes à être expédiées », la colonne « Infos livraison »
   affiche le lien **« Suivre le colis »** ; le `href` correspond à la valeur de
   `sendcloudTrackingUrl` et ouvre la page de suivi du transporteur dans un nouvel onglet.

2. **Commande liée à Sendcloud sans étiquette générée** (`sendcloudTrackingUrl` null) : aucun
   lien de suivi ni « Voir sur Sendcloud » n'apparaît — seule la mention `shippingService` (ou
   `—`) reste affichée.

3. **Commande non-Sendcloud** : comportement inchangé (bloc suivi absent).

4. Confirmer l'absence de régression sur la vue `delivery=1` : le template d'actions
   `order_sendcloud_action.html.twig` (colonne « Sendcloud », sélection méthode / génération
   d'étiquette) n'est pas touché et continue de fonctionner.

Contrôle rapide en base pour cibler un cas de test :
`SELECT id, sendcloud_tracking_url FROM \`order\` WHERE sendcloud_tracking_url IS NOT NULL LIMIT 5;`
