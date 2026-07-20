# Plan — Livraison en point relais dans le tunnel d'achat (Sendcloud)

## Contexte

Le tunnel d'achat Eurocommemo (`panier → informations → reception → paiement`) ne propose
aujourd'hui qu'une **livraison à l'adresse** du client : à l'étape `/order/delivery`
(`templates/order/delivery.html.twig`), un unique radio `name="delivery"` porte l'id d'une règle
`Delivery` (grille poids/pays). On veut **ajouter, en plus**, la possibilité de choisir un
**point relais** pour la livraison.

Toute la brique Sendcloud existe déjà mais **uniquement côté back-office, gated aux commandes eBay** :
- `src/Service/Sendcloud/SendcloudApiClient.php` : `getShippingOptions(...)` (POST `/api/v3/shipping-options`, `calculate_quotes:true`) et `getServicePoints(...)`.
- DTOs `src/Dto/Sendcloud/SendcloudShippingOptionDTO.php` (avec `requiresServicePoint(): bool`) et `SendcloudServicePointDTO.php`.
- Colonnes déjà en base sur `orders` (migration `Version20260712000000.php`) : `sendcloud_shipping_option_code`, `sendcloud_service_point_id`, `sendcloud_service_point_name` — plus getters/setters sur `src/Entity/Order.php`.
- Picker admin `<select>` piloté par `assets/back/js/back.js` (l.284-397) + endpoints `OrderCrudController::sendcloudShippingOptions/servicePoints/applyShipping`.

**Décisions produit validées** (cette session) :
1. **Tarif** = devis live Sendcloud par option (`calculate_quotes`) → nécessite d'exposer le prix sur le DTO.
2. **UX** = widget carte **Service Point Picker** de Sendcloud (script CDN `embed.sendcloud.sc`), pas un `<select>`.
3. **Options** = **une seule** option relais : **Shop2Shop** (identifié par le code exact
   `chronopost:shop2shop` — produit **Chronopost** « Chrono Shop2Shop », vérifié sur le compte réel ;
   ce n'est PAS un produit Mondial Relay). Filtre dans `OrderController::loadSendcloudRelayOptions()`
   via la constante `SENDCLOUD_SHOP2SHOP_CODE`.

> ⚠ **Prérequis compte Sendcloud** : Shop2Shop étant un produit Chronopost, le picker carte ouvre
> `carrier=chronopost`. L'affichage des points relais **Chronopost** doit être **activé dans le
> panneau Sendcloud** (Paramètres → Transporteurs), sinon l'erreur « transporteurs pas encore activés
> dans votre section chronopost » apparaît à l'ouverture de la carte. C'est une config compte, pas un
> correctif code.

**Résultat visé** : à l'étape `reception`, le client voit toujours la livraison adresse (grille `Delivery`
inchangée) **et**, en dessous, un radio par transporteur relais renvoyé par Sendcloud (avec son prix
live) ; en sélectionnant un relais, un bouton ouvre la carte Sendcloud, le point choisi est capturé,
puis persisté sur la commande et affiché dans les mails de confirmation et le back-office.

**Hors périmètre (à flaguer)** :
- La création d'étiquette / push du colis vers Sendcloud pour les commandes **web** (non-eBay) reste
  hors scope : le flux admin Sendcloud est gated `getIsEbay()`. Ce plan **persiste et affiche** le choix
  relais ; l'exploitation aval (génération d'étiquette pour une commande web) est un chantier séparé.
- Le paiement, la grille `Delivery` adresse et le retrait magasin (radio commenté) ne changent pas.

## Fichiers concernés

### Nouveaux

Aucun nouveau fichier PHP ni migration : les colonnes `orders.sendcloud_*` existent déjà
(`migrations/Version20260712000000.php`), et l'appel Sendcloud est fait inline dans `OrderController`
en miroir du pattern admin (`OrderCrudController::sendcloudShippingOptions`). Les seuls ajouts sont
des clés de traduction (fichiers existants) et du JS dans un entrypoint existant.

### Modifiés — repo `src-eurocommemo`

#### 1. `src/Dto/Sendcloud/SendcloudShippingOptionDTO.php` — exposer le prix du devis

