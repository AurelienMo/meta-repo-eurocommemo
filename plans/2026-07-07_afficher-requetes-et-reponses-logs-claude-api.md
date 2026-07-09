# Plan — Afficher requêtes et réponses sur la vue détail des logs Claude API (2026-07-07)

**Run** : N/A · **Ticket** : N/A · **Repo(s)** : src-esp · **Branche** : feature/claude-api-log-response-content → main · **Risk** : low · **Complexité** : simple

## Contexte

Sur la vue « consulter » (detail EasyAdmin) d'un log Claude (`ClaudeApiLog`), on veut voir le
contenu des requêtes envoyées à l'API Anthropic **et** leur réponse.

État actuel dans `src-esp` (`/Users/aurelienmorvan/OrbStack/docker/volumes/src-esp`) :

- L'entité `ClaudeApiLog` (`src/Entity/OpenAI/ClaudeApiLog.php`) stocke `requestPayload` (json)
  et `responseUsage` (tokens), mais **jamais le contenu de la réponse**.
- La vue détail (`src/Controller/Admin/OpenAI/ClaudeApiLogCrudController.php:69-71`) affiche déjà
  le payload de requête en JSON pretty-print.
- Pour un log `batch_submit`, seule la **première** requête du batch est stockée
  (`ClaudeApiConnector.php:138` → `$requests[0]['params']`), et les réponses arrivent en différé
  dans `PollAiBatchHandler` sans lien retour vers le log.

**Décision utilisateur (2026-07-06)** : option « Complet » pour les batchs — stocker toutes les
requêtes (`custom_id` + payload) à la soumission, puis rattacher les réponses par item
(`custom_id` + contenu + usage/erreur) au log via `batchExternalId` à la fin du polling.

**Contrainte utilisateur (2026-07-07)** : les migrations Doctrine ne sont **jamais exécutées par
Claude** — elles sont jouées manuellement.

