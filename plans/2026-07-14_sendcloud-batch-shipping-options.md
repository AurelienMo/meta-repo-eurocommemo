# Plan — Optimisation des shipping options Sendcloud (appel batch unique) sur la vue « prêtes à être expédiées »

## Contexte

Sur la page admin **« commandes en attente de livraison prêtes à être expédiées »**
(`OrderCrudController` index filtré `state=VALID & delivery=1 & ready=1`, `setPaginatorPageSize(500)`),
chaque ligne rend un `<select>` de méthodes de livraison Sendcloud **vide**, peuplé au chargement de
la page par **un `fetch()` par commande** (`assets/back/js/back.js:308`). Chaque `fetch` frappe la route
`app_admin_order_sendcloud_shipping_options` qui déclenche **un POST live vers l'API Sendcloud**
(`SendcloudApiClient::getShippingOptions`, `SendcloudApiClient.php:71-105`), **sans aucun cache**.

Résultat : jusqu'à **500 requêtes HTTP navigateur → back → Sendcloud** au chargement, limitées par le
plafond de connexions du navigateur (~6 en parallèle) → page lente, API Sendcloud sollicitée inutilement.

**Peut-on faire un seul appel global ?** L'endpoint Sendcloud `POST /api/v3/shipping-options` est
**intrinsèquement paramétré par commande** : il exige `to_address` (pays/CP/ville) + `parcels[].weight`.
Il **n'existe pas** d'appel Sendcloud couvrant plusieurs destinations. En revanche on peut :

1. **Remplacer les N requêtes navigateur par UNE seule** requête vers le back (le « appel global » du
   point de vue de la page) ;
2. **Dédupliquer** côté serveur les appels Sendcloud par **signature exacte de l'expédition**
   (`pays + code postal + ville + poids`) — deux commandes identiques = un seul appel Sendcloud,
   **sans aucun changement de comportement** (mêmes paramètres → même résultat) ;
3. **Paralléliser** les appels Sendcloud uniques restants côté serveur (Guzzle `Pool`), au lieu de les
   sérialiser au gré des connexions navigateur.

Résultat attendu : **1 requête navigateur** + **U appels Sendcloud** (U = nb de signatures uniques ≤ N),
exécutés en parallèle côté serveur.

## Fichiers concernés

### Modifiés — repo `src-eurocommemo`

#### 1. `src/Service/Sendcloud/SendcloudApiClient.php` — nouvelle méthode batch

Ajouter les imports Guzzle en tête de fichier (après la ligne 11) :

```php
use GuzzleHttp\Pool;
use GuzzleHttp\Psr7\Request;
```

Ajouter une constante de concurrence près des constantes existantes (après `SendcloudApiClient.php:21`) :

```php
private const SHIPPING_OPTIONS_CONCURRENCY = 10;
```

Ajouter la méthode publique batch (à placer juste après `getShippingOptions()`, soit après la ligne 105).
Elle réutilise la logique d'authentification de `request()` (`SendcloudApiClient.php:242-255`) mais monte
les requêtes de façon concurrente via un `Pool`. La construction du body est **identique** à
`getShippingOptions()` (`SendcloudApiClient.php:79-93`), `calculate_quotes` reste à `true` pour préserver
exactement le jeu d'options renvoyé aujourd'hui.

