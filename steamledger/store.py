# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 abel0x <https://github.com/abel0x>
"""The database folder. Plain files only, so everything opens with a double click:
JSON in a browser or an editor, CSV in a spreadsheet, HTML in a browser.

    database/
      index.html            every snapshot, with links (index.<lang>.html per language)
      README.txt            what is where
      latest/               the newest snapshot, always at the same path
      archive/<id>/         every snapshot, kept for later review
      archive/index.json    one entry per snapshot: date and headline numbers
      changes/              comparisons saved with `steamledger diff --save`
      media/                images for offline viewing
      cache/                Steam API cache, safe to delete

Each snapshot folder holds ``<part>.json`` for every part in snapshot.PARTS,
``meta.json``, ``changes.json`` (what changed since the snapshot before it), CSV
copies of the tables and ``report.html`` plus one report per extra language.
"""

from __future__ import annotations

import csv
import io
import os
import re
import shutil
from pathlib import Path
from typing import Any

from . import diff, report
from .paths import Paths
from .snapshot import PARTS
from .util import local_stamp, read_json, remove_tree, replace, write_json, write_text

_ID = re.compile(r"^\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}(?:-\d+)?$")
_DATE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")


class SnapshotNotFound(LookupError):
    def __init__(self, ref: str) -> None:
        super().__init__(ref)
        self.ref = ref