Ajouter deux accesseurs lisant le quote renvoyé quand `calculate_quotes:true`. **⚠ Chemin JSON à
confirmer sur une réponse Sendcloud réelle** (v3 `/shipping-options`) — la forme probable est
`quotes[0].price.total.value` / `.currency`, mais elle n'a pas pu être vérifiée contre une réponse
live dans cette exploration. Le corps ci-dessous tente plusieurs chemins usuels et retombe sur `null` ;
à ajuster après un premier appel réel (le payload brut reste accessible via `getPayload()`).

```php
/** Prix TTC du devis Sendcloud pour cette option (calculate_quotes). Null si absent. */
public function getPrice(): ?float
{
    $quote = $this->payload['quotes'][0] ?? null;
    if (null === $quote) {
        return null;
    }
    // Chemins candidats à confirmer contre une réponse réelle :
    $value = $quote['price']['total']['value']
        ?? $quote['price']['value']
        ?? $quote['total']['value']
        ?? null;

    return null === $value ? null : (float) $value;
}

public function getCurrency(): ?string
{
    $quote = $this->payload['quotes'][0] ?? null;

    return $quote['price']['total']['currency']
        ?? $quote['price']['currency']
        ?? null;
}
```

#### 2. `src/Controller/OrderController.php` — charger les options relais (GET) + capturer le choix (POST)

Constructeur (l.46-57) : injecter le client Sendcloud, le service de config (clé publique du widget)
et un logger. Ajouter en tête de classe une constante pays d'expédition (miroir de
`OrderCrudController::SENDCLOUD_FROM_COUNTRY = 'FR'`, l.77).

```php
private const SENDCLOUD_FROM_COUNTRY = 'FR';

public function __construct(
    // ... dépendances existantes ...
    private readonly RequestStack $requestStack,
    private readonly SendcloudApiClient $sendcloudApiClient,
    private readonly SendcloudConfigurationService $sendcloudConfigurationService,
    private readonly LoggerInterface $logger,
) {
}
```

Réécrire `delivery()` (l.161-192) — la branche POST distingue une valeur `sendcloud:<code>` d'un id de
grille ; la branche GET récupère les options relais et les passe au template :

```php
#[Route('/order/delivery', name: 'order_delivery')]
#[IsGranted('ROLE_USER')]
public function delivery(Request $request): Response
{
    $bannerGenerale = $this->em->getRepository(Away::class)->findOneBy(['active' => true, 'orderProcess' => true]);
    $session = $request->getSession();

    /*** SUBMIT POST ***/
    if ($deliveryValue = $request->request->get('delivery')) {

        // --- Point relais Sendcloud ---
        if (str_starts_with((string) $deliveryValue, 'sendcloud:')) {
            $code   = substr((string) $deliveryValue, strlen('sendcloud:'));
            $stored = $session->get('checkoutSendcloudOptions', []); // résolu côté serveur au GET

            if (!isset($stored[$code])) {
                $this->addFlash('danger', $this->translator->trans('shop.order.deliveryMissing', [], 'shop'));
                return $this->redirectToRoute('order_delivery');
            }

            $servicePointId   = (string) $request->request->get('service_point_id');
            $servicePointName = (string) $request->request->get('service_point_name');
            if ('' === $servicePointId) {
                $this->addFlash('danger', $this->translator->trans('shop.order.servicePointMissing', [], 'shop'));
                return $this->redirectToRoute('order_delivery');
            }

            $session->set('delivery', null);
            $session->set('sendcloudDelivery', array_merge($stored[$code], [
                'servicePointId'   => $servicePointId,
                'servicePointName' => $servicePointName,
            ]));

            return $this->redirectToRoute('order_payment');
        }

        // --- Livraison adresse (grille Delivery) — comportement existant ---
        $session->set('sendcloudDelivery', null);
        $delivery = ($deliveryValue === GlobalConstants::LIVRAISON_RETRAIT) ? null : (int) $deliveryValue;
        $session->set('delivery', $delivery);

        return $this->redirectToRoute('order_payment');
    }

    /*** Remove item unavailable ***/
    $this->cartHelper->removeCartItemUnavailable();

    $weightCart = $this->cartHelper->getWeightCart();               // grammes
    $arrayListAmountTva = $this->cartHelper->listAmountTvaByCart();

    /*** Options relais Sendcloud (dynamiques) ***/
    [$relayOptions, $publicKey, $countryCode, $postalCode] =
        $this->loadSendcloudRelayOptions($weightCart, $session);

    return $this->render('order/delivery.html.twig', [
        'arrayListAmountTva'    => $arrayListAmountTva,
        'bannerGenerale'        => $bannerGenerale,
        'weight'                => $weightCart,
        'delivery'              => $this->orderHelper->getDelivery($weightCart),
        'sendcloudRelayOptions' => $relayOptions,
        'sendcloudPublicKey'    => $publicKey,
        'deliveryCountryCode'   => $countryCode,
        'deliveryPostalCode'    => $postalCode,
    ]);
}
```

