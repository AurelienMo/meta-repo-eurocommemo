# Plan — Commande de backfill du tracking Sendcloud

## Contexte

Depuis la migration `Version20260712120000`, l'entité `Order` porte trois champs de suivi
Sendcloud — `sendcloudParcelId`, `sendcloudTrackingNumber`, `sendcloudTrackingUrl` — hydratés
uniquement lors de la génération d'étiquette (`SendcloudLabelService::generateLabel()`, via
`createLabelSync` + `getParcel`). Les commandes eBay **expédiées avant cette feature** possèdent
un `sendcloudOrderId` valide mais ces trois champs vides. Résultat : dans la vue admin
« Toutes les commandes » (`OrderCrudController.php:266` → template
`admin/order/order_ebay_shipping_service.html.twig`, branche `else`), le lien **« Suivre le
colis »** ne s'affiche pas (condition `sendcloudTrackingUrl` truthy, ligne 30 du template).

Objectif : une commande Symfony de rattrapage qui, pour chaque commande eBay **déjà expédiée**
(`dateExpedition` non nul) **liée à Sendcloud** (`sendcloudOrderId` non nul et `!= '0'`) et à
laquelle il **manque au moins un** des trois champs de suivi, récupère le colis **déjà annoncé**
sur Sendcloud **en lecture seule** (aucune régénération d'étiquette) et renseigne les trois
champs. Le lien « Suivre le colis » apparaîtra alors automatiquement.

Décisions validées avec le demandeur :
- **Source du tracking : lecture seule** — on interroge Sendcloud pour retrouver le colis
  existant, on ne rappelle **jamais** `createLabelSync` (pas de risque de colis en double).
- **Périmètre : commandes expédiées uniquement** (`dateExpedition IS NOT NULL`).
- **Récupération du colis via l'API Shipments** : `GET /api/v3/shipments?order_number=<orderIdEbay>`
  (documentée dans `specs/sendcloud-v3/shipments/openapi.yaml`, opId `sc-public-v3-scp-get-all_shipments`).
  La réponse renvoie `{ data: [ { parcels: [ { id, tracking_number, tracking_url, ... } ] } ] }` → le
  tracking se lit directement dans les colis du/des shipment(s), sans appel intermédiaire.

> ✅ **Forme de la réponse confirmée par la spec** (`specs/sendcloud-v3/shipments/openapi.yaml`,
> path `/shipments`, lignes 779-1072) : enveloppe `data` (array de `shipment-response`) ; chaque
> shipment porte `order_number` et un array `parcels` ; chaque colis expose `id` (int),
> `tracking_number` et `tracking_url`. Filtre query `order_number` (lignes 1000-1006), pagination
> cursor via header `Link` (`rel="next"`). Un `--dry-run` de contrôle reste recommandé avant le run réel.

## Fichiers concernés

### Nouveaux

#### `src/Command/BackfillSendcloudTrackingCommand.php`

Nouvelle commande, calquée sur `SyncSendcloudOrderIdsCommand`
(`src/Command/SyncSendcloudOrderIdsCommand.php`) : même `#[AsCommand(name, description)]` nommé,
mêmes dépendances `private readonly`, même boucle avec `ProgressBar` et flush par lots de 200,
même gestion d'abort global sur `ExternalSendcloudApiException`.

```php
<?php

namespace App\Command;

use App\Entity\Order;
use App\Exceptions\ExternalSendcloudApiException;
use App\Repository\OrderRepository;
use App\Service\Sendcloud\SendcloudTrackingResolver;
use Doctrine\ORM\EntityManagerInterface;
use Psr\Log\LoggerInterface;
use Symfony\Component\Console\Attribute\AsCommand;
use Symfony\Component\Console\Command\Command;
use Symfony\Component\Console\Helper\ProgressBar;
use Symfony\Component\Console\Input\InputInterface;
use Symfony\Component\Console\Input\InputOption;
use Symfony\Component\Console\Output\OutputInterface;

#[AsCommand(
    name: 'app:sendcloud:backfill-tracking',
    description: 'Backfill parcel id + tracking number/url on shipped eBay orders linked to Sendcloud (read-only from Sendcloud, no label regeneration)'
)]
class BackfillSendcloudTrackingCommand extends Command
{
    public function __construct(
        private readonly OrderRepository $orderRepository,
        private readonly SendcloudTrackingResolver $trackingResolver,
        private readonly EntityManagerInterface $entityManager,
        private readonly LoggerInterface $logger
    ) {
        parent::__construct();
    }

    protected function configure(): void
    {
        $this
            ->addOption(
                'orderId',
                'o',
                InputOption::VALUE_OPTIONAL,
                'Restrict the backfill to a single eBay order id (orderIdEbay)'
            )
            ->addOption(
                'dry-run',
                null,
                InputOption::VALUE_NONE,
                'Resolve tracking but do not persist (prints what would change)'
            );
    }

    protected function execute(InputInterface $input, OutputInterface $output): int
    {
        $orderId = $input->getOption('orderId');
        $dryRun  = (bool) $input->getOption('dry-run');

        if (null !== $orderId && '' !== $orderId) {
            $order  = $this->orderRepository->findOneBy(['orderIdEbay' => $orderId, 'isEbay' => true]);
            $orders = $order instanceof Order ? [$order] : [];
        } else {
            $orders = $this->orderRepository->findEbayOrdersShippedMissingTracking();
        }

        $output->writeln(count($orders) . ' order(s) to backfill');
        if (0 === count($orders)) {
            return Command::SUCCESS;
        }

        $progressBar = new ProgressBar($output, count($orders));
        $progressBar->start();

        $updated = 0;
        $skipped = 0;
        $cptProcess = 0;

        foreach ($orders as $order) {
            try {
                $tracking = $this->trackingResolver->resolveTracking($order);
            } catch (ExternalSendcloudApiException $e) {
                // Not-configured / API error: abort the whole run — nothing else will succeed.
                $progressBar->finish();
                $output->writeln('');
                $output->writeln('<error>' . $e->getMessage() . '</error>');

                return Command::FAILURE;
            }

            if (null === $tracking) {
                ++$skipped;
                $this->logger->warning('No Sendcloud parcel found for shipped eBay order', [
                    'orderIdEbay'      => $order->getOrderIdEbay(),
                    'sendcloudOrderId' => $order->getSendcloudOrderId(),
                ]);
            } else {
                $order->setSendcloudParcelId($tracking['parcelId'])
                    ->setSendcloudTrackingNumber($tracking['trackingNumber'])
                    ->setSendcloudTrackingUrl($tracking['trackingUrl']);
                ++$updated;

                if ($dryRun) {
                    $output->writeln(sprintf(
                        "\n  %s → parcel %s, tracking %s",
                        $order->getOrderIdEbay(),
                        $tracking['parcelId'],
                        $tracking['trackingNumber'] ?? '(none)'
                    ));
                }
            }

            $progressBar->advance();
            ++$cptProcess;
            if (!$dryRun && 0 === $cptProcess % 200) {
                $this->entityManager->flush();
            }
        }

        $progressBar->finish();
        if (!$dryRun) {
            $this->entityManager->flush();
        }

        $output->writeln('');
        $output->writeln(sprintf(
            '%d updated, %d skipped%s',
            $updated,
            $skipped,
            $dryRun ? ' (dry-run, nothing persisted)' : ''
        ));

        return Command::SUCCESS;
    }
}
```

> Note : en `--dry-run`, les setters mutent quand même l'entité en mémoire (nécessaire pour
> l'affichage), mais aucun `flush()` n'est appelé → rien n'est persisté.

#### `src/Service/Sendcloud/SendcloudTrackingResolver.php`

Nouveau service de résolution en lecture seule, calqué sur `SendcloudOrderLinker`
(`final class`, dépend de `SendcloudApiClient`, retourne une valeur, **ne flush pas**). Il
interroge l'API Shipments par `order_number` (= `orderIdEbay`), aplatit les colis des shipments
renvoyés et lit directement leur tracking — un seul appel, pas de résolution de `parcel_id`
intermédiaire. La commande reste ainsi mince et le résolveur est testable isolément.

```php
<?php

namespace App\Service\Sendcloud;

use App\Entity\Order;
use App\Exceptions\ExternalSendcloudApiException;

final class SendcloudTrackingResolver
{
    public function __construct(
        private readonly SendcloudApiClient $apiClient,
    ) {
    }

    /**
     * Read the tracking data of the parcel already announced for an eBay order, by querying
     * the Sendcloud Shipments API filtered on order_number = orderIdEbay. WITHOUT recreating any
     * label. Returns null when no parcel can be located on Sendcloud.
     *
     * @return array{parcelId: string, trackingNumber: ?string, trackingUrl: ?string}|null
     *
     * @throws ExternalSendcloudApiException
     */
    public function resolveTracking(Order $order): ?array
    {
        $orderNumber = $order->getOrderIdEbay();
        if (null === $orderNumber || '' === $orderNumber) {
            return null;
        }

        $shipments = $this->apiClient->getShipmentsByOrderNumber($orderNumber);

        // Flatten the parcels of every matched shipment.
        $parcels = [];
        foreach ($shipments as $shipment) {
            foreach ($shipment['parcels'] ?? [] as $parcel) {
                $parcels[] = $parcel;
            }
        }
        if ([] === $parcels) {
            return null;
        }

        // Prefer the most recent parcel that actually carries a tracking number
        // (a re-announced order may expose several parcels for the same order_number).
        $selected = null;
        foreach ($parcels as $parcel) {
            if (!empty($parcel['tracking_number'])) {
                $selected = $parcel;
            }
        }
        $selected ??= $parcels[array_key_last($parcels)];

        $parcelId = (int) ($selected['id'] ?? 0);
        if (0 === $parcelId) {
            return null;
        }

        return [
            'parcelId'       => (string) $parcelId,
            'trackingNumber' => $selected['tracking_number'] ?? null,
            'trackingUrl'    => $selected['tracking_url'] ?? null,
        ];
    }
}
```

### Modifiés

#### `src/Service/Sendcloud/SendcloudApiClient.php`

Deux ajouts :

1. Une constante d'endpoint, à côté des existantes (lignes 17-22) :

```php
private const ENDPOINT_SHIPMENTS = '/shipments';
```

2. Une méthode `getShipmentsByOrderNumber()` (liste des shipments filtrée par `order_number`) à
placer près de `getOrders()` (lignes 40-65), dont elle reprend exactement le pattern (déballage
`data` + pagination `Link rel="next"` via `extractNextLink()`, lignes 379-390).

```php
/**
 * Retrieve the shipments matching an external order number.
 * Mirrors getOrders(): cursor-based pagination via the RFC 5988 `Link` header.
 *
 * @return array<int, array<string, mixed>> raw shipment nodes (each exposes a `parcels` list
 *                                           whose items carry id / tracking_number / tracking_url)
 *
 * @throws ExternalSendcloudApiException
 */
public function getShipmentsByOrderNumber(string $orderNumber): array
{
    $shipments = [];
    $url       = self::PREFIX_URL . self::ENDPOINT_SHIPMENTS;
    $options   = ['query' => ['order_number' => $orderNumber], 'http_errors' => false];

    while (null !== $url) {
        $response = $this->request('GET', $url, $options);
        $decoded  = json_decode($response->getBody()->getContents(), true) ?? [];

        foreach ($decoded['data'] ?? [] as $shipment) {
            $shipments[] = $shipment;
        }

        // The `next` link already carries the cursor/query params → drop `query` for it.
        $url     = $this->extractNextLink($response);
        $options = ['http_errors' => false];
    }

    return $shipments;
}
```

`PREFIX_URL` (ligne 17) et le helper `extractNextLink()` (lignes 379-390) existent déjà. La méthode
`getParcel(int $parcelId)` (ligne 316) n'est plus nécessaire au backfill (le shipment liste porte
déjà les colis et leur tracking).

