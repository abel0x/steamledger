# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 abel0x <https://github.com/abel0x>
"""Translations for the command line, the HTML reports and the site.

Every user-facing string lives in ``locales/<code>.json``. English is the source
language; a key missing from another language falls back to English, so a partial
translation never breaks anything. Plural forms use the CLDR categories ("one",
"other", ...) and messages use ``{name}`` placeholders - the same format the
site's JavaScript reads. Numbers, percentages and dates are formatted with the
conventions in each catalog's ``format`` section, never with the process locale,
which is unreliable on Windows.
"""

from __future__ import annotations

import contextlib
import datetime as dt
import functools
import json
import locale
import os
import re
import sys
from typing import Any

from .paths import LOCALES_DIR
from .util import from_unix, parse_iso

DEFAULT_LANGUAGE = "en"
PLURAL_CATEGORIES = frozenset({"zero", "one", "two", "few", "many", "other"})

# CLDR cardinal plural rules (integer operands) for the shipped languages.
_PLURAL_RULES = {
    "en": lambda n: "one" if n == 1 else "other",
    "tr": lambda n: "one" if n == 1 else "other",
}

# Windows primary language ids (LANGID & 0x3FF) for the shipped languages.
_WINDOWS_LANGS = {0x09: "en", 0x1F: "tr"}
# locale.getlocale() on Windows returns names such as 'Turkish_Türkiye'.
_LOCALE_ALIASES = {"english": "en", "turkish": "tr"}

# Namespaces shipped to the browser.
WEB_NAMESPACES = ("web.", "data.", "units.", "diff.")


@functools.cache
def available_languages() -> tuple[str, ...]:
    codes = sorted(path.stem for path in LOCALES_DIR.glob("*.json"))
    if DEFAULT_LANGUAGE in codes:
        codes.remove(DEFAULT_LANGUAGE)
        codes.insert(0, DEFAULT_LANGUAGE)
    return tuple(codes)


@functools.cache
def load_catalog(code: str) -> dict[str, Any]:
    with open(LOCALES_DIR / f"{code}.json", encoding="utf-8") as handle:
        return json.load(handle)


def is_plural(value: Any) -> bool:
    return isinstance(value, dict) and "other" in value and set(value) <= PLURAL_CATEGORIES


def flatten(tree: dict[str, Any], prefix: str = "") -> dict[str, Any]:
    flat: dict[str, Any] = {}
    for key, value in tree.items():
        name = f"{prefix}{key}"
        if isinstance(value, dict) and not is_plural(value):
            flat.update(flatten(value, name + "."))
        else:
            flat[name] = value
    return flat


def plural_category(lang: str, count: Any) -> str:
    try:
        number = abs(float(count))
    except (TypeError, ValueError):
        return "other"
    rule = _PLURAL_RULES.get(lang)
    if rule is None or number != int(number):
        return "other"
    return rule(int(number))


def normalize(code: str | None) -> str:
    """'tr_TR.UTF-8', 'tr-TR', 'Turkish_Türkiye' -> 'tr'."""
    if not code:
        return ""
    base = re.split(r"[-_.@:]", code.strip(), maxsplit=1)[0].lower()
    return _LOCALE_ALIASES.get(base, base)


def system_languages() -> list[str]:
    found = []
    for var in ("LANGUAGE", "LC_ALL", "LC_MESSAGES", "LANG"):
        for part in os.environ.get(var, "").split(":"):
            code = normalize(part)
            if code and code not in ("c", "posix"):
                found.append(code)
    if sys.platform == "win32":
        try:
            import ctypes

            langid = ctypes.windll.kernel32.GetUserDefaultUILanguage()  # type: ignore[attr-defined]
            found.append(_WINDOWS_LANGS.get(langid & 0x3FF, ""))
        except (AttributeError, OSError):
            pass
    with contextlib.suppress(ValueError):
        found.append(normalize(locale.getlocale()[0]))
    return [code for code in found if code]


def detect_language(*preferred: str | None) -> str:
    """First supported language among ``preferred`` (flag, env, config...), then the system's."""
    langs = available_languages()
    for candidate in (*preferred, *system_languages()):
        code = normalize(candidate)
        if code in langs:
            return code
    return DEFAULT_LANGUAGE


