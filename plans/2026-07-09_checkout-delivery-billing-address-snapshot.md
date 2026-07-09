# Plan — Adresse de livraison / facturation sur le tunnel d'achat

**Repo**: `src-eurocommemo` (Symfony e-commerce, resolved via `workspace.yaml` → `${REPOS_ROOT}/src-eurocommemo`)

## Contexte

Le client a demandé d'ajouter la notion « adresse de livraison / facturation » sur le tunnel d'achat, avec la contrainte explicite que **l'adresse est toujours identique pour la livraison et la facturation** — aucune UI à deux adresses n'est souhaitée.

L'exploration (deux passes de lecture en parallèle sur `src-eurocommemo`) a établi le point de départ réel :

- Le tunnel collecte et affiche déjà **exactement une adresse**, stockée sur `User` (`address`, `addressComplement`, `postalCode`, `commune`, `country`, `countryZone`, `countryZoneCommune`), saisie une fois à `/order/information` (formulaires `AddressType`/`OrderType`) et affichée en lecture seule à `/order/delivery` et `/order/payment` via `app.user.fullAddress`. Il n'y a donc rien à « fusionner » — elle n'a jamais été scindée.
- **L'adresse n'est jamais persistée sur `Order`.** `CartHelper::cartToOrder()` construit l'`Order` à partir du panier/session mais ne copie aucune donnée d'adresse ; chaque page et email affichant l'adresse d'une commande la lit **en direct** depuis `getUser()`. Si le client modifie son adresse de profil plus tard, les commandes historiques affichent silencieusement la nouvelle adresse — l'historique commande/facture n'est donc pas fiable.
- Un mécanisme équivalent existe déjà intégralement, mais uniquement câblé sur le pipeline d'**import eBay** : `App\Entity\OrderAddress` (table `order_address`, colonnes `type` [`delivery`|`billing`], `fullName`, `line1`, `line2`, `city`, `postalCode`, `countryCode`, `phone`, `state`), avec les accesseurs `Order::getDeliveryAddress()/getBillingAddress()/setDeliveryAddress()/setBillingAddress()/getDeliveryAddressText()` déjà en place (`src/Entity/Order.php:464-527`). `templates/order/pdf-invoice.html.twig:67-73` préfère déjà `order.billingAddress` et ne retombe sur `order.user.*` que si null — c'est-à-dire que le template de facture est déjà écrit pour ce snapshot, il ne le reçoit simplement jamais pour les commandes web.

Le plan couvre donc **deux volets**, validés avec l'utilisateur :
1. **Relabelling** de l'UI/des libellés de l'adresse unique existante pour expliciter qu'elle sert à la fois de livraison et de facturation.
2. **Snapshot** de cette adresse sur `Order` au moment du checkout, en réutilisant l'entité `OrderAddress` existante (peuplant à la fois `TYPE_DELIVERY` et `TYPE_BILLING` à partir des mêmes données `User`), afin que la commande garde une trace figée même si le client modifie son profil ensuite — et bascule des templates qui affichent l'adresse d'une commande (emails de confirmation, bon de préparation, récapitulatif de paiement) vers ce snapshot plutôt que vers `User` en direct.

Aucune migration n'est nécessaire — la table `order_address` et toutes ses colonnes existent déjà (construites pour eBay). Aucun nouveau champ de formulaire/UI n'est nécessaire — le formulaire d'adresse unique reste inchangé.

## Fichiers concernés

### Nouveaux

Aucun.

### Modifiés

| Fichier | Changement |
|---------|-----------|
| `src/Entity/OrderAddress.php` | Ajout de la factory statique `fromUser(User $user): self` |
| `src/Service/CartHelper.php` | `cartToOrder()` : snapshot de l'adresse (delivery + billing) sur le nouvel `Order` |
| `translations/shop.fr.yml` | Relabelling des clés `address`, `yourAddress`, `modifier` |
| `translations/shop.en.yml` | Relabelling des clés `address`, `yourAddress`, `modifier` |
| `translations/shop.de.yml` | Relabelling des clés `address`, `yourAddress`, `modifier` |
| `templates/order/paiement.html.twig` | Récapitulatif d'adresse : lecture depuis `order.deliveryAddress` au lieu de `app.user.*` |
| `templates/mail/mail_order.html.twig` | Bloc adresse de livraison : lecture depuis `order.deliveryAddress` |
| `templates/mail/mail_order_waiting_payment.html.twig` | Bloc adresse de livraison : lecture depuis `order.deliveryAddress` |
| `templates/order/pdf-preparation.html.twig` | Bon de préparation : lecture depuis `order.deliveryAddress` |

Fichiers réutilisés sans modification : `src/Entity/Order.php` (`getDeliveryAddress()`/`setDeliveryAddress()`/`setBillingAddress()`, lignes 464-511), `templates/order/pdf-invoice.html.twig` (déjà compatible snapshot), `src/Twig/CountryCodeToCountryEntityExtension.php`.

