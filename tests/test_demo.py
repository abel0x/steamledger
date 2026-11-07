# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 abel0x <https://github.com/abel0x>
"""End to end: the demo account goes through the real collector, database and
site builder, every command runs against the result, and the Python and
JavaScript diff engines are held to the same answer on every pair of snapshots."""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any

from steamledger import diff
from steamledger.i18n import Translator
from steamledger.paths import Paths
from steamledger.store import Database

ROOT = Path(__file__).resolve().parent.parent
DIFF_JS = ROOT / "steamledger" / "web" / "assets" / "diff.js"
SNAPSHOTS = 3

_tmp: tempfile.TemporaryDirectory[str] | None = None
paths: Paths
db: Database


def setUpModule() -> None:
    global _tmp, paths, db
    _tmp = tempfile.TemporaryDirectory()
    root = Path(_tmp.name)
    subprocess.run(
        [
            sys.executable,
            "-m",
            "steamledger",
            "--root",
            str(root),
            "--lang",
            "en",
            "-q",
            "--no-color",
            "demo",
            "--no-open",
            "--snapshots",
            str(SNAPSHOTS),
        ],
        cwd=ROOT,
        check=True,
        timeout=600,
    )
    paths = Paths(root / "demo")
    db = Database(paths)


def tearDownModule() -> None:
    if _tmp is not None:
        _tmp.cleanup()


def plain(data: Any) -> Any:
    return json.loads(json.dumps(data))


