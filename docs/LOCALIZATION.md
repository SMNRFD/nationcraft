# Localization Guide

NationCraft ships with English (`en`) and Persian (`fa`) catalogs.
Adding a new language takes three steps.

## 1. Catalog file layout

```
locales/
├── en/
│   └── catalog.yaml
└── fa/
    └── catalog.yaml
```

Each `catalog.yaml` is a flat YAML file with namespaced keys:

```yaml
common:
  welcome: "Welcome to NationCraft, {username}!"
  pagination:
    prev: "Prev"
    next: "Next"
    page: "Page {current}/{total}"
errors:
  rate_limited: "You're doing that too fast. Please wait."
```

## 2. Look-up API

```python
from nationcraft.core.i18n import _, i18n

# Translate a key for the user's locale.
text = _("common.welcome", locale="en", username="alice")
# "Welcome to NationCraft, alice!"

# With pluralization (count drives plural rule).
text = _("country.population", locale="en", count=5)
```

## 3. Adding a new language

1. Pick an [ISO 639-1](https://en.wikipedia.org/wiki/List_of_ISO_639-1_codes) code (e.g. `ar` for Arabic).
2. Create `locales/ar/catalog.yaml` and translate every key.
3. Add `ar` to `SUPPORTED_LOCALES` in your `.env`:
   ```
   SUPPORTED_LOCALES=en,fa,ar
   ```
4. Add a plural rule in `core/i18n/manager.py::_PLURAL_RULES` if your
   language has more than the simple one/other distinction (e.g. Arabic
   has 6 plural forms — see [CLDR plural rules](https://www.unicode.org/cldr/charts/latest/supplemental/language_plural_rules.html)).
5. If your language is RTL, add its code to `_RTL_LOCALES`.
6. Reload via `POST /admin/game-data/reload` or restart the API.

## 4. Pluralization

The catalog can specify plural variants as a dict:

```yaml
country:
  units:
    one: "You have {count} unit."
    other: "You have {count} units."
```

The `i18n.t(key, count=N)` call picks the right variant based on the
locale's plural rule.

## 5. Number formatting

```python
i18n.format_number(1234567.89, locale="en")  # "1,234,567.89"
i18n.format_number(1234567, locale="fa")     # "۱،۲۳۴،۵۶۷"
```

Persian digits are automatically substituted for `fa` locale.

## 6. Direction

```python
i18n.is_rtl("fa")    # True
i18n.direction("fa") # "rtl"
i18n.direction("en") # "ltr"
```

The bot can use this to wrap messages in appropriate Unicode marks if
needed. aiogram handles most RTL rendering automatically.

## 7. Fallback

If a key is missing in the requested locale, `i18n.t()` falls back to
the default locale (`DEFAULT_LOCALE`, default `en`). If still missing,
it returns the key itself (useful for spotting untranslated keys
during development).

## 8. Hot reload

Catalogs are loaded lazily on first access and cached. To reload
without restart, call `i18n.load()` (or trigger via the admin reload
endpoint, which also reloads game data).
