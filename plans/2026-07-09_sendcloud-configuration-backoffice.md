# Plan — Configuration Sendcloud (identifiant / mot de passe / webhooks) dans le backoffice

## Contexte

Aujourd'hui les credentials Sendcloud vivent uniquement dans des variables d'environnement
(`.env.local`, lignes 79-83 : `SENDCLOUD_BASE_URL`, `SENDCLOUD_PUBLIC_KEY`,
`SENDCLOUD_SECRET_KEY`). Aucun code ne les consomme : les dossiers `src/Entity/Sendcloud/`,
`src/Repository/Sendcloud/`, `src/Dto/Sendcloud/`, `src/Service/Sendcloud/UseCase/` sont des
scaffolds vides, et aucune référence `Sendcloud`/`SENDCLOUD_` n'existe dans `src/` ni `config/`.

Le besoin : permettre à un administrateur de saisir depuis le backoffice **l'identifiant
(public key)** et le **mot de passe (secret key)** Sendcloud, ainsi qu'un booléen
**« webhooks Sendcloud actifs »**, et de persister ces trois réglages en base de données.

**Hors périmètre (confirmé) :** aucune implémentation du déclenchement ni de la consommation
des webhooks Sendcloud, ni de l'appel à l'API Sendcloud. Le toggle `webhookEnable` est un
simple réglage persisté ; son exploitation viendra dans un chantier ultérieur. Ce plan crée
uniquement la brique de **configuration persistée + éditable dans le backoffice**.

Le projet (`src-eurocommemo`, Symfony + EasyAdmin v4) possède déjà un cas quasi identique :
la configuration **Ebay** (`EbayConfiguration`), servie via une page custom montée dans le
menu EasyAdmin, et qui embarque elle-même un booléen `webhookEnable`. Le plan **calque
intégralement ce pattern** — c'est la voie la plus cohérente avec l'existant.

**Note sur l'intégration future (contexte, hors périmètre).** Des patches WIP « shelved »
IntelliJ (`.idea/shelf/`, non appliqués, non committés) esquissent déjà un
`SendcloudApiConnector` en **HTTP Basic auth** (public key = user, secret key = password),
calqué sur `App\Service\PaypalApiConnector` (`src/Service/PaypalApiConnector.php:23-31,92`)
qui lit ses credentials via bind de variables d'env. Quand cette intégration sera reprise,
le connecteur devra consommer `SendcloudConfiguration` (entité créée ici) au lieu des binds
d'env — c'est précisément l'intérêt de persister la config en base. Une des variantes WIP
référence aussi un `SENDCLOUD_SENDER_ADDRESS_ID` : champ potentiel à ajouter plus tard, non
inclus ici car hors de la demande (identifiant / mot de passe / toggle webhooks).

Chemin racine du repo : `/Users/aurelienmorvan/OrbStack/docker/volumes/src-eurocommemo`
(déclaré `src-eurocommemo` dans `workspace.yaml`). Tous les chemins ci-dessous sont relatifs
à ce repo.

## Fichiers concernés

### Nouveaux fichiers (repo `src-eurocommemo`)

#### `src/Entity/Sendcloud/SendcloudConfiguration.php`

Entité de configuration singleton, calquée sur `src/Entity/Ebay/EbayConfiguration.php`
(mêmes conventions ORM, mêmes signatures de setters fluides retournant `self`).