Méthode privée dédiée (nouvelle, dans `OrderController`) — appel Sendcloud + fallback silencieux si
API indisponible/non configurée (miroir de la tolérance de `sendcloudShippingOptions`) :

```php
/**
 * @return array{0: array<string, array{code:string,carrierCode:?string,carrierName:?string,label:string,price:float}>,
 *               1: ?string, 2: ?string, 3: ?string}
 */
private function loadSendcloudRelayOptions(int|float $weightGrams, SessionInterface $session): array
{
    /** @var User $user */
    $user    = $this->getUser();
    $address = OrderAddress::fromUser($user); // countryCode / postalCode / city (priorité commune)

    $countryCode = $address->getCountryCode();
    $postalCode  = $address->getPostalCode();
    $publicKey   = $this->sendcloudConfigurationService->getConfiguration()->getPublicKey();

    $relayOptions = [];
    try {
        $options = $this->sendcloudApiClient->getShippingOptions(
            self::SENDCLOUD_FROM_COUNTRY,
            null,
            (string) $countryCode,
            $postalCode,
            $address->getCity(),
            $weightGrams / 1000, // kg
        );

        foreach ($options as $option) {
            if (!$option->requiresServicePoint()) {
                continue;
            }
            $relayOptions[(string) $option->getCode()] = [
                'code'        => (string) $option->getCode(),
                'carrierCode' => $option->getCarrierCode(),
                'carrierName' => $option->getCarrierName(),
                'label'       => $option->getLabel(),
                'price'       => (float) ($option->getPrice() ?? 0.0),
            ];
        }
    } catch (ExternalSendcloudApiException|GuzzleException $e) {
        $this->logger->warning('Sendcloud relay options unavailable at checkout: '.$e->getMessage());
        // On dégrade proprement : seule la livraison adresse (grille) reste proposée.
    }

    // Source de vérité serveur pour la validation du POST (jamais confiance au client sur le prix).
    $session->set('checkoutSendcloudOptions', $relayOptions);

    return [$relayOptions, $publicKey, $countryCode, $postalCode];
}
```

Imports à ajouter : `App\Entity\OrderAddress`, `App\Service\Sendcloud\SendcloudApiClient`,
`App\Service\Sendcloud\SendcloudConfigurationService`, `App\Exceptions\ExternalSendcloudApiException`,
`GuzzleHttp\Exception\GuzzleException`, `Psr\Log\LoggerInterface`,
`Symfony\Component\HttpFoundation\Session\SessionInterface`.

#### 3. `src/Service/CartHelper.php` — persister le choix relais + son prix (`cartToOrder`)

Dans `cartToOrder()` (l.263-277), remplacer le bloc « Livraison » pour brancher le relais avant la
grille. Le prix relais vient **exclusivement** de la session résolue serveur, pas d'une valeur client :

```php
/*** Livraison */
$order->setAmountLivraison(0);
if ($sc = $session->get('sendcloudDelivery')) {
    $order->setSendcloudShippingOptionCode($sc['code'] ?? null);
    $order->setSendcloudServicePointId($sc['servicePointId'] ?? null);
    $order->setSendcloudServicePointName($sc['servicePointName'] ?? null);

    $amountDelivery = (float) ($sc['price'] ?? 0);
    $order->setAmountLivraison($amountDelivery);
    $sumAmountCmd += $amountDelivery;
} elseif ($session->get('delivery')) {
    /** @var Delivery $delivery */
    $delivery = $this->em->getRepository(Delivery::class)->find($session->get('delivery'));
    $order->setDelivery($delivery);

    $amountDelivery = $delivery->getPrice();
    if ($delivery->getFreeCartCondition() && $delivery->getFreeCartCondition() <= $sumAmountCmd) {
        $amountDelivery = 0;
    }
    $order->setAmountLivraison($amountDelivery);
    $sumAmountCmd += $amountDelivery;
}
```

