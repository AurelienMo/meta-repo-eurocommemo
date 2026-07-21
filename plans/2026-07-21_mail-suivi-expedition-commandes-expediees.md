# Plan — Action admin « Envoyer le mail de suivi d'expédition » sur la liste de toutes les commandes

## Contexte

Le mail de confirmation d'expédition (`mail/mail_delivery.html.twig`) n'est envoyé **qu'une seule
fois, automatiquement**, depuis `OrderListener::onFlush()`
(`src/EventListener/OrderListener.php:47-58`) : au moment où `numSuiviLivraison` change, pour une
commande non-eBay. Si l'envoi échoue (transport indisponible, template en erreur, adresse invalide au
moment T) ou si l'acheteur réclame l'information, **aucun moyen de le renvoyer** depuis le back-office.

Objectif : exposer une **action EasyAdmin par ligne** sur la vue « toutes les commandes »
(`OrderCrudController`, vue sans query param `state`, titre « Listing des commandes ») permettant
d'envoyer le mail de suivi d'expédition à l'acheteur pour toute commande au statut **« Expédiée »**.

Décisions de cadrage validées :

- **Périmètre** : commandes **web uniquement** (`isEbay` faux) — même règle que le déclenchement
  automatique existant. Les commandes eBay sont exclues (l'email acheteur est souvent masqué par eBay :
  `ImportBuyerDTO::fromFulfillmentOrder` applique `maskedToNull`, `src/Service/Ebay/DTO/Input/ImportBuyerDTO.php:56`).
- **Pas de traçabilité en base** : aucune colonne `…MailSentAt`, **aucune migration Doctrine**. L'action
  reste disponible en permanence sur une commande expédiée ; un `confirm()` JS protège du clic accidentel.
- **Correction du template hors périmètre** (voir le risque ci-dessous).

Définition retenue de « statut expédiée » — celle déjà implémentée deux fois dans le code, et reprise à
l'identique (restreinte au cas web) :

- `templates/admin/order/order_state.html.twig:20` (badge « Expédiée »)
- `src/Filter/OrderShippingStatusFilter.php:85-91` (`STATUS_SHIPPED`)

soit : `statePayment === CONST_STATE_PAYMENT_VALID` **et** `delivery !== null` **et**
`dateExpedition !== null`.

### Risque connu, hors périmètre de ce plan

`templates/mail/mail_delivery.html.twig:19` contient une erreur de syntaxe Twig — une parenthèse
fermante en trop :

```twig
{% if order.sendcloudServicePointId is null) %}
```

Twig lève une `SyntaxError` au rendu. Aujourd'hui `MailService::sendMailExpeditionOrder()` l'avale dans
son `catch (Exception $e)` et la journalise en `critical` : **le mail d'expédition n'est donc plus envoyé
du tout**, silencieusement. Ce plan **ne corrige pas** ce bug (décision utilisateur), mais rend l'échec
**visible** : `sendMailExpeditionOrder()` renverra désormais un booléen, et la nouvelle action affichera
un flash `danger` au lieu d'un faux succès. Tant que le template n'est pas corrigé (ticket séparé),
l'action remontera systématiquement un échec — c'est le comportement attendu et le critère de
vérification ci-dessous en tient compte.

**Repo cible** : `src-eurocommemo` (Symfony 6 + EasyAdmin 4), racine
`/Users/aurelienmorvan/OrbStack/docker/volumes/src-eurocommemo`.

**Modèle imposé** : l'action existante `resolveSendcloudTracking`
(`src/Controller/Admin/OrderCrudController.php:203-232` pour la déclaration, `437-483` pour la méthode) —
action `linkToUrl` en GET avec `_csrf_token` en query param, `displayIf`, méthode CRUD qui garde le CSRF,
garde le métier, `addFlash()` puis `redirect($context->getReferrer())`.

---

## Fichiers concernés