#### `src/Repository/OrderRepository.php`

Ajouter une méthode de sélection, à placer près de `findEbayOrdersMissingSendcloudId()`
(lignes 105-112) dont elle reprend le style (`createQueryBuilder('o')` + `where('o.isEbay = true')`).
Le `OR` sur les trois champs de suivi doit être groupé via `expr()->orX()` pour ne pas casser la
combinaison avec les autres `andWhere`.

```php
/**
 * eBay orders already shipped and linked to Sendcloud, but missing at least one tracking field.
 * Used by app:sendcloud:backfill-tracking.
 *
 * @return Order[]
 */
public function findEbayOrdersShippedMissingTracking(): array
{
    $qb = $this->createQueryBuilder('o');

    return $qb
        ->where('o.isEbay = true')
        ->andWhere('o.sendcloudOrderId IS NOT NULL')
        ->andWhere("o.sendcloudOrderId != '0'")
        ->andWhere('o.dateExpedition IS NOT NULL')
        ->andWhere($qb->expr()->orX(
            'o.sendcloudParcelId IS NULL',
            'o.sendcloudTrackingNumber IS NULL',
            'o.sendcloudTrackingUrl IS NULL'
        ))
        ->getQuery()
        ->getResult();
}
```

### Tests (nouveaux, recommandés)

