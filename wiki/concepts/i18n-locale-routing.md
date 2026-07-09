---
title: "Concept: locale routing & translatable entities"
type: concept
status: stable
sources:
  - src-eurocommemo/CLAUDE.md
related:
  - src-eurocommemo
  - eurocommemo-symfony
updated: 2026-06-27
---

How `src-eurocommemo` handles its three locales (`fr`, `en`, `de`) at the routing layer and in
the data model.

## Routing

- **Front-end routes** carry a `/{_locale}` prefix (supported `fr`, `en`, `de`; default `fr`)
  — defined in `config/routes.yaml`.
- **Admin routes** (EasyAdmin) do **not** carry a locale prefix; admin access is gated by
  `ROLE_ADMIN` on `^/({locale})/admin`.
- The eBay webhook `POST /ebay/notification` has no locale prefix either.

## Translatable entities (KnpLabs DoctrineBehaviors)

Translatable entities implement `TranslatableInterface` via `TranslatableTrait` and have a
paired `*Translation` entity. Translation fetch mode is **EAGER** globally
(`doctrine_behaviors_translation_fetch_mode`). Always call `->translate('fr')->getX()`
explicitly in `__toString()` and `getX()` shortcuts.

Entities with translations include: `Product`/`ProductTranslation` (holds `title`, `path`
slug, `shortTitle`, `resume`, `description`), `Category`, `Away`, `CategoryFilter`, `Country`,
`CountryZone`, `CountryZoneCommune`, `Faq`, `Footer` (via `FooterLink`), `HomePage`, `Page`,
`Selection`, `ServiceContact`.

Pattern for a new translatable entity (also implement `TimestampableInterface`):

```php
class MyEntity implements TranslatableInterface, TimestampableInterface
{
    use TranslatableTrait;
    use TimestampableTrait;
    public function getTitle(): ?string { return $this->translate('fr')->getTitle(); }
    public function __call($m, $a) { return $this->proxyCurrentLocaleTranslation($m, $a); }
    public function __toString(): string { return $this->translate('fr')->getTitle(); }
}
```

## In EasyAdmin

Use `TranslationField::new('translations', '', $fieldsconfig)` and add
`@A2lixTranslationForm/bootstrap_5_layout.html.twig` to `setFormThemes()` in
`configureCrud()`. See [[eurocommemo-symfony]]. Translation files live under `translations/`
(fr/en/de).