Aucun fichier nouveau. Aucune migration. Aucun asset JS/CSS à recompiler (une action EasyAdmin se rend
automatiquement dans la colonne « Actions » de l'index).

### Modifiés

#### 1. `src/Service/MailService.php`

`sendMailExpeditionOrder()` (lignes 150-168) retourne aujourd'hui `void` et échoue en silence dans deux
cas : email invalide (garde `filter_var`) et exception de rendu/transport. Pour qu'une action admin
puisse rendre compte à l'opérateur, la méthode doit renvoyer le résultat de l'envoi.

**Avant** (lignes 150-168) :

```php
    /**
     * @throws TransportExceptionInterface
     */
    public function sendMailExpeditionOrder(Order $order): void
    {
        if(filter_var($order->getUser()->getEmail(),FILTER_VALIDATE_EMAIL)) {
            try {
                $message = (new Email())
                    ->subject((($this->requestStack->getCurrentRequest()) ? $this->requestStack->getCurrentRequest()->attributes->get("seo")->getTitle() : "").' - Confirmation d\'expédition de votre commande')
                    ->from(new Address($this->params->get('mailer_from'), ($this->requestStack->getCurrentRequest()) ? $this->requestStack->getCurrentRequest()->attributes->get("seo")->getTitle() : ""))
                    ->to(new Address($order->getUser()->getEmail()))
                    ->html($this->templating->render('mail/mail_delivery.html.twig', ['order' => $order, 'absolute_url' => $this->params->get('absolute_url')]))
                ;
                $this->mailer->send($message);
            } catch (Exception $e) {
                $this->logger->critical("Erreur lors de l'envoie de l'email : ".$e->getMessage());
            }
        }
    }
```

**Après** — même corps, signature `bool`, retours explicites :

```php
    /**
     * Send the shipment confirmation email to the buyer.
     *
     * @return bool true when the email was handed over to the transport, false when the buyer has no
     *              valid email address or when rendering/sending failed (error is logged).
     */
    public function sendMailExpeditionOrder(Order $order): bool
    {
        if(!filter_var($order->getUser()->getEmail(),FILTER_VALIDATE_EMAIL)) {
            return false;
        }

        try {
            $message = (new Email())
                ->subject((($this->requestStack->getCurrentRequest()) ? $this->requestStack->getCurrentRequest()->attributes->get("seo")->getTitle() : "").' - Confirmation d\'expédition de votre commande')
                ->from(new Address($this->params->get('mailer_from'), ($this->requestStack->getCurrentRequest()) ? $this->requestStack->getCurrentRequest()->attributes->get("seo")->getTitle() : ""))
                ->to(new Address($order->getUser()->getEmail()))
                ->html($this->templating->render('mail/mail_delivery.html.twig', ['order' => $order, 'absolute_url' => $this->params->get('absolute_url')]))
            ;
            $this->mailer->send($message);
        } catch (Exception $e) {
            $this->logger->critical("Erreur lors de l'envoie de l'email : ".$e->getMessage());

            return false;
        }

        return true;
    }
```

Notes :
- L'annotation `@throws TransportExceptionInterface` est supprimée : le `catch (Exception)` la capture
  déjà, elle était trompeuse.
- **Rétro-compatibilité** : le seul appelant existant est `OrderListener.php:57`, qui ignore la valeur de
  retour — comportement inchangé côté flux automatique.
- L'attribut de requête `seo` est disponible en contexte admin :
  `ConfigurationListener` est tagué `kernel.event_listener` sur `kernel.request` **sans restriction de
  chemin** (`config/services.yaml:41-43`) et pose `attributes->set('seo', $seo)`
  (`src/EventListener/ConfigurationListener.php:50`).

#### 2. `src/Controller/Admin/OrderCrudController.php`

Trois modifications : injection du service, déclaration de l'action, méthode CRUD cible.

**(a) Import + constructeur** (imports lignes 4-57, constructeur lignes 60-74)

Ajouter l'import à côté des `use App\Service\…` existants (après `use App\Service\GenerateAndConcatePdfInvoiceUseCase;`, ligne 13) :

```php
use App\Service\MailService;
```

et la dépendance en fin de constructeur :

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
        private readonly LoggerInterface $logger,
        private readonly MessageBusInterface $messageBus,
        private readonly OrderRepository $orderRepository,
        private readonly MailService $mailService,
    ) {
    }