Conventions à respecter : annotations Doctrine uniquement (pas d'attributs PHP 8),
commandes via `scripts/repo_exec.py` (mode compose, service `php-fpm-per80`).

## Fichiers concernés

Tous les fichiers sont dans le repo **src-esp**.

### Nouveaux

| Fichier | Rôle |
|---------|------|
| `migrations/Version20260707XXXXXX.php` | Ajout colonnes `response_content`, `response_received_at` + index sur `batch_external_id` |

Migration (générer via `doctrine:migrations:diff` après modification de l'entité, ou manuelle —
le timestamp `XXXXXX` sera celui de la génération) :

```php
<?php

declare(strict_types=1);

namespace DoctrineMigrations;

use Doctrine\DBAL\Schema\Schema;
use Doctrine\Migrations\AbstractMigration;

final class Version20260707XXXXXX extends AbstractMigration
{
    public function getDescription(): string
    {
        return 'Add response_content and response_received_at to claude_api_log + index on batch_external_id';
    }

    public function up(Schema $schema): void
    {
        $this->addSql('ALTER TABLE claude_api_log ADD response_content JSON DEFAULT NULL, ADD response_received_at DATETIME DEFAULT NULL');
        $this->addSql('CREATE INDEX idx_claude_api_log_batch_external ON claude_api_log (batch_external_id)');
    }

    public function down(Schema $schema): void
    {
        $this->addSql('DROP INDEX idx_claude_api_log_batch_external ON claude_api_log');
        $this->addSql('ALTER TABLE claude_api_log DROP response_content, DROP response_received_at');
    }
}
```

### Modifiés

| Fichier | Changement |
|---------|-----------|
| `src/Entity/OpenAI/ClaudeApiLog.php` | 2 nouveaux champs json/datetime + index en annotation + getters/setters |
| `src/Api/Connector/AI/ClaudeApiConnector.php` | `persistLog()` étendu, réponses transmises, batch complet stocké, nouvelle méthode `attachBatchResults()` |
| `src/Messenger/Handler/AI/PollAiBatchHandler.php` | Appel `attachBatchResults()` après récupération des résultats |
| `src/Controller/Admin/OpenAI/ClaudeApiLogCrudController.php` | Affichage `responseContent` + `responseReceivedAt` sur la vue détail |

#### 1. `src/Entity/OpenAI/ClaudeApiLog.php`

Mettre à jour l'annotation de classe (lignes 8-11) pour déclarer l'index (garde
`doctrine:schema:validate` cohérent avec la migration) :

```php
/**
 * @ORM\Entity(repositoryClass=ClaudeApiLogRepository::class)
 * @ORM\Table(name="claude_api_log", indexes={
 *     @ORM\Index(name="idx_claude_api_log_batch_external", columns={"batch_external_id"})
 * })
 */
```

Ajouter les propriétés après `$errorMessage` (ligne 64), dans le style annotations des champs
voisins :

```php
/**
 * @ORM\Column(type="json", nullable=true)
 */
private ?array $responseContent = null;

/**
 * @ORM\Column(type="datetime", nullable=true)
 */
private ?\DateTime $responseReceivedAt = null;
```

Getters/setters à la fin de la classe (même style fluent que les existants) :

```php
public function getResponseContent(): ?array
{
    return $this->responseContent;
}

public function setResponseContent(?array $responseContent): self
{
    $this->responseContent = $responseContent;
    return $this;
}

public function getResponseReceivedAt(): ?\DateTime
{
    return $this->responseReceivedAt;
}

public function setResponseReceivedAt(?\DateTime $responseReceivedAt): self
{
    $this->responseReceivedAt = $responseReceivedAt;
    return $this;
}
```

Sémantique de `responseContent` selon `requestType` :
- `single`, `single_with_cache`, `prewarm` : réponse API décodée complète (`$data` — inclut
  `content`, `stop_reason`, `usage`…).
- `batch_submit` : tableau d'items `[{custom_id, type, content?, usage?, error?}]`, rattaché à la
  fin du polling ; `null` tant que le batch n'est pas terminé.

#### 2. `src/Api/Connector/AI/ClaudeApiConnector.php`

**a. `persistLog()` (lignes 436-448)** — nouveau paramètre `?array $responseContent = null` :

```php
private function persistLog(
    string $type,
    array $payload,
    ?array $usage,
    ?string $batchId,
    ?int $count,
    ?string $model,
    ?string $error = null,
    ?array $responseContent = null
): void {
    $log = (new ClaudeApiLog())
        ->setRequestType($type)
        ->setRequestPayload($payload)
        ->setResponseUsage($usage)
        ->setBatchExternalId($batchId)
        ->setRequestCount($count)
        ->setModel($model)
        ->setErrorMessage($error)
        ->setResponseContent($responseContent)
        ->setResponseReceivedAt($responseContent !== null ? new \DateTime() : null);
    $this->entityManager->persist($log);
    $this->entityManager->flush();
}
```

**b. Appels succès — transmettre la réponse décodée `$data`** (les appels d'erreur dans les
`catch` restent inchangés, `errorMessage` suffit) :

- `prewarmCache()` ligne 85 :
  ```php
  $this->persistLog(ClaudeApiLog::TYPE_PREWARM, $payload, $data['usage'] ?? null, null, null, $payload['model'], null, $data);
  ```
- `sendPrompt()` ligne 250 :
  ```php
  $this->persistLog(ClaudeApiLog::TYPE_SINGLE, $payload, $usage, null, null, $payload['model'] ?? null, null, $data);
  ```
- `sendPromptWithCache()` ligne 334 :
  ```php
  $this->persistLog(ClaudeApiLog::TYPE_SINGLE_WITH_CACHE, $json, $data['usage'] ?? null, null, null, $json['model'] ?? null, null, $data);
  ```

**c. `submitBatch()` — stocker toutes les requêtes du batch** (`custom_id` + `params`) au lieu de
la première seule :

- Ligne 125 (catch) :
  ```php
  $this->persistLog(ClaudeApiLog::TYPE_BATCH_SUBMIT, $requests, null, null, count($requests), $requests[0]['params']['model'] ?? null, $e->getMessage());
  ```
- Ligne 138 (succès) :
  ```php
  $this->persistLog(ClaudeApiLog::TYPE_BATCH_SUBMIT, $requests, null, $data['id'], count($requests), $requests[0]['params']['model'] ?? null);
  ```
  `responseContent` reste `null` à la soumission ; il est renseigné à la fin du polling.

**d. Nouvelle méthode publique `attachBatchResults()`** (après `getBatchResults()`, ligne 207) —
rattache les réponses par item au log de soumission via `batchExternalId` :

```php
/**
 * @param BatchItemResultDTO[] $results
 */
public function attachBatchResults(string $batchExternalId, array $results): void
{
    $log = $this->entityManager->getRepository(ClaudeApiLog::class)->findOneBy([
        'batchExternalId' => $batchExternalId,
        'requestType'     => ClaudeApiLog::TYPE_BATCH_SUBMIT,
    ]);

    if ($log === null) {
        return;
    }

    $items = [];
    foreach ($results as $result) {
        $entry = [
            'custom_id' => $result->getCustomId(),
            'type'      => $result->getType(),
        ];
        if ($result->getType() === 'succeeded') {
            $entry['content'] = $result->getContent();
            $entry['usage']   = $result->getUsage();
        } else {
            $entry['error'] = $result->getError();
        }
        $items[] = $entry;
    }

    $log->setResponseContent($items)
        ->setResponseReceivedAt(new \DateTime());
    $this->entityManager->flush();
}
```

Points d'attention :
- Pour un item non `succeeded`, ne **jamais** appeler `getContent()`/`getUsage()`
  (`BatchItemResultDTO::getMessage()` lèverait une erreur sur clé absente) — utiliser
  `getError()` (`DTO/BatchItemResultDTO.php:66-69`).
- Idempotent : un re-poll écrase avec les mêmes données.
- `BatchItemResultDTO` est déjà importé dans le connector (ligne 5).

#### 3. `src/Messenger/Handler/AI/PollAiBatchHandler.php`

Après la récupération des résultats (ligne 107), rattacher les réponses au log :

```php
$results = $this->claudeApiConnector->getBatchResults($job->getExternalId());
$this->claudeApiConnector->attachBatchResults($job->getExternalId(), $results);
```

Aucun autre changement — les chemins timeout (ligne 65) et expiration (ligne 81) sortent avant
`getBatchResults`, le log garde alors `responseContent = null`, ce qui est correct.

#### 4. `src/Controller/Admin/OpenAI/ClaudeApiLogCrudController.php`

Dans `configureFields()`, insérer après le champ `requestPayload` (lignes 69-71), en miroir du
pattern existant :

```php
TextareaField::new('responseContent', 'Réponse')
    ->onlyOnDetail()
    ->formatValue(fn ($v) => $v ? json_encode($v, JSON_PRETTY_PRINT | JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES) : ''),
DateTimeField::new('responseReceivedAt', 'Réponse reçue le')->onlyOnDetail(),
```

Aucun import supplémentaire (`TextareaField`, `DateTimeField` déjà importés).

## Étapes d'implémentation

1. **Entité** — ajouter `responseContent`, `responseReceivedAt` et l'index d'annotation dans
   `src/Entity/OpenAI/ClaudeApiLog.php` (§ Fichiers 1).
2. **Migration** — générer/écrire `migrations/Version20260707XXXXXX.php` (§ Nouveaux).
   **Ne pas l'exécuter** : les migrations sont jouées manuellement par l'utilisateur.
3. **Connector** — dans `src/Api/Connector/AI/ClaudeApiConnector.php` : étendre `persistLog()`,
   passer `$data` aux 3 appels succès single/prewarm/cache, stocker `$requests` complet dans
   `submitBatch()`, ajouter `attachBatchResults()` (§ Fichiers 2).
4. **Poll handler** — appeler `attachBatchResults()` dans
   `src/Messenger/Handler/AI/PollAiBatchHandler.php:107` (§ Fichiers 3).
5. **Admin** — ajouter les 2 champs détail dans
   `src/Controller/Admin/OpenAI/ClaudeApiLogCrudController.php` (§ Fichiers 4).
6. **Journal** — consigner l'action dans `logs/src-esp.md` du meta-repo (règle action-logging).

Notes de périmètre :
- Les logs existants gardent `responseContent = null` (affiché vide) — pas de backfill.
- Volume : `request_payload` d'un batch contient désormais N payloads (system prompt répété par
  item). Limite pratique = `max_allowed_packet` MySQL ; acceptable pour les tailles de batch
  actuelles, à surveiller si les batchs grossissent.
