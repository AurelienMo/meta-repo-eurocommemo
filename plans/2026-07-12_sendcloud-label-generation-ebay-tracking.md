# Plan — Génération d'étiquette Sendcloud (v3) et cascade tracking eBay depuis le BO

> Prose en français, identifiants/code en anglais (règle `english.md`).

## Contexte

L'intégration Sendcloud existante (commits récents) couvre : configuration des credentials, association asynchrone de l'ID d'ordre Sendcloud à la commande eBay (`Order::sendcloudOrderId`), et sélection depuis le BO de la méthode d'envoi + point relais (API **v3** : `getShippingOptions`, `getServicePoints`, `updateOrder` PATCH `ship_with`). Aujourd'hui **aucune étiquette n'est générée** et le numéro de suivi eBay est saisi **à la main** dans le BO puis poussé vers eBay via `EbayTradingAPI::completeSell()` (Trading API `CompleteSale`).

Objectif : depuis le BO, pour une commande eBay dont l'ordre Sendcloud est lié et la méthode d'envoi choisie :
1. **Générer l'étiquette** sur Sendcloud (API v3 synchrone `POST /api/v3/orders/create-label-sync`).
2. **Télécharger le PDF** de l'étiquette pour l'imprimer.
3. **Récupérer le numéro de suivi** et **pré-remplir** le champ « N° de suivi » du bouton d'expédition existant, l'humain validant l'envoi vers eBay (cascade `completeSell` inchangée).

Décisions actées avec le demandeur :
- **API étiquette : tout v3** — on annonce l'ordre déjà PATCHé via `create-label-sync` (endpoint synchrone qui renvoie `parcel_id` + `label.file` en PDF base64). Le `tracking_number` n'étant pas dans cette réponse, on le récupère via `GET /api/v2/parcels/{parcel_id}` (v2 et v3 partagent le même Basic auth `public:secret`, déjà en place dans `SendcloudApiClient::request()`).
- **Cascade eBay : pré-remplir + gate humain** — la génération stocke le tracking et pré-remplit `#num-suivi-{id}` ; l'humain clique « Confirmer l'expédition » (flux `admin_delivery_validate` → `completeSell` **inchangé**).
- **Transporteur eBay : sélection manuelle conservée** — aucun mapping carrier Sendcloud→eBay ; le `<select>` provider existant reste.

Sources API Sendcloud vérifiées :
- `POST /api/v3/orders/create-label-sync` → réponse `{ parcel_id, label: { file (base64), mime_type, dpi } }` ; champs requis `integration_id`, `order.order_id`, `label.mime_type`, `label.dpi` — https://sendcloud.dev/docs/orders/ship-an-order
- `integration_id` : Settings > Integrations dans le panel, ou endpoint « retrieve a list of integrations ».
- Tracking : `GET /api/v2/parcels/{id}` → `parcel.tracking_number`, `parcel.tracking_url`, `parcel.carrier.code` — https://support.sendcloud.com/hc/en-us/articles/7789894544276-Sendcloud-APIs-FAQ

**Note résolution d'URL Guzzle** : le client `sendcloud_api` a `base_url = %SENDCLOUD_BASE_URL%/api/v3`, mais `SendcloudApiClient` passe des chemins **absolus** (`/api/v3/...`). En RFC 3986 un chemin absolu ne conserve que l'autorité (host) de la base → l'appel résout bien vers `https://panel.sendcloud.sc/api/v3/...`. **Le même mécanisme rend `/api/v2/...` valide sans nouveau client** : `https://panel.sendcloud.sc/api/v2/...`. (Le « double préfixe » soupçonné n'existe donc pas.)

---

## Fichiers concernés

Tous dans le repo `src-eurocommemo` (monté sous `/Users/aurelienmorvan/OrbStack/docker/volumes/src-eurocommemo`).

### Nouveaux

#### `src/Service/Sendcloud/SendcloudLabelService.php`
Orchestrateur métier : génère l'étiquette, persiste le PDF sur disque (comme les factures), récupère le tracking, met à jour l'`Order`. Ne flushe pas (le contrôleur flushe, cohérent avec `SendcloudOrderShippingService`).