```php
/**
 * Fetch shipping options for several shipments in a single batch of concurrent requests.
 *
 * @param array<string, array{
 *     fromCountryCode: string, fromPostalCode: ?string,
 *     toCountryCode: string, toPostalCode: ?string, toCity: ?string, weightKg: float
 * }> $shipments Shipment descriptors keyed by a caller-defined deduplication key.
 *
 * @return array<string, SendcloudShippingOptionDTO[]> Options keyed by the same keys as $shipments.
 *                                                      A failed request yields an empty array for its key.
 *
 * @throws ExternalSendcloudApiException When Sendcloud credentials are not configured.
 */
public function getShippingOptionsBatch(array $shipments): array
{
    if ([] === $shipments) {
        return [];
    }

    $configuration = $this->configurationService->getConfiguration();
    if (!$configuration->isConfigured()) {
        throw new ExternalSendcloudApiException('Sendcloud API credentials are not configured.');
    }

    $authHeader = 'Basic '.base64_encode(
        $configuration->getPublicKey().':'.$configuration->getSecretKey()
    );

    $requests = static function () use ($shipments, $authHeader) {
        foreach ($shipments as $key => $s) {
            $body = [
                'from_address' => array_filter([
                    'country_code' => $s['fromCountryCode'],
                    'postal_code'  => $s['fromPostalCode'],
                ]),
                'to_address' => array_filter([
                    'country_code' => $s['toCountryCode'],
                    'postal_code'  => $s['toPostalCode'],
                    'city'         => $s['toCity'],
                ]),
                'parcels' => [[
                    'weight' => ['value' => number_format(max($s['weightKg'], 0.001), 3, '.', ''), 'unit' => 'kg'],
                ]],
                'calculate_quotes' => true,
            ];

            yield $key => new Request(
                'POST',
                self::PREFIX_URL.self::ENDPOINT_SHIPPING_OPTIONS,
                ['Authorization' => $authHeader, 'Content-Type' => 'application/json', 'Accept' => 'application/json'],
                json_encode($body, JSON_THROW_ON_ERROR)
            );
        }
    };

    $results = [];
    $pool = new Pool($this->sendcloudApiClient, $requests(), [
        'concurrency' => self::SHIPPING_OPTIONS_CONCURRENCY,
        'fulfilled'   => static function (ResponseInterface $response, string $key) use (&$results): void {
            $status = $response->getStatusCode();
            if ($status < 200 || $status >= 300) {
                $results[$key] = [];
                return;
            }
            $decoded = json_decode($response->getBody()->getContents(), true) ?? [];
            $results[$key] = array_map(
                static fn (array $option) => new SendcloudShippingOptionDTO($option),
                $decoded['data'] ?? []
            );
        },
        'rejected'    => static function (mixed $reason, string $key) use (&$results): void {
            $results[$key] = [];
        },
    ]);

    $pool->promise()->wait();

    return $results;
}
```

> Note : le `Pool` transmet la **clé** de l'itérateur (`$key`) comme `$index` aux callbacks
> `fulfilled`/`rejected`, ce qui permet de recoller chaque réponse à sa signature d'expédition.
> `$this->sendcloudApiClient` est le client Guzzle injecté (`SendcloudApiClient.php:24`), qui expose
> `sendAsync()` requis par `Pool`.

#### 2. `src/Controller/Admin/OrderCrudController.php` — nouvelle route batch

Ajouter une route **avant** ou après les routes Sendcloud existantes (aucune collision : le chemin
`/admin/order/sendcloud/...` ne matche pas la route paramétrée `/admin/order/{id}/sendcloud/...`).
À insérer juste avant `sendcloudShippingOptions()` (`OrderCrudController.php:433`).

La déduplication utilise une **signature exacte** `pays|CP|ville|poids(3 décimales)`. Les entrées viennent
des mêmes getters que la route mono-commande (`OrderCrudController.php:436-449`) :
`getDeliveryAddress()`, `getCountryCode()/getPostalCode()/getCity()`, `getTotalWeightKg()`, origine fixe
`self::SENDCLOUD_FROM_COUNTRY` (`OrderCrudController.php:68`).

```php
#[Route('/admin/order/sendcloud/shipping-options/batch', name: 'app_admin_order_sendcloud_shipping_options_batch', methods: ['POST'])]
public function sendcloudShippingOptionsBatch(Request $request): JsonResponse
{
    $ids = array_values(array_filter(array_map('intval', (array) $request->request->all('ids'))));
    if ([] === $ids) {
        return new JsonResponse((object) []);
    }

    /** @var Order[] $orders */
    $orders = $this->em->getRepository(Order::class)->findBy(['id' => $ids]);

    $shipments = [];          // dedup key => shipment descriptor
    $keyByOrderId = [];       // orderId => dedup key
    foreach ($orders as $order) {
        $address = $order->getDeliveryAddress();
        if (!$order->getIsEbay() || null === $address) {
            continue;
        }

        $descriptor = [
            'fromCountryCode' => self::SENDCLOUD_FROM_COUNTRY,
            'fromPostalCode'  => null,
            'toCountryCode'   => (string) $address->getCountryCode(),
            'toPostalCode'    => $address->getPostalCode(),
            'toCity'          => $address->getCity(),
            'weightKg'        => $order->getTotalWeightKg(),
        ];

        $key = md5(implode('|', [
            $descriptor['toCountryCode'],
            (string) $descriptor['toPostalCode'],
            (string) $descriptor['toCity'],
            number_format($descriptor['weightKg'], 3, '.', ''),
        ]));

        $shipments[$key] = $descriptor;           // identical signatures collapse to one Sendcloud call
        $keyByOrderId[$order->getId()] = $key;
    }

    try {
        $optionsByKey = $this->apiClient->getShippingOptionsBatch($shipments);
    } catch (ExternalSendcloudApiException $e) {
        return new JsonResponse(['error' => $e->getMessage()], 502);
    }

    $payload = [];
    foreach ($keyByOrderId as $orderId => $key) {
        $payload[$orderId] = array_map(static fn ($option) => [
            'code'                 => $option->getCode(),
            'label'                => $option->getLabel(),
            'carrierCode'          => $option->getCarrierCode(),
            'requiresServicePoint' => $option->requiresServicePoint(),
        ], $optionsByKey[$key] ?? []);
    }

    return new JsonResponse($payload);
}
```

