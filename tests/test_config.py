# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 abel0x <https://github.com/abel0x>
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from steamledger.config import Config, ConfigError, load_config, mask_key

KEY = "0123456789ABCDEF0123456789ABCDEF"
ID64 = "76561197960287930"


class ConfigTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "config.json"

    def load_text(self, text: str) -> Config:
        self.path.write_text(text, encoding="utf-8")
        return load_config(self.path)

    def test_missing_file_gives_defaults(self) -> None:
        config = load_config(self.path)
        self.assertEqual(config.get("media.achievement_icons"), "unlocked")
        self.assertFalse(config.is_configured)

    def test_partial_file_keeps_the_other_defaults(self) -> None:
        config = self.load_text('{"collect": {"friends": false}}')
        self.assertFalse(config.get("collect.friends"))
        self.assertTrue(config.get("collect.wishlist"))

    def test_notepad_bom_is_accepted(self) -> None:
        config = self.load_text('﻿{"language": "tr"}')
        self.assertEqual(config.language, "tr")

    def test_broken_json_reports_where(self) -> None:
        with self.assertRaises(ConfigError) as caught:
            self.load_text('{\n  "language": tr\n}')
        self.assertEqual(caught.exception.key, "syntax")
        self.assertEqual(caught.exception.params["line"], 2)

    def test_not_an_object(self) -> None:
        with self.assertRaises(ConfigError) as caught:
            self.load_text("[]")
        self.assertEqual(caught.exception.key, "syntax")

    def test_invalid_values_name_the_option(self) -> None:
        cases = {
            '{"api_key": "short"}': ("api_key", None),
            '{"steam_id": "gaben"}': ("steam_id", None),
            '{"media": {"achievement_icons": "some"}}': ("choice", "media.achievement_icons"),
            '{"media": {"achievement_icon_limit": -1}}': ("number", "media.achievement_icon_limit"),
            '{"media": {"achievement_icon_limit": true}}': (
                "number",
                "media.achievement_icon_limit",
            ),
            '{"output": {"csv_delimiter": "|"}}': ("choice", "output.csv_delimiter"),
            '{"network": {"workers": 0}}': ("number", "network.workers"),
            '{"network": {"timeout": "fast"}}': ("number", "network.timeout"),
        }
        for text, (key, option) in cases.items():
            with self.subTest(text=text), self.assertRaises(ConfigError) as caught:
                self.load_text(text)
            self.assertEqual(caught.exception.key, key)
            if option:
                # A placeholder named "key" must reach the message intact.
                self.assertEqual(caught.exception.params["key"], option)

    def test_environment_overrides_the_file(self) -> None:
        config = Config(self.path, {"api_key": "a" * 32, "steam_id": ID64})
        with mock.patch.dict(os.environ, {"STEAM_API_KEY": KEY, "STEAM_ID": " 1 "}):
            self.assertEqual(config.api_key, KEY)
            self.assertEqual(config.steam_id, "1")
        with mock.patch.dict(os.environ, {"STEAM_API_KEY": "", "STEAM_ID": ""}):
            self.assertEqual(config.api_key, "a" * 32)

    def test_set_creates_nested_options(self) -> None:
        config = Config(self.path)
        config.set("collect.friends", False)
        config.set("extra.deep.value", 1)
        self.assertFalse(config.get("collect.friends"))
        self.assertEqual(config.get("extra.deep.value"), 1)
        self.assertIsNone(config.get("collect.friends.nothing"))

    def test_save_round_trip(self) -> None:
        config = Config(self.path, {"api_key": KEY, "steam_id": ID64})
        config.save()
        self.assertEqual(load_config(self.path).steam_id, ID64)
        if sys.platform != "win32":
            self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)

    def test_mask_key(self) -> None:
        self.assertEqual(mask_key(KEY), "0123…CDEF")
        self.assertEqual(mask_key("abc"), "***")
        self.assertEqual(mask_key(""), "")


if __name__ == "__main__":
    unittest.main()
