# Plan — Boost Delcampe (TRELLO-5W1Csy08)
_Generated: 2026-06-16 — run-15062026-001_

## Context

Implement Delcampe boost business rules on `src-esp`:
- 100-day configurable re-listing delay (configurable parameter)
- Immediate re-listing exception for products sold directly on Delcampe with restock
- Other-platform sales → 100-day rule always applies
- Single-category constraint per product at any time
- Round-robin category rotation: country → theme1 → theme2 → … at each boost
- One-off idempotent console command to close products currently in >1 category

## Key findings from codebase

| Element | Location | Note |
|---|---|---|
| `BoostProductsOnDelcampeUseCase` | `src/Domain/Product/BoostProductsOnDelcampeUseCase.php` | Currently creates one listing **per child category** — must become single-category with rotation |
| `ProductDelcampe` entity | `src/Entity/ProductDelcampe.php` | Has `startedAt` (with hidden +1h setter), `categoryDelcampe`. No `last_boost_at` on `Product` yet |
| `Category::CACHE_KEY_COUNTRY` / `CACHE_KEY_THEME` | `src/Entity/Category.php:25-26` | Country vs theme distinction already modelled |
| `CategoryRepository::listChildStampCategories()` | `src/Repository/CategoryRepository.php` | Used by boost use case to get eligible categories |
| `CleanDoubleDelcampeProductCommand` | `src/Command/Delcampe/CleanDoubleDelcampeProductCommand.php` | Existing cleanup — distinct from new multi-category cleanup |
| `ProductDelcampeRepository` | `src/Repository/ProductDelcampeRepository.php` | Has `findDuplicates()`, `findDuplicateDelcampeIds()` — reuse pattern |

## Files to create / modify

### New files
| File | Purpose |
|---|---|
| `src/Command/Delcampe/CloseMultiCategoryProductsCommand.php` | One-off idempotent command: close Delcampe listings for products with >1 category, keep country (or first if none) |
| `migrations/Version<timestamp>.php` | Add `last_boost_at` + `delcampe_boost_category_index` to `products` table |

### Modified files
| File | Change |
|---|---|
| `src/Entity/Product.php` | Add `lastBoostAt: ?DateTimeInterface` + `delcampeBoostCategoryIndex: int = 0` with Doctrine annotations |
| `src/Domain/Product/BoostProductsOnDelcampeUseCase.php` | Inject `$boostDelayDays`, add delay check, add Delcampe-sale bypass, replace multi-category loop with single-category rotation logic, update `lastBoostAt` |
| `src/Repository/ProductDelcampeRepository.php` | Add `findProductsWithMultipleCategories()` query method |
| `src/Repository/CategoryRepository.php` | Add `findOrderedDelcampeCategories(Product $product)` — country first, then themes deterministic order |
| `config/services.yaml` | Bind `$boostDelayDays: '%env(int:BOOST_DELAY_DAYS)%'` to `BoostProductsOnDelcampeUseCase` |
| `.env` (documentation only — never commit secrets) | Document `BOOST_DELAY_DAYS=100` as new variable |

## Implementation steps (in order)

1. **Entity** — add `lastBoostAt` and `delcampeBoostCategoryIndex` to `Product` (Doctrine annotations, getters/setters)
2. **Migration** — generate via `doctrine:migrations:diff`, verify SQL
3. **Repository** — `CategoryRepository::findOrderedDelcampeCategories()` (country first, then themes by id)
4. **Repository** — `ProductDelcampeRepository::findProductsWithMultipleCategories()`
5. **Config** — bind `$boostDelayDays` in `services.yaml`; document env var
6. **UseCase** — rewrite `BoostProductsOnDelcampeUseCase::execute()` with delay gate, bypass logic, single-category rotation
7. **Command** — `CloseMultiCategoryProductsCommand` (idempotent: skip products already with ≤1 category)
8. **Tests** — PHPUnit for use case (delay gate, bypass, rotation) and command (idempotence)

## Boost delay logic (pseudocode)

```
referenceDate = product.lastBoostAt ?? product.firstListedAt  // or earliest ProductDelcampe.startedAt
daysSince = today - referenceDate

if product was sold on Delcampe AND stock was replenished:
    → bypass delay, allow immediate re-listing
elif daysSince < boostDelayDays:
    → throw BoostTooEarlyException (or return early)
else:
    → proceed with boost
```

## Category rotation logic (pseudocode)

```
categories = [countryCategory, ...themeCategories]  // ordered, deterministic
index = product.delcampeBoostCategoryIndex % categories.length
activeCategory = categories[index]
// after successful boost:
product.delcampeBoostCategoryIndex = index + 1
product.lastBoostAt = now()
```

## Verification

1. Run `php bin/console doctrine:migrations:diff` inside container — should produce non-empty migration
2. Run `php bin/console doctrine:migrations:migrate` — applies without error
3. Run `php bin/phpunit` — all new tests green, no regression
4. Run `php vendor/bin/phpstan analyse --no-progress` — no new errors at level 6
5. Manually test: call `BoostProductsOnDelcampeUseCase::execute()` on a product < 100 days old → blocked
6. Run `php bin/console app:close-multi-category-delcampe-products` twice → idempotent (second run: 0 changes)
