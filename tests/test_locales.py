# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 abel0x <https://github.com/abel0x>
import json
import re
import unittest
from pathlib import Path
from typing import Any

PACKAGE = Path(__file__).resolve().parent.parent / "steamledger"
LOCALES = PACKAGE / "locales"
PLACEHOLDER = re.compile(r"\{(\w+)\}")
# t("web.games.title"), tr.t('cli.list.empty'), self.tr.raw("report.readme")...
USED_KEY = re.compile(r"""\b(?:t|raw|has)\(\s*["']([a-z_]+(?:\.[a-z0-9_]+)+)["']""")
PLURAL = {"zero", "one", "two", "few", "many", "other"}


def flatten(tree: dict[str, Any], prefix: str = "", *, leaves: bool = True) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in tree.items():
        if isinstance(value, dict) and (leaves or not set(value) <= PLURAL):
            out.update(flatten(value, f"{prefix}{key}.", leaves=leaves))
        else:
            out[prefix + key] = value
    return out


def load(name: str) -> dict[str, Any]:
    return flatten(json.loads((LOCALES / f"{name}.json").read_text(encoding="utf-8")))


class LocaleTest(unittest.TestCase):
    def test_turkish_matches_english(self) -> None:
        en, tr = load("en"), load("tr")
        self.assertEqual(sorted(set(en) - set(tr)), [], "missing in tr.json")
        self.assertEqual(sorted(set(tr) - set(en)), [], "only in tr.json")
        for key, text in en.items():
            with self.subTest(key=key):
                self.assertEqual(type(tr[key]), type(text))
                if isinstance(text, str):
                    self.assertEqual(
                        set(PLACEHOLDER.findall(tr[key])), set(PLACEHOLDER.findall(text))
                    )

    def test_every_key_the_code_uses_exists(self) -> None:
        catalog = json.loads((LOCALES / "en.json").read_text(encoding="utf-8"))
        known = set(flatten(catalog, leaves=False))
        sources = [*PACKAGE.glob("*.py"), *PACKAGE.glob("web/assets/*.js")]
        checked = 0
        for source in sources:
            for key in USED_KEY.findall(source.read_text(encoding="utf-8")):
                checked += 1
                with self.subTest(source=source.name, key=key):
                    self.assertIn(key, known)
        self.assertGreater(checked, 400)  # the pattern still finds the calls


if __name__ == "__main__":
    unittest.main()