Dans `removeAllCartItem()` (nettoyage post-commande), ajouter la purge des clés de session ajoutées :

```php
$session->remove('sendcloudDelivery');
$session->remove('checkoutSendcloudOptions');
```

#### 4. `templates/order/delivery.html.twig` — radios relais + widget + bloc JS

- Donner un `id` au `<form method="post">` (l.42) : `<form method="post" id="order-delivery-form">`.
- Après le bloc grille adresse (après l.65, dans `.container-type-delivery`), ajouter la boucle relais
  et le bloc picker :

```twig
{% for opt in sendcloudRelayOptions %}
    <div class="radio mt-2 mx-0">
        <input id="delivery-sc-{{ opt.code }}" type="radio" name="delivery"
               value="sendcloud:{{ opt.code }}" data-carrier="{{ opt.carrierCode }}">
        <label for="delivery-sc-{{ opt.code }}" class="radio-label cursor-pointer text-dark fs-6">
            {{ opt.label }} <b>(+ {{ opt.price|number_format(2, '.', ' ') }} €)</b>
        </label>
    </div>
{% endfor %}

{% if sendcloudRelayOptions is not empty %}
    <div id="service-point-picker" class="d-none mt-3"
         data-api-key="{{ sendcloudPublicKey }}"
         data-country="{{ deliveryCountryCode }}"
         data-postal-code="{{ deliveryPostalCode }}">
        <button type="button" id="open-service-point" class="btn btn-outline-dark px-4 py-2">
            {{ "shop.order.servicePointOpen"|trans({}, 'shop') }}
        </button>
        <div id="service-point-summary" class="mt-2 fw-bold fs-14"></div>
        <div id="service-point-error" class="text-danger small mt-1 d-none">
            {{ "shop.order.servicePointMissing"|trans({}, 'shop') }}
        </div>
        <input type="hidden" id="service_point_id"   name="service_point_id"   value="">
        <input type="hidden" id="service_point_name" name="service_point_name" value="">
    </div>
{% endif %}
```

- Ajouter un bloc `javascripts` (la page ne charge aujourd'hui **que** le CSS `app-order`, cf.
  l.5-8 — aucun `<script>`), avec le CDN Sendcloud SPP puis l'entrypoint `app-order` :

```twig
{% block javascripts %}
    {{ parent() }}
    <script src="https://embed.sendcloud.sc/spp/1.0.0/api.min.js" defer></script>
    {{ encore_entry_script_tags('app-order') }}
{% endblock %}
```

#### 5. `assets/app-order.js` — glue du widget Service Point Picker

