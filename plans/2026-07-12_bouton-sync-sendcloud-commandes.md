# Plan — Bouton de synchronisation Sendcloud par commande sur la liste admin

## Contexte

Les commandes eBay reçoivent leur `sendcloudOrderId` de façon **asynchrone** après l'import
(message Messenger `AssociateSendcloudOrderIdMessage`, retries ~40 min). Quand Sendcloud n'a
toujours pas la commande à l'épuisement des retries, le subscriber pose la valeur sentinelle
`"0"` (« pas trouvé »). Une commande jamais synchronisée reste à `null`. Dans les deux cas,
le lien « Voir sur Sendcloud » de la liste admin ne s'affiche pas
(`templates/admin/order/order_ebay_shipping_service.html.twig:18`).

Aujourd'hui, la seule façon de re-synchroniser est la commande CLI
`app:sendcloud:sync-order-ids --orderId <n>`. On veut offrir à l'admin un bouton **par ligne**,
visible **uniquement pour les commandes eBay** dont `sendcloudOrderId` est `null` **ou** `"0"`,
qui déclenche la résolution de l'ID Sendcloud pour cette seule commande.

**Approche retenue** : action EasyAdmin native (`configureActions()` + handler CRUD action),
avec rechargement de page et message flash, protégée par un token CSRF (aligné sur le pattern
`change_password`). Aucune écriture JS, aucun rebuild Encore. La logique métier réutilise
intégralement `SendcloudOrderLinker::matchSendcloudId()` — aucune duplication d'appel API.

## Fichiers concernés

### Modifiés

#### `src/Controller/Admin/OrderCrudController.php`

Trois modifications : imports, constructeur (injection), déclaration de l'action, méthode handler.

**a) Imports à ajouter** (après les `use` existants, l.2-42) :

```php
use App\Exceptions\ExternalSendcloudApiException;
use App\Service\Sendcloud\SendcloudOrderLinker;
use Psr\Log\LoggerInterface;
use Symfony\Component\Security\Csrf\CsrfTokenManagerInterface;
```

`Order`, `AdminContext`, `Action`, `Actions`, `Crud`, `RedirectResponse`, `RequestStack`,
`AdminUrlGenerator`, `EntityManagerInterface` sont déjà importés.

**b) Constructeur** (l.46-51) — ajouter trois dépendances au constructeur promu existant :

```php
public function __construct(
    private readonly RequestStack $requestStack,
    private readonly EntityManagerInterface $em,
    private readonly OrderHelper $orderHelper,
    private readonly AdminUrlGenerator $adminUrlGenerator,
    private readonly SendcloudOrderLinker $linker,
    private readonly CsrfTokenManagerInterface $csrfTokenManager,
    private readonly LoggerInterface $logger,
) {
}
```

**c) `configureActions()`** (l.133-170) — déclarer l'action après `$cancelOrder` (l.135-151),
puis l'enregistrer et la réordonner. Le token CSRF est généré ici et passé en query param
`_csrf_token`; `displayIf` porte la condition « eBay ET (null OU "0") » :

```php
$syncSendcloud = Action::new('syncSendcloud', 'Sync Sendcloud')
    ->setIcon('fa fa-truck')
    ->linkToUrl(function (Order $entity) {
        $token = $this->csrfTokenManager
            ->getToken('sendcloud_sync_' . $entity->getId())
            ->getValue();

        return $this->adminUrlGenerator
            ->setController(self::class)
            ->setAction('syncSendcloud')
            ->setEntityId($entity->getId())
            ->set('_csrf_token', $token)
            ->includeReferrer()
            ->generateUrl();
    })
    ->addCssClass('text-primary')
    ->displayIf(static function (Order $entity) {
        return $entity->getIsEbay()
            && (null === $entity->getSendcloudOrderId() || '0' === $entity->getSendcloudOrderId());
    });
```

Dans le `return $actions` (l.158-169), ajouter l'enregistrement et intégrer l'action au
`reorder` de la page index :

```php
return $actions
    ->disable(Action::NEW)
    ->disable(Action::DELETE)
    ->add(Crud::PAGE_INDEX, $cancelOrder)
    ->add(Crud::PAGE_INDEX, $syncSendcloud)
    ->addBatchAction($batchPrintPdfTodayGlobal)
    ->update(Crud::PAGE_INDEX, Action::EDIT, function (Action $action) {
        return $action->displayIf(function (Order $order) {
            return $order->getStatePayment() !== GlobalConstants::CONST_STATE_PAYMENT_CANCEL;
        });
    })
    ->reorder(Crud::PAGE_INDEX, [Action::EDIT, 'cancelOrder', 'syncSendcloud'])
;
```

**d) Méthode handler** — à ajouter à côté de `cancelOrder()` (l.272-279), même style
(récupération via `$context->getEntity()->getInstance()`, `flush`, `redirect($context->getReferrer())`) :