> Réponse : map `{ orderId: [ {code,label,carrierCode,requiresServicePoint}, … ] }` — même forme
> unitaire que `sendcloudShippingOptions()` (`OrderCrudController.php:454-459`), indexée par id de commande.
> Route en **POST** (jusqu'à 500 ids en corps de formulaire, trop volumineux/fragile en query GET) ;
> lecture seule, sans CSRF, cohérent avec l'absence de CSRF sur la route GET mono-commande existante.
> Réutilisation possible : `OrderRepository::findByIds()` (`OrderRepository.php:114`, déjà filtré
> `statePayment=VALID`) au lieu de `findBy(['id' => $ids])` — équivalent ici puisque la vue ne liste que
> des commandes VALID ; garder `findBy` évite d'écarter par erreur une ligne rendue.

#### 3. `templates/admin/order/order_sendcloud_action.html.twig` — exposer l'URL batch au JS

Ajouter un attribut `data-batch-url` sur le conteneur `.sendcloud-shipping-block`
(`order_sendcloud_action.html.twig:6`). Le JS lira cette URL depuis le premier bloc.

Avant (`order_sendcloud_action.html.twig:6`) :

```twig
<div class="sendcloud-shipping-block text-start small" data-order-id="{{ entity.instance.id }}">
```

Après :

```twig
<div class="sendcloud-shipping-block text-start small"
     data-order-id="{{ entity.instance.id }}"
     data-batch-url="{{ path('app_admin_order_sendcloud_shipping_options_batch') }}">
```

> L'attribut `data-url` du `<select class="select-sendcloud-shipping">`
> (`order_sendcloud_action.html.twig:10`) **devient inutile** pour le chargement initial ; il peut être
> laissé en place (inoffensif) ou retiré. Les selects service-points et boutons apply/generate-label
> (`order_sendcloud_action.html.twig:14-27,36-58`) restent **inchangés** (chargés à la demande).

#### 4. `assets/back/js/back.js` — un seul fetch batch au lieu de N

Remplacer le bloc `sendcloudBlocks.forEach` qui fait un `fetch` par bloc (`back.js:293-386`).
La configuration par ligne (loader service-point, `maybeLoadServicePoints`, écouteur `change`, bouton
« Enregistrer ») **reste identique** (`back.js:299-379`) ; seul le **peuplement initial** des selects passe
d'un `fetch` par bloc à **un seul `fetch` batch** dont on redistribue le résultat.

Structure cible (remplace `back.js:293-386`) :

```js
const batchUrl = sendcloudBlocks[0].dataset.batchUrl;
const rows = [];                     // { orderId, shippingSelect, populate }
const params = new URLSearchParams();

sendcloudBlocks.forEach(function (block) {
    const orderId = block.dataset.orderId;
    params.append('ids[]', orderId);

    const shippingSelect = block.querySelector('.select-sendcloud-shipping');
    const spSelect = block.querySelector('.select-sendcloud-servicepoint');

    // --- per-row service-point loader + handlers: UNCHANGED (back.js:299-350) ---
    const spLoader = document.createElement('div');
    spLoader.className = 'loader loader-spin sendcloud-sp-loader d-none';
    spSelect.parentNode.insertBefore(spLoader, spSelect);
    function showSpLoader() { spLoader.classList.remove('d-none'); }
    function hideSpLoader() { spLoader.classList.add('d-none'); }

    function maybeLoadServicePoints() { /* identical to back.js:324-349 */ }
    shippingSelect.addEventListener('change', maybeLoadServicePoints);

    // --- apply button: UNCHANGED (back.js:353-379) ---
    block.querySelector('.btn-sendcloud-apply').addEventListener('click', function () { /* … */ });

    // populate this row's shipping <select> from batched options
    function populate(options) {
        if (!Array.isArray(options)) { return; }
        const current = shippingSelect.dataset.current;
        shippingSelect.innerHTML = '<option value="">— Choisir une méthode —</option>' +
            options.map(o =>
                `<option value="${o.code}" data-requires-sp="${o.requiresServicePoint ? 1 : 0}" ` +
                `data-carrier="${o.carrierCode || ''}" ${o.code === current ? 'selected' : ''}>${o.label}</option>`
            ).join('');
        maybeLoadServicePoints();
    }

    rows.push({ orderId, populate });
});

// ONE global request instead of one fetch per row
fetch(batchUrl, {
    method: 'POST',
    headers: { 'X-Requested-With': 'XMLHttpRequest' },
    body: params,
})
    .then(r => r.json())
    .then(map => {
        if (!map || typeof map !== 'object') { return; }
        rows.forEach(({ orderId, populate }) => populate(map[orderId]));
    })
    .catch(() => {})
    .finally(() => { overlay.remove(); });
```

> L'overlay global (`back.js:288-291`) est **conservé** et retiré dans le `.finally()` du fetch unique
> (remplace le `Promise.allSettled(...)` de `back.js:383-385`). Le corps de `maybeLoadServicePoints`
> et du handler « Enregistrer » est repris **verbatim** de l'existant — seule l'orchestration du
> chargement initial change.

## Étapes

1. **Client API batch** — `src/Service/Sendcloud/SendcloudApiClient.php` : ajouter les imports `Pool`
   et `Request`, la constante `SHIPPING_OPTIONS_CONCURRENCY`, et la méthode `getShippingOptionsBatch()`.
   Vérifiable en isolation (test unitaire mockant le client Guzzle, cf. Vérification).
2. **Route batch** — `src/Controller/Admin/OrderCrudController.php` : ajouter
   `sendcloudShippingOptionsBatch()` avec déduplication par signature exacte et sortie `{orderId: [...]}`.
3. **Template** — `templates/admin/order/order_sendcloud_action.html.twig` : ajouter `data-batch-url`
   sur `.sendcloud-shipping-block`.
4. **JS** — `assets/back/js/back.js` : remplacer la boucle de `fetch` par-ligne par un seul `fetch` batch
   redistribué ; conserver la logique service-points / apply / overlay.
5. **Build assets** — recompiler le bundle back (Webpack Encore) via `scripts/repo_exec.py`
   (jamais `npm` en direct), cf. CLAUDE.md § « Comportement pipeline ».
6. **Rafraîchir le graphe graphify** du repo après modification (cf. CLAUDE.md § graphify) et
   **journaliser** l'action dans `logs/src-eurocommemo.md` (cf. règle action-logging).

## Vérification

- **Unitaire (client)** : test de `getShippingOptionsBatch()` avec un `MockHandler` Guzzle renvoyant
  plusieurs réponses ; asserter que les clés de sortie correspondent aux clés d'entrée, qu'une réponse
  non-2xx/rejetée donne `[]` pour sa clé, et que le body POST est identique à `getShippingOptions()`.
- **Fonctionnel (route)** : `WebTestCase` POST sur `app_admin_order_sendcloud_shipping_options_batch`
  avec `ids[]` mêlant commandes eBay/non-eBay et avec/sans adresse ; asserter que seules les commandes
  éligibles apparaissent, et que deux commandes de même signature partagent le même jeu d'options.
- **Manuel — navigateur (via `claude-in-chrome`)** : ouvrir la vue « prêtes à être expédiées »,
  onglet Réseau ; confirmer qu'il n'y a plus **qu'une seule** requête `…/shipping-options/batch`
  (au lieu d'une par ligne), que chaque `<select>` est peuplé correctement, que `data-current`
  présélectionne la méthode déjà enregistrée, et que le sous-select point relais se charge toujours au
  `change`. Comparer le temps de chargement avant/après.
- **Non-régression** : boutons « Enregistrer sur Sendcloud » et « Générer l'étiquette » toujours
  fonctionnels (routes `apply-shipping` / `generate-label` inchangées).
- **Commandes projet** (via `scripts/repo_exec.py`) : lint + tests du repo `src-eurocommemo`.

## Limites & décision

- **Un seul appel Sendcloud global est impossible** : l'API `/api/v3/shipping-options` est orientée
  expédition unique (une destination + un colis par requête). Le gain vient de (1) la fusion des N
  requêtes navigateur en une seule et (2) la déduplication + parallélisation côté serveur.
- **Déduplication par signature exacte** (choix validé) : `pays + CP + ville + poids`. Aucun risque de
  changement de comportement. Un regroupement plus agressif (pays + tranche de poids) donnerait moins
  d'appels mais supposerait que la liste des méthodes ne dépend pas du code postal — écarté.
- **Aucun cache persistant** ajouté dans ce plan. Extension possible ultérieure : mettre en cache
  (`cache.app`, TTL court) les options par signature d'expédition pour réutiliser les résultats entre
  rechargements de page — hors périmètre ici.
