"""Unit tests for i18n."""
from __future__ import annotations

import pytest

from nationcraft.core.i18n import I18n


@pytest.fixture
def i18n_instance() -> I18n:
    i = I18n(base_dir="locales", default_locale="en")
    i.load()
    return i


def test_lookup_english(i18n_instance: I18n) -> None:
    assert i18n_instance.t("common.welcome", locale="en", username="Alice") == "Welcome to NationCraft, Alice!"


def test_lookup_farsi(i18n_instance: I18n) -> None:
    assert "NationCraft" in i18n_instance.t("common.welcome", locale="fa", username="Bob")


def test_fallback_to_default(i18n_instance: I18n) -> None:
    # Unknown key returns the key itself.
    assert i18n_instance.t("does.not.exist", locale="en") == "does.not.exist"


def test_rtl_detection(i18n_instance: I18n) -> None:
    assert i18n_instance.is_rtl("fa") is True
    assert i18n_instance.is_rtl("en") is False
    assert i18n_instance.direction("fa") == "rtl"
    assert i18n_instance.direction("en") == "ltr"


def test_number_formatting(i18n_instance: I18n) -> None:
    assert i18n_instance.format_number(1234567, "en") == "1,234,567"
    # Persian digits substitution.
    fa = i18n_instance.format_number(1234567, "fa")
    assert "۱" in fa


def test_available_locales(i18n_instance: I18n) -> None:
    locales = i18n_instance.available_locales()
    assert "en" in locales
    assert "fa" in locales


def test_pluralization_unsupported(i18n_instance: I18n) -> None:
    # Catalog uses simple strings; plural lookup returns the string as-is.
    out = i18n_instance.t("errors.rate_limited", locale="en", count=1)
    assert isinstance(out, str)
    assert "fast" in out
