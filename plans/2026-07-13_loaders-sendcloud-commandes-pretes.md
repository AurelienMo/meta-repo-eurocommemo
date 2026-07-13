# Plan — Loaders Sendcloud sur la page « commandes prêtes à être expédiées »

## Contexte

Sur la page admin **« Commandes prêtes à être expédiées »** (liste EasyAdmin générée par
`OrderCrudController`, entrée de menu `DashboardController.php:122`), chaque ligne de commande
eBay affiche un bloc Sendcloud (`templates/admin/order/order_sendcloud_action.html.twig`) avec
un select de méthode de livraison et un sous-select de point relais.

Au chargement de la page, le JS (`assets/back/js/back.js`, bloc lignes 284-355) exécute **un
appel Ajax par ligne** vers `app_admin_order_sendcloud_shipping_options`
(`/fr/admin/order/{ID}/sendcloud/shipping-options`) pour remplir chaque select de méthode.
Ces appels sont silencieux : aucun retour visuel ne signale que les selects sont encore en cours
de peuplement, ils apparaissent vides puis se remplissent d'un coup. De même, quand l'opérateur
choisit une méthode nécessitant un point relais (`data-requires-sp="1"`), un second appel Ajax
vers `app_admin_order_sendcloud_service_points` charge le sous-select sans aucun indicateur
d'attente.

**Objectif :**
1. Afficher un **loader global** (overlay) au chargement de la page, tant que **tous** les appels
   `shipping-options` ne sont pas terminés. Le masquer une fois tous résolus.
2. Afficher un **loader par ligne** (inline, à côté du sous-select) lorsqu'une méthode Sendcloud
   nécessitant un point relais est choisie, le temps que l'appel `service-points` réponde et que
   le sous-select soit peuplé. Le masquer une fois le sous-select prêt (ou en cas d'erreur / de
   méthode ne nécessitant pas de point relais).

Contrainte : réutiliser le spinner CSS déjà présent (`.loader` + animation `@keyframes spin`,
`assets/back/scss/back.scss:115-159`) plutôt que d'introduire une nouvelle dépendance. Ne modifier
que l'UI/JS — aucun changement backend n'est requis (les endpoints et leur payload conviennent
déjà : `shipping-options` renvoie `{code,label,carrierCode,requiresServicePoint}`,
`service-points?carrier=…` renvoie `{id,label}`).

## Fichiers concernés

### Modifiés

Racine applicative : `/Users/aurelienmorvan/OrbStack/docker/volumes/src-eurocommemo`.

#### 1. `assets/back/scss/back.scss`