```php
<?php

namespace App\Service\Sendcloud;

use App\Entity\Order;
use App\Exceptions\ExternalSendcloudApiException;

class SendcloudLabelService
{
    public function __construct(
        private readonly SendcloudApiClient $apiClient,
        private readonly SendcloudConfigurationService $configurationService,
        private readonly string $projectDir, // bind %kernel.project_dir%
    ) {
    }

    /**
     * Generate the Sendcloud label for an already-linked eBay order, store the PDF
     * on disk and hydrate tracking data on the Order. Caller is responsible for flush().
     *
     * @throws ExternalSendcloudApiException
     * @throws \InvalidArgumentException  when the order is not ready (no Sendcloud id / no shipping option)
     */
    public function generateLabel(Order $order): void
    {
        $sendcloudOrderId = $order->getSendcloudOrderId();
        if (in_array($sendcloudOrderId, [null, '0'], true)) {
            throw new \InvalidArgumentException("Commande non liée à Sendcloud.");
        }
        if (null === $order->getSendcloudShippingOptionCode()) {
            throw new \InvalidArgumentException("Aucune méthode d'envoi Sendcloud sélectionnée.");
        }

        $integrationId = $this->configurationService->getConfiguration()->getIntegrationId();
        if (null === $integrationId) {
            throw new \InvalidArgumentException("integration_id Sendcloud non configuré.");
        }

        // 1. v3 synchronous label creation (external order_id = eBay order id)
        $result   = $this->apiClient->createLabelSync((string) $order->getOrderIdEbay(), $integrationId);
        $parcelId = (int) ($result['parcel_id'] ?? 0);
        $base64   = $result['label']['file'] ?? null;
        if (0 === $parcelId || null === $base64) {
            throw new ExternalSendcloudApiException('Réponse Sendcloud create-label-sync invalide.');
        }

        // 2. persist PDF on disk (mirrors invoice-preparation pattern)
        file_put_contents($this->labelPath($order), base64_decode($base64));

        // 3. retrieve tracking data (v2 parcel)
        $parcel = $this->apiClient->getParcel($parcelId);

        $order->setSendcloudParcelId((string) $parcelId)
            ->setSendcloudTrackingNumber($parcel['tracking_number'] ?? null)
            ->setSendcloudTrackingUrl($parcel['tracking_url'] ?? null)
            ->setSendcloudLabelGeneratedAt(new \DateTime());
    }

    /** Absolute path of the stored label PDF for this order. */
    public function labelPath(Order $order): string
    {
        return $this->projectDir.'/pdf/sendcloud-label-'.$order->getId().'.pdf';
    }
}
```

> `$projectDir` : bind dans `config/services.yaml` (bloc `_defaults` / `bind`) `string $projectDir: '%kernel.project_dir%'`, ou injecter via `#[Autowire('%kernel.project_dir%')]`. Vérifier le style déjà présent dans `services.yaml` avant de choisir.

#### `migrations/Version20260712120000.php`
Ajoute les colonnes tracking/label sur `orders` et `integration_id` sur `sendcloud_configuration`.

```php
<?php

declare(strict_types=1);

namespace DoctrineMigrations;

use Doctrine\DBAL\Schema\Schema;
use Doctrine\Migrations\AbstractMigration;

final class Version20260712120000 extends AbstractMigration
{
    public function getDescription(): string
    {
        return 'Add Sendcloud label/tracking columns to orders and integration_id to sendcloud_configuration';
    }

    public function up(Schema $schema): void
    {
        $this->addSql('ALTER TABLE orders
            ADD sendcloud_parcel_id VARCHAR(255) DEFAULT NULL,
            ADD sendcloud_tracking_number VARCHAR(255) DEFAULT NULL,
            ADD sendcloud_tracking_url VARCHAR(255) DEFAULT NULL,
            ADD sendcloud_label_generated_at DATETIME DEFAULT NULL');
        $this->addSql('ALTER TABLE sendcloud_configuration
            ADD integration_id INT DEFAULT NULL');
    }

    public function down(Schema $schema): void
    {
        $this->addSql('ALTER TABLE orders
            DROP sendcloud_parcel_id,
            DROP sendcloud_tracking_number,
            DROP sendcloud_tracking_url,
            DROP sendcloud_label_generated_at');
        $this->addSql('ALTER TABLE sendcloud_configuration DROP integration_id');
    }
}
```
> Nom de fichier à générer via `make:migration` idéalement ; le SQL ci-dessus est la référence. Confirmer que le driver est MySQL (syntaxe `ADD ... , ADD ...` déjà utilisée dans `Version20260712000000.php`).