def run(
    root: Path, *args: str, env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    """The command line as a user runs it, in its own process."""
    environ = {**os.environ, "COLUMNS": "200", "NO_COLOR": "1", **(env or {})}
    for name in ("STEAM_API_KEY", "STEAM_ID", "STEAMLEDGER_LANG", "STEAMLEDGER_HOME"):
        environ.pop(name, None)
    return subprocess.run(
        [sys.executable, "-m", "steamledger", "--root", str(root), *args],
        cwd=ROOT,
        env=environ,
        stdin=subprocess.DEVNULL,  # never a terminal: commands must not wait for input
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
    )


class CommandTest(unittest.TestCase):
    def check(self, result: subprocess.CompletedProcess[str], code: int = 0) -> str:
        output = result.stdout + result.stderr
        self.assertNotIn("Traceback", output)
        self.assertEqual(result.returncode, code, output)
        return output

    def test_list_show_and_diff(self) -> None:
        ids = db.ids()
        listing = self.check(run(paths.root, "--lang", "en", "list"))
        for sid in ids:
            self.assertIn(sid, listing)
        shown = self.check(run(paths.root, "--lang", "en", "show", "previous"))
        self.assertIn(ids[-2], shown)
        self.assertNotIn("None", shown)
        self.check(run(paths.root, "--lang", "en", "diff", "1"))
        # Older and newer given the wrong way round still compare forwards.
        raw = self.check(run(paths.root, "diff", "latest", "first", "--json"))
        changes = json.loads(raw)
        self.assertEqual((changes["from"]["id"], changes["to"]["id"]), (ids[0], ids[-1]))

    def test_wrong_references_are_explained(self) -> None:
        output = self.check(run(paths.root, "--lang", "en", "show", "nope"), 2)
        self.assertIn(Translator("en").t("cli.errors.snapshot", ref="nope"), output)
        output = self.check(run(paths.root, "--lang", "tr", "diff", "latest", "-1"), 2)
        self.assertIn(Translator("tr").t("cli.diff.same", id=db.ids()[-1]), output)

    def test_turkish_and_a_legacy_windows_console(self) -> None:
        listing = self.check(run(paths.root, "--lang", "tr", "list"))
        self.assertIn(Translator("tr").t("cli.list.date"), listing)
        # cp1252 cannot encode "★" or "ş": they are replaced, never a crash.
        self.check(run(paths.root, "--lang", "tr", "show", env={"PYTHONIOENCODING": "cp1252"}))

    def test_build_and_reports(self) -> None:
        self.check(run(paths.root, "build", "--reports"))
        self.assertTrue((paths.site / "data" / "index.js").is_file())
        for sid in db.ids():
            self.assertTrue((paths.site / "data" / "s" / f"{sid}.js").is_file())

    def test_build_refuses_a_folder_it_did_not_make(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "keep.txt").write_text("mine", encoding="utf-8")
            self.check(run(paths.root, "build", "--out", tmp), 1)
            self.assertEqual(os.listdir(tmp), ["keep.txt"])

    def test_saved_comparison(self) -> None:
        ids = db.ids()
        self.check(run(paths.root, "diff", "1", "2", "--save"))
        stem = f"{ids[0]}__{ids[1]}"
        self.assertTrue((paths.changes / f"{stem}.json").is_file())
        self.assertTrue((paths.changes / f"{stem}.tr.html").is_file())
        self.assertIn(stem, (paths.database / "index.html").read_text(encoding="utf-8"))

    def test_prune(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            copy = Path(tmp) / "copy"
            shutil.copytree(paths.root, copy)
            dry = self.check(run(copy, "prune", "--keep", "1", "--dry-run"))
            self.assertIn(db.ids()[0], dry)
            self.assertEqual(len(Database(Paths(copy)).ids()), SNAPSHOTS)
            # Without --yes and without a terminal to ask on, nothing is deleted.
            self.check(run(copy, "prune", "--keep", "1"), 1)
            self.check(run(copy, "prune", "--before", "2999-01-01", "--yes"))
            left = Database(Paths(copy)).ids()
            self.assertEqual(left, [db.ids()[-1]])  # the newest always stays
            self.assertIsNone(Database(Paths(copy)).changes(left[0]))
            self.check(run(copy, "prune", "--keep", "0"), 2)

    def test_config_problems_are_messages_not_crashes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.check(run(root, "config", "set", "network.workers", "0"), 2)
            self.check(run(root, "config", "set", "no.such.option", "1"), 2)
            self.check(run(root, "config", "set", "steam_id", "gaben"), 2)
            self.check(run(root, "config", "set", "network.workers", "2"))
            saved = json.loads((root / "config.json").read_text(encoding="utf-8"))
            self.assertEqual(saved["network"]["workers"], 2)
            shown = self.check(run(root, "config", "show"))
            self.assertIn('"workers": 2', shown)
            for broken in ('{"media": {"achievement_icons": "x"}}', "{oops"):
                (root / "config.json").write_text(broken, encoding="utf-8")
                with self.subTest(config=broken):
                    self.check(run(root, "--lang", "en", "list"), 2)
                    self.check(run(root, "--lang", "en", "collect"), 2)

    def test_commands_that_need_setup_say_so(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output = self.check(run(Path(tmp), "--lang", "en", "collect"), 2)
            self.assertIn("steamledger setup", output)
            self.check(run(Path(tmp), "--lang", "en", "setup"), 2)  # no terminal, no key
            self.check(run(Path(tmp), "--lang", "en", "doctor"), 1)
            self.check(run(Path(tmp), "--lang", "en", "list"))


class DatabaseTest(unittest.TestCase):
    def test_snapshots_and_offline_files(self) -> None:
        ids = db.ids()
        self.assertEqual(len(ids), SNAPSHOTS)
        database = paths.database
        for name in ("index.html", "index.tr.html", "README.txt"):
            self.assertTrue((database / name).is_file(), name)
        for sid in ids:
            folder = database / "archive" / sid
            for name in (
                "meta.json",
                "profile.json",
                "games.json",
                "report.html",
                "report.tr.html",
            ):
                self.assertTrue((folder / name).is_file(), f"{sid}/{name}")
        self.assertTrue((database / "latest" / "report.html").is_file())
        self.assertTrue((paths.site / "index.html").is_file())

    def test_api_key_is_never_stored_in_the_database(self) -> None:
        from steamledger.demo import API_KEY

        for file in paths.database.rglob("*"):
            if file.is_file() and file.suffix in (".json", ".html", ".csv", ".txt", ".js"):
                self.assertNotIn(API_KEY, file.read_text(encoding="utf-8"), str(file))

    def test_icons_moved_to_the_new_cdn_path_are_still_downloaded(self) -> None:
        from steamledger.demo import MOVED_ICON

        self.assertTrue(
            (paths.database / "media" / "apps").joinpath(*MOVED_ICON.split("/")[1:]).is_file()
        )
        self.assertFalse((paths.database / "media" / "missing.json").is_file())

    def test_a_game_that_hides_achievements_does_not_hide_the_rest(self) -> None:
        from steamledger.demo import HIDDEN_ACHIEVEMENTS

        snapshot = db.load(db.ids()[-1])
        section = snapshot["meta"]["sections"]["achievements"]
        self.assertEqual(section["status"], "ok")
        self.assertEqual(set(section["hidden"]), HIDDEN_ACHIEVEMENTS)
        self.assertTrue(snapshot["achievements"])
        for appid in HIDDEN_ACHIEVEMENTS:
            self.assertNotIn(str(appid), snapshot["achievements"])

    def test_saved_changes_match_a_fresh_comparison(self) -> None:
        ids = db.ids()
        for older, newer in zip(ids, ids[1:], strict=False):
            saved = db.changes(newer)
            self.assertIsNotNone(saved)
            fresh = diff.compare(db.load(older), db.load(newer))
            self.assertEqual(plain(saved)["summary"], plain(fresh)["summary"])


@unittest.skipUnless(shutil.which("node"), "node is not installed")
class DiffParityTest(unittest.TestCase):
    def test_python_and_javascript_agree(self) -> None:
        ids = db.ids()
        pairs = [(a, b) for i, a in enumerate(ids) for b in ids[i + 1 :]]
        pairs += [(ids[-1], ids[0])]  # newer first must work too
        snapshots = {sid: db.load(sid) for sid in ids}
        script = (
            "const fs = require('fs');"
            f"require({json.dumps(str(DIFF_JS))});"
            "const input = JSON.parse(fs.readFileSync(0, 'utf8'));"
            "const out = input.pairs.map(([a, b]) => globalThis.SteamLedgerDiff.compare(input.snapshots[a], input.snapshots[b]));"
            "process.stdout.write(JSON.stringify(out));"
        )
        result = subprocess.run(
            ["node", "-e", script],
            input=json.dumps({"snapshots": snapshots, "pairs": pairs}),
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=True,
            timeout=120,
        )
        from_js = json.loads(result.stdout)
        for (a, b), js in zip(pairs, from_js, strict=True):
            with self.subTest(older=a, newer=b):
                self.assertEqual(js, plain(diff.compare(snapshots[a], snapshots[b])))


if __name__ == "__main__":
    unittest.main()