Le spinner existant est stylé via le sélecteur d'**ID** `#loader-1` (lignes 124-143), ce qui
interdit sa réutilisation sur plusieurs éléments simultanés (un ID doit être unique, or on veut
un loader par ligne + un loader d'overlay). Généraliser l'animation à une **classe**
`.loader-spin` et ajouter les styles de l'overlay + du loader inline. Ne pas toucher au bloc
`#loader-1` existant (utilisé ailleurs : `back.js:54`, `back.js:88`) — on **ajoute** une classe
partagée en plus.

Modifier la ligne 124 pour que la règle des pseudo-éléments s'applique aussi à `.loader-spin` :

```scss
/* LOADER 1 */
#loader-1, .loader-spin {          /* était: #loader-1 */
  &:before, &:after {
    content: "";
    position: absolute;
    top: 0;
    left: 0;
    width: 100%;
    height: 100%;
    border-radius: 100%;
    border: 3px solid transparent;
    border-top-color: #5368d5;
  }
  &:before {
    z-index: 100;
    animation: spin 1s infinite;
  }
  &:after {
    border: 3px solid #dbdbdb;
  }
}
```

Puis ajouter, à la suite du bloc `@keyframes spin` (après la ligne 159), les styles propres à la
feature :

```scss
/* Sendcloud — global page-load overlay */
.sendcloud-loading-overlay {
  position: fixed;
  inset: 0;
  background: rgba(255, 255, 255, 0.6);
  z-index: 2000;
  display: flex;
  align-items: center;
  justify-content: center;
}

/* Sendcloud — per-row inline loader for the service-point sub-select */
.sendcloud-sp-loader {
  width: 18px;
  height: 18px;
  margin: 0 0 4px 0;
}
```

> Note : `.loader` (lignes 115-121) fixe déjà `width/height/position:relative/margin`. Le loader
> inline garde `.loader` pour `position:relative` (indispensable aux pseudo-éléments `absolute`)
> et surcharge la taille via `.sendcloud-sp-loader`. L'overlay contient un `.loader.loader-spin`
> de taille par défaut (28px). Les deux loaders portent la classe `.loader-spin` pour hériter de
> l'animation.

#### 2. `assets/back/js/back.js` — bloc Sendcloud (lignes 284-355)

Remplacer le bloc actuel (`document.querySelectorAll('.sendcloud-shipping-block').forEach(...)`,
lignes 285-355) par la version ci-dessous. Trois changements :

- **(A)** Envelopper la boucle dans un garde `if (sendcloudBlocks.length > 0)` et créer/attacher
  un overlay global au `document.body` avant la boucle.
- **(B)** Collecter la promesse de chaque `fetch` `shipping-options` dans un tableau
  `shippingOptionPromises`, puis `Promise.allSettled(...)` pour retirer l'overlay une fois **tous**
  les appels terminés (succès ou échec).
- **(C)** Créer un loader inline `.sendcloud-sp-loader` par bloc, l'afficher dans
  `maybeLoadServicePoints()` avant le `fetch` `service-points` et le masquer dans un `.finally()`
  (et immédiatement dans le cas « pas de point relais requis »).

Version complète du bloc de remplacement (remplace `back.js:284-355`) :

```js
    // --- Sendcloud shipping option + service point ---
    const sendcloudBlocks = document.querySelectorAll('.sendcloud-shipping-block');
    if (sendcloudBlocks.length > 0) {
        // Global overlay shown until every shipping-options request has settled.
        const overlay = document.createElement('div');
        overlay.className = 'sendcloud-loading-overlay';
        overlay.innerHTML = '<div class="loader loader-spin"></div>';
        document.body.appendChild(overlay);

        const shippingOptionPromises = [];

        sendcloudBlocks.forEach(function (block) {
            const shippingSelect = block.querySelector('.select-sendcloud-shipping');
            const spSelect = block.querySelector('.select-sendcloud-servicepoint');

            // Per-row inline loader for the service-point sub-select.
            const spLoader = document.createElement('div');
            spLoader.className = 'loader loader-spin sendcloud-sp-loader d-none';
            spSelect.parentNode.insertBefore(spLoader, spSelect);

            function showSpLoader() { spLoader.classList.remove('d-none'); }
            function hideSpLoader() { spLoader.classList.add('d-none'); }

            // 1. Load shipping methods
            const p = fetch(shippingSelect.dataset.url)
                .then(r => r.json())
                .then(options => {
                    if (!Array.isArray(options)) { return; }
                    const current = shippingSelect.dataset.current;
                    shippingSelect.innerHTML = '<option value="">— Choisir une méthode —</option>' +
                        options.map(o =>
                            `<option value="${o.code}" data-requires-sp="${o.requiresServicePoint ? 1 : 0}" ` +
                            `data-carrier="${o.carrierCode || ''}" ${o.code === current ? 'selected' : ''}>${o.label}</option>`
                        ).join('');
                    maybeLoadServicePoints();
                })
                .catch(() => {});
            shippingOptionPromises.push(p);

            // 2. Show/load service points when the option requires one
            function maybeLoadServicePoints() {
                const opt = shippingSelect.selectedOptions[0];
                if (!opt || opt.dataset.requiresSp !== '1') {
                    spSelect.classList.add('d-none');
                    spSelect.innerHTML = '';
                    hideSpLoader();
                    return;
                }
                const carrier = opt.dataset.carrier || '';
                spSelect.classList.add('d-none');
                showSpLoader();
                fetch(spSelect.dataset.url + '?carrier=' + encodeURIComponent(carrier))
                    .then(r => r.json())
                    .then(points => {
                        if (!Array.isArray(points)) { return; }
                        const curId = spSelect.dataset.currentId;
                        spSelect.innerHTML = '<option value="">— Choisir un point relais —</option>' +
                            points.map(p =>
                                `<option value="${p.id}" data-name="${p.label}" ` +
                                `${String(p.id) === curId ? 'selected' : ''}>${p.label}</option>`
                            ).join('');
                        spSelect.classList.remove('d-none');
                    })
                    .catch(() => {})
                    .finally(hideSpLoader);
            }
            shippingSelect.addEventListener('change', maybeLoadServicePoints);

            // 3. Save to Sendcloud
            block.querySelector('.btn-sendcloud-apply').addEventListener('click', function () {
                const spOpt = spSelect.selectedOptions[0];
                $.ajax({
                    url: this.dataset.path,
                    type: 'POST',
                    dataType: 'json',
                    data: {
                        shippingOptionCode: shippingSelect.value,
                        servicePointId: spSelect.classList.contains('d-none') ? '' : spSelect.value,
                        servicePointName: (spOpt && spOpt.dataset.name) || '',
                        _csrf_token: this.dataset.csrf,
                    },
                    success: (data) => {
                        const ok = data.state === 1;
                        const msg = ok
                            ? 'Enregistré sur Sendcloud' + (data.servicePointName ? ' (' + data.servicePointName + ')' : '')
                            : (data.message || 'Erreur');
                        const existing = block.querySelector('.sendcloud-feedback');
                        if (existing) { existing.remove(); }
                        const el = document.createElement('div');
                        el.className = 'sendcloud-feedback small mt-1 ' + (ok ? 'text-success' : 'text-danger');
                        el.textContent = msg;
                        block.appendChild(el);
                    },
                    error: () => console.log('Sendcloud apply request failed.'),
                });
            });
        });

        // Hide the overlay once EVERY shipping-options request has settled.
        Promise.allSettled(shippingOptionPromises).then(() => {
            overlay.remove();
        });
    }
```

Points clés du diff par rapport à l'existant :
- `back.js:290` : le `fetch` est désormais assigné à `const p` et `.catch(() => {})` est ajouté
  pour que l'échec d'un appel ne bloque pas `Promise.allSettled` (l'overlay se retire toujours).
- `back.js:304-324` (`maybeLoadServicePoints`) : ajout de `showSpLoader()` avant le `fetch`,
  `spSelect.classList.add('d-none')` pendant le chargement (le sous-select ne s'affiche qu'une
  fois peuplé), `hideSpLoader()` immédiat dans la branche « pas de point relais », et
  `.finally(hideSpLoader)` pour masquer le loader quel que soit le résultat.
- Le loader inline est inséré **avant** le sous-select (`insertBefore`) pour occuper sa place
  pendant le chargement.

> Le bloc « Sendcloud label generation » (`back.js:357` et suivant) reste **inchangé**.

### Non modifiés (référence, pas d'édition)

- `templates/admin/order/order_sendcloud_action.html.twig` — la structure HTML actuelle suffit
  (les classes `.sendcloud-shipping-block`, `.select-sendcloud-shipping`,
  `.select-sendcloud-servicepoint` sont les points d'ancrage du JS ; le loader inline est créé
  dynamiquement, aucun ajout Twig n'est nécessaire).
- `src/Controller/Admin/OrderCrudController.php` — endpoints `shipping-options` (ligne 433) et
  `service-points` (ligne 462) inchangés ; payloads déjà adaptés.

## Étapes

1. **SCSS — généraliser le spinner et ajouter les styles** (`assets/back/scss/back.scss`)
   Modifier le sélecteur ligne 124 (`#loader-1` → `#loader-1, .loader-spin`) et ajouter les blocs
   `.sendcloud-loading-overlay` et `.sendcloud-sp-loader` après la ligne 159.

2. **JS — overlay global + collecte des promesses** (`assets/back/js/back.js`)
   Remplacer le bloc `back.js:284-355` par la version ci-dessus : garde `if (length > 0)`,
   création de l'overlay, tableau `shippingOptionPromises`, `Promise.allSettled(...)` → retrait de
   l'overlay.

3. **JS — loader inline par ligne** (même remplacement, `maybeLoadServicePoints`)
   Créer le `spLoader`, l'afficher avant le `fetch` `service-points`, le masquer via `.finally`
   et dans la branche « pas de point relais requis » ; masquer le sous-select pendant le
   chargement.

4. **Build des assets** — recompiler le bundle Webpack Encore (voir Vérification). `back.js` et
   `back.scss` sont bundlés (`import '../scss/back.scss'` en tête de `back.js`) ; sans build, les
   modifications ne sont pas prises en compte par le navigateur.

5. **Log d'action** — ajouter une entrée dans `logs/src-eurocommemo.md` (règle action-logging)
   décrivant les fichiers touchés et le statut.

## Vérification

**Build** (via `scripts/repo_exec.py`, conformément à CLAUDE.md — jamais d'appel direct à
`yarn`/`encore`) :

```sh
# Build de production
scripts/repo_exec.py src-eurocommemo -- yarn build
# ou, en développement avec rechargement :
scripts/repo_exec.py src-eurocommemo -- yarn watch
```

(Scripts npm disponibles : `dev`, `watch`, `build` — cf. `package.json`.)

**Scénario manuel** (navigateur, éventuellement piloté via les outils `mcp__claude-in-chrome__*`) :

1. Se connecter à l'admin, ouvrir le menu **« Commandes prêtes à être expédiées »**.
2. **Loader global** : au chargement, un overlay semi-transparent avec spinner central doit
   apparaître immédiatement et **rester visible tant qu'au moins un** appel
   `GET /fr/admin/order/{ID}/sendcloud/shipping-options` est en cours. Vérifier dans l'onglet
   Réseau que l'overlay disparaît **après** la dernière réponse `shipping-options`. Sur une page
   sans aucune ligne eBay Sendcloud, l'overlay ne doit pas apparaître (garde `length > 0`).
3. **Selects peuplés** : une fois l'overlay parti, chaque select de méthode contient bien ses
   options et la valeur persistée (`data-current`) est présélectionnée.
4. **Loader inline** : sur une ligne, choisir une méthode nécessitant un point relais (ex.
   Mondial Relay, `data-requires-sp="1"`). Un petit spinner doit s'afficher à l'emplacement du
   sous-select pendant l'appel `GET .../service-points?carrier=…`, puis disparaître et laisser
   place au sous-select peuplé (« — Choisir un point relais — » + points). Choisir ensuite une
   méthode **sans** point relais : le sous-select et le loader inline doivent être masqués sans
   appel réseau superflu.
5. **Robustesse erreur** : simuler une réponse `{error: …}` ou un échec réseau sur un appel
   `shipping-options` (throttling / offline ponctuel) — l'overlay doit tout de même se retirer
   (grâce à `Promise.allSettled` + `.catch`), la page ne doit pas rester bloquée sous l'overlay.
   De même, un échec sur `service-points` doit masquer le loader inline (`.finally`).
6. **Non-régression** : le bouton « Enregistrer sur Sendcloud » et le bloc de génération
   d'étiquette (`back.js:357+`) fonctionnent comme avant.
