# DAG — AI Batch Admin Screens

**Run**: run-18062026-001 · **Ticket**: MANUAL-ai-batch-admin
**Repo**: src-esp · **Branch**: feature/ai-batch-admin → develop
**Risk**: low · **Complexity**: simple · **review_position**: after_tests

## Intent

Read-only EasyAdmin screen in `src-esp` to monitor `AiBatchJob`: columns
(id, createdAt, workflowType, step, status, processingStatus, requestCount,
succeededCount, failedCount, externalId) + item count + progress bar. ROLE_ADMIN only.

## DAG

```
read-src-esp → diff-src-esp → prs
  (code-reader) (diff-writer)  (pr-builder)
                  write/php

  (test-src-esp + review-src-esp + validate-src-esp SKIPPED —
   user requested no test generation, no code review, no validation)
```

| id | skill | sub_skill | depends_on | notes |
|----|-------|-----------|------------|-------|
| read-src-esp | code-reader | — | — | graphify first; AiBatchJob/Item entities, DashboardController, ProductTemporaryCrudController pattern |
| diff-src-esp | diff-writer | write/php | read | new controller + twig + dashboard menu; read-only; ROLE_ADMIN; annotations only |
| ~~test-src-esp~~ | test-generator | — | — | SKIPPED — user requested no test generation |
| ~~review-src-esp~~ | code-reviewer | — | — | SKIPPED — user requested no code review |
| ~~validate-src-esp~~ | validator | — | — | SKIPPED — user requested no validation |
| prs | pr-builder | — | diff | branch feature/ai-batch-admin → develop |

## Files

- **NEW** `src/Controller/Admin/OpenAI/AiBatchJobCrudController.php`
- **NEW** `templates/admin/openai-batch/crud/index.html.twig`
- **MODIFY** `src/Controller/Admin/DashboardController.php`

## Constraints

- Doctrine annotations only (no PHP 8 ORM attributes)
- Do NOT renumber prompt steps 501–511; do NOT touch async OpenAI handlers
- Guard division by zero in progress bar when requestCount = 0
- EasyAdmin 3.5 `AbstractCrudController` pattern (follow `ProductTemporaryCrudController`)

## Verification

1. `composer install` — exits 0
2. `php vendor/bin/phpstan analyse --no-progress` — no new errors
3. `php bin/phpunit` — no regression
4. `/admin` → "Batch IA" menu visible (ROLE_ADMIN), list renders with all columns + progress
5. Filters (status, workflowType, createdAt) + sort createdAt DESC work; no New/Edit/Delete buttons
