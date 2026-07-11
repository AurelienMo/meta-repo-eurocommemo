# Plan — Lien Sendcloud dans la colonne « Service eBay sélectionné » de la liste des commandes

## Contexte

La liste des commandes du back-office (EasyAdmin) affiche une colonne « Service eBay
sélectionné » rendue par le template de cellule
`templates/admin/order/order_ebay_shipping_service.html.twig`. Les commits récents ont
introduit un connecteur Sendcloud (`SendcloudApiClient`), un champ `Order::$sendcloudOrderId`
(migration `Version20260711001138`) et une commande de synchronisation
(`app:sendcloud:sync-order-ids`) qui rapproche chaque commande eBay de son homologue Sendcloud.

On veut réutiliser cette même colonne pour afficher **en plus** du nom du service un lien
direct vers la commande sur la plateforme Sendcloud, ouvert dans un nouvel onglet. Le lien
pointe vers la recherche Sendcloud en injectant l'**identifiant eBay** de la commande dans
l'URL (format `02-14852-44592`) :

```
https://app.sendcloud.com/v2/shipping/list/orders?search=<orderIdEbay>
```

Contrainte d'affichage : le lien n'apparaît **que si** `sendcloudOrderId` est renseigné et
différent de la chaîne `"0"`. En effet, la commande de sync écrit littéralement `"0"` dans ce
champ quand aucune correspondance Sendcloud n'est trouvée
(`SyncSendcloudOrderIdsCommand.php:98` : `$order->setSendcloudOrderId("0")`) ; `"0"` signifie
donc « pas de commande Sendcloud », et un `null` signifie « jamais synchronisé ». Dans les deux
cas, pas de lien.

Aucune modification de PHP, d'entité, de contrôleur ni de traduction n'est nécessaire : la
colonne, la relation `shippingService` et le champ `sendcloudOrderId` existent déjà et sont
accessibles dans le template via `entity.instance`. Le changement est **entièrement contenu
dans un seul template Twig**.

## Fichiers concernés

### Modifiés

#### `templates/admin/order/order_ebay_shipping_service.html.twig`

Fichier actuel (16 lignes) — rend le nom du service eBay avec un tooltip optionnel :

```twig
<div class="text-center small">
    {% if entity.instance.shippingService is not null %}
        {% set shippingServiceDescription = entity.instance.shippingService.description %}
        <span
            {% if shippingServiceDescription %}
                data-bs-toggle="tooltip"
                data-bs-placement="top"
                title="{{ shippingServiceDescription }}"
            {% endif %}
        >
            {{ entity.instance.shippingService.shippingService }}
        </span>
    {% else %}
        <span class="text-muted">—</span>
    {% endif %}
</div>
```

Nouvelle version complète — on conserve le bloc existant à l'identique et on ajoute, **après**
le `{% endif %}` du service (donc sous le nom du service, dans la même cellule), un bloc de lien
Sendcloud conditionnel :

```twig
<div class="text-center small">
    {% if entity.instance.shippingService is not null %}
        {% set shippingServiceDescription = entity.instance.shippingService.description %}
        <span
            {% if shippingServiceDescription %}
                data-bs-toggle="tooltip"
                data-bs-placement="top"
                title="{{ shippingServiceDescription }}"
            {% endif %}
        >
            {{ entity.instance.shippingService.shippingService }}
        </span>
    {% else %}
        <span class="text-muted">—</span>
    {% endif %}

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
</div>
```

Détails d'ancrage :

- **Condition de visibilité** : `sendcloudOrderId is not null and sendcloudOrderId != '0'`
  couvre exactement la règle métier demandée (renseigné et ≠ `"0"`). L'ajout de
  `and entity.instance.orderIdEbay` est une garde défensive : sans identifiant eBay, l'URL
  Sendcloud n'a pas de valeur de recherche exploitable. Getters sous-jacents :
  `Order::getSendcloudOrderId(): ?string` (`src/Entity/Order.php:444`) et
  `Order::getOrderIdEbay(): ?string` (`src/Entity/Order.php:455`).
