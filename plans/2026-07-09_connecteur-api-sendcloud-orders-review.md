# Plan Review — 2026-07-09_connecteur-api-sendcloud-orders

**Verdict** : approve — 0 blocking, 2 warnings, 4 suggestions

## Annotations

| # | Axe | Localisation | Type | Message | Fix suggéré |
|---|---|---|---|---|---|
| 1 | exhaustiveness | SendcloudOrderItemDTO | warning | Le DTO omet `image_url` et 9 autres champs du schéma `order-items`. Le plan dit « champs principaux » mais ne liste pas les champs différés. | Ajouter un commentaire listant les champs différés, ou inclure `image_url`. |
| 2 | steps | SendcloudApiClientTest.php | warning | 5 scénarios listés mais seulement 2 stubs de test (pagination, config non renseignée). Scénarios sans filtre, avec order_id, et status ≠ 200 manquants. | Ajouter les 3 méthodes manquantes. |
| 3 | anchoring | SendcloudApiClient | suggestion | `DEFAULT_PAGE_SIZE = 50` vs default 100 dans la spec OpenAPI. | Confirmer l'intention ou ajuster à 100. |
| 4 | risk_format | Contexte | suggestion | « credentials lus en base à chaque requête » — le service est un singleton. | Remplacer par « credentials lus en base, mis en cache par le service ». |
| 5 | risk_format | SendcloudPriceDTO | suggestion | DTO utilisé pour `price` (value: number) et `costs-object` (value: [string, 'null']). | Documenter l'intention ou créer un DTO séparé. |
| 6 | risk_format | Tests | suggestion | Plan dit « tests/ ne contient que bootstrap.php » mais `tests/Service/Sendcloud/` existe déjà (vide). | Corriger la description. |

## Vérifications d'ancrage

| Référence | Statut |
|---|---|
| SendcloudConfiguration.php:80 — commentaire « futur connecteur API » | ✅ |
| config/services.yaml:21-28 — binds paypal/ebay | ✅ |
| ExternalEbayApiException — pattern mirror | ✅ |
| eightpoints/guzzle-bundle: ^8.5 | ✅ |
| SENDCLOUD_BASE_URL dans .env.local | ✅ |
| src/Dto/Sendcloud/ n'existe pas encore | ✅ |
| tests/Service/Sendcloud/ vide | ✅ |
| scripts/repo_exec.py | ✅ |
| Spec OpenAPI orders/openapi.yaml | ✅ |
| Pattern injection Guzzle (private readonly Client) | ✅ |
| Pattern http_errors => false + check status | ✅ |
| PHPUnit 9.5 | ✅ |

## review_report (JSON)

```json
{
  "review_report": {
    "outcome": "approve",
    "plan_path": "plans/2026-07-09_connecteur-api-sendcloud-orders.md",
    "summary": "Plan solide et bien ancré. Toutes les références code sont vérifiées. 2 warnings (champs DTO manquants, tests incomplets) et 4 suggestions mineures, aucun blocage.",
    "annotations": [
      {
        "axis": "exhaustiveness",
        "plan_location": "Fichiers concernés → SendcloudOrderItemDTO",
        "code_ref": "src/Dto/Sendcloud/SendcloudOrderItemDTO.php",
        "type": "warning",
        "message": "Le DTO omet image_url et 9 autres champs du schéma order-items. Le plan dit « champs principaux » mais ne liste pas les champs différés.",
        "suggested_fix": "Ajouter un commentaire listant les champs différés, ou inclure image_url."
      },
      {
        "axis": "steps",
        "plan_location": "Fichiers concernés → SendcloudApiClientTest.php",
        "code_ref": "tests/Service/Sendcloud/SendcloudApiClientTest.php",
        "type": "warning",
        "message": "5 scénarios listés mais seulement 2 stubs de test (pagination, config non renseignée). Scénarios sans filtre, avec order_id, et status ≠ 200 manquants.",
        "suggested_fix": "Ajouter testGetOrdersWithoutFilter, testGetOrdersWithOrderIdFilter, testGetOrdersThrowsOnNon200Status."
      },
      {
        "axis": "anchoring",
        "plan_location": "Étapes → Client Guzzle",
        "code_ref": "src/Service/Sendcloud/SendcloudApiClient.php",
        "type": "suggestion",
        "message": "DEFAULT_PAGE_SIZE = 50 alors que la spec OpenAPI définit 100 par défaut (min 1, max 200).",
        "suggested_fix": "Confirmer l'intention ou ajuster à 100 pour coller au comportement par défaut de l'API."
      },
      {
        "axis": "risk_format",
        "plan_location": "Contexte",
        "code_ref": "",
        "type": "suggestion",
        "message": "La description dit « credentials lus en base à chaque requête » mais SendcloudConfigurationService::getConfiguration() est un singleton.",
        "suggested_fix": "Remplacer par « credentials lus en base, mis en cache par le service »."
      },
      {
        "axis": "risk_format",
        "plan_location": "Fichiers concernés → SendcloudPriceDTO",
        "code_ref": "src/Dto/Sendcloud/SendcloudPriceDTO.php",
        "type": "suggestion",
        "message": "DTO utilisé pour price (value: number) et costs-object (value: [string, 'null']). Cast (float) fonctionne mais peut perdre en précision.",
        "suggested_fix": "Documenter l'intention ou créer un DTO séparé SendcloudCostsDTO."
      },
      {
        "axis": "risk_format",
        "plan_location": "Fichiers concernés → tests",
        "code_ref": "tests/Service/Sendcloud/",
        "type": "suggestion",
        "message": "Plan dit « tests/ ne contient que bootstrap.php » mais tests/Service/Sendcloud/ existe déjà (vide).",
        "suggested_fix": "Corriger la description."
      }
    ],
    "stats": { "blocking_count": 0, "warning_count": 2, "suggestion_count": 4 },
    "routing": { "retry_to": "none", "correction_brief": "" }
  }
}
```