```

Autowiring standard (`config/services.yaml`, `App\:` charge `../src/`) — aucune déclaration explicite.

**(b) Déclaration de l'action** — dans `configureActions()`, à insérer **après** le bloc
`$backfillTrackingAll` (qui se termine ligne 250) et **avant** `$batchPrintPdfTodayGlobal` (ligne 252).
Miroir strict de `$resolveSendcloudTracking` (lignes 203-232), plus le `setHtmlAttributes(['onclick' => …])`
de `$backfillTrackingAll` (lignes 247-249). Le libellé du `confirm()` est volontairement **sans
apostrophe** pour ne pas casser le littéral JS (comme le fait déjà `$backfillTrackingAll`).

```php
        $sendShippingMail = Action::new('sendShippingMail', "Envoyer le mail de suivi")
            ->setIcon('fa fa-envelope')
            ->linkToUrl(function (Order $entity) {
                $token = $this->csrfTokenManager
                    ->getToken('shipping_mail_' . $entity->getId())
                    ->getValue();

                return $this->adminUrlGenerator
                    ->setController(self::class)
                    ->setAction('sendShippingMail')
                    ->setEntityId($entity->getId())
                    ->set('_csrf_token', $token)
                    ->includeReferrer()
                    ->generateUrl();
            })
            ->addCssClass('text-primary')
            ->setHtmlAttributes([
                'onclick' => "return confirm('Envoyer le mail de suivi expedition au client ?')",
            ])
            ->displayIf(static function (Order $entity) {
                return true !== $entity->getIsEbay()
                    && GlobalConstants::CONST_STATE_PAYMENT_VALID === $entity->getStatePayment()
                    && null !== $entity->getDelivery()
                    && null !== $entity->getDateExpedition();
            })
        ;
```

> `getIsEbay()` renvoie `?bool` (`Order.php:414`, colonne nullable) : `true !== …` couvre à la fois
> `false` et `null`, contrairement à `!$entity->getIsEbay()` qui serait équivalent ici mais moins
> explicite sur le tri-état.

**(c) Enregistrement dans le retour de `configureActions()`** (lignes 257-271) — ajouter l'action à la
page index et au `reorder` :

```php
        return $actions
            ->disable(Action::NEW)
            ->disable(Action::DELETE)
            ->add(Crud::PAGE_INDEX, $cancelOrder)
            ->add(Crud::PAGE_INDEX, $syncSendcloud)
            ->add(Crud::PAGE_INDEX, $resolveSendcloudTracking)
            ->add(Crud::PAGE_INDEX, $sendShippingMail)
            ->add(Crud::PAGE_INDEX, $backfillTrackingAll)
            ->addBatchAction($batchPrintPdfTodayGlobal)
            ->update(Crud::PAGE_INDEX, Action::EDIT, function (Action $action) {
                return $action->displayIf(function(Order $order) {
                    return $order->getStatePayment() !== GlobalConstants::CONST_STATE_PAYMENT_CANCEL;
                });
            })
            ->reorder(Crud::PAGE_INDEX, [Action::EDIT, 'cancelOrder', 'syncSendcloud', 'resolveSendcloudTracking', 'sendShippingMail'])
        ;