def _cell(value: Any) -> Any:
    """CSV cell. Text that a spreadsheet would run as a formula gets a leading quote."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return value
    if isinstance(value, (list, tuple)):
        value = "; ".join(str(v) for v in value)
    text = str(value)
    if text[:1] in ("=", "+", "-", "@", "\t", "\r"):
        text = "'" + text
    return text


def _date(stamp: Any) -> str:
    return local_stamp(stamp, with_time=False)


def csv_tables(snapshot: dict[str, Any]) -> dict[str, tuple[list[str], list[list[Any]]]]:
    games = []
    for g in snapshot.get("games") or []:
        progress = g.get("achievements") or {}
        store = g.get("store") or {}
        games.append(
            [
                g["appid"],
                g["name"],
                round(g["playtime_forever"] / 60, 2),
                g["playtime_forever"],
                g["playtime_2weeks"],
                g["playtime_windows"],
                g["playtime_mac"],
                g["playtime_linux"],
                g["playtime_deck"],
                local_stamp(g.get("last_played")),
                progress.get("unlocked"),
                progress.get("total"),
                progress.get("percent"),
                _date(store.get("release")),
                store.get("developers"),
                store.get("publishers"),
                (store.get("tags") or [])[:5],
                store.get("type"),
            ]
        )
    achievements = []
    for key, entry in sorted(
        (snapshot.get("achievements") or {}).items(), key=lambda kv: int(kv[0])
    ):
        for item in entry["unlocked"]:
            achievements.append(
                [
                    int(key),
                    entry["name"],
                    item["apiname"],
                    item["name"],
                    item["description"],
                    local_stamp(item["unlocktime"]),
                    item["unlocktime"],
                    item.get("percent"),
                ]
            )
    friends = []
    for f in snapshot.get("friends") or []:
        bans = f.get("bans") or {}
        friends.append(
            [
                f["steamid"],
                f["name"],
                f.get("realname"),
                _date(f.get("friend_since")),
                f.get("country"),
                f.get("level"),
                _date(f.get("created")),
                f.get("profile_url"),
                bans.get("vac_bans"),
                bans.get("game_bans"),
            ]
        )
    badges = [
        [
            b["badgeid"],
            b.get("appid"),
            b.get("name"),
            b.get("level"),
            b.get("xp"),
            local_stamp(b.get("earned")),
            b.get("scarcity"),
            b.get("foil"),
        ]
        for b in snapshot.get("badges") or []
    ]
    wishlist = []
    for w in snapshot.get("wishlist") or []:
        store = w.get("store") or {}
        review = store.get("review") or {}
        wishlist.append(
            [
                w["appid"],
                w.get("name"),
                w.get("priority"),
                _date(w.get("added")),
                _date(store.get("release")),
                review.get("percent"),
                (store.get("tags") or [])[:5],
            ]
        )
    return {
        "games": (
            [
                "appid",
                "name",
                "playtime_hours",
                "playtime_minutes",
                "last_2_weeks_minutes",
                "windows_minutes",
                "mac_minutes",
                "linux_minutes",
                "steam_deck_minutes",
                "last_played",
                "achievements_unlocked",
                "achievements_total",
                "achievements_percent",
                "release_date",
                "developers",
                "publishers",
                "tags",
                "type",
            ],
            games,
        ),
        "achievements": (
            [
                "appid",
                "game",
                "apiname",
                "name",
                "description",
                "unlocked_at",
                "unlocktime",
                "global_percent",
            ],
            achievements,
        ),
        "friends": (
            [
                "steamid",
                "name",
                "real_name",
                "friend_since",
                "country",
                "level",
                "account_created",
                "profile_url",
                "vac_bans",
                "game_bans",
            ],
            friends,
        ),
        "badges": (
            ["badgeid", "appid", "name", "level", "xp", "earned_at", "scarcity", "foil"],
            badges,
        ),
        "wishlist": (
            ["appid", "name", "priority", "added_at", "release_date", "review_percent", "tags"],
            wishlist,
        ),
    }


def write_csv(path: Path, header: list[str], rows: list[list[Any]], delimiter: str) -> None:
    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter=delimiter, lineterminator="\r\n")
    writer.writerow(header)
    writer.writerows([_cell(v) for v in row] for row in rows)
    # The BOM lets Excel on Windows recognise UTF-8 (Turkish letters, emoji in names).
    write_text(path, buffer.getvalue(), encoding="utf-8-sig")


class Database:
    def __init__(self, paths: Paths, *, csv_delimiter: str = ",") -> None:
        self.paths = paths
        self.csv_delimiter = csv_delimiter
        self.locked: list[str] = []
        self._meta: dict[str, dict[str, Any]] = {}

    # ------------------------------------------------------------------ reading

    def meta(self, sid: str) -> dict[str, Any]:
        if sid not in self._meta:
            self._meta[sid] = read_json(self.paths.archive / sid / "meta.json", {})
        return self._meta[sid]

    def ids(self) -> list[str]:
        archive = self.paths.archive
        if not archive.is_dir():
            return []
        entries = []
        for child in archive.iterdir():
            if (
                child.is_dir()
                and not child.name.startswith(".")
                and (child / "meta.json").is_file()
            ):
                entries.append((self.meta(child.name).get("collected_at", ""), child.name))
        return [name for _stamp, name in sorted(entries)]

    def latest_id(self) -> str | None:
        found = self.ids()
        return found[-1] if found else None

    def load(self, sid: str) -> dict[str, Any]:
        folder = self.paths.archive / sid
        if not (folder / "meta.json").is_file():
            raise SnapshotNotFound(sid)
        snapshot: dict[str, Any] = {"meta": self.meta(sid)}
        for part, kind in PARTS.items():
            snapshot[part] = read_json(folder / f"{part}.json", kind())
        return snapshot

    def load_latest(self) -> dict[str, Any] | None:
        sid = self.latest_id()
        return self.load(sid) if sid else None

    def changes(self, sid: str) -> dict[str, Any] | None:
        return read_json(self.paths.archive / sid / "changes.json", None)

    def resolve(self, ref: str) -> str:
        """Turn what a person types into a snapshot id: latest, previous, first,
        -2 (second newest), 3 (third in `steamledger list`), a full id, an id prefix
        such as 2026-10-30_19, or a date (the last snapshot that day, else the
        closest one before it)."""
        ids = self.ids()
        if not ids:
            raise SnapshotNotFound(ref)
        text = ref.strip().replace(" ", "_").replace(":", "-").lstrip("#")
        lowered = text.lower()
        if lowered in ("latest", "last", "newest"):
            return ids[-1]
        if lowered in ("previous", "prev"):
            if len(ids) < 2:
                raise SnapshotNotFound(ref)
            return ids[-2]
        if lowered in ("first", "oldest"):
            return ids[0]
        if re.fullmatch(r"-\d+", text):
            n = int(text[1:])
            if 1 <= n <= len(ids):
                return ids[-n]
            raise SnapshotNotFound(ref)
        if text.isdigit() and len(text) <= 3 and 1 <= int(text) <= len(ids):
            return ids[int(text) - 1]
        if text in ids:
            return text
        matches = [sid for sid in ids if sid.startswith(text)]
        if matches:
            return matches[-1]
        if _DATE.match(text):
            day_end = text + "_99"
            earlier = [sid for sid in ids if sid < day_end]
            if earlier:
                return earlier[-1]
        raise SnapshotNotFound(ref)

    # ------------------------------------------------------------------ writing

    def _unique_id(self, sid: str) -> str:
        if not _ID.match(sid):
            raise ValueError(f"bad snapshot id {sid!r}")
        candidate, n = sid, 2
        while (self.paths.archive / candidate).exists():
            candidate = f"{sid}-{n}"
            n += 1
        return candidate

    def write_files(self, folder: Path, snapshot: dict[str, Any]) -> None:
        folder.mkdir(parents=True, exist_ok=True)
        write_json(folder / "meta.json", snapshot["meta"])
        for part in PARTS:
            write_json(folder / f"{part}.json", snapshot.get(part, PARTS[part]()))
        for name, (header, rows) in csv_tables(snapshot).items():
            write_csv(folder / f"{name}.csv", header, rows, self.csv_delimiter)

    def write(self, snapshot: dict[str, Any]) -> str:
        """Store a new snapshot in the archive, refresh latest/ and the indexes."""
        meta = snapshot["meta"]
        previous = self.latest_id()
        sid = self._unique_id(meta["id"])
        meta["id"] = sid
        tmp = self.paths.archive / f".tmp-{sid}"
        remove_tree(tmp)
        self.write_files(tmp, snapshot)
        changes = diff.compare(self.load(previous), snapshot) if previous else None
        if changes is not None:
            write_json(tmp / "changes.json", changes)
        report.write_snapshot_reports(tmp, snapshot, changes, depth=2, database=self.paths.database)
        replace(tmp, self.paths.archive / sid)
        self._meta[sid] = meta
        self.refresh_latest()
        self.write_index()
        return sid

    def refresh_latest(self) -> list[str]:
        """Point latest/ at the newest snapshot. Returns files that could not be
        replaced (Windows keeps files open in a spreadsheet locked)."""
        sid = self.latest_id()
        latest = self.paths.latest
        if sid is None:
            remove_tree(latest)
            return []
        tmp = self.paths.database / ".tmp-latest"
        old = self.paths.database / ".old-latest"
        remove_tree(tmp)
        remove_tree(old)
        shutil.copytree(
            self.paths.archive / sid, tmp, ignore=shutil.ignore_patterns("report*.html")
        )
        report.write_snapshot_reports(
            tmp, self.load(sid), self.changes(sid), depth=1, database=self.paths.database
        )
        locked: list[str] = []
        try:
            if latest.exists():
                os.replace(latest, old)
            os.replace(tmp, latest)
        except PermissionError:
            latest.mkdir(parents=True, exist_ok=True)
            for source in tmp.iterdir():
                try:
                    shutil.copy2(source, latest / source.name)
                except PermissionError:
                    locked.append(str(latest / source.name))
        remove_tree(old)
        remove_tree(tmp)
        self.locked = locked
        return locked

    def delete(self, sids: list[str]) -> None:
        for sid in sids:
            remove_tree(self.paths.archive / sid)
            self._meta.pop(sid, None)
        self.relink()
        self.refresh_latest()
        self.write_index()

    def relink(self) -> None:
        """After snapshots were removed, recompute changes.json (and the reports
        that show it) where the previous snapshot is no longer the same one."""
        ids = self.ids()
        for index, sid in enumerate(ids):
            folder = self.paths.archive / sid
            stored = self.changes(sid)
            previous = ids[index - 1] if index else None
            if (stored or {}).get("from", {}).get("id") == previous:
                continue
            snapshot = self.load(sid)
            changes = diff.compare(self.load(previous), snapshot) if previous else None
            if changes is None:
                (folder / "changes.json").unlink(missing_ok=True)
            else:
                write_json(folder / "changes.json", changes)
            report.write_snapshot_reports(
                folder, snapshot, changes, depth=2, database=self.paths.database
            )

    def rebuild_reports(self) -> None:
        for sid in self.ids():
            report.write_snapshot_reports(
                self.paths.archive / sid,
                self.load(sid),
                self.changes(sid),
                depth=2,
                database=self.paths.database,
            )
        self.refresh_latest()
        self.write_index()

    def save_comparison(self, changes: dict[str, Any]) -> Path:
        name = f"{changes['from']['id']}__{changes['to']['id']}"
        folder = self.paths.changes
        write_json(folder / f"{name}.json", changes)
        for tr in report.translators():
            filename = f"{name}.html" if tr.lang == "en" else f"{name}.{tr.lang}.html"
            write_text(
                folder / filename,
                report.render_changes_page(changes, tr, depth=1, database=self.paths.database),
            )
        return folder / f"{name}.html"

    def write_index(self) -> None:
        ids = self.ids()
        entries = []
        for sid in ids:
            meta = self.meta(sid)
            entries.append(
                {
                    "id": sid,
                    "collected_at": meta.get("collected_at"),
                    "summary": meta.get("summary", {}),
                }
            )
        write_json(self.paths.archive / "index.json", {"snapshots": entries})
        saved = (
            sorted(p.stem for p in self.paths.changes.glob("*__*.json"))
            if self.paths.changes.is_dir()
            else []
        )
        for tr in report.translators():
            filename = "index.html" if tr.lang == "en" else f"index.{tr.lang}.html"
            write_text(
                self.paths.database / filename, report.render_database_index(entries, saved, tr)
            )
        write_text(self.paths.database / "README.txt", report.database_readme())
