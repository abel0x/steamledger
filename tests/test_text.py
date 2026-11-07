# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 abel0x <https://github.com/abel0x>
"""Translation, number and date formatting, and the small helpers in util."""

import datetime as dt
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from steamledger import i18n
from steamledger.console import is_terminal
from steamledger.i18n import Translator, detect_language, normalize, plural_category
from steamledger.util import (
    UTC,
    dump_js,
    from_unix,
    human_bytes,
    local_stamp,
    parse_iso,
    write_bytes,
    write_json,
)


class TranslatorTest(unittest.TestCase):
    def test_numbers_follow_the_language(self) -> None:
        self.assertEqual(Translator("en").number(1234567.25, 1), "1,234,567.2")
        self.assertEqual(Translator("tr").number(1234567.25, 1), "1.234.567,2")
        self.assertEqual(Translator("tr").percent(12.5), "%12,5")

    def test_playtime(self) -> None:
        en = Translator("en")
        self.assertEqual(en.playtime(1), "1 min")
        self.assertEqual(en.playtime(90), "1.5 h")
        self.assertEqual(en.signed_playtime(-90), "−1.5 h")
        self.assertEqual(Translator("tr").playtime(90), "1,5 sa")

    def test_plurals_and_counts(self) -> None:
        en = Translator("en")
        self.assertEqual(en.t("units.days", count=1), "1 day")
        self.assertEqual(en.t("units.days", count=1500), "1,500 days")
        self.assertEqual(plural_category("en", 1.5), "other")
        self.assertEqual(plural_category("en", "x"), "other")

    def test_missing_keys_and_placeholders_never_raise(self) -> None:
        en = Translator("en")
        self.assertEqual(en.t("no.such.key"), "no.such.key")
        self.assertEqual(en.t("format.percent"), "{value}%")
        self.assertEqual(en.t("format.percent", other=1), "{value}%")

    def test_unknown_language_falls_back_to_english(self) -> None:
        self.assertEqual(Translator("xx").lang, "en")

    def test_dates_in_local_time(self) -> None:
        stamp = "2026-10-30T12:00:00Z"
        local = parse_iso(stamp).astimezone()
        en, tr = Translator("en"), Translator("tr")
        self.assertEqual(en.date(stamp), f"Oct {local.day}, 2026")
        self.assertEqual(tr.date(int(local.timestamp())), f"{local.day} Eki 2026")
        self.assertEqual(en.date(None), "")
        self.assertEqual(en.date("not a date"), "")

    def test_span(self) -> None:
        en = Translator("en")
        self.assertEqual(en.span(0.01), "1 hour")
        self.assertEqual(en.span(0.5), "12 hours")
        self.assertEqual(en.span(29.4), "29 days")

    def test_browser_bundle_only_carries_web_namespaces(self) -> None:
        bundle = Translator("tr").bundle()
        self.assertTrue(bundle)
        self.assertTrue(all(k.startswith(i18n.WEB_NAMESPACES) for k in bundle))


class LanguageDetectionTest(unittest.TestCase):
    def test_normalize(self) -> None:
        for raw, code in (
            ("tr_TR.UTF-8", "tr"),
            ("tr-TR", "tr"),
            ("Turkish_Türkiye", "tr"),
            ("en_US", "en"),
            ("", ""),
            (None, ""),
        ):
            with self.subTest(raw=raw):
                self.assertEqual(normalize(raw), code)

    def test_first_supported_preference_wins(self) -> None:
        self.assertEqual(detect_language(None, "auto", "de", "tr", "en"), "tr")

    def test_system_language(self) -> None:
        env = {"LANGUAGE": "", "LC_ALL": "", "LC_MESSAGES": "", "LANG": "tr_TR.UTF-8"}
        with mock.patch.dict(os.environ, env):
            self.assertEqual(detect_language(None, "auto"), "tr")


class UtilTest(unittest.TestCase):
    def test_parse_iso(self) -> None:
        expected = dt.datetime(2026, 10, 30, 12, 0, tzinfo=UTC)
        self.assertEqual(parse_iso("2026-10-30T12:00:00Z"), expected)
        self.assertEqual(parse_iso("2026-10-30T15:00:00+03:00"), expected)
        self.assertEqual(parse_iso("2026-10-30T12:00:00"), expected)

    def test_unix_stamps(self) -> None:
        self.assertIsNone(from_unix(0))
        self.assertIsNone(from_unix("garbage"))
        self.assertIsNone(from_unix(10**20))
        self.assertEqual(local_stamp(None), "")
        self.assertRegex(local_stamp(1_700_000_000), r"^2023-11-1\d \d\d:\d\d:\d\d$")

    def test_dump_js_cannot_close_the_script_tag(self) -> None:
        data = {"name": "</script><script>alert(1)</script>", "line": "a\u2028b"}
        text = dump_js(data)
        self.assertNotIn("</", text)
        self.assertNotIn("\u2028", text)
        self.assertEqual(json.loads(text), data)

    def test_writes_replace_the_file_without_leftovers(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "deep" / "file.json"
            write_json(target, {"a": 1})
            write_bytes(target, b"second")
            self.assertEqual(target.read_bytes(), b"second")
            self.assertEqual([p.name for p in target.parent.iterdir()], ["file.json"])

    def test_null_device_and_buffers_are_not_terminals(self) -> None:
        # Windows answers isatty() with True for NUL; setup must not wait on it.
        with open(os.devnull, encoding="utf-8") as null:
            self.assertFalse(is_terminal(null))
        self.assertFalse(is_terminal(io.StringIO()))
        self.assertFalse(is_terminal(None))

    def test_human_bytes(self) -> None:
        self.assertEqual(human_bytes(512), "512 B")
        self.assertEqual(human_bytes(1536), "1.5 KB")
        self.assertEqual(human_bytes(5 * 1024**4), "5120.0 GB")


if __name__ == "__main__":
    unittest.main()
