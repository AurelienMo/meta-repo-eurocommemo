# Plan — Mention du délai de retrait de 7 jours dans le mail « colis disponible en point relais »

> Repo cible : `src-eurocommemo` · Suite de `plans/2026-08-01_mail-colis-dispo-point-relais.md`
> (implémenté et commité en `c7bbba7` — `feat(sendcloud): notify buyer on relay pickup`).

## Contexte

Le mail « Votre colis est disponible en point relais » est envoyé depuis le webhook Sendcloud
(`WebhookController::webhookSendcloud()` → `NotifyServicePointPickupUseCase` →
`MailService::sendMailServicePointPickup()` → `templates/mail/mail_service_point_pickup.html.twig`)
dès qu'un colis passe en statut `AWAITING_CUSTOMER_PICKUP`.

Il n'indique aujourd'hui **aucune limite de temps** : le client ignore que Chronopost Shop2Shop ne
garde le colis que 7 jours et le renvoie ensuite à l'expéditeur. Le plan précédent avait conclu
qu'« aucun délai de retrait n'est transmis » par Sendcloud — c'est exact, mais le payload transmet
la **date du changement de statut**, ce qui suffit à calculer la date limite côté application.

Le payload de production capturé (`tests/fixtures/sendcloud_parcel_awaiting_pickup.json`) contient :

| Champ | Valeur | Rôle ici |
|---|---|---|
| `parcel.date_updated` | `"29-07-2026 09:15:57"` | Date du passage en « Awaiting customer pickup » → point de départ des 7 jours |
| `parcel.date_announced` | `"26-07-2026 16:21:37"` | Annonce de l'étiquette — **inutilisable** comme point de départ |
| `parcel.date_cancel_before` | `"27-07-2026 17:55:00"` | Annulation de l'étiquette — **sans rapport** avec la rétention en relais |

Format observé sur les cinq champs date du payload : `d-m-Y H:i:s` (forme v2). La forme v3 émettrait
de l'ISO 8601 — le parsing doit donc rester tolérant, sans jamais faire échouer l'envoi.

### Décisions validées avec l'utilisateur

1. **Date limite calculée et affichée** : `date_updated` + 7 jours, rendue au format `dd/mm/YYYY`.
   Si la date est absente ou illisible, on **n'invente pas** de date — le mail bascule sur une
   formulation générique (« pendant 7 jours à compter de la réception de cet email »).
2. **Délai figé à 7 jours** via une constante, pas de table par transporteur : toutes les commandes
   web en point relais passent aujourd'hui par `chronopost:shop2shop` (rétention 7 jours), constaté
   sur les 6 commandes relais en base lors de la session du 2026-07-22.