### Modifiés

#### `src/Entity/Order.php` (après la ligne 113, dans le même bloc que les champs `sendcloud*`)
Ajouter 4 champs typés + getters/setters fluent (style des voisins `sendcloud*`, cf. l.450-492) :

```php
#[ORM\Column(type: 'string', length: 255, nullable: true)]
private ?string $sendcloudParcelId = null;
#[ORM\Column(type: 'string', length: 255, nullable: true)]
private ?string $sendcloudTrackingNumber = null;
#[ORM\Column(type: 'string', length: 255, nullable: true)]
private ?string $sendcloudTrackingUrl = null;
#[ORM\Column(type: 'datetime', nullable: true)]
private ?\DateTime $sendcloudLabelGeneratedAt = null;
```
Getters/setters (retour `self`/`Order` comme les setters `sendcloud*` existants) :
```php
public function getSendcloudParcelId(): ?string { return $this->sendcloudParcelId; }
public function setSendcloudParcelId(?string $v): self { $this->sendcloudParcelId = $v; return $this; }
public function getSendcloudTrackingNumber(): ?string { return $this->sendcloudTrackingNumber; }
public function setSendcloudTrackingNumber(?string $v): self { $this->sendcloudTrackingNumber = $v; return $this; }
public function getSendcloudTrackingUrl(): ?string { return $this->sendcloudTrackingUrl; }
public function setSendcloudTrackingUrl(?string $v): self { $this->sendcloudTrackingUrl = $v; return $this; }
public function getSendcloudLabelGeneratedAt(): ?\DateTime { return $this->sendcloudLabelGeneratedAt; }
public function setSendcloudLabelGeneratedAt(?\DateTime $v): self { $this->sendcloudLabelGeneratedAt = $v; return $this; }
```

#### `src/Entity/Sendcloud/SendcloudConfiguration.php`
Ajouter le champ `integrationId` (après `secretKey`, l.26) + getter/setter, dans le style existant :
```php
/** Sendcloud integration id used by the v3 label endpoint. */
#[ORM\Column(type: 'integer', nullable: true)]
private ?int $integrationId = null;

public function getIntegrationId(): ?int { return $this->integrationId; }
public function setIntegrationId(?int $integrationId): self { $this->integrationId = $integrationId; return $this; }
```
> `isConfigured()` (l.81) reste inchangé (integration_id optionnel pour les autres appels ; sa présence est vérifiée dans `SendcloudLabelService`).