```

**(d) Méthode CRUD** — à insérer **après** `resolveSendcloudTracking()` (qui se termine ligne 483) et
**avant** `backfillTrackingAll()` (ligne 485). Structure calquée sur `resolveSendcloudTracking()` :
garde CSRF, garde métier (re-vérification serveur des conditions du `displayIf`, contre une URL forgée),
flash + redirection referrer.

```php
    public function sendShippingMail(AdminContext $context): RedirectResponse
    {
        /** @var Order $order */
        $order = $context->getEntity()->getInstance();
        $request = $this->requestStack->getCurrentRequest();

        if (!$this->isCsrfTokenValid('shipping_mail_' . $order->getId(), $request->query->get('_csrf_token'))) {
            $this->addFlash('danger', 'Token CSRF invalide.');

            return $this->redirect($context->getReferrer());
        }

        if (true === $order->getIsEbay()
            || GlobalConstants::CONST_STATE_PAYMENT_VALID !== $order->getStatePayment()
            || null === $order->getDelivery()
            || null === $order->getDateExpedition()) {
            $this->addFlash('danger', "Action indisponible : cette commande n'est pas au statut expédiée.");

            return $this->redirect($context->getReferrer());
        }

        if (!$this->mailService->sendMailExpeditionOrder($order)) {
            $this->logger->warning('Shipping confirmation mail could not be sent from admin', [
                'orderId'   => $order->getId(),
                'reference' => $order->getReference(),
                'email'     => $order->getUser()->getEmail(),
            ]);
            $this->addFlash('danger', sprintf(
                "Échec de l'envoi du mail de suivi pour la commande %s (adresse e-mail invalide ou erreur d'envoi — voir les logs).",
                $order->getReference()
            ));

            return $this->redirect($context->getReferrer());
        }

        $this->addFlash('success', sprintf(
            'Mail de suivi envoyé à %s pour la commande %s.',
            $order->getUser()->getEmail(),
            $order->getReference()
        ));

        return $this->redirect($context->getReferrer());
    }
```

> Aucun `flush()` : l'action ne mute pas l'entité (décision « pas de traçabilité en base »).
> `AdminContext`, `RedirectResponse`, `Order`, `GlobalConstants`, `Action`, `Crud` sont déjà importés
> (lignes 4, 19, 23, 29-31).

#### 3. `logs/src-eurocommemo.md` (meta-repo)

Ajouter une entrée au format imposé par `.claude/rules/action-logging.md` après implémentation
(`## [YYYY-MM-DD HH:MM] src-eurocommemo — …`, `**Target**`, `**Status**`, `**Files affected**`,
`**Notes**` mentionnant le bug Twig laissé ouvert).

---

## Étapes

1. **`MailService`** — Passer `sendMailExpeditionOrder(Order $order)` de `void` à `bool` : inverser la
   garde `filter_var` en early-return `false`, retourner `false` dans le `catch`, `true` en fin de
   méthode ; retirer le `@throws TransportExceptionInterface`. Vérifier que `OrderListener.php:57`
   compile toujours (appel en statement, valeur ignorée).
2. **Contrôleur — injection** — Ajouter `use App\Service\MailService;` et
   `private readonly MailService $mailService,` au constructeur de `OrderCrudController`.
3. **Contrôleur — action** — Déclarer `$sendShippingMail` dans `configureActions()` (`linkToUrl` + CSRF
   `shipping_mail_<id>` + `confirm()` + `displayIf` sur « web & expédiée »), l'ajouter à
   `Crud::PAGE_INDEX` et au `reorder`.