## Étapes

### 1. `src/Entity/OrderAddress.php` — nouvelle factory `fromUser()`

Miroir de la factory existante `fromDto(?FulfillmentShipToDTO $dto): ?self` (lignes 148-163), ajoutée juste après :

```php
public static function fromUser(User $user): self
{
    $commune = $user->getCountryZoneCommune();

    return (new self())
        ->setFullName(trim($user->getFirstName().' '.$user->getLastName()))
        ->setLine1($user->getAddress())
        ->setLine2($user->getAddressComplement())
        ->setCity($commune ? $commune->getTitle() : $user->getCommune())
        ->setPostalCode($commune ? $commune->getPostalCode() : $user->getPostalCode())
        ->setCountryCode($user->getCountry()?->getCodeIso())
        ->setState($user->getCountryZone()?->getTitle())
        ->setPhone($user->getPhone());
}
```

Nécessite `use App\Entity\User;` dans les imports du fichier. `$commune->getTitle()`/`getPostalCode()` sont les mêmes accesseurs magiques `__call` proxy-traduction que `CountryZoneCommune::__toString()` utilise déjà (`src/Entity/CountryZoneCommune.php:66-69`) — les appeler directement (plutôt que de concaténer la sortie de `__toString()`) évite de re-parser une chaîne formatée. Ceci respecte la priorité déjà établie par `User::getFullAddress()` (`src/Entity/User.php:396-412`) : quand un `countryZoneCommune` est sélectionné (adresses zonées/outre-mer), il prime sur les champs texte libres `postalCode`/`commune`.

### 2. `src/Service/CartHelper.php` — snapshot de l'adresse dans `cartToOrder()`

Ajouter `use App\Entity\OrderAddress;` aux imports (`src/Service/CartHelper.php:1-17`).

Dans `cartToOrder()` (`src/Service/CartHelper.php:206-278`), juste après `$order->setUser($user);` (ligne 215), ajouter :

```php
$order->setDeliveryAddress(OrderAddress::fromUser($user));
$order->setBillingAddress(OrderAddress::fromUser($user));
```

Deux appels distincts à `OrderAddress::fromUser($user)` sont nécessaires (pas une instance partagée) — `Order::replaceAddress()` (`src/Entity/Order.php:500-511`) mute le `type` de l'objet passé en place ; réutiliser une seule instance laisserait les deux emplacements pointer vers le même objet avec seulement le dernier type appliqué.

C'est le seul changement fonctionnel : il s'exécute pour chaque commande créée par le checkout web standard (`OrderController::paiement()` appelle `cartToOrder()` à `src/Controller/OrderController.php:258`), indépendamment du moyen de paiement, donc chaque future commande obtient une paire d'adresses `delivery`+`billing` figée à la création.

### 3. Relabelling de l'étape adresse en FR/EN/DE

`translations/shop.fr.yml` :
- ligne 67 : `address: Adresse de livraison` → `address: Adresse de livraison et de facturation`
- ligne 68 : `yourAddress: Votre adresse` → `yourAddress: Votre adresse de livraison et de facturation`
- ligne 94 : `modifier: Modifier l'adresse de livraison` → `modifier: Modifier l'adresse de livraison et de facturation`

`translations/shop.en.yml` :
- ligne 68 : `address: Shipping address` → `address: Shipping & billing address`
- ligne 69 : `yourAddress: Your address` → `yourAddress: Your shipping & billing address`
- ligne 95 : `modifier: Modify shipping address` → `modifier: Modify shipping & billing address`

`translations/shop.de.yml` :
- ligne 67 : `address: Lieferadresse` → `address: Liefer- und Rechnungsadresse`
- ligne 68 : `yourAddress: Ihre Adresse` → `yourAddress: Ihre Liefer- und Rechnungsadresse`
- ligne 94 : `modifier: Lieferadresse ändern` → `modifier: Liefer- und Rechnungsadresse ändern`

Ces trois clés sont les seuls libellés d'adresse traduits du tunnel (le titre de `templates/order/informations.html.twig` utilise `shop.order.address` ; `templates/order/delivery.html.twig:34,37` utilisent `shop.order.yourAddress`/`shop.order.modifier`) — aucun changement de template nécessaire pour ces deux fichiers au-delà des valeurs de clés ci-dessus.

### 4. Basculer les templates orientés commande vers le snapshot figé

**`templates/order/paiement.html.twig`** — c'est la seule page du tunnel rendue **après** l'exécution de `cartToOrder()` (`OrderController::paiement()` appelle `cartToOrder()` ligne 258, puis rend avec `'order' => $order` ligne ~264), donc `order.deliveryAddress` est garanti non-null ici. Remplacer la branche `{% else %}` du bloc récapitulatif de livraison (actuellement lignes 65-67) :

