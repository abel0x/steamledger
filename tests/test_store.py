# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 abel0x <https://github.com/abel0x>
"""The database folder: snapshot references, CSV safety, deleting and relinking."""

import tempfile
import unittest
from pathlib import Path

from steamledger.paths import Paths
from steamledger.store import Database, SnapshotNotFound, _cell, write_csv
from tests.helpers import game, snapshot

STAMPS = [
    ("2026-10-01_10-00-00", "2026-10-01T07:00:00Z", 60),
    ("2026-10-01_20-00-00", "2026-10-01T17:00:00Z", 120),
    ("2026-10-05_09-00-00", "2026-10-05T06:00:00Z", 300),
    ("2026-10-09_09-00-00", "2026-10-09T06:00:00Z", 600),
]


class DatabaseTest(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.paths = Paths(Path(tmp.name))
        self.db = Database(self.paths)
        for sid, when, minutes in STAMPS:
            self.db.write(snapshot(sid, when, games=[game(10, "Ten", minutes)]))

    def test_references(self) -> None:
        ids = [sid for sid, _when, _minutes in STAMPS]
        for ref, expected in (
            ("latest", ids[3]),
            ("LAST", ids[3]),
            ("previous", ids[2]),
            ("first", ids[0]),
            ("-1", ids[3]),
            ("-4", ids[0]),
            ("1", ids[0]),
            ("#2", ids[1]),
            (ids[2], ids[2]),
            ("2026-10-01 20:00", ids[1]),  # typed with a space and colons
            ("2026-10-01", ids[1]),  # the last one that day
            ("2026-10-07", ids[2]),  # no snapshot that day: the one before
        ):
            with self.subTest(ref=ref):
                self.assertEqual(self.db.resolve(ref), expected)
        for ref in ("-5", "5", "2026-09-30", "nope"):
            with self.subTest(ref=ref), self.assertRaises(SnapshotNotFound):
                self.db.resolve(ref)

    def test_same_second_gets_a_suffix(self) -> None:
        sid = self.db.write(snapshot(STAMPS[-1][0], "2026-10-09T06:00:01Z"))
        self.assertEqual(sid, STAMPS[-1][0] + "-2")

    def test_bad_id_is_refused(self) -> None:
        with self.assertRaises(ValueError):
            self.db.write(snapshot("../escape", "2026-10-10T00:00:00Z"))

    def test_files_of_a_snapshot(self) -> None:
        folder = self.paths.archive / STAMPS[1][0]
        for name in ("meta.json", "games.json", "games.csv", "changes.json", "report.html"):
            self.assertTrue((folder / name).is_file(), name)
        self.assertFalse((self.paths.archive / STAMPS[0][0] / "changes.json").exists())
        self.assertEqual(
            (self.paths.latest / "meta.json").read_text(encoding="utf-8"),
            (self.paths.archive / STAMPS[-1][0] / "meta.json").read_text(encoding="utf-8"),
        )
        self.assertEqual(list(self.paths.database.glob(".tmp-*")), [])

    def test_deleting_relinks_the_next_snapshot(self) -> None:
        ids = self.db.ids()
        self.db.delete([ids[2]])
        self.assertEqual(self.db.ids(), [ids[0], ids[1], ids[3]])
        changes = self.db.changes(ids[3])
        self.assertEqual(changes["from"]["id"], ids[1])
        self.assertEqual(changes["summary"]["playtime"], 600 - 120)

    def test_deleting_the_newest_moves_latest(self) -> None:
        ids = self.db.ids()
        self.db.delete([ids[3]])
        meta = (self.paths.latest / "meta.json").read_text(encoding="utf-8")
        self.assertIn(ids[2], meta)

    def test_saved_comparison_is_listed_in_the_index(self) -> None:
        from steamledger import diff

        ids = self.db.ids()
        changes = diff.compare(self.db.load(ids[0]), self.db.load(ids[3]))
        page = self.db.save_comparison(changes)
        self.db.write_index()
        self.assertTrue(page.is_file())
        self.assertTrue(page.with_name(page.stem + ".tr.html").is_file())
        index = (self.paths.database / "index.html").read_text(encoding="utf-8")
        self.assertIn(f"changes/{ids[0]}__{ids[3]}.html", index)


class CsvTest(unittest.TestCase):
    def test_cells_that_spreadsheets_would_run_are_quoted(self) -> None:
        for raw, cell in (
            ("=HYPERLINK(1)", "'=HYPERLINK(1)"),
            ("+1", "'+1"),
            ("-2", "'-2"),
            ("@SUM", "'@SUM"),
            ("plain", "plain"),
            (-2, -2),
            (None, ""),
            (True, "true"),
            (["a", "b"], "a; b"),
        ):
            with self.subTest(raw=raw):
                self.assertEqual(_cell(raw), cell)

    def test_bom_crlf_and_delimiter(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "t.csv"
            write_csv(path, ["a", "b"], [["ş", "x;y"]], ";")
            raw = path.read_bytes()
        self.assertTrue(raw.startswith(b"\xef\xbb\xbf"))
        self.assertEqual(raw[3:].decode("utf-8"), 'a;b\r\nş;"x;y"\r\n')


if __name__ == "__main__":
    unittest.main()
