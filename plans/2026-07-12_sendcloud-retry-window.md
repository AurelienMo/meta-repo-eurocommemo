# Plan — Élargir la fenêtre de retry de l'association Sendcloud (délai réel ~15 min en prod)

**Repo(s)** : src-eurocommemo · **Branche** : `feature/sendcloud-async-order-link` (ou nouvelle `fix/sendcloud-retry-window`) · **Risk** : low · **Complexité** : trivial

> Repo applicatif monté sous `/Users/aurelienmorvan/OrbStack/docker/volumes/src-eurocommemo/` — Symfony 6.4, `symfony/messenger`, transport Doctrine (`messenger_messages`). Chemins relatifs à la racine de ce repo.

## Contexte

Le dev « association asynchrone de l'ID Sendcloud à l'import d'une commande eBay »
(`plans/2026-07-11_sendcloud-async-order-link.md`) est déployé en prod. L'analyse des logs
montre que Sendcloud ne reçoit la commande — via sa propre intégration eBay — qu'au bout de
**~15 minutes**. Or la stratégie de retry configurée épuise ses **4 tentatives en 60 secondes**
(`delay: 20000`, `multiplier: 1`, `max_retries: 3` → passages à t=0 / +20 / +40 / +60 s).

Conséquence en prod : le handler `AssociateSendcloudOrderIdHandler` lève
`SendcloudOrderNotFoundException` sur les 4 passages ; `SendcloudLinkFailureSubscriber` déclenche
l'échec final au bout d'1 min, pose la sentinelle `"0"` (qui masque **définitivement** le lien
« Voir sur Sendcloud » dans le backoffice) et envoie un mail d'alerte — **à tort**, sur des
commandes qui finissent par arriver sur Sendcloud ~14 min plus tard.

Le transport est **Doctrine** (`doctrine://default?auto_setup=0`, `.env:80`) : les retries différés
sont persistés en base (`messenger_messages.available_at`) et **survivent aux redémarrages du
worker** (`messenger:consume async_create_ebay async_sendcloud --time-limit=1800`, `cron.php:2`).
Une fenêtre de retry longue (dizaines de minutes) est donc parfaitement viable et ne consomme
aucune ressource entre deux tentatives : le message dort en base jusqu'à son `available_at`.

**Objectif** : porter la fenêtre de retry à **~40 minutes** (marge > 2,5× le délai observé de
15 min), avec un backoff exponentiel plafonné pour rester économe en appels API. L'échec final
(`"0"` + mail) ne survient alors plus que pour les commandes réellement jamais poussées vers
Sendcloud — c'est sa vraie sémantique d'alerte.

**Décision produit à cadrer** : la fenêtre exacte (~40 min proposés) est un arbitrage « latence
d'alerte acceptable vs marge de sécurité », ajustable en une ligne (voir la note de tuning).

## Fichiers concernés

### Modifiés (repo `src-eurocommemo`)

#### 1. `config/packages/messenger.yaml` — stratégie de retry `async_sendcloud`

Remplacer le bloc `retry_strategy` du transport `async_sendcloud` (`config/packages/messenger.yaml:23-27`).
Backoff exponentiel démarrant à 60 s, doublant à chaque passage, plafonné à 5 min par intervalle,
10 re-essais → 11 passages étalés sur ~42 min.

Avant (`config/packages/messenger.yaml:18-27`) :

```yaml
            async_sendcloud:
                dsn: "%env(MESSENGER_TRANSPORT_DSN)%"
                options:
                    auto_setup: true
                    queue_name: async_sendcloud
                retry_strategy:
                    max_retries: 3
                    delay: 20000      # 20 s between attempts
                    multiplier: 1     # constant delay (no exponential backoff)
                    max_delay: 0
```

Après :

```yaml
            async_sendcloud:
                dsn: "%env(MESSENGER_TRANSPORT_DSN)%"
                options:
                    auto_setup: true
                    queue_name: async_sendcloud
                retry_strategy:
                    # Sendcloud receives the order from its own eBay integration only after
                    # ~15 min in prod. Cover ~40 min with exponential backoff capped at 5 min:
                    # attempts at ~0s, +1, +3, +7, +12, +17, +22, +27, +32, +37, +42 min.
                    max_retries: 10
                    delay: 60000       # first retry after 60 s
                    multiplier: 2      # exponential backoff
                    max_delay: 300000  # cap each interval at 5 min
```

Séquence des délais (Symfony `MultiplierRetryStrategy` : `min(delay × multiplier^(n-1), max_delay)`) :
60 s, 120 s, 240 s, puis 300 s (plafonné) à chaque re-essai suivant. Cumul ≈ 42 min sur 11 passages.
La commande observée à 15 min est associée au passage ~17 min (au plus ~5 min après son apparition) ;
`"0"` + mail ne se déclenchent qu'après épuisement (~42 min).