- **Valeur injectée dans l'URL** : `entity.instance.orderIdEbay` (et **non**
  `sendcloudOrderId`), conformément à la demande — c'est l'id eBay `02-14852-44592` qui sert de
  terme de recherche Sendcloud. Filtre `|url_encode` par sécurité sur le paramètre de requête
  (le format `02-14852-44592` est déjà URL-safe, mais l'encodage garantit la robustesse).
- **Nouvel onglet** : `target="_blank"`. Le projet n'utilise pas `rel="noopener"` sur ses liens
  de commande (cf. `order_delivery_resume.html.twig:5` et `order_preparation.html.twig:2`, tous
  deux en `target="_blank"` seul) ; on respecte cette convention. Les navigateurs modernes
  appliquent `noopener` implicitement pour `target="_blank"`.
- **Style** : classes `fw-bold text-primary` reprises telles quelles du lien de suivi
  La Poste existant (`order_delivery_resume.html.twig:5`) pour l'homogénéité visuelle ;
  wrapper `<div class="mt-1">` pour séparer le lien du nom du service sur une nouvelle ligne.
- **Libellé** : `Voir sur Sendcloud` (chaîne française littérale, cohérente avec les autres
  libellés en dur du CRUD Order — aucune clé de traduction n'existe ni n'est requise pour cette
  colonne).

## Étapes

1. Éditer `templates/admin/order/order_ebay_shipping_service.html.twig` : conserver le bloc
   d'affichage du service existant (lignes 1-16) et insérer, avant la balise fermante `</div>`,
   le bloc `{% set sendcloudOrderId %}` + `{% if %}` avec le lien Sendcloud décrit ci-dessus.
   C'est l'unique modification de code.

2. Rafraîchir le graphe graphify du repo après modification (facultatif, sans coût API) :
   `graphify extract <repo-path> --out docs/src-eurocommemo ...` puis
   `graphify cluster-only docs/src-eurocommemo --no-label` (cf. `CLAUDE.md` § graphify).

3. Consigner l'action dans `logs/src-eurocommemo.md` (règle action-logging) : entrée datée,
   statut, fichier affecté.

## Vérification

- **Rendu conditionnel — lien présent** : ouvrir la liste des commandes du back-office et
  repérer une commande eBay dont `sendcloud_order_id` est renseigné et ≠ `"0"`. La colonne
  « Service eBay sélectionné » doit afficher le nom du service puis, en dessous, le lien
  « Voir sur Sendcloud ». Vérifier l'URL générée (clic droit → copier le lien) :
  `https://app.sendcloud.com/v2/shipping/list/orders?search=<orderIdEbay>` avec le bon id, et
  l'ouverture dans un **nouvel onglet**.
- **Rendu conditionnel — lien absent** : vérifier qu'aucun lien n'apparaît pour :
  (a) une commande dont `sendcloud_order_id` vaut `"0"` ; (b) une commande dont
  `sendcloud_order_id` est `NULL` (jamais synchronisée) ; (c) une commande sans `orderIdEbay`.
- **Non-régression** : l'affichage du nom du service eBay et de son tooltip reste inchangé
  pour les commandes avec un `shippingService`, et le `—` s'affiche toujours quand la relation
  est nulle.
- **Données de test** : au besoin, alimenter `sendcloud_order_id` via la commande
  `bin/console app:sendcloud:sync-order-ids --orderId <orderIdEbay>` (exécutée via
  `scripts/repo_exec.py` selon le mode d'exécution du workspace), ou directement en base pour
  couvrir les cas `"0"` / `NULL`.
- **Sanity Twig** : `bin/console lint:twig templates/admin/order/order_ebay_shipping_service.html.twig`
  (via `scripts/repo_exec.py`) pour valider la syntaxe du template.