Aligner sur l'existant `tests/Service/Sendcloud/SendcloudOrderLinkerTest.php` et
`tests/Service/Sendcloud/SendcloudApiClientTest.php` :

- `tests/Service/Sendcloud/SendcloudTrackingResolverTest.php` — `resolveTracking()` : cas shipment
  avec colis (les 3 clés retournées), cas `orderIdEbay` vide → `null`, cas liste vide / shipment
  sans `parcels` → `null`, cas plusieurs colis → sélection du dernier portant un `tracking_number`,
  cas colis sans `id` → `null`.
- (optionnel) un cas dans `SendcloudApiClientTest` couvrant `getShipmentsByOrderNumber()`
  (déballage `data` + pagination `Link`).

## Étapes

1. **`SendcloudApiClient::getShipmentsByOrderNumber()`** — ajouter la constante `ENDPOINT_SHIPMENTS`
   et la méthode (fichier `src/Service/Sendcloud/SendcloudApiClient.php`, près de `getOrders()`).
   Vérifiable seule par un test unitaire mockant le client Guzzle (déballage `data` + pagination `Link`).
2. **`SendcloudTrackingResolver`** — créer le service
   (`src/Service/Sendcloud/SendcloudTrackingResolver.php`). L'autowiring Symfony le câble
   automatiquement (services par convention dans `App\Service\`). Vérifiable par test unitaire.
3. **`OrderRepository::findEbayOrdersShippedMissingTracking()`** — ajouter la requête
   (`src/Repository/OrderRepository.php`). Vérifiable via `bin/console dbal:run-sql` ou un test
   d'intégration repository.
4. **`BackfillSendcloudTrackingCommand`** — créer la commande
   (`src/Command/BackfillSendcloudTrackingCommand.php`). Vérifiable : elle apparaît dans
   `bin/console list app:sendcloud`.
5. **Contrôle sur la réponse Shipments (avant run réel)** — exécuter la commande en `--dry-run`
   sur une commande témoin (`--orderId=<id>`) et confirmer que la réponse
   `GET /shipments?order_number=<orderIdEbay>` expose bien `data[].parcels[]` avec `id` /
   `tracking_number` / `tracking_url` (forme documentée par la spec). Ne pas passer à l'étape 6
   tant que le dry-run ne retourne pas un `parcelId` + tracking corrects.
6. **Run réel** — `bin/console app:sendcloud:backfill-tracking` (sans `--dry-run`) ; contrôler le
   compteur `X updated, Y skipped`.
7. **Journalisation & graphe** — après implémentation : entrée dans `logs/src-eurocommemo.md`
   (règle action-logging) puis rafraîchir le graphe graphify du repo (voir CLAUDE.md § graphify).

## Vérification

Toutes les commandes du repo passent par `scripts/repo_exec.py` (CLAUDE.md § pipeline) — jamais
d'appel direct. Exemples (à router via `repo_exec.py`) :

- **Découverte de la commande** :
  `bin/console list app:sendcloud` → `app:sendcloud:backfill-tracking` listée avec sa description.
- **Dry-run ciblé (contrôle réponse Shipments, étape 5)** :
  `bin/console app:sendcloud:backfill-tracking --orderId=<orderIdEbay> --dry-run`
  → doit afficher `<orderIdEbay> → parcel <id>, tracking <num>` et `1 updated, 0 skipped (dry-run, nothing persisted)`.
- **Dry-run global** :
  `bin/console app:sendcloud:backfill-tracking --dry-run` → affiche le nombre de commandes
  ciblées et, pour chacune résolue, la ligne parcel/tracking, sans rien persister.
- **Run réel** : `bin/console app:sendcloud:backfill-tracking` → `X updated, Y skipped`.
- **Contrôle base** : vérifier qu'une commande traitée a bien ses trois colonnes renseignées
  (`sendcloud_parcel_id`, `sendcloud_tracking_number`, `sendcloud_tracking_url`).
- **Contrôle UI (critère final)** : dans l'admin, menu « Toutes les commandes »
  (`DashboardController.php:123`), sur une commande expédiée traitée, le lien **« Suivre le
  colis »** doit désormais apparaître dans la colonne « Infos livraison » (template
  `admin/order/order_ebay_shipping_service.html.twig`, branche `else`, condition
  `sendcloudTrackingUrl`).
- **Tests** : exécuter la suite Sendcloud (`tests/Service/Sendcloud/…`) via `repo_exec.py` ;
  ajouter/valider `SendcloudTrackingResolverTest`.
- **Non-régression clé** : confirmer qu'aucun appel à `createLabelSync` n'est effectué par le
  backfill (lecture seule) — vérifiable par le mock du client dans le test du résolveur (seul
  `getShipmentsByOrderNumber` est attendu).