4. **Contrôleur — méthode** — Ajouter `sendShippingMail(AdminContext $context): RedirectResponse` (garde
   CSRF, garde métier, appel `MailService`, flashs `success`/`danger`, log `warning` en cas d'échec).
5. **Vérification** — Dérouler la section ci-dessous (lint conteneur, cache, scénarios manuels).
6. **Log d'action** — Consigner l'intervention dans `logs/src-eurocommemo.md` (règle action-logging), en
   notant explicitement le bug Twig `mail_delivery.html.twig:19` laissé ouvert.

---

## Vérification

Toutes les commandes passent par `scripts/repo_exec.py` (repo en `exec.mode: compose`, service
`php-fpm-per83`) — jamais d'appel direct à `php`/`composer`.

**Statique / build**

- `php bin/console lint:container` → valide l'autowiring de `MailService` dans `OrderCrudController`.
- `php bin/console cache:clear` → purge le cache EasyAdmin (nouvelle action).
- `php bin/console lint:twig templates/` → **doit remonter l'erreur connue** sur
  `templates/mail/mail_delivery.html.twig:19` (`Unexpected token "punctuation" of value ")"`). C'est le
  bug hors périmètre : sa présence confirme le diagnostic, son absence signifie qu'il a été corrigé
  entre-temps.
- `vendor/bin/phpstan analyse src/Service/MailService.php src/Controller/Admin/OrderCrudController.php`
  (si PHPStan est configuré) → typage `bool` et signature de la méthode CRUD.

Aucune recompilation d'assets (`yarn build`) : pas de JS/CSS touché.

**Scénario manuel — cœur de la demande**

1. Ouvrir la liste « Toutes les commandes » (URL admin sans query param `state`, titre « Listing des
   commandes »).
2. Filtrer avec « Statut d'expédition » = **Expédiée** (`OrderShippingStatusFilter`) pour isoler le
   périmètre.
3. Sur une ligne **web** (colonne « N° Commande eBay » vide, badge vert « Expédiée ») : l'action
   **« Envoyer le mail de suivi »** (icône enveloppe) doit apparaître dans la colonne « Actions ».
4. Cliquer → une `confirm()` s'affiche ; annuler ⇒ aucune requête. Confirmer ⇒ retour sur la liste avec :
   - **template corrigé + adresse valide** ⇒ flash `success` « Mail de suivi envoyé à <email> pour la
     commande <référence>. », et le mail est visible dans le profiler Symfony (panneau Mailer) ou dans
     Mailpit/le transport configuré ;
   - **en l'état actuel (template Twig cassé)** ⇒ flash `danger` « Échec de l'envoi du mail de suivi … »
     + une ligne `critical` (`Erreur lors de l'envoie de l'email : Unexpected token …`) et une ligne
     `warning` (`Shipping confirmation mail could not be sent from admin`) dans `var/log/dev.log`.
     **C'est le résultat attendu tant que `mail_delivery.html.twig` n'est pas corrigé.**
5. Vérifier la **non-apparition** de l'action sur : une commande eBay expédiée, une commande
   « En attente d'expédition » / « Prévente » (`dateExpedition` nul), une commande « Annulée », une
   commande « En attente de paiement », et une commande retirée sur place (`delivery` nul,
   `collected = true`).
6. Vérifier que la vue « commandes en attente de livraison » (`?state=…&delivery=1&ready=1`) est
   inchangée — aucune commande n'y est expédiée, l'action n'y apparaît donc jamais.

**Sécurité**

- Rejouer l'URL de l'action en modifiant `_csrf_token` ⇒ flash « Token CSRF invalide. », aucun mail
  envoyé.
- Forger l'URL (token valide) sur une commande **eBay** ou **non expédiée** ⇒ flash « Action
  indisponible : cette commande n'est pas au statut expédiée. », aucun mail envoyé.

**Non-régression du flux automatique**

- Depuis « Commandes en attente de livraison », saisir un n° de suivi et cliquer « Confirmer
  l'expédition de la commande » sur une commande web ⇒ `OrderListener::onFlush` positionne
  `dateExpedition` et appelle `sendMailExpeditionOrder()` comme avant (valeur de retour ignorée, aucune
  exception nouvelle ne remonte dans le flush Doctrine).

**Critères mesurables**

- Aucune migration Doctrine générée (`php bin/console doctrine:schema:validate` inchangé).
- L'action est présente sur 100 % des lignes au statut « Expédiée » non-eBay de la vue « toutes les
  commandes », et sur aucune autre.
- Chaque clic produit exactement un flash (`success` **ou** `danger`) et une redirection vers la liste
  d'origine (referrer préservé, filtres et pagination conservés).