```php
<?php

namespace App\Entity\Sendcloud;

use App\Repository\Sendcloud\SendcloudConfigurationRepository;
use Doctrine\ORM\Mapping as ORM;

#[ORM\Table()]
#[ORM\Entity(repositoryClass: SendcloudConfigurationRepository::class)]
class SendcloudConfiguration
{
    #[ORM\Id]
    #[ORM\GeneratedValue]
    #[ORM\Column(type: 'integer')]
    private $id;

    #[ORM\Column(type: 'datetime', nullable: true)]
    private ?\DateTime $updatedAt = null;

    /** Identifiant Sendcloud (public key) */
    #[ORM\Column(type: 'string', nullable: true)]
    private ?string $publicKey = null;

    /** Mot de passe Sendcloud (secret key) */
    #[ORM\Column(type: 'string', nullable: true)]
    private ?string $secretKey = null;

    #[ORM\Column(type: 'boolean', options: ['default' => false])]
    private bool $webhookEnable = false;

    public function getId()
    {
        return $this->id;
    }

    public function getUpdatedAt(): ?\DateTime
    {
        return $this->updatedAt;
    }

    public function setUpdatedAt(?\DateTime $updatedAt): self
    {
        $this->updatedAt = $updatedAt;
        return $this;
    }

    public function getPublicKey(): ?string
    {
        return $this->publicKey;
    }

    public function setPublicKey(?string $publicKey): self
    {
        $this->publicKey = $publicKey;
        return $this;
    }

    public function getSecretKey(): ?string
    {
        return $this->secretKey;
    }

    public function setSecretKey(?string $secretKey): self
    {
        $this->secretKey = $secretKey;
        return $this;
    }

    public function isWebhookEnable(): bool
    {
        return $this->webhookEnable;
    }

    public function setWebhookEnable(bool $webhookEnable): self
    {
        $this->webhookEnable = $webhookEnable;
        return $this;
    }

    /** True quand les deux credentials sont renseignés (utile pour un futur connecteur API). */
    public function isConfigured(): bool
    {
        return !is_null($this->publicKey) && !is_null($this->secretKey);
    }
}
```

#### `src/Repository/Sendcloud/SendcloudConfigurationRepository.php`