> **Note de tuning** — la fenêtre s'ajuste sans changer la forme :
> - fenêtre plus courte → baisser `max_retries` (ex. `8` ≈ 32 min) ;
> - association plus serrée autour de 15 min → baisser `max_delay` (ex. `120000` = 2 min, au prix
>   de plus d'appels API) ;
> - tuning **sans redéploiement** → exposer les valeurs en env
>   (`max_retries: '%env(int:SENDCLOUD_LINK_MAX_RETRIES)%'`, idem `delay`/`max_delay`) avec des
>   défauts committés dans `.env`. Optionnel, non retenu par défaut pour garder un correctif d'une
>   seule ligne de config.

#### 2. `templates/mail/sendcloud_link_failed.html.twig` — texte d'alerte

Le gabarit code en dur « après 4 tentatives » (`templates/mail/sendcloud_link_failed.html.twig:1`),
ce qui devient faux avec 11 passages. Le rendre indépendant du nombre de tentatives.

Avant (`templates/mail/sendcloud_link_failed.html.twig:1`) :

```twig
<p>Aucune commande Sendcloud n'a pu être associée après 4 tentatives.</p>
```

Après :

```twig
<p>Aucune commande Sendcloud n'a pu être associée à cette commande eBay après épuisement des tentatives (~40 min d'attente).</p>
```

> `MailService::sendSendcloudLinkFailure()` (`src/Service/MailService.php`) ne passe que
> `orderIdEbay` et `id` au template — inutile d'y ajouter un compteur de tentatives ; la
> formulation générique suffit.

### Non modifiés (confirmés corrects par l'exploration)

- `src/Messenger/Handler/AssociateSendcloudOrderIdHandler.php` — lève toujours
  `SendcloudOrderNotFoundException` tant que Sendcloud ne connaît pas la commande (`:43-45`) ; le
  garde d'idempotence (`getSendcloudOrderId() !== null`, `:37`) court-circuite une commande déjà
  associée **ou** déjà marquée `"0"`. Aucun changement.
- `src/EventSubscriber/SendcloudLinkFailureSubscriber.php` — n'agit qu'à `willRetry() === false`
  (`:33-35`) ; avec la nouvelle stratégie, cet événement final ne survient qu'après ~42 min.
  Aucun changement.
- `cron.php` — consomme déjà `async_create_ebay async_sendcloud` (`:2`). Aucun changement de code ;
  voir la dépendance infra en Vérification (§6).

## Étapes

1. **Retry strategy** — modifier le bloc `retry_strategy` de `async_sendcloud` dans
   `config/packages/messenger.yaml` (fichier #1) : `max_retries: 10`, `delay: 60000`,
   `multiplier: 2`, `max_delay: 300000`.
2. **Texte du mail** — retirer le « 4 tentatives » codé en dur dans
   `templates/mail/sendcloud_link_failed.html.twig` (fichier #2).
3. **(Décision produit)** valider la fenêtre visée (~40 min) ou ajuster `max_retries` / `max_delay`
   selon la note de tuning.
4. **Rafraîchir le graphe graphify** du repo (cf. CLAUDE.md § graphify) — impact quasi nul
   (yaml/twig exclus de l'extraction), sans coût API.

## Vérification

Toutes les commandes passent par `scripts/repo_exec.py . src-eurocommemo -- …` (cf. CLAUDE.md).

1. **Lint config** :
   ```sh
   python3 scripts/repo_exec.py . src-eurocommemo -- php bin/console lint:yaml config/packages/messenger.yaml
   python3 scripts/repo_exec.py . src-eurocommemo -- php bin/console lint:twig templates/mail/sendcloud_link_failed.html.twig
   ```
2. **Cache / routing** :
   ```sh
   python3 scripts/repo_exec.py . src-eurocommemo -- php bin/console cache:clear
   python3 scripts/repo_exec.py . src-eurocommemo -- php bin/console debug:messenger
   ```
   Attendu : `AssociateSendcloudOrderIdMessage` toujours routé vers `AssociateSendcloudOrderIdHandler`.
3. **Fenêtre de retry — inspection base** (transport Doctrine) : importer une commande eBay
   **absente** de Sendcloud, consommer une itération, puis vérifier que le message est reprogrammé
   avec un `available_at` repoussé (≈ +60 s, puis +2, +4, +5 min…) et que l'échec final ne se
   déclenche pas avant ~42 min :
   ```sh
   python3 scripts/repo_exec.py . src-eurocommemo -- php bin/console messenger:consume async_sendcloud -vv --limit=1
   python3 scripts/repo_exec.py . src-eurocommemo -- php bin/console doctrine:query:sql \
     "SELECT id, available_at, delivered_at FROM messenger_messages WHERE queue_name='async_sendcloud'"
   ```
4. **Bout-en-bout — succès tardif** (le scénario du bug) : sur une commande qui apparaîtra sur
   Sendcloud après plusieurs minutes, laisser tourner le worker (ou le cron) et confirmer qu'au
   passage suivant son apparition, `orders.sendcloud_order_id` reçoit l'ID interne et que **ni**
   `"0"` **ni** mail ne sont émis.
5. **Bout-en-bout — échec réel** : commande jamais poussée vers Sendcloud → après ~42 min,
   `sendcloud_order_id = "0"` + un seul mail d'alerte (texte sans « 4 tentatives »).
6. **Dépendance infra à valider (hors repo)** : le cron OVH qui invoque `cron.php` doit relancer
   `messenger:consume` assez régulièrement pour qu'un message devenu disponible à +N min soit
   consommé sans gros retard. Avec `--time-limit=1800` (worker de 30 min), s'assurer que `cron.php`
   est relancé à une cadence ≤ 30 min (idéalement en continu), sinon un message différé attend le
   prochain lancement. Vérifier la crontab de prod (non versionnée) — c'est la seule dépendance hors
   code du correctif.