class _Params(dict):
    def __missing__(self, key: str) -> str:
        return "{" + key + "}"


class Translator:
    def __init__(self, lang: str = DEFAULT_LANGUAGE) -> None:
        if lang not in available_languages():
            lang = DEFAULT_LANGUAGE
        self.lang = lang
        catalog = load_catalog(lang)
        self.meta: dict[str, str] = catalog.get("_meta", {})
        self._strings = flatten({k: v for k, v in catalog.items() if k != "_meta"})
        if lang == DEFAULT_LANGUAGE:
            self._fallback = self._strings
        else:
            english = load_catalog(DEFAULT_LANGUAGE)
            self._fallback = flatten({k: v for k, v in english.items() if k != "_meta"})

    # ------------------------------------------------------------------ lookup

    @property
    def name(self) -> str:
        return self.meta.get("name", self.lang)

    @property
    def steam_language(self) -> str:
        """Language name the Steam Web API expects, e.g. 'turkish'."""
        return self.meta.get("steam", "english")

    def has(self, key: str) -> bool:
        return key in self._strings or key in self._fallback

    def raw(self, key: str) -> Any:
        value = self._strings.get(key)
        return self._fallback.get(key) if value is None else value

    def t(self, key: str, /, **params: Any) -> str:
        """Translate ``key``. A numeric ``count`` picks the plural form and is shown
        formatted for the language (1,234 / 1.234)."""
        value = self.raw(key)
        if value is None:
            return key
        if is_plural(value):
            value = value.get(plural_category(self.lang, params.get("count", 0))) or value["other"]
        if not params:
            return str(value)
        count = params.get("count")
        if isinstance(count, (int, float)) and not isinstance(count, bool):
            params["count"] = self.number(count)
        return str(value).format_map(_Params(params))

    def bundle(self, prefixes: tuple[str, ...] = WEB_NAMESPACES) -> dict[str, Any]:
        """Flat catalog for the browser, English filled in where a key is missing."""
        merged = {**self._fallback, **self._strings}
        return {k: v for k, v in merged.items() if k.startswith(prefixes)}

    # ------------------------------------------------------------------ format

    def number(self, value: float, decimals: int = 0) -> str:
        text = f"{value:,.{decimals}f}"
        group = self.raw("format.group") or ","
        decimal = self.raw("format.decimal") or "."
        return text.replace(",", "\0").replace(".", decimal).replace("\0", group)

    def percent(self, value: float, decimals: int = 1) -> str:
        return self.t("format.percent", value=self.number(value, decimals))

    def playtime(self, minutes: Any) -> str:
        minutes = int(minutes or 0)
        if minutes < 60:
            return self.t("units.minutes", count=minutes)
        return self.t("units.hours", value=self.number(minutes / 60, 1))

    def signed_playtime(self, minutes: int) -> str:
        sign = "+" if minutes >= 0 else "−"
        return sign + self.playtime(abs(minutes))

    def date(self, value: Any) -> str:
        moment = _as_local(value)
        if moment is None:
            return ""
        return self.t(
            "format.date",
            day=moment.day,
            month=self.raw("format.months_short")[moment.month - 1],
            year=moment.year,
        )

    def datetime(self, value: Any) -> str:
        moment = _as_local(value)
        if moment is None:
            return ""
        return self.t(
            "format.datetime",
            day=moment.day,
            month=self.raw("format.months_short")[moment.month - 1],
            year=moment.year,
            hour=f"{moment.hour:02d}",
            minute=f"{moment.minute:02d}",
        )

    def span(self, days: float) -> str:
        """Length of a period: '3 hours', '29 days'."""
        if days < 1:
            return self.t("units.hours_long", count=max(1, round(days * 24)))
        return self.t("units.days", count=round(days))


def _as_local(value: Any) -> dt.datetime | None:
    if isinstance(value, dt.datetime):
        return value.astimezone()
    if isinstance(value, str) and not value.isdigit():
        try:
            return parse_iso(value).astimezone()
        except ValueError:
            return None
    return from_unix(value)