Copie exacte du pattern `src/Repository/Ebay/EbayConfigurationRepository.php` (méthode
`findFirst()` renvoyant l'unique ligne).

```php
<?php

namespace App\Repository\Sendcloud;

use App\Entity\Sendcloud\SendcloudConfiguration;
use Doctrine\Bundle\DoctrineBundle\Repository\ServiceEntityRepository;
use Doctrine\Persistence\ManagerRegistry;

class SendcloudConfigurationRepository extends ServiceEntityRepository
{
    public function __construct(ManagerRegistry $registry)
    {
        parent::__construct($registry, SendcloudConfiguration::class);
    }

    public function findFirst(): ?SendcloudConfiguration
    {
        return $this->createQueryBuilder('sc')
            ->setMaxResults(1)
            ->getQuery()
            ->getOneOrNullResult();
    }
}
```

#### `src/Service/Sendcloud/SendcloudConfigurationService.php`

Service get-or-create + save, calqué sur `src/Service/Ebay/EbayService.php` (méthodes
`getEbayConfiguration()` / `saveEbayConfiguration()`). `save()` positionne `updatedAt` avant
le flush pour tracer la dernière modification.

```php
<?php

namespace App\Service\Sendcloud;

use App\Entity\Sendcloud\SendcloudConfiguration;
use App\Repository\Sendcloud\SendcloudConfigurationRepository;
use Doctrine\ORM\EntityManagerInterface;

class SendcloudConfigurationService
{
    private ?SendcloudConfiguration $configuration = null;

    public function __construct(
        private readonly SendcloudConfigurationRepository $repository,
        private readonly EntityManagerInterface $entityManager,
    ) {
    }

    public function getConfiguration(): SendcloudConfiguration
    {
        if (is_null($this->configuration)) {
            $this->configuration = $this->repository->findFirst();
            if (is_null($this->configuration)) {
                $this->configuration = new SendcloudConfiguration();
                $this->entityManager->persist($this->configuration);
                $this->entityManager->flush();
            }
        }

        return $this->configuration;
    }

    public function save(SendcloudConfiguration $configuration): void
    {
        $configuration->setUpdatedAt(new \DateTime());
        $this->entityManager->flush();
    }
}
```

#### `src/Form/Sendcloud/SendcloudConfigurationFormType.php`

Calqué sur `src/Form/Ebay/EbayConfigurationFormType.php`. Trois champs : identifiant, mot
de passe, toggle webhook. Le mot de passe utilise `PasswordType` avec `always_empty => false`
pour préremplir la valeur existante (Sendcloud secret key ; visible uniquement en zone
`ROLE_ADMIN`). Si l'on préfère l'homogénéité stricte avec Ebay (qui affiche `clientSecret`
en `TextType`), remplacer par `TextType` — voir note en fin de section.

```php
<?php

namespace App\Form\Sendcloud;

use App\Entity\Sendcloud\SendcloudConfiguration;
use Symfony\Component\Form\AbstractType;
use Symfony\Component\Form\Extension\Core\Type\CheckboxType;
use Symfony\Component\Form\Extension\Core\Type\PasswordType;
use Symfony\Component\Form\Extension\Core\Type\TextType;
use Symfony\Component\Form\FormBuilderInterface;
use Symfony\Component\OptionsResolver\OptionsResolver;

class SendcloudConfigurationFormType extends AbstractType
{
    public function buildForm(FormBuilderInterface $builder, array $options)
    {
        $builder
            ->add(
                'publicKey',
                TextType::class,
                [
                    'label' => 'Identifiant (Public Key)',
                    'required' => false,
                ]
            )
            ->add(
                'secretKey',
                PasswordType::class,
                [
                    'label' => 'Mot de passe (Secret Key)',
                    'required' => false,
                    'always_empty' => false,
                ]
            )
            ->add(
                'webhookEnable',
                CheckboxType::class,
                [
                    'label' => 'Webhooks Sendcloud activés',
                    'required' => false,
                ]
            );
    }

    public function configureOptions(OptionsResolver $resolver)
    {
        $resolver
            ->setDefaults(
                [
                    'data_class' => SendcloudConfiguration::class,
                ]
            );
    }
}
```

> Note homogénéité : `EbayConfigurationFormType` déclare `clientSecret` en `TextType` (secret
> affiché en clair dans le backoffice `ROLE_ADMIN`). Le choix `PasswordType` ci-dessus est un
> léger durcissement ; pour rester strictement iso-Ebay, utiliser `TextType` pour `secretKey`.

#### `src/Controller/Admin/Sendcloud/SendcloudConfigurationController.php`

Calqué sur la méthode `index()` de `src/Controller/Admin/Ebay/EbayConfigurationController.php:33-60`
(page custom EasyAdmin : get-or-create → `handleRequest` → sur submit valide `save()` + flash).
On ne reprend PAS les routes de synchronisation/connexion Ebay (hors périmètre).

```php
<?php

namespace App\Controller\Admin\Sendcloud;

use App\Entity\Sendcloud\SendcloudConfiguration;
use App\Form\Sendcloud\SendcloudConfigurationFormType;
use App\Service\Sendcloud\SendcloudConfigurationService;
use Symfony\Bundle\FrameworkBundle\Controller\AbstractController;
use Symfony\Component\Form\FormFactoryInterface;
use Symfony\Component\HttpFoundation\Request;
use Symfony\Component\HttpFoundation\Response;
use Symfony\Component\Routing\Attribute\Route;

class SendcloudConfigurationController extends AbstractController
{
    #[Route('/admin/sendcloud-configuration', name: 'sendcloud_configuration')]
    public function index(
        Request $request,
        FormFactoryInterface $formFactory,
        SendcloudConfigurationService $sendcloudConfigurationService
    ): Response {
        $configuration = $sendcloudConfigurationService->getConfiguration();
        $form = $formFactory->create(SendcloudConfigurationFormType::class, $configuration)
            ->handleRequest($request);

        if ($form->isSubmitted() && $form->isValid()) {
            /** @var SendcloudConfiguration $formData */
            $formData = $form->getData();
            $sendcloudConfigurationService->save($formData);
            $this->addFlash('success', 'La configuration Sendcloud a bien été enregistrée.');

            return $this->redirectToRoute('sendcloud_configuration');
        }

        return $this->render(
            'admin/sendcloud/configuration/index.html.twig',
            [
                'form' => $form->createView(),
                'sendcloudConfiguration' => $configuration,
            ]
        );
    }
}
```

> Sécurité : l'accès est déjà couvert par `config/packages/security.yaml:31`
> (`- { path: ^/(%app_locales%)/admin, roles: ROLE_ADMIN }`) et le `->setPermission('ROLE_ADMIN')`
> ajouté sur l'entrée de menu (voir fichier modifié). Aucune modification de `security.yaml`.

#### `templates/admin/sendcloud/configuration/index.html.twig`

Version épurée du template Ebay (`templates/admin/ebay/configuration/index.html.twig`) : on
garde l'ossature EasyAdmin (`@EasyAdmin/page/content.html.twig` + form theme) et une seule
carte « Configuration Sendcloud », sans les cartes de connexion/synchronisation Ebay.

```twig
{% extends "@EasyAdmin/page/content.html.twig" %}

{% form_theme form '@EasyAdmin/crud/form_theme.html.twig' %}

{% block page_content %}
    <div class="bg-primary-light p-2 mb-3">
        <div class="row">
            <div class="col-md-6 col-sm-12">
                <div class="card">
                    <div class="d-flex flex-column card-body">
                        <h2 class="card-title">Configuration Sendcloud</h2>
                        <p class="legend-help">
                            Identifiant et mot de passe de l'API Sendcloud, et activation des webhooks.
                            {% if sendcloudConfiguration.updatedAt %}
                                <br/><span class="fw-bold">Dernière modification : {{ sendcloudConfiguration.updatedAt|date('d/m/Y H:i:s') }}</span>
                            {% endif %}
                        </p>
                        <div class="card-text">
                            {{ form_start(form) }}
                            {{ form_widget(form) }}
                            <button type="submit" class="btn btn-primary mt-2">Enregistrer</button>
                            {{ form_end(form) }}
                        </div>
                    </div>
                </div>
            </div>
        </div>
    </div>
{% endblock %}
```

#### `migrations/Version<timestamp>.php`

Nouvelle migration générée via `make:migration` (le `<timestamp>` sera au format
`YYYYMMDDHHMMSS`, cf. dernière migration `migrations/Version20260708224710.php`). Table
`sendcloud_configuration` calquée sur la structure de `ebay_configuration`.

```php
<?php

declare(strict_types=1);

namespace DoctrineMigrations;

use Doctrine\DBAL\Schema\Schema;
use Doctrine\Migrations\AbstractMigration;

final class Version<timestamp> extends AbstractMigration
{
    public function getDescription(): string
    {
        return 'Create sendcloud_configuration table (public key, secret key, webhook toggle)';
    }

    public function up(Schema $schema): void
    {
        $this->addSql('CREATE TABLE sendcloud_configuration (
            id INT AUTO_INCREMENT NOT NULL,
            updated_at DATETIME DEFAULT NULL,
            public_key VARCHAR(255) DEFAULT NULL,
            secret_key VARCHAR(255) DEFAULT NULL,
            webhook_enable TINYINT(1) DEFAULT 0 NOT NULL,
            PRIMARY KEY(id)
        ) DEFAULT CHARACTER SET utf8mb4 COLLATE `utf8mb4_unicode_ci` ENGINE = InnoDB');
    }

    public function down(Schema $schema): void
    {
        $this->addSql('DROP TABLE sendcloud_configuration');
    }
}
```

### Fichiers modifiés (repo `src-eurocommemo`)

#### `src/Controller/Admin/DashboardController.php`

Ajouter une entrée de menu Sendcloud dans `configureMenuItems()`, sur le modèle exact de
l'entrée Ebay (lignes 84-87). Insérer juste après le sous-menu Ebay :

```php
// après le bloc :
//   MenuItem::subMenu('Ebay', 'fab fa-ebay')->setSubItems([
//       MenuItem::linkToRoute('Configuration Ebay', '', 'ebay_configuration')
//           ->setPermission('ROLE_ADMIN'),
//   ]),
MenuItem::subMenu('Sendcloud', 'fa fa-truck')->setSubItems([
    MenuItem::linkToRoute('Configuration Sendcloud', '', 'sendcloud_configuration')
        ->setPermission('ROLE_ADMIN'),
]),
```

> Alternative : rattacher l'entrée au sous-menu existant « Configuration du site »
> (lignes 76-82) plutôt qu'un nouveau sous-menu. Retenu : nouveau sous-menu dédié, iso-Ebay,
> car la page est une route custom et non un onglet du CRUD `Configuration`.

### Fichiers volontairement NON modifiés

- **`.env.local` (lignes 79-83)** : les variables `SENDCLOUD_*` restent en place. Aucun code
  ne les lit aujourd'hui ; la nouvelle entité devient la source de vérité pour la future
  intégration. Optionnel (hors périmètre) : un `DataFixtures`/commande de seed pourrait
  initialiser la ligne à partir de ces variables — non prévu ici.
- **`config/packages/security.yaml`** : accès admin déjà protégé (ligne 31).
- **`config/services.yaml`** : autowiring/autoconfigure par défaut suffit (repository
  `ServiceEntityRepository`, service et controller taggés automatiquement, comme pour Ebay).

## Étapes

1. **Entité** — créer `src/Entity/Sendcloud/SendcloudConfiguration.php` (bloc ci-dessus).
2. **Repository** — créer `src/Repository/Sendcloud/SendcloudConfigurationRepository.php`
   avec `findFirst()`.
3. **Service** — créer `src/Service/Sendcloud/SendcloudConfigurationService.php`
   (`getConfiguration()` get-or-create, `save()` avec `updatedAt`).
4. **Formulaire** — créer `src/Form/Sendcloud/SendcloudConfigurationFormType.php`
   (publicKey / secretKey / webhookEnable).
5. **Contrôleur** — créer `src/Controller/Admin/Sendcloud/SendcloudConfigurationController.php`
   avec la route `sendcloud_configuration`.
6. **Template** — créer `templates/admin/sendcloud/configuration/index.html.twig`.
7. **Menu** — modifier `src/Controller/Admin/DashboardController.php::configureMenuItems()`
   pour ajouter le sous-menu « Sendcloud → Configuration Sendcloud ».
8. **Migration** — générer la migration (`make:migration`), vérifier le SQL produit contre
   le bloc ci-dessus, puis l'appliquer (`doctrine:migrations:migrate`).

Toutes les commandes de build/console doivent passer par `scripts/repo_exec.py`
(le repo est en `exec.mode: compose`, service `php-fpm-per83`), jamais un appel direct.

## Vérification

Exécuter via `scripts/repo_exec.py` (route vers le conteneur `php-fpm-per83`) :

1. **Schéma & migration**
   - `bin/console make:migration` puis relire le `Version<timestamp>.php` généré (doit créer
     `sendcloud_configuration`, colonnes `public_key`, `secret_key`, `webhook_enable`).
   - `bin/console doctrine:migrations:migrate --no-interaction`.
   - `bin/console doctrine:schema:validate` → « mapping OK » et « schema in sync ».
2. **Lint & sanity**
   - `bin/console lint:twig templates/admin/sendcloud/configuration/index.html.twig`.
   - `bin/console debug:router | grep sendcloud_configuration` → la route `/admin/sendcloud-configuration`
     est bien enregistrée.
   - `bin/console cache:clear` sans erreur (autowiring service/controller OK).
3. **Scénario manuel (backoffice)**
   - Se connecter en `ROLE_ADMIN`, ouvrir le menu **Sendcloud → Configuration Sendcloud**.
   - Saisir un identifiant, un mot de passe, cocher « Webhooks Sendcloud activés »,
     enregistrer → flash de succès, valeurs persistées (recharger la page : champs
     préremplis, case cochée, date de modification affichée).
   - Décocher le webhook, ré-enregistrer → l'état booléen est bien mis à jour en base
     (`SELECT public_key, secret_key, webhook_enable FROM sendcloud_configuration;`).
   - Vérifier qu'un utilisateur non-admin ne peut pas atteindre `/admin/sendcloud-configuration`
     (redirection / 403).
4. **Graphe de connaissances** — après implémentation, rafraîchir le graphe du repo :
   `graphify extract <repo-path> --out docs/src-eurocommemo --exclude '*.md' --exclude '*.yaml' --exclude '*.yml' --exclude '*.html' --exclude '*.jpg' --exclude '*.svg' --exclude '*.png'`
   puis `graphify cluster-only docs/src-eurocommemo --no-label`.