Ajouter (fin de fichier) la logique jQuery/vanilla : afficher le picker seulement quand un radio
`sendcloud:*` est coché, ouvrir la carte scoping le transporteur, remplir les inputs cachés, bloquer
le submit si relais coché sans point choisi (pas d'`alert()` — message inline) :

```js
document.addEventListener('DOMContentLoaded', function () {
    const picker = document.getElementById('service-point-picker');
    const form   = document.getElementById('order-delivery-form');
    if (!picker || !form) { return; }

    const idInput   = document.getElementById('service_point_id');
    const nameInput = document.getElementById('service_point_name');
    const summary   = document.getElementById('service-point-summary');
    const errorBox  = document.getElementById('service-point-error');
    const openBtn   = document.getElementById('open-service-point');

    const selectedRelay = () => {
        const r = document.querySelector('input[name="delivery"]:checked');
        return (r && r.value.indexOf('sendcloud:') === 0) ? r : null;
    };
    const refresh = () => { picker.classList.toggle('d-none', !selectedRelay()); };

    document.querySelectorAll('input[name="delivery"]').forEach((r) => {
        r.addEventListener('change', function () {
            idInput.value = ''; nameInput.value = ''; summary.textContent = '';
            errorBox.classList.add('d-none');
            refresh();
        });
    });
    refresh();

    openBtn.addEventListener('click', function () {
        const relay = selectedRelay();
        if (!relay || typeof sendcloud === 'undefined') { return; }
        sendcloud.servicePoints.open(
            {
                apiKey:     picker.dataset.apiKey,
                country:    picker.dataset.country,
                postalCode: picker.dataset.postalCode,
                carriers:   relay.dataset.carrier,   // scope à ce transporteur
                language:   'fr-fr',
            },
            function (payload) {
                const p = Array.isArray(payload) ? payload[0] : payload;
                idInput.value   = p.id;
                nameInput.value = p.name;
                summary.textContent = p.name + ' — ' + (p.street || '') + ' ' +
                    (p.house_number || '') + ', ' + (p.postal_code || '') + ' ' + (p.city || '');
                errorBox.classList.add('d-none');
            },
            function (errors) { console.log('Sendcloud SPP error', errors); }
        );
    });

    form.addEventListener('submit', function (e) {
        if (selectedRelay() && !idInput.value) {
            e.preventDefault();
            errorBox.classList.remove('d-none');
        }
    });
});
```
> ⚠ La signature exacte de `sendcloud.servicePoints.open(config, success, failure)` et les noms de champs
> du point (`id`, `name`, `street`, `house_number`, `postal_code`, `city`) suivent la doc SPP 1.0.0 ;
> à revérifier contre la version chargée (le `id` renvoyé doit être l'id Sendcloud attendu par
> `service_point_details.id`). Rebuild Encore requis : `yarn dev` (ou `yarn build`).

#### 6. `templates/order/paiement.html.twig` — récap du choix relais

Le récap livraison lit aujourd'hui la variable `delivery` (entité `Delivery`, cf.
`OrderController::paiement` l.251-268). Ajouter une branche affichant le point relais quand
`order.sendcloudServicePointId` est renseigné (l'`order` est déjà passé au template, l.265).
Repérer le bloc « livraison / adresse » et insérer :

```twig
{% if order.sendcloudServicePointId %}
    <b>{{ "shop.order.relayDelivery"|trans({}, 'shop') }}</b>
    <br />{{ order.sendcloudServicePointName }}
{% elseif ... branche adresse existante ... %}
```

#### 7. `templates/mail/mail_order.html.twig` + `templates/mail/mail_order_waiting_payment.html.twig`

Dans le bloc « Réception » (mail_order l.63-84 : `{% if order.delivery is null and not order.isEbay %}
… {% else %} adresse … {% endif %}`), insérer une branche relais **avant** le `{% else %}` adresse :

```twig
{% elseif order.sendcloudServicePointId %}
    <b>{{ "shop.order.relayDelivery"|trans({}, "shop", user_locale) }}</b>
    <br />{{ order.sendcloudServicePointName }}
```
Appliquer le même ajout dans `mail_order_waiting_payment.html.twig` (structure jumelle).

#### 8. `templates/admin/order/order_delivery.html.twig` — affichage back-office

Ce template affiche « à récupérer en magasin » quand `delivery is null and not isEbay` — ce qui
matcherait à tort une commande web relais (`delivery` null). Ajouter en premier une branche relais :

```twig
{% if entity.instance.sendcloudServicePointId %}
    Point relais : <b>{{ entity.instance.sendcloudServicePointName }}</b>
{% elseif ... logique existante (magasin / adresse) ... %}
```

#### 9. `translations/shop.fr.yml` · `shop.en.yml` · `shop.de.yml`

Sous `shop.order:` (ex. après `shopAddress`), ajouter :

```yaml
# shop.fr.yml
order:
    servicePointOpen: "Choisir un point relais"
    servicePointMissing: "Veuillez sélectionner un point relais."
    relayDelivery: "Livraison en point relais"
    deliveryMissing: "Mode de livraison invalide, veuillez réessayer."
```
```yaml
# shop.en.yml
    servicePointOpen: "Choose a pickup point"
    servicePointMissing: "Please select a pickup point."
    relayDelivery: "Pickup point delivery"
    deliveryMissing: "Invalid delivery method, please try again."
```
```yaml
# shop.de.yml
    servicePointOpen: "Paketshop wählen"
    servicePointMissing: "Bitte wählen Sie einen Paketshop."
    relayDelivery: "Lieferung an Paketshop"
    deliveryMissing: "Ungültige Versandart, bitte erneut versuchen."
```
> Vérifier si `shop.order.deliveryMissing` existe déjà (une entrée de log l'évoque comme ajout d'un
> travail antérieur perdu) ; ne pas dupliquer la clé le cas échéant.

#### 10. (Optionnel) `src/Entity/Order.php` — helper de lisibilité

Ajouter un raccourci pour les templates (facultatif, sinon tester `sendcloudServicePointId` directement) :

```php
public function hasSendcloudServicePoint(): bool
{
    return null !== $this->sendcloudServicePointId && '' !== $this->sendcloudServicePointId;
}
```

## Étapes

1. **DTO prix** — Fichier 1 : ajouter `getPrice()`/`getCurrency()` à `SendcloudShippingOptionDTO`.
   Vérifier le chemin JSON du quote sur une réponse réelle (`app:` ou log) et ajuster.
2. **Contrôleur GET** — Fichier 2 : injecter `SendcloudApiClient` + `SendcloudConfigurationService` +
   `LoggerInterface` + const `SENDCLOUD_FROM_COUNTRY` ; ajouter `loadSendcloudRelayOptions()` et
   enrichir le rendu de `delivery()` (options relais, clé publique, pays, code postal en session + template).
3. **Contrôleur POST** — Fichier 2 : brancher la reconnaissance `sendcloud:<code>`, la validation
   serveur (option connue + point choisi), et le stockage `sendcloudDelivery` en session.
4. **Persistance** — Fichier 3 : `CartHelper::cartToOrder()` écrit les champs `sendcloud*` + `amountLivraison`
   depuis la session ; `removeAllCartItem()` purge les clés de session.
5. **Front — template** — Fichier 4 : `id` sur le form, boucle radios relais, bloc picker, bloc `javascripts`
   (CDN SPP + `app-order`).
6. **Front — JS** — Fichier 5 : glue SPP dans `assets/app-order.js` ; `yarn dev` pour rebuild Encore.
7. **Récaps** — Fichiers 6/7/8 : afficher le point relais dans `paiement.html.twig`, les 2 mails, et
   le back-office `order_delivery.html.twig`.
8. **Traductions** — Fichier 9 : clés `servicePointOpen`/`servicePointMissing`/`relayDelivery`/`deliveryMissing`
   en fr/en/de (dédupliquer `deliveryMissing` si déjà présent).
9. **(Optionnel)** Fichier 10 : `Order::hasSendcloudServicePoint()`.
10. **Graphe** — après modif, rafraîchir le graphe graphify du repo (cf. CLAUDE.md § graphify).

## Vérification

Toutes commandes via `scripts/repo_exec.py` (conteneur), jamais d'appel direct.

- **Statique** : `php -l` sur `OrderController.php`, `CartHelper.php`, `SendcloudShippingOptionDTO.php` ;
  `bin/console lint:twig templates/` ; `bin/console lint:yaml translations/` ; `bin/console lint:container` ;
  `bin/console cache:clear`. Aucun `make:migration` ne doit générer de diff sur les colonnes `sendcloud_*`
  (déjà en base) — confirmer `doctrine:schema:validate` mapping OK.
- **Build front** : `yarn dev` (Encore) réussit ; la page `/order/delivery` charge bien le script
  `app-order` + le CDN SPP (absents auparavant).
- **Scénario manuel (humain, clés Sendcloud réelles requises dans `SendcloudConfiguration`)** :
  1. Panier → `/order/information` (adresse FR) → `/order/delivery` : la livraison adresse (grille) est
     affichée **et** au moins un radio relais avec un prix.
  2. Sélectionner un relais → le bouton « Choisir un point relais » apparaît → ouvre la carte Sendcloud
     scoping le bon transporteur → choisir un point → le résumé (nom + adresse) s'affiche.
  3. Tenter de soumettre sans point → message inline bloquant ; avec point → passage à `/order/payment`.
  4. Payer (virement/chèque pour éviter PayPal live) → en base, `orders.sendcloud_shipping_option_code`,
     `sendcloud_service_point_id`, `sendcloud_service_point_name`, `amount_livraison` = prix du devis.
  5. Mail de confirmation + récap paiement + fiche back-office affichent « Livraison en point relais :
     <nom> » (pas « à récupérer en magasin »).
  6. **Non-régression** : une commande livrée à l'adresse (radio grille) fonctionne comme avant
     (`Order::delivery` + `amountLivraison` grille, aucun champ `sendcloud*` posé) ; le retrait magasin
     (si réactivé) inchangé.
- **Dégradation** : sans clés Sendcloud ou API en erreur → aucun radio relais, seule la grille adresse
  s'affiche, aucune exception remontée (log `warning`).
- **Point d'attention** : si l'adresse client est hors zone servie par Sendcloud (ex. Nouvelle-Calédonie —
  TGC), `getShippingOptions` peut ne renvoyer aucune option relais : comportement attendu (grille seule).