```twig
{% else %}
    La commande sera expédiée à l'adresse :
    <br />{{ app.user.firstName~" "~app.user.lastName }}
    <br />{{ app.user.fullAddress|raw }}
{% endif %}
```
par :
```twig
{% else %}
    La commande sera expédiée à l'adresse de livraison et de facturation :
    <br />{{ order.deliveryAddress.fullName }}
    <br />{{ order.deliveryAddress.line1 }}
    {% if order.deliveryAddress.line2 %}
        <br />{{ order.deliveryAddress.line2 }}
    {% endif %}
    <br />{{ order.deliveryAddress.postalCode }} {{ order.deliveryAddress.city }}
    <br/>{{ countryCodeToCountryEntity(order.deliveryAddress.countryCode).translate().title }}
{% endif %}
```

**`templates/mail/mail_order.html.twig`** et **`templates/mail/mail_order_waiting_payment.html.twig`** (bloc identique dans les deux, lignes 70-75) — remplacer :
```twig
{% else %}
    <b>La commande sera expédiée à l'adresse</b>
    <br />{{ order.user.firstName~" "~order.user.lastName }}
    <br />{{ order.user.fullAddress|raw }}
    {% if order.user.phone %}
        <br /> Téléphone : {{ order.user.phone }}
    {% endif %}
```
par :
```twig
{% else %}
    <b>La commande sera expédiée à l'adresse de livraison et de facturation</b>
    <br />{{ order.deliveryAddress.fullName }}
    <br />{{ order.deliveryAddress.line1 }}
    {% if order.deliveryAddress.line2 %}
        <br />{{ order.deliveryAddress.line2 }}
    {% endif %}
    <br />{{ order.deliveryAddress.postalCode }} {{ order.deliveryAddress.city }}
    <br/>{{ countryCodeToCountryEntity(order.deliveryAddress.countryCode).translate().title }}
    {% if order.deliveryAddress.phone %}
        <br /> Téléphone : {{ order.deliveryAddress.phone }}
    {% endif %}
```

**`templates/order/pdf-preparation.html.twig`** (bon de préparation, lignes 34-37) — remplacer :
```twig
<b style="color: #000000">{{ order.user.getFullName }}</b>
<br />{{ order.user.fullAddress|raw }}
```
par :
```twig
<b style="color: #000000">{{ order.user.getFullName }}</b>
<br />{{ order.deliveryAddress.line1 }}
{% if order.deliveryAddress.line2 %}
    <br />{{ order.deliveryAddress.line2 }}
{% endif %}
<br />{{ order.deliveryAddress.postalCode }} {{ order.deliveryAddress.city }}
<br/>{{ countryCodeToCountryEntity(order.deliveryAddress.countryCode).translate().title }}
```

Les quatre blocs ci-dessus reprennent le pattern de rendu champ par champ que `templates/order/pdf-invoice.html.twig:67-73` utilise déjà pour `order.billingAddress` (y compris la fonction Twig existante `countryCodeToCountryEntity()`, définie dans `src/Twig/CountryCodeToCountryEntityExtension.php:19-23`) — aucun nouveau helper Twig requis. `pdf-invoice.html.twig` lui-même ne nécessite **aucun changement** : il préfère déjà `order.billingAddress` à `order.user.*`, il récupérera donc le snapshot automatiquement dès que l'étape 2 le peuple.

`templates/order/delivery.html.twig` continue intentionnellement de lire `app.user.fullAddress` (lignes 35-36) — à ce stade du tunnel, l'`Order` n'existe pas encore (elle n'est créée que plus tard, dans `cartToOrder()` lors de `/order/payment`) ; seul le relabelling de traduction de l'étape 3 s'y applique.

## Vérification

1. `scripts/repo_exec.py src-eurocommemo -- vendor/bin/phpunit` — pas de régression.
2. Manuel : ajouter un produit au panier, parcourir `/order/information` → `/order/delivery` → `/order/payment` ; confirmer que le titre/libellés d'adresse affichent désormais « adresse de livraison et de facturation » en FR (et basculer `_locale` pour vérifier EN/DE).
3. Finaliser une commande test (virement/chèque pour éviter un PayPal réel) ; sur l'email de confirmation et le récapitulatif de `/order/payment`, confirmer que l'adresse affichée correspond à celle saisie — elle provient désormais du snapshot de la commande, pas du profil en direct.
4. En base, vérifier que la nouvelle commande a bien deux lignes `order_address` (`type = 'delivery'` et `type = 'billing'`) avec des valeurs identiques.
5. Après avoir passé la commande, modifier l'adresse de profil du client (`/profile`) vers une adresse différente, puis rouvrir l'email de confirmation / la facture admin / le PDF de préparation de cette même commande — confirmer qu'ils affichent toujours l'adresse **d'origine** (snapshot figé), pas la nouvelle adresse du profil.
6. Générer la facture PDF de cette commande (`/order/{id}/invoice`) et confirmer qu'elle rend déjà l'adresse de facturation snapshotée (aucun changement de template n'était nécessaire ici, donc c'est un test de non-régression).
