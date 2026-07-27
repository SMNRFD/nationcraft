"""I18n manager: loads YAML translation catalogs, supports pluralization & direction."""
from __future__ import annotations

import math
import re
from pathlib import Path
from typing import Any

import yaml

from nationcraft.core.logging import get_logger

log = get_logger(__name__)

_PLURAL_RULES = {
    "en": lambda n: "one" if n == 1 else "other",
    "fa": lambda n: "one" if n == 1 else "other",
}

_RTL_LOCALES = {"fa", "ar", "he", "ur"}


class I18n:
    """Translation catalog with locale fallback."""

    def __init__(self, base_dir: str | Path = "locales", default_locale: str = "en") -> None:
        self.base_dir = Path(base_dir)
        self.default_locale = default_locale
        self._catalogs: dict[str, dict[str, Any]] = {}
        self._loaded = False

    def load(self) -> None:
        for path in self.base_dir.glob("*/catalog.yaml"):
            locale = path.parent.name
            with path.open("r", encoding="utf-8") as f:
                self._catalogs[locale] = yaml.safe_load(f) or {}
        self._loaded = True
        log.info("i18n.loaded", locales=list(self._catalogs))

    def _ensure(self) -> None:
        if not self._loaded:
            self.load()

    def t(
        self,
        key: str,
        *,
        locale: str | None = None,
        count: int | None = None,
        **vars: Any,
    ) -> str:
        """Translate ``key`` for ``locale`` with optional plural form & interpolation."""
        self._ensure()
        locale = locale or self.default_locale
        cat = self._catalogs.get(locale) or self._catalogs.get(self.default_locale, {})
        text = self._lookup(cat, key)
        if text is None:
            return key

        if count is not None and isinstance(text, dict):
            rule = _PLURAL_RULES.get(locale, _PLURAL_RULES[self.default_locale])
            text = text.get(rule(count), text.get("other", str(count)))

        if vars:
            try:
                text = text.format(**vars)
            except (KeyError, IndexError):
                pass
        return str(text)

    def _lookup(self, catalog: dict[str, Any], key: str) -> Any:
        cur: Any = catalog
        for part in key.split("."):
            if not isinstance(cur, dict) or part not in cur:
                return None
            cur = cur[part]
        return cur

    def is_rtl(self, locale: str) -> bool:
        return locale.split("-")[0].lower() in _RTL_LOCALES

    def direction(self, locale: str) -> str:
        return "rtl" if self.is_rtl(locale) else "ltr"

    def available_locales(self) -> list[str]:
        self._ensure()
        return list(self._catalogs)

    def format_number(self, n: float, locale: str | None = None) -> str:
        locale = locale or self.default_locale
        if isinstance(n, float) and n.is_integer():
            n = int(n)
        if locale == "fa":
            return self._to_persian_digits(f"{n:,}")
        return f"{n:,}"

    def _to_persian_digits(self, s: str) -> str:
        return s.translate(str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹"))


# Singleton
i18n = I18n(base_dir="locales", default_locale="en")


def _(key: str, *, locale: str | None = None, count: int | None = None, **vars: Any) -> str:
    """Shorthand for ``i18n.t(...)``."""
    return i18n.t(key, locale=locale, count=count, **vars)