```php
public function syncSendcloud(AdminContext $context): RedirectResponse
{
    /** @var Order $order */
    $order = $context->getEntity()->getInstance();
    $request = $this->requestStack->getCurrentRequest();

    if (!$this->isCsrfTokenValid('sendcloud_sync_' . $order->getId(), $request->query->get('_csrf_token'))) {
        $this->addFlash('danger', 'Token CSRF invalide.');

        return $this->redirect($context->getReferrer());
    }

    if (!$order->getIsEbay()) {
        $this->addFlash('danger', "Cette commande n'est pas une commande eBay.");

        return $this->redirect($context->getReferrer());
    }

    try {
        $sendcloudId = $this->linker->matchSendcloudId($order);
    } catch (ExternalSendcloudApiException $e) {
        $this->logger->warning('Sendcloud sync failed from admin', [
            'orderId' => $order->getId(),
            'orderIdEbay' => $order->getOrderIdEbay(),
            'error' => $e->getMessage(),
        ]);
        $this->addFlash('danger', 'Erreur API Sendcloud : ' . $e->getMessage());

        return $this->redirect($context->getReferrer());
    }

    if (null === $sendcloudId) {
        $order->setSendcloudOrderId('0');
        $this->em->flush();
        $this->addFlash('warning', sprintf(
            'Aucune commande Sendcloud trouvée pour la commande eBay %s.',
            $order->getOrderIdEbay()
        ));
    } else {
        $order->setSendcloudOrderId($sendcloudId);
        $this->em->flush();
        $this->addFlash('success', sprintf(
            'ID Sendcloud %s associé à la commande eBay %s.',
            $sendcloudId,
            $order->getOrderIdEbay()
        ));
    }

    return $this->redirect($context->getReferrer());
}
```

### Non modifiés (réutilisés tels quels)

- `src/Service/Sendcloud/SendcloudOrderLinker.php:22` — `matchSendcloudId(Order $order): ?string`,
  point d'entrée unique de résolution (appelle `SendcloudApiClient::getOrders()`), lève
  `ExternalSendcloudApiException` si l'API n'est pas configurée / en erreur.
- `src/Entity/Order.php` — `getIsEbay():?bool` (l.400), `getSendcloudOrderId():?string` (l.444),
  `setSendcloudOrderId(?string):Order` (l.449), `getOrderIdEbay()` (l.455). Aucun changement de
  schéma : la colonne `sendcloud_order_id` existe déjà (migration `Version20260711001138`).
- `templates/admin/order/order_ebay_shipping_service.html.twig` — inchangé. Le lien
  « Voir sur Sendcloud » (l.18) apparaîtra automatiquement dès que `sendcloudOrderId` devient un
  ID réel, et le bouton d'action disparaîtra (condition `displayIf` complémentaire).

**Aucun template Twig, aucun JS (`assets/back/js/back.js`), aucun rebuild Encore, aucune
migration** : l'action native EasyAdmin s'affiche via le mécanisme d'actions de ligne existant
et les flash sont rendus par le template EasyAdmin par défaut (`admin/layout.html.twig:114-116`).

## Étapes

1. **`OrderCrudController.php` — imports & constructeur** : ajouter les 4 `use` (b/a) et les 3
   dépendances promues (`SendcloudOrderLinker`, `CsrfTokenManagerInterface`, `LoggerInterface`).
   L'autowiring Symfony les résout sans config supplémentaire.
2. **`OrderCrudController.php` — `configureActions()`** : déclarer `$syncSendcloud` (génération
   du token + `displayIf` eBay/null/"0"), l'ajouter via `->add(Crud::PAGE_INDEX, $syncSendcloud)`
   et l'insérer dans le `->reorder(...)`.
3. **`OrderCrudController.php` — handler `syncSendcloud()`** : ajouter la méthode (validation CSRF,
   garde eBay, appel `matchSendcloudId`, `setSendcloudOrderId($id ?? '0')`, `flush`, flash, redirect).
4. **Rafraîchir le graphe** (CLAUDE.md § graphify) après modification du code.

## Vérification

- **Lint / analyse** (via `scripts/repo_exec.py`, jamais d'appel direct) : contrôler la syntaxe PHP
  et l'analyse statique du repo `src-eurocommemo` (ex. `php -l` sur le contrôleur, phpstan/php-cs-fixer
  si configurés).
- **Vidage du cache** EasyAdmin/routing puis chargement de la liste des commandes admin.
- **Scénario manuel principal** :
  1. Ouvrir la liste des commandes admin.
  2. Repérer une commande **eBay** dont `sendcloudOrderId` vaut `null` ou `"0"` → le bouton
     **« Sync Sendcloud »** doit être présent sur sa ligne. Vérifier qu'il est **absent** sur les
     commandes non-eBay et sur les commandes eBay déjà pourvues d'un ID réel (lien
     « Voir sur Sendcloud » affiché à la place).
  3. Cliquer le bouton :
     - Match trouvé → flash **success**, `sendcloudOrderId` mis à jour, au rechargement le bouton
       disparaît et le lien « Voir sur Sendcloud » apparaît.
     - Aucun match → flash **warning**, `sendcloudOrderId` reste `"0"`, le bouton reste affiché
       (re-synchronisation possible).
     - API Sendcloud non configurée / en erreur → flash **danger**, aucune modification en base.
- **Sécurité CSRF** : rejouer l'URL de l'action en altérant le paramètre `_csrf_token` → flash
  **danger** « Token CSRF invalide. » et aucune écriture.
- **Non-régression** : vérifier que les actions existantes de la ligne (`Modifier`, `cancelOrder`)
  et les vues filtrées (`?state=...`, `?delivery=1`) s'affichent toujours correctement.
- **Cohérence CLI** : le résultat du bouton doit être identique à
  `app:sendcloud:sync-order-ids --orderId <orderIdEbay>` pour la même commande.
