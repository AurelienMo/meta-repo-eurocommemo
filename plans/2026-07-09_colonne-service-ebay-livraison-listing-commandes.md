# Plan — Colonne « Service eBay sélectionné » sur les listings de commande

## Contexte

Sur les commandes importées depuis eBay, l'acheteur choisit un service de livraison
eBay (ex. « Standard International Shipping ») lors du checkout. Cette information est
déjà stockée sur `Order` via la relation `shippingService` (`App\Entity\Ebay\ShippingService`),
peuplée à l'import (`ImportEbayOrderCommand.php:134`, `ImportFulfillmentOrderUseCase.php:89`) —
à ne pas confondre avec `Order::shippingProvider`, qui est le transporteur choisi par le
back-office au moment de l'expédition.

Actuellement, aucun des écrans de listing de commande de l'admin (`OrderCrudController`,
`Crud::PAGE_INDEX`) n'affiche ce service. Le back-office doit ouvrir chaque commande pour
savoir quel service eBay a été sélectionné, ce qui ralentit la préparation des expéditions
(en particulier sur le listing « commandes en attente de livraison prêtes à être expédiées »,
qui affiche jusqu'à 500 lignes).

Objectif : ajouter une colonne affichant le nom du service eBay sélectionné, avec un tooltip
Bootstrap montrant sa description (`ShippingService::description`), sur tous les écrans de
listing de commande. Si la commande n'est pas une commande eBay (`shippingService` null),
afficher un tiret neutre.

## Fichiers concernés

Repo : `src-eurocommemo`.

### Nouveaux

**`templates/admin/order/order_ebay_shipping_service.html.twig`** — nouveau template de
colonne, sur le modèle de `templates/admin/product/title-ebay-valid.html.twig:25-31` qui
utilise déjà le pattern tooltip Bootstrap de ce projet (`data-bs-toggle="tooltip"`,
`data-bs-placement="top"`, attribut `title`). Ces tooltips sont auto-initialisés par le JS
du bundle EasyAdmin (`vendor/easycorp/easyadmin-bundle/assets/js/app.js:395-399`,
`document.querySelectorAll('[data-bs-toggle="tooltip"]')`) — aucun JS applicatif à ajouter.

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

### Modifiés

**`src/Controller/Admin/OrderCrudController.php`**

1. `configureFields()` (`OrderCrudController.php:207-267`) — insérer la nouvelle colonne
   juste après la colonne « Informations de réception » (`order_delivery.html.twig`), dans
   les deux branches du `if` sur le paramètre `delivery` (lignes 211-220), pour qu'elle
   apparaisse sur les 4 variantes du listing (listing principal, en attente de paiement,
   commandes valides, prêtes à être expédiées) :

   Avant (`OrderCrudController.php:211-220`) :
   ```php
   if ((int)$this->requestStack->getCurrentRequest()->query->get('delivery') === 1 ) {
       $return[] = Field::new('adminObject', "Informations de contact")->setTemplatePath('admin/order/order_contact.html.twig');
       $return[] = Field::new('adminObject', "Informations de réception")->setTemplatePath('admin/order/order_delivery.html.twig');
       $return[] = Field::new('adminObject', "Informations paiement")->setTemplatePath('admin/order/order_state_payment.html.twig');
   } else {
       $return[] = Field::new('adminObject', "Commande")->setTemplatePath('admin/order/order_id.html.twig');
       $return[] = Field::new('adminObject', "Informations de contact")->setTemplatePath('admin/order/order_contact.html.twig');
       $return[] = Field::new('adminObject', "Informations de réception")->setTemplatePath('admin/order/order_delivery.html.twig');
       $return[] = Field::new('adminObject', "Informations paiement")->setTemplatePath('admin/order/order_state_payment.html.twig');
   }
   ```

   Après :
   ```php
   if ((int)$this->requestStack->getCurrentRequest()->query->get('delivery') === 1 ) {
       $return[] = Field::new('adminObject', "Informations de contact")->setTemplatePath('admin/order/order_contact.html.twig');
       $return[] = Field::new('adminObject', "Informations de réception")->setTemplatePath('admin/order/order_delivery.html.twig');
       $return[] = Field::new('adminObject', "Service eBay<br/>sélectionné")->setTemplatePath('admin/order/order_ebay_shipping_service.html.twig')->addCssClass('text-center')->setTextAlign('center');
       $return[] = Field::new('adminObject', "Informations paiement")->setTemplatePath('admin/order/order_state_payment.html.twig');
   } else {
       $return[] = Field::new('adminObject', "Commande")->setTemplatePath('admin/order/order_id.html.twig');
       $return[] = Field::new('adminObject', "Informations de contact")->setTemplatePath('admin/order/order_contact.html.twig');
       $return[] = Field::new('adminObject', "Informations de réception")->setTemplatePath('admin/order/order_delivery.html.twig');
       $return[] = Field::new('adminObject', "Service eBay<br/>sélectionné")->setTemplatePath('admin/order/order_ebay_shipping_service.html.twig')->addCssClass('text-center')->setTextAlign('center');
       $return[] = Field::new('adminObject', "Informations paiement")->setTemplatePath('admin/order/order_state_payment.html.twig');
   }
   ```

   Le libellé `"Service eBay<br/>sélectionné"` suit la convention déjà utilisée pour les
   en-têtes de colonne sur deux lignes (`"N° Commande<br/>eBay"`, ligne 226 ; `"N° Fake<br/>Facture"`,
   ligne 243).

2. `createIndexQueryBuilder()` (`OrderCrudController.php:83-130`) — ajouter un `leftJoin` +
   `addSelect` sur `shippingService` pour éviter le N+1 sur les listings qui affichent
   jusqu'à 500 lignes (`setPaginatorPageSize(500)`, `configureCrud()` ligne 193) :

   Avant (`OrderCrudController.php:83-85`) :
   ```php
   public function createIndexQueryBuilder(SearchDto $searchDto, EntityDto $entityDto, FieldCollection $fields, FilterCollection $filters): QueryBuilder{
       $response = parent::createIndexQueryBuilder($searchDto, $entityDto, $fields, $filters);

   ```

   Après :
   ```php
   public function createIndexQueryBuilder(SearchDto $searchDto, EntityDto $entityDto, FieldCollection $fields, FilterCollection $filters): QueryBuilder{
       $response = parent::createIndexQueryBuilder($searchDto, $entityDto, $fields, $filters);
       $response->leftJoin('entity.shippingService', 'shippingService')->addSelect('shippingService');

   ```

Aucune migration Doctrine n'est nécessaire : `Order::shippingService` et
`ShippingService::description` existent déjà (`src/Entity/Order.php:101-103`,
`src/Entity/Ebay/ShippingService.php:23-24`).

## Étapes

1. Créer `templates/admin/order/order_ebay_shipping_service.html.twig` avec le contenu
   ci-dessus.
2. Modifier `OrderCrudController::configureFields()` pour insérer la nouvelle colonne dans
   les deux branches (delivery=1 et sinon).
3. Modifier `OrderCrudController::createIndexQueryBuilder()` pour ajouter le `leftJoin` +
   `addSelect` évitant le N+1.
4. Vider le cache Symfony si nécessaire (`php bin/console cache:clear`, via le conteneur
   `stack-orb_php83`).

## Vérification

- `docker exec stack-orb_php83 sh -c "cd /var/www/eurocommemo && php bin/console cache:clear"`
  puis recharger l'admin sans erreur Twig/EasyAdmin.
- Ouvrir successivement les 4 écrans de listing (`/admin?...` sans état, `?state=<WAITING_RECEIPT>`,
  `?state=<VALID>`, `?state=<VALID>&delivery=1&ready=1`) et vérifier que la colonne « Service
  eBay sélectionné » apparaît sur chacun, avec :
  - le nom du service (`ShippingService::shippingService`) pour les commandes eBay ayant un
    `shippingService` renseigné,
  - un tiret « — » pour les commandes non-eBay ou sans service renseigné,
  - un tooltip Bootstrap au survol affichant `ShippingService::description` quand elle est
    définie, sans tooltip si la description est vide.
- Vérifier dans `var/log/dev.log` (ou le profiler Symfony) l'absence de requêtes N+1
  supplémentaires liées à `shippingService` sur le listing « prêtes à être expédiées »
  (500 lignes).