- La route debug de `sendPrompt()` (`ClaudeApiConnector.php:229-234`, `dd()`) court-circuite
  toujours le log — comportement inchangé.

## DAG d'exécution

Non généré — feature mono-repo simple, séquentielle. Utiliser le skill `planner` si un DAG
machine est requis (`plans/2026-07-07_afficher-requetes-et-reponses-logs-claude-api-dag.md`).

## Vérification

Toutes les commandes depuis la racine du meta-repo, via `repo_exec.py` (jamais d'appel direct) :

1. Migration **jouée manuellement par l'utilisateur** (jamais par Claude) :
   ```sh
   # exécuté par l'utilisateur uniquement
   python3 scripts/repo_exec.py . src-esp -- php bin/console doctrine:migrations:migrate -n
   ```
   Puis cohérence schéma (lecture seule, exécutable par Claude après la migration) :
   ```sh
   python3 scripts/repo_exec.py . src-esp -- php bin/console doctrine:schema:validate
   ```
2. Compilation conteneur / cache :
   ```sh
   python3 scripts/repo_exec.py . src-esp -- php bin/console cache:clear
   ```
3. **Scénario single** : déclencher un appel single (ex. traduction via `TranslateAIUseCase`),
   puis ouvrir Admin → Logs Claude API → détail du log `single_with_cache` : le champ « Réponse »
   affiche le JSON complet de la réponse API et « Réponse reçue le » est renseigné.
4. **Scénario batch** : lancer un pipeline produit IA (submit batch), vérifier immédiatement le
   log `batch_submit` : « Payload envoyé » liste bien tous les items (`custom_id` + `params`),
   « Réponse » vide. Après fin du polling (`PollAiBatchHandler`), recharger le détail :
   « Réponse » contient un item par `custom_id` avec `content`/`usage` (ou `error` pour les items
   échoués) et « Réponse reçue le » est renseigné.
5. **Scénario erreur** : provoquer un échec API (clé invalide en env de test) et vérifier que le
   log d'erreur garde `errorMessage` avec « Réponse » vide, sans exception.