Périmètre : **ce seul mail**. `mail_delivery.html.twig` (mail d'expédition) n'est pas touché, ni le
sujet du mail, ni la logique de déclenchement, ni l'anti-doublon.

## Fichiers concernés

Repo : `src-eurocommemo` (Symfony 6, PHP 8, Doctrine ORM, EasyAdmin).

### Nouveaux

Aucun.

### Modifiés

#### `src/Dto/Sendcloud/SendcloudParcelDTO.php`

Deux getters à insérer après `getStatus()` (`SendcloudParcelDTO.php:50-53`), dans le style des
getters voisins (tolérance aux clés absentes, jamais d'exception). `getPickupDeadline()` est une
dérivation, au même titre que `getServicePointFullAddress()` déjà présent.

```php
/**
 * Sendcloud date format on the v2 webhook shape, observed on every date field of a real payload:
 * "29-07-2026 09:15:57". The v3 shape would emit ISO 8601, hence the generic second attempt.
 */
private const DATE_FORMAT = 'd-m-Y H:i:s';

/**
 * When the parcel last changed status — for an AWAITING_CUSTOMER_PICKUP notification, this is the
 * moment the parcel became available at the pickup point.
 *
 * Returns null rather than throwing when the key is missing or the value unparsable: this feeds a
 * customer email that must go out even without a date.
 */
public function getStatusUpdatedAt(): ?\DateTimeImmutable
{
    $value = $this->nonEmpty($this->payload['date_updated'] ?? null);

    if (null === $value) {
        return null;
    }

    $date = \DateTimeImmutable::createFromFormat(self::DATE_FORMAT, $value);

    if ($date instanceof \DateTimeImmutable) {
        return $date;
    }

    try {
        return new \DateTimeImmutable($value);
    } catch (\Exception) {
        return null;
    }
}

/**
 * Last day the parcel can be collected before the carrier returns it to the sender:
 * status change date + the carrier retention period. Null when the payload carries no usable date —
 * the email then falls back to a wording without an explicit date.
 */
public function getPickupDeadline(int $retentionDays): ?\DateTimeImmutable
{
    return $this->getStatusUpdatedAt()?->modify(sprintf('+%d days', $retentionDays));
}
```

Note : `createFromFormat` accepte une chaîne partiellement conforme (ex. `29-07-2026`) en complétant
les composantes manquantes avec l'heure courante ; c'est sans incidence ici, seule la date est
affichée. Le fuseau appliqué est celui par défaut de l'application, cohérent avec le filtre Twig
`|date` utilisé au rendu.

#### `src/Service/MailService.php`

`sendMailServicePointPickup()` (`MailService.php:192-217`) : ajouter la constante de rétention et
deux variables de template. Le corps de la méthode, le sujet et la gestion d'erreur restent
inchangés.

Constante à déclarer en tête de classe, avec les autres constantes de la classe :

```php
/**
 * Days a parcel stays available at the pickup point before the carrier returns it to the sender.
 * Chronopost Shop2Shop — the only relay option used by web orders today — retains parcels 7 days.
 */
public const PICKUP_RETENTION_DAYS = 7;
```

Bloc `render()` (`MailService.php:203-207`), avant/après :

```php
// avant
->html($this->templating->render('mail/mail_service_point_pickup.html.twig', [
    'order'        => $order,
    'parcel'       => $parcel,
    'absolute_url' => $this->params->get('absolute_url'),
]))

// après
->html($this->templating->render('mail/mail_service_point_pickup.html.twig', [
    'order'                  => $order,
    'parcel'                 => $parcel,
    'absolute_url'           => $this->params->get('absolute_url'),
    'pickup_retention_days'  => self::PICKUP_RETENTION_DAYS,
    'pickup_deadline'        => $parcel->getPickupDeadline(self::PICKUP_RETENTION_DAYS),
]))
```

#### `templates/mail/mail_service_point_pickup.html.twig`

Insérer le bloc de délai **entre** le bouton de suivi (`mail_service_point_pickup.html.twig:39-46`)
et la mention « Pensez à vous munir d'une pièce d'identité » (lignes 48-50) : le client lit d'abord
où est son colis, puis jusqu'à quand, puis quoi emporter.

Bloc exact à insérer :

```twig
                <div class="mt-4" style="font-size: 13px !important;">
                    {% if pickup_deadline %}
                        Votre colis reste disponible pendant {{ pickup_retention_days }} jours,
                        <b>jusqu'au {{ pickup_deadline|date('d/m/Y') }} inclus</b>.
                    {% else %}
                        Votre colis reste disponible pendant <b>{{ pickup_retention_days }} jours</b>
                        à compter de la réception de cet email.
                    {% endif %}
                    Passé ce délai, il sera automatiquement renvoyé à l'expéditeur.
                </div>
```

Résultat sur le payload de production (`date_updated` = 29-07-2026) :
« Votre colis reste disponible pendant 7 jours, **jusqu'au 05/08/2026 inclus**. Passé ce délai, il
sera automatiquement renvoyé à l'expéditeur. »

Les deux variables sont toujours passées par `MailService`, y compris `pickup_deadline` à `null` —
aucun risque de variable indéfinie sous `strict_variables` (activé dans l'environnement `test`,
`config/packages/twig.yaml:16`).

#### `tests/Dto/Sendcloud/SendcloudParcelDTOTest.php`

Ajouter quatre tests, dans le style existant (`PHPUnit\Framework\TestCase`, helper privé
`productionParcel()` qui charge `tests/fixtures/sendcloud_parcel_awaiting_pickup.json`) :

```php
public function testReadsStatusUpdatedAtFromProductionPayload(): void
{
    self::assertSame(
        '2026-07-29 09:15:57',
        $this->productionParcel()->getStatusUpdatedAt()?->format('Y-m-d H:i:s')
    );
}

public function testComputesPickupDeadlineFromStatusDate(): void
{
    self::assertSame(
        '05/08/2026',
        $this->productionParcel()->getPickupDeadline(7)?->format('d/m/Y')
    );
}

public function testPickupDeadlineIsNullWhenDateIsMissingOrUnparsable(): void
{
    self::assertNull((new SendcloudParcelDTO([]))->getPickupDeadline(7));
    self::assertNull((new SendcloudParcelDTO(['date_updated' => '   ']))->getPickupDeadline(7));
    self::assertNull((new SendcloudParcelDTO(['date_updated' => 'not a date']))->getPickupDeadline(7));
}

public function testReadsIsoDateFromV3Shape(): void
{
    $parcel = new SendcloudParcelDTO(['date_updated' => '2026-07-29T09:15:57+02:00']);

    self::assertSame('2026-07-29', $parcel->getStatusUpdatedAt()?->format('Y-m-d'));
}
```

### Non modifiés (vérifié)

- `src/Service/Sendcloud/UseCase/NotifyServicePointPickupUseCase.php` — il passe déjà le DTO complet
  à `MailService` ; aucune signature ne change, ses 7 tests restent verts.
- `src/Controller/WebhookController.php` — `new SendcloudParcelDTO($parcel)`
  (`WebhookController.php:108`) porte déjà le bloc `parcel` entier, `date_updated` compris.
- `src/Entity/Order.php`, `migrations/` — aucune donnée nouvelle à persister : la date limite est
  dérivée du payload au moment de l'envoi, jamais stockée.
- `templates/mail/mail_delivery.html.twig` — mail d'expédition, hors périmètre.
- `MailService::sendMailServicePointPickup()` sujet et destinataire — inchangés.

## Étapes

1. **DTO** — ajouter `DATE_FORMAT`, `getStatusUpdatedAt()` et `getPickupDeadline()` dans
   `src/Dto/Sendcloud/SendcloudParcelDTO.php`, puis les quatre tests dans
   `tests/Dto/Sendcloud/SendcloudParcelDTOTest.php`. Vérifiable isolément, sans base ni HTTP.

2. **Service mail** — déclarer `MailService::PICKUP_RETENTION_DAYS` et enrichir le tableau de
   variables du `render()` de `sendMailServicePointPickup()`.

3. **Template** — insérer le bloc de délai dans `templates/mail/mail_service_point_pickup.html.twig`
   entre le bouton de suivi et la mention pièce d'identité.

4. **Recette locale** — rejouer le payload de production en curl et contrôler le rendu du mail
   (date attendue `05/08/2026`), puis le même payload sans `date_updated` pour la formulation de
   repli (voir Vérification).

5. **Journalisation** — ajouter l'entrée dans `logs/src-eurocommemo.md` au format imposé par
   `.claude/rules/action-logging.md`.

## Vérification

Toutes les commandes passent par `scripts/repo_exec.py` (repo en `compose`, service `php-fpm-per83`,
workdir `/var/www/eurocommemo`) — jamais d'appel direct à `php`/`composer`.

### Tests et lint

```sh
scripts/repo_exec.py src-eurocommemo -- php bin/phpunit tests/Dto/Sendcloud/SendcloudParcelDTOTest.php
scripts/repo_exec.py src-eurocommemo -- php bin/phpunit
scripts/repo_exec.py src-eurocommemo -- php bin/console lint:twig templates/mail/mail_service_point_pickup.html.twig
scripts/repo_exec.py src-eurocommemo -- php -l src/Dto/Sendcloud/SendcloudParcelDTO.php
scripts/repo_exec.py src-eurocommemo -- php -l src/Service/MailService.php
```

Attendu : suite complète verte (49 tests actuellement → 53 après ajout), `lint:twig` OK.

### Scénario manuel — date limite affichée

Sur une commande web éligible dont `sendcloud_pickup_notified_at` est `NULL` (remettre la colonne à
`NULL` avant chaque rejeu, le use case étant idempotent) :

```sh
curl -s -o /dev/null -w '%{http_code}\n' -X POST \
  'https://eurocommemo.orb.local/fr/sendcloud/notification' \
  -H 'Content-Type: application/json' \
  --data-binary @tests/fixtures/sendcloud_parcel_awaiting_pickup.json
```

Attendu : `200`, et dans le catcher local un mail contenant
« disponible pendant 7 jours, jusqu'au **05/08/2026** inclus. Passé ce délai, il sera automatiquement
renvoyé à l'expéditeur. », le reste du mail (relais, adresse, transporteur, suivi) inchangé.

### Scénario manuel — repli sans date

Rejouer le même payload en **retirant** la clé `parcel.date_updated`, sur une autre commande
éligible. Attendu : `200`, mail envoyé, phrase « disponible pendant **7 jours** à compter de la
réception de cet email. Passé ce délai, il sera automatiquement renvoyé à l'expéditeur. » — aucune
date affichée, aucune erreur en log.

### Scénario manuel — forme v3

Rejouer avec `"date_updated": "2026-07-29T09:15:57+02:00"`. Attendu : même rendu que le scénario
nominal (`05/08/2026`), ce qui valide le chemin de parsing ISO 8601.

### Non-régression

- Les 7 tests de `NotifyServicePointPickupUseCaseTest` restent verts sans modification : la
  signature de `sendMailServicePointPickup()` ne change pas.
- Anti-doublon inchangé : rejouer un payload sur une commande déjà tamponnée ne produit toujours
  aucun mail.
