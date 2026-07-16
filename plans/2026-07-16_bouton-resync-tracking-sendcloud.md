# Plan — Action EasyAdmin « Récupérer le suivi Sendcloud » sur la liste des commandes

## Contexte

Sur la liste admin « Toutes les commandes » (EasyAdmin, `OrderCrudController`, vue sans query param
`state` ni `delivery`), certaines commandes expédiées sont liées à Sendcloud
(`sendcloudOrderId` renseigné) mais n'ont jamais reçu leurs informations de colis
(`sendcloudParcelId`, `sendcloudTrackingNumber`, `sendcloudTrackingUrl` restés `NULL`) — typiquement
les commandes dont l'étiquette a été générée hors application, ou avant l'ajout du workflow
Sendcloud. Le lien « Suivre le colis » (basé sur `sendcloudTrackingUrl`) n'apparaît donc jamais pour
elles.

L'objectif : exposer une **action EasyAdmin par ligne** (sur le modèle exact de l'action existante
`syncSendcloud`) qui appelle l'API Sendcloud déjà intégrée pour récupérer le colis annoncé (via
`order_number = orderIdEbay`) et hydrater les trois champs sur l'`Order`, sans régénérer d'étiquette.
L'action est affichée conditionnellement (`displayIf`) uniquement pour les commandes concernées. Si
Sendcloud n'a **aucun colis** pour la commande, on écrit la valeur sentinelle `"0"` dans les trois
colonnes — ce qui satisfait automatiquement le `displayIf` (colonnes non nulles → action masquée) et
reprend la même convention que `sendcloudOrderId = '0'` (« pas de correspondance Sendcloud »).

La logique de résolution existe déjà : `SendcloudTrackingResolver::resolveTracking(Order): ?array`
(retourne `{parcelId, trackingNumber, trackingUrl}` ou `null`), aujourd'hui consommée uniquement par
la commande CLI `app:sendcloud:backfill-tracking` (`src/Command/BackfillSendcloudTrackingCommand.php`).
La demande impose d'extraire cette logique dans un **UseCase réutilisable** afin que la commande batch
et la nouvelle action admin partagent le même comportement (dont la nouvelle règle « pas de colis →
`"0"` »).

Contraintes connues :
- Repo cible : `src-eurocommemo` (Symfony + EasyAdmin), racine
  `/Users/aurelienmorvan/OrbStack/docker/volumes/src-eurocommemo`.
- Modèle imposé : l'action EasyAdmin `syncSendcloud` (`OrderCrudController.php` lignes 170-190 pour la
  déclaration, 322-371 pour la méthode) — action `linkToUrl` en GET avec `_csrf_token` en query param,
  `displayIf`, méthode CRUD qui `flush()` + `addFlash()` + `redirect($context->getReferrer())`.
- Convention de persistance Sendcloud : le UseCase **mute l'entité managée mais ne flushe pas** ; c'est
  l'appelant qui `flush()` (cf. `SendcloudLabelService::generateLabel` +
  `OrderCrudController::sendcloudGenerateLabel` ligne 602). Ceci préserve le batch-flush de la
  commande (`flush()` tous les 200).
- Aucune migration Doctrine : les trois colonnes existent déjà (`string(255)`, nullable) sur
  `Order.php` lignes 114-119.
- Pas de JS ni de template custom : une action EasyAdmin s'affiche automatiquement dans la colonne
  « Actions » de l'index dès qu'elle est ajoutée à `Crud::PAGE_INDEX`.

## Fichiers concernés

### Nouveaux

#### `src/Service/Sendcloud/UseCase/BackfillSendcloudTrackingUseCase.php`