#### `src/Form/Sendcloud/SendcloudConfigurationFormType.php`
Ajouter un champ `integrationId` (Symfony `IntegerType`, `required: false`, label « ID d'intégration Sendcloud ») aligné sur les champs `publicKey`/`secretKey` existants, pour le rendre saisissable dans l'écran de config (`SendcloudConfigurationController::index`). *(Fichier non lu en détail — reproduire le style des champs voisins.)*

#### `src/Service/Sendcloud/SendcloudApiClient.php`
Ajouter les constantes v2 et deux méthodes publiques. La méthode privée `request()` (l.180) est réutilisée telle quelle (Basic auth + gestion d'erreurs).

Constantes (après l.19) :
```php
private const PREFIX_URL_V2       = "/api/v2";
private const ENDPOINT_CREATE_LABEL_SYNC = '/orders/create-label-sync';
private const ENDPOINT_PARCELS    = '/parcels';
```

Méthodes (à ajouter avant `request()`) :
```php
/**
 * v3 synchronous label creation. Announces the (already ship_with-configured) order
 * and returns the decoded payload: ['parcel_id' => int, 'label' => ['file' => base64, ...]].
 *
 * @throws ExternalSendcloudApiException
 */
public function createLabelSync(string $externalOrderId, int $integrationId): array
{
    $body = [
        'integration_id' => $integrationId,
        'order'          => ['order_id' => $externalOrderId],
        'label'          => ['mime_type' => 'application/pdf', 'dpi' => 72],
    ];

    $response = $this->request('POST', self::PREFIX_URL.self::ENDPOINT_CREATE_LABEL_SYNC, [
        'json'        => $body,
        'http_errors' => false,
    ]);

    return json_decode($response->getBody()->getContents(), true) ?? [];
}

/**
 * v2 parcel retrieval — used to read tracking_number / tracking_url / carrier.code
 * after the v3 label has been created (create-label-sync does not return tracking).
 *
 * @return array  the `parcel` node
 * @throws ExternalSendcloudApiException
 */
public function getParcel(int $parcelId): array
{
    $response = $this->request('GET', self::PREFIX_URL_V2.self::ENDPOINT_PARCELS.'/'.$parcelId, [
        'http_errors' => false,
    ]);
    $decoded = json_decode($response->getBody()->getContents(), true) ?? [];

    return $decoded['parcel'] ?? [];
}
```
> Le PDF est stocké depuis la réponse base64 de `create-label-sync` (pas d'appel binaire nécessaire). Un helper `downloadLabelPdf(int $parcelId)` (GET `/api/v2/labels/normal_printer/{id}` → body brut) est **optionnel** ; il ne sert qu'à re-télécharger sans régénérer si le fichier disque a disparu (voir action `downloadSendcloudLabel`). À n'ajouter que si l'on veut ce filet de secours.

#### `src/Controller/Admin/OrderCrudController.php`
1. Injecter `SendcloudLabelService $labelService` dans le constructeur (l.52-62), à côté des services Sendcloud existants.
2. Ajouter deux routes (à placer près des routes `sendcloud/*`, l.430-524) :

```php
#[Route('/admin/order/{id}/sendcloud/generate-label', name: 'app_admin_order_sendcloud_generate_label', methods: ['POST'])]
public function sendcloudGenerateLabel(Order $order, Request $request): JsonResponse
{
    if (!$this->isCsrfTokenValid('sendcloud_label_' . $order->getId(), (string) $request->request->get('_csrf_token'))) {
        return new JsonResponse(['state' => 0, 'message' => 'Token CSRF invalide.']);
    }
    if (!$order->getIsEbay()
        || $order->getStatePayment() !== GlobalConstants::CONST_STATE_PAYMENT_VALID
        || null !== $order->getDateExpedition()
        || in_array($order->getSendcloudOrderId(), [null, '0'], true)) {
        return new JsonResponse(['state' => 0, 'message' => "Action indisponible pour cette commande."]);
    }

    try {
        $this->labelService->generateLabel($order);
        $this->em->flush();
    } catch (ExternalSendcloudApiException $e) {
        $this->logger->warning('Sendcloud label generation failed', [
            'orderId' => $order->getId(), 'error' => $e->getMessage(),
        ]);
        return new JsonResponse(['state' => 0, 'message' => 'Erreur API Sendcloud : ' . $e->getMessage()]);
    } catch (\InvalidArgumentException $e) {
        return new JsonResponse(['state' => 0, 'message' => $e->getMessage()]);
    }

    return new JsonResponse([
        'state'          => 1,
        'trackingNumber' => $order->getSendcloudTrackingNumber(),
        'downloadUrl'    => $this->generateUrl('app_admin_order_sendcloud_label_pdf', ['id' => $order->getId()]),
    ]);
}

#[Route('/admin/order/{id}/sendcloud/label', name: 'app_admin_order_sendcloud_label_pdf', methods: ['GET'])]
public function downloadSendcloudLabel(Order $order): BinaryFileResponse
{
    $path = $this->labelService->labelPath($order);
    if (!file_exists($path)) {
        // Filet de secours optionnel : refetch via labelService->refetchLabel($order) si parcelId présent.
        throw $this->createNotFoundException("Étiquette introuvable.");
    }

    return new BinaryFileResponse($path, 200, ['Content-Type' => 'application/pdf']);
}
```
> Le pattern `BinaryFileResponse(..., ['Content-Type' => 'application/pdf'])` copie `orderPreparationPdf` (l.531-544). `generateUrl` est fourni par `AbstractCrudController`.

3. **Ajouter le champ d'affichage** dans `configureFields` : le template `order_sendcloud_action.html.twig` est déjà branché sur la vue « delivery » (l.290). On enrichit ce template existant (ci-dessous), donc **pas de nouveau champ** à déclarer.

#### `templates/admin/order/order_sendcloud_action.html.twig`
Après le bloc « Enregistrer sur Sendcloud » existant (avant le `{% endif %}` de fin, l.33), ajouter le bloc génération/téléchargement, gated sur la présence d'une méthode d'envoi :

```twig
{% if entity.instance.sendcloudShippingOptionCode is not null %}
    <div class="sendcloud-label-block mt-2" data-order-id="{{ entity.instance.id }}">
        {% if entity.instance.sendcloudLabelGeneratedAt is null %}
            <button type="button"
                    class="btn btn-outline-success btn-sm btn-sendcloud-generate-label"
                    data-path="{{ path('app_admin_order_sendcloud_generate_label', {id: entity.instance.id}) }}"
                    data-tracking-target="num-suivi-{{ entity.instance.id }}"
                    data-csrf="{{ csrf_token('sendcloud_label_' ~ entity.instance.id) }}">
                <small>Générer l'étiquette</small>
            </button>
        {% else %}
            <a href="{{ path('app_admin_order_sendcloud_label_pdf', {id: entity.instance.id}) }}"
               target="_blank" class="btn btn-outline-secondary btn-sm">
                <small>Télécharger l'étiquette</small>
            </a>
            {% if entity.instance.sendcloudTrackingNumber %}
                <div class="small text-muted mt-1">
                    Suivi : <b>{{ entity.instance.sendcloudTrackingNumber }}</b>
                </div>
            {% endif %}
        {% endif %}
    </div>
{% endif %}
```
> Le bouton porte `data-tracking-target` = l'id de l'input `#num-suivi-{id}` rendu par `order_delivery_action.html.twig` (l.10) dans la même ligne → le JS pré-remplira ce champ après génération (choix « pré-remplir + gate humain »).

#### `assets/back/js/back.js`
Ajouter, dans le même `DOMContentLoaded` que le bloc Sendcloud existant (après l.355), le handler du bouton « Générer l'étiquette » : POST CSRF, puis pré-remplissage du champ suivi + remplacement du bouton par le lien de téléchargement. Style aligné sur le bloc `.btn-sendcloud-apply` (l.328-354, jQuery `$.ajax`).

```javascript
// --- Sendcloud label generation ---
document.querySelectorAll('.btn-sendcloud-generate-label').forEach(function (btn) {
    btn.addEventListener('click', function () {
        const block = btn.closest('.sendcloud-label-block');
        btn.disabled = true;
        $.ajax({
            url: btn.dataset.path,
            type: 'POST',
            dataType: 'json',
            data: { _csrf_token: btn.dataset.csrf },
            success: (data) => {
                if (data.state === 1) {
                    // 1. prefill the eBay tracking input (human still validates shipping)
                    const target = document.getElementById(btn.dataset.trackingTarget);
                    if (target && data.trackingNumber) { target.value = data.trackingNumber; }
                    // 2. swap the button for a download link + tracking line
                    block.innerHTML =
                        '<a href="' + data.downloadUrl + '" target="_blank" class="btn btn-outline-secondary btn-sm">' +
                        '<small>Télécharger l\'étiquette</small></a>' +
                        (data.trackingNumber
                            ? '<div class="small text-muted mt-1">Suivi : <b>' + data.trackingNumber + '</b></div>'
                            : '');
                } else {
                    btn.disabled = false;
                    const el = document.createElement('div');
                    el.className = 'sendcloud-feedback small mt-1 text-danger';
                    el.textContent = data.message || 'Erreur';
                    block.appendChild(el);
                }
            },
            error: () => { btn.disabled = false; console.log('Sendcloud label request failed.'); },
        });
    });
});
```
> Recompiler les assets back après modif (voir Vérification).

---

## Étapes

1. **Migration + entités** — Ajouter les 4 colonnes `sendcloud_*` à `Order` (+ getters/setters) et `integration_id` à `SendcloudConfiguration` (+ getter/setter). Écrire `Version20260712120000.php` et l'appliquer. → couvre `src/Entity/Order.php`, `src/Entity/Sendcloud/SendcloudConfiguration.php`, `migrations/`.
2. **Config integration_id** — Ajouter le champ `integrationId` au `SendcloudConfigurationFormType`, saisir la vraie valeur via l'écran `/admin/sendcloud-configuration`. → `src/Form/Sendcloud/SendcloudConfigurationFormType.php`.
3. **Client API** — Ajouter `createLabelSync()` + `getParcel()` (+ constantes v2) à `SendcloudApiClient`. → `src/Service/Sendcloud/SendcloudApiClient.php`.
4. **Service métier** — Créer `SendcloudLabelService` (génération v3 → PDF disque → tracking v2 → hydratation `Order`). Déclarer le bind `$projectDir` si nécessaire. → `src/Service/Sendcloud/SendcloudLabelService.php`, `config/services.yaml`.
5. **Contrôleur** — Injecter `SendcloudLabelService`, ajouter les routes `app_admin_order_sendcloud_generate_label` (POST, CSRF `sendcloud_label_{id}`) et `app_admin_order_sendcloud_label_pdf` (GET, `BinaryFileResponse`). → `src/Controller/Admin/OrderCrudController.php`.
6. **UI Twig** — Enrichir `order_sendcloud_action.html.twig` : bouton « Générer l'étiquette » (si option d'envoi choisie et pas encore généré) / lien « Télécharger l'étiquette » + n° de suivi (sinon). → `templates/admin/order/order_sendcloud_action.html.twig`.
7. **JS** — Handler `.btn-sendcloud-generate-label` : POST, pré-remplissage `#num-suivi-{id}`, swap bouton→lien. Recompiler les assets. → `assets/back/js/back.js`.
8. **Cascade eBay** — Aucune modification : l'humain vérifie le n° de suivi pré-rempli, choisit le transporteur, clique « Confirmer l'expédition » → `admin_delivery_validate` → `completeSell` (inchangé).
9. **Rafraîchir le graphe** graphify du repo après modif (cf. CLAUDE.md § graphify) et **journaliser** dans `logs/src-eurocommemo.md` (règle action-logging).

---

## Vérification

**Build / statique**
- `scripts/repo_exec.py` (jamais d'appel direct) pour lint/analyse du repo `src-eurocommemo` : `php bin/console lint:twig templates/admin/order/order_sendcloud_action.html.twig`, `php bin/console lint:container`, éventuellement PHPStan si présent.
- Migration : `php bin/console doctrine:migrations:migrate` puis `doctrine:schema:validate` (mapping ↔ DB OK).
- Assets : recompiler le bundle back (`npm run build` / Encore) et vérifier l'absence d'erreur JS console.

**Scénario manuel (BO, commande eBay « prête à expédier »)**
1. Config : renseigner `integration_id` dans `/admin/sendcloud-configuration`.
2. Sur une commande eBay avec `sendcloudOrderId` valide : sélectionner une méthode d'envoi (+ point relais si requis), « Enregistrer sur Sendcloud » (flux existant) → `sendcloudShippingOptionCode` renseigné.
3. Cliquer « Générer l'étiquette » → vérifier : réponse `state:1`, un PDF `pdf/sendcloud-label-{id}.pdf` créé, `Order.sendcloudParcelId` / `sendcloudTrackingNumber` / `sendcloudLabelGeneratedAt` renseignés, le champ « N° de suivi » pré-rempli, le bouton remplacé par « Télécharger l'étiquette ».
4. « Télécharger l'étiquette » → le PDF s'ouvre et est imprimable.
5. Choisir le transporteur, cliquer « Confirmer l'expédition » → `completeSell` pousse le tracking sur eBay ; vérifier `dateExpedition`, `numSuiviLivraison`, et le suivi visible côté eBay.

**Cas d'erreur à couvrir**
- `integration_id` absent / `sendcloudShippingOptionCode` null → message clair, pas d'appel API.
- CSRF invalide → `state:0`.
- Échec API Sendcloud → flash/log `warning`, bouton réactivé, aucune donnée persistée.
- Idempotence : re-cliquer « Générer » n'est plus possible (bouton remplacé) tant que `sendcloudLabelGeneratedAt` est renseigné → évite la création de parcels/étiquettes en double sur Sendcloud.

**Points à confirmer en implémentation** (non bloquants pour le plan) :
- `order.order_id` de `create-label-sync` = bien l'`order_id` externe (eBay) scopé par `integration_id` (cohérent avec le matching `SendcloudOrderLinker`). À valider au premier appel réel.
- Présence effective de `tracking_number` dans `GET /api/v2/parcels/{id}` immédiatement après `create-label-sync` (l'étiquette étant annoncée de façon synchrone, le tracking doit être présent ; sinon prévoir un court retry ou lecture de `shipping_details` sur l'ordre v3).