UseCase réutilisable qui encapsule la résolution + l'hydratation de l'`Order`. Ne flushe pas
(l'appelant décide). Applique la règle « pas de colis → `"0"` ». Le dossier `UseCase/` sous
`Service/Sendcloud/` reprend la convention `src/Service/Ebay/UseCase/`.

```php
<?php

namespace App\Service\Sendcloud\UseCase;

use App\Entity\Order;
use App\Exceptions\ExternalSendcloudApiException;
use App\Service\Sendcloud\SendcloudTrackingResolver;

final class BackfillSendcloudTrackingUseCase
{
    /**
     * Sentinel written on the three parcel columns when Sendcloud has no parcel for the order,
     * so the order is not re-processed and the "resolve tracking" action no longer shows.
     */
    public const NO_PARCEL_SENTINEL = '0';

    public function __construct(
        private readonly SendcloudTrackingResolver $trackingResolver,
    ) {
    }

    /**
     * Resolve the parcel tracking data announced on Sendcloud for the given order and hydrate the
     * three sendcloud tracking columns. When no parcel exists on Sendcloud, the three columns are
     * set to NO_PARCEL_SENTINEL. Mutates the (managed) entity but does NOT flush — the caller flushes.
     *
     * @return array{status: 'resolved'|'not_found', parcelId: ?string, trackingNumber: ?string, trackingUrl: ?string}
     *
     * @throws ExternalSendcloudApiException
     */
    public function execute(Order $order): array
    {
        $tracking = $this->trackingResolver->resolveTracking($order);

        if (null === $tracking) {
            $order->setSendcloudParcelId(self::NO_PARCEL_SENTINEL)
                ->setSendcloudTrackingNumber(self::NO_PARCEL_SENTINEL)
                ->setSendcloudTrackingUrl(self::NO_PARCEL_SENTINEL);

            return [
                'status'         => 'not_found',
                'parcelId'       => self::NO_PARCEL_SENTINEL,
                'trackingNumber' => self::NO_PARCEL_SENTINEL,
                'trackingUrl'    => self::NO_PARCEL_SENTINEL,
            ];
        }

        $order->setSendcloudParcelId($tracking['parcelId'])
            ->setSendcloudTrackingNumber($tracking['trackingNumber'])
            ->setSendcloudTrackingUrl($tracking['trackingUrl']);

        return [
            'status'         => 'resolved',
            'parcelId'       => $tracking['parcelId'],
            'trackingNumber' => $tracking['trackingNumber'],
            'trackingUrl'    => $tracking['trackingUrl'],
        ];
    }
}
```

> Note : les setters de `Order` sont fluent (`set…(): Order`, `Order.php` lignes 507/518/529), le
> chaînage ci-dessus est valide et mirroir `SendcloudLabelService::generateLabel` lignes 47-50.
> Autowiring automatique (services.yaml `App\:` charge tout `../src/`), aucune déclaration explicite.

### Modifiés

#### `src/Controller/Admin/OrderCrudController.php`

Trois modifications : injecter le UseCase, déclarer l'action EasyAdmin conditionnelle, ajouter la
méthode CRUD cible.

**(a) Constructeur** (lignes 54-66) — ajouter la dépendance et l'import
`use App\Service\Sendcloud\UseCase\BackfillSendcloudTrackingUseCase;` (bloc d'imports lignes 11-14) :

```php
public function __construct(
    private readonly RequestStack $requestStack,
    private readonly EntityManagerInterface $em,
    private readonly OrderHelper $orderHelper,
    private readonly AdminUrlGenerator $adminUrlGenerator,
    private readonly SendcloudOrderLinker $linker,
    private readonly SendcloudApiClient $apiClient,
    private readonly SendcloudOrderShippingService $sendcloudShippingService,
    private readonly SendcloudLabelService $labelService,
    private readonly BackfillSendcloudTrackingUseCase $backfillTracking,
    private readonly CsrfTokenManagerInterface $csrfTokenManager,
    private readonly LoggerInterface $logger
) {
}
```

**(b) Action** — dans `configureActions()` (lignes 150-210), déclarer l'action après `$syncSendcloud`
(après la ligne 190), en miroir strict de `syncSendcloud`. Le `displayIf` encode les conditions
demandées : commande eBay, expédiée (`dateExpedition` non nulle), liée Sendcloud
(`sendcloudOrderId` non nul et `!= '0'`), et au moins une des trois colonnes de suivi vide.

```php
$resolveSendcloudTracking = Action::new('resolveSendcloudTracking', 'Récupérer le suivi Sendcloud')
    ->setIcon('fa fa-barcode')
    ->linkToUrl(function (Order $entity) {
        $token = $this->csrfTokenManager
            ->getToken('sendcloud_tracking_' . $entity->getId())
            ->getValue();

        return $this->adminUrlGenerator
            ->setController(self::class)
            ->setAction('resolveSendcloudTracking')
            ->setEntityId($entity->getId())
            ->set('_csrf_token', $token)
            ->includeReferrer()
            ->generateUrl();
    })
    ->addCssClass('text-primary')
    ->displayIf(static function (Order $entity) {
        return $entity->getIsEbay()
            && null !== $entity->getDateExpedition()
            && !in_array($entity->getSendcloudOrderId(), [null, '0'], true)
            && (
                null === $entity->getSendcloudParcelId()
                || null === $entity->getSendcloudTrackingNumber()
                || null === $entity->getSendcloudTrackingUrl()
            );
    })
;
```

Puis l'enregistrer dans le `return $actions` (lignes 197-209) — ajouter après la ligne 201 et l'inclure
dans le `reorder` (ligne 208) :

```php
return $actions
    ->disable(Action::NEW)
    ->disable(Action::DELETE)
    ->add(Crud::PAGE_INDEX, $cancelOrder)
    ->add(Crud::PAGE_INDEX, $syncSendcloud)
    ->add(Crud::PAGE_INDEX, $resolveSendcloudTracking)
    ->addBatchAction($batchPrintPdfTodayGlobal)
    ->update(Crud::PAGE_INDEX, Action::EDIT, function (Action $action) {
        return $action->displayIf(function(Order $order) {
            return $order->getStatePayment() !== GlobalConstants::CONST_STATE_PAYMENT_CANCEL;
        });
    })
    ->reorder(Crud::PAGE_INDEX, [Action::EDIT, 'cancelOrder', 'syncSendcloud', 'resolveSendcloudTracking'])
;
```

**(c) Méthode CRUD** — ajouter après `syncSendcloud()` (après la ligne 371), en miroir strict (CSRF via
`$request->query->get('_csrf_token')`, garde métier, `flush()`, `addFlash()`, redirection referrer) :

```php
public function resolveSendcloudTracking(AdminContext $context): RedirectResponse
{
    /** @var Order $order */
    $order = $context->getEntity()->getInstance();
    $request = $this->requestStack->getCurrentRequest();

    if (!$this->isCsrfTokenValid('sendcloud_tracking_' . $order->getId(), $request->query->get('_csrf_token'))) {
        $this->addFlash('danger', 'Token CSRF invalide.');

        return $this->redirect($context->getReferrer());
    }

    if (!$order->getIsEbay() || in_array($order->getSendcloudOrderId(), [null, '0'], true)) {
        $this->addFlash('danger', "Action indisponible pour cette commande.");

        return $this->redirect($context->getReferrer());
    }

    try {
        $result = $this->backfillTracking->execute($order);
        $this->em->flush();
    } catch (ExternalSendcloudApiException $e) {
        $this->logger->warning('Sendcloud tracking resolution failed from admin', [
            'orderId'     => $order->getId(),
            'orderIdEbay' => $order->getOrderIdEbay(),
            'error'       => $e->getMessage(),
        ]);
        $this->addFlash('danger', 'Erreur API Sendcloud : ' . $e->getMessage());

        return $this->redirect($context->getReferrer());
    }

    if ('not_found' === $result['status']) {
        $this->addFlash('warning', sprintf(
            'Aucun colis Sendcloud pour la commande eBay %s — colonnes de suivi définies à "0".',
            $order->getOrderIdEbay()
        ));
    } else {
        $this->addFlash('success', sprintf(
            'Suivi Sendcloud récupéré pour la commande eBay %s (colis %s).',
            $order->getOrderIdEbay(),
            $result['parcelId']
        ));
    }

    return $this->redirect($context->getReferrer());
}
```

> `ExternalSendcloudApiException` (ligne 6), `AdminContext`, `RedirectResponse`, `Order`,
> `GlobalConstants`, `Action`, `Crud` sont déjà importés. La garde `!in_array(... [null,'0'])` protège
> contre un appel forgé sur une commande non éligible ; le cas « tracking déjà présent » est déjà exclu
> par le `displayIf` (l'action n'est alors pas rendue).

#### `src/Command/BackfillSendcloudTrackingCommand.php`

Refactorer pour déléguer au nouveau UseCase (réutilisabilité + application uniforme de la règle
`"0"`). Le champ `SendcloudTrackingResolver` est remplacé par `BackfillSendcloudTrackingUseCase`. La
distinction `updated`/`skipped` devient `resolved`/`notFound` (les « not_found » ne sont plus ignorés
mais écrits à `"0"`) ; le batch-flush tous les 200 (ligne 110-112) et le flush final (ligne 116-118)
sont conservés.

Constructeur (lignes 24-31) :

```php
public function __construct(
    private readonly OrderRepository $orderRepository,
    private readonly BackfillSendcloudTrackingUseCase $backfillTracking,
    private readonly EntityManagerInterface $entityManager,
    private readonly LoggerInterface $logger
) {
    parent::__construct();
}
```

Imports : retirer `use App\Service\Sendcloud\SendcloudTrackingResolver;`, ajouter
`use App\Service\Sendcloud\UseCase\BackfillSendcloudTrackingUseCase;`.

Boucle `foreach` (lignes 74-113) — remplacer le bloc resolve+set+skip :

```php
foreach ($orders as $order) {
    try {
        $result = $this->backfillTracking->execute($order);
    } catch (ExternalSendcloudApiException $e) {
        // Not-configured / API error: abort the whole run — nothing else will succeed.
        $progressBar->finish();
        $output->writeln('');
        $output->writeln('<error>' . $e->getMessage() . '</error>');

        return Command::FAILURE;
    }

    if ('not_found' === $result['status']) {
        ++$notFound;
        $this->logger->warning('No Sendcloud parcel found for shipped eBay order — columns set to "0"', [
            'orderIdEbay'      => $order->getOrderIdEbay(),
            'sendcloudOrderId' => $order->getSendcloudOrderId(),
        ]);
    } else {
        ++$resolved;
        if ($dryRun) {
            $output->writeln(sprintf(
                "\n  %s → parcel %s, tracking %s",
                $order->getOrderIdEbay(),
                $result['parcelId'],
                $result['trackingNumber'] ?? '(none)'
            ));
        }
    }

    $progressBar->advance();
    ++$cptProcess;
    if (!$dryRun && 0 === $cptProcess % 200) {
        $this->entityManager->flush();
    }
}
```

Renommer `$updated`/`$skipped` → `$resolved`/`$notFound` (init lignes 70-71) et adapter le résumé
(lignes 121-126) :

```php
$output->writeln(sprintf(
    '%d resolved, %d without parcel (set to "0")%s',
    $resolved,
    $notFound,
    $dryRun ? ' (dry-run, nothing persisted)' : ''
));
```

> Rétro-compatibilité : en `dry-run`, le UseCase mute quand même l'entité en mémoire (y compris `"0"`) ;
> comme la commande ne flushe pas en dry-run, rien n'est persisté — comportement observable identique.
> À valider en revue.

#### `templates/admin/order/order_ebay_shipping_service.html.twig` (ajustement mineur)

Aucun bouton à ajouter (l'action vit dans la colonne « Actions » d'EasyAdmin). Seul ajustement : dans la
branche `else` (lignes 28-40), garder le lien « Suivre le colis » mais éviter qu'il pointe vers la
sentinelle `"0"` après un `not_found`. Remplacer la condition ligne 30 :

```twig
        {% set sendcloudTrackingUrl = entity.instance.sendcloudTrackingUrl %}
        {% if sendcloudTrackingUrl and sendcloudTrackingUrl != '0' %}
```

## Étapes

1. **UseCase** — Créer `src/Service/Sendcloud/UseCase/BackfillSendcloudTrackingUseCase.php` (fetch via
   `SendcloudTrackingResolver`, hydratation des trois champs, règle `"0"` sur `not_found`, pas de flush).
2. **Contrôleur — injection** — Injecter `BackfillSendcloudTrackingUseCase` dans le constructeur de
   `OrderCrudController.php` + import.
3. **Contrôleur — action** — Déclarer l'action `resolveSendcloudTracking` dans `configureActions()`
   (`linkToUrl` + CSRF `sendcloud_tracking_<id>` + `displayIf` sur les conditions), l'ajouter à
   `Crud::PAGE_INDEX` et au `reorder`.
4. **Contrôleur — méthode** — Ajouter `resolveSendcloudTracking(AdminContext): RedirectResponse` (garde
   CSRF + garde métier + `flush()` + `addFlash()` + gestion `ExternalSendcloudApiException`).
5. **Template** — Ajuster la condition du lien « Suivre le colis » (`!= '0'`) dans
   `order_ebay_shipping_service.html.twig`.
6. **Refactor commande** — Adapter `BackfillSendcloudTrackingCommand.php` pour consommer le UseCase
   (compteurs `resolved`/`notFound`, résumé, batch-flush conservé) et retirer l'injection du resolver.
7. **Log d'action** — Consigner l'intervention dans `logs/src-eurocommemo.md` (règle action-logging).

## Vérification

**Build / statique** (via `scripts/repo_exec.py`, jamais d'appel direct) :
- `php bin/console lint:container` — valide l'autowiring du UseCase et l'injection contrôleur.
- `php bin/console cache:clear` — purge le cache EasyAdmin (déclaration d'action).
- `vendor/bin/phpstan analyse src/Service/Sendcloud/UseCase src/Controller/Admin/OrderCrudController.php`
  (si PHPStan configuré) — typage du UseCase, de l'action et de la méthode CRUD.

Aucune recompilation d'assets nécessaire (pas de JS/CSS touché).

**Commande CLI (non-régression du refactor)** :
- `php bin/console app:sendcloud:backfill-tracking --orderId=<id eBay expédié sans tracking> --dry-run`
  → `1 order(s) to backfill` puis `… resolved …` / `… without parcel …`, **sans rien persister**.
- Rejouer sans `--dry-run` → colonnes hydratées, ou passées à `"0"` si aucun colis.

**Scénario manuel (cœur de la demande)** :
1. Ouvrir la liste « Toutes les commandes » (aucun filtre `state`/`delivery`).
2. Repérer une commande **expédiée** avec `sendcloudOrderId` défini mais tracking vide → l'action
   « Récupérer le suivi Sendcloud » (icône code-barres) doit apparaître dans la colonne « Actions ».
3. Cliquer :
   - **Colis trouvé** → flash de succès ; en base `sendcloudParcelId` / `sendcloudTrackingNumber` /
     `sendcloudTrackingUrl` renseignés ; le lien « Suivre le colis » apparaît désormais ; l'action
     disparaît de la ligne.
   - **Aucun colis** → flash d'avertissement ; les trois colonnes valent `"0"` ; l'action disparaît de
     la ligne (colonnes non nulles).
4. Vérifier que l'action **n'apparaît pas** pour : une commande non expédiée (`dateExpedition` nul),
   sans `sendcloudOrderId` (`null`/`'0'`), ou déjà pourvue d'un tracking complet.
5. Tester un token CSRF invalide (URL forgée) → flash « Token CSRF invalide. », aucune mutation.

**Critères mesurables** : l'action redirige avec un flash `success`/`warning`/`danger` selon le cas ;
`displayIf` masque l'action dès que le tracking est présent ou marqué `"0"` ; aucune régression de la
commande batch ; aucune migration BDD requise.
