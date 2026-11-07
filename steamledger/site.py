# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 abel0x <https://github.com/abel0x>
"""The static site, built from the database.

Everything the pages need sits in the output folder - scripts, styles, data and
images - so the site works from a double click (file://), from ``steamledger serve``
or copied to any static host, with no network. Data files are plain scripts that
assign to a global instead of JSON fetched at runtime, because browsers refuse
fetch() for pages opened from disk.

    site/
      index.html
      assets/            app.css, app.js, charts.js, diff.js, i18n.js
      data/index.js      snapshot list, history series, tag and category names
      data/s/<id>.js     one file per snapshot, loaded when it is viewed
      data/a/<appid>.js  achievements and store texts of one game, loaded on demand
      media/             images (hard links into database/media where possible)
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Any

from . import __version__
from .cache import Cache
from .i18n import DEFAULT_LANGUAGE, Translator, available_languages
from .media import STAMP, local_path
from .paths import WEB_DIR, Paths
from .store import Database
from .util import (
    KeyedError,
    dump_js,
    iso_utc,
    link_or_copy,
    read_json,
    utcnow,
    write_json,
    write_text,
)

SITE_FORMAT = 1
MARKER = ".steamledger-site"


class SiteError(KeyedError):
    pass


def _check_target(out: Path) -> None:
    """Only ever write into an empty folder or one this tool created."""
    if out.exists() and not out.is_dir():
        raise SiteError("cli.build.not_a_folder", path=str(out))
    if out.is_dir() and any(out.iterdir()) and not (out / MARKER).is_file():
        raise SiteError("cli.build.not_ours", path=str(out))


def _localize(value: Any, media_root: Path) -> Any:
    """Swap image URLs for the local copy when one exists."""
    if isinstance(value, str):
        rel = local_path(value) if value.startswith("http") else None
        if rel and (media_root.parent / rel).is_file():
            return rel
        return value
    if isinstance(value, list):
        return [_localize(v, media_root) for v in value]
    if isinstance(value, dict):
        return {k: _localize(v, media_root) for k, v in value.items()}
    return value


def _script(var: str, key: str | None, data: Any) -> str:
    payload = dump_js(data)
    if key is None:
        return f"window.{var}={payload};\n"
    return f"(window.{var}=window.{var}||{{}})[{dump_js(key)}]={payload};\n"


def _stale(target: Path, *sources: Path) -> bool:
    if not target.is_file():
        return True
    mtime = target.stat().st_mtime
    return any(s.is_file() and s.stat().st_mtime > mtime for s in sources)


class SiteBuilder:
    def __init__(
        self, paths: Paths, db: Database, out: Path | None = None, *, force: bool = False
    ) -> None:
        self.paths = paths
        self.db = db
        self.out = out or paths.site
        self.force = force
        self.cache = Cache(paths.cache)
        self.media_root = paths.media
        self.languages = [(code, Translator(code).steam_language) for code in available_languages()]
        self._schemas: dict[tuple[int, str], dict[str, dict[str, Any]]] = {}

    def build(self) -> Path:
        _check_target(self.out)
        self.out.mkdir(parents=True, exist_ok=True)
        previous = read_json(self.out / "data" / "build.json", {})
        if previous.get("format") != SITE_FORMAT or previous.get("version") != __version__:
            self.force = True
        write_text(
            self.out / MARKER,
            "Built by steamledger. Safe to delete; `steamledger build` recreates it.\n",
        )
        self.copy_assets()
        self.write_translations()
        ids = self.db.ids()
        timeline = self.timeline(ids)
        for sid in ids:
            self.write_snapshot(sid)
        self.drop_removed(ids)
        latest = self.db.load(ids[-1]) if ids else None
        apps = self.write_apps(latest) if latest else []
        self.write_index(ids, timeline, apps)
        self.mirror_media()
        write_json(
            self.out / "data" / "build.json",
            {"format": SITE_FORMAT, "version": __version__, "built_at": iso_utc(utcnow())},
        )
        return self.out / "index.html"

    # ------------------------------------------------------------------ parts

    def copy_assets(self) -> None:
        for source in WEB_DIR.rglob("*"):
            if source.is_file():
                target = self.out / source.relative_to(WEB_DIR)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, target)

    def write_translations(self) -> None:
        bundles = {}
        for code in available_languages():
            tr = Translator(code)
            bundles[code] = {
                "name": tr.name,
                "locale": tr.meta.get("bcp47", code),
                "strings": tr.bundle(),
            }
        write_text(self.out / "assets" / "i18n.js", _script("STEAMLEDGER_I18N", None, bundles))

    def write_snapshot(self, sid: str) -> None:
        target = self.out / "data" / "s" / f"{sid}.js"
        folder = self.paths.archive / sid
        sources = (folder / "meta.json", folder / "changes.json", self.paths.database / STAMP)
        if not self.force and not _stale(target, *sources):
            return
        snapshot = self.db.load(sid)
        snapshot["changes"] = self.db.changes(sid)
        self.enrich(snapshot)
        write_text(
            target, _script("STEAMLEDGER_SNAPSHOTS", sid, _localize(snapshot, self.media_root))
        )

    def schema(self, appid: int, steam_language: str) -> dict[str, dict[str, Any]]:
        key = (appid, steam_language)
        if key not in self._schemas:
            found = self.cache.read(f"schema/{appid}.{steam_language}") or {}
            self._schemas[key] = {a["apiname"]: a for a in found.get("achievements", [])}
        return self._schemas[key]

    def enrich(self, snapshot: dict[str, Any]) -> None:
        """Add what the browser cannot look up cheaply: achievement names in every
        language, and the easiest achievements still locked (by global unlock rate)."""
        extra = [(code, steam) for code, steam in self.languages if code != DEFAULT_LANGUAGE]
        upcoming = []
        for key, entry in (snapshot.get("achievements") or {}).items():
            appid = int(key)
            english = self.schema(appid, "english")
            for item in entry.get("unlocked") or []:
                local = {}
                for code, steam in extra:
                    definition = self.schema(appid, steam).get(item["apiname"])
                    if definition and (definition.get("name"), definition.get("description")) != (
                        item.get("name"),
                        item.get("description"),
                    ):
                        local[code] = {
                            "name": definition.get("name"),
                            "description": definition.get("description"),
                        }
                if local:
                    item["l"] = local
            rarity = self.cache.read(f"global/{appid}") or {}
            unlocked = {u["apiname"] for u in entry.get("unlocked") or []}
            for apiname, definition in english.items():
                if apiname in unlocked or definition.get("hidden") or apiname not in rarity:
                    continue
                names = {
                    code: (self.schema(appid, steam).get(apiname) or definition).get("name")
                    for code, steam in self.languages
                }
                upcoming.append(
                    {
                        "appid": appid,
                        "game": entry.get("name"),
                        "apiname": apiname,
                        "names": names,
                        "percent": rarity[apiname],
                        "icon": definition.get("icon"),
                    }
                )
        upcoming.sort(key=lambda n: (-n["percent"], n["appid"], n["apiname"]))
        snapshot["next"] = upcoming[:30]

    def drop_removed(self, ids: list[str]) -> None:
        keep = {f"{sid}.js" for sid in ids}
        folder = self.out / "data" / "s"
        for stale in folder.glob("*.js") if folder.is_dir() else []:
            if stale.name not in keep:
                stale.unlink()

    def timeline(self, ids: list[str]) -> dict[str, dict[str, int]]:
        """Playtime per game per snapshot, cached so each games.json is read once."""
        cached = self.cache.read("timeline") or {}
        current = {sid: cached[sid] for sid in ids if sid in cached}
        changed = len(current) != len(cached)
        for sid in ids:
            if sid not in current:
                games = read_json(self.paths.archive / sid / "games.json", [])
                current[sid] = {str(g["appid"]): g.get("playtime_forever", 0) for g in games}
                changed = True
        if changed:
            self.cache.write("timeline", current)
        return current

    def write_apps(self, latest: dict[str, Any]) -> list[int]:
        """Per-game achievement lists (every language) and store texts."""
        languages = self.languages
        appids = sorted(
            {g["appid"] for g in latest.get("games") or []}
            | {w["appid"] for w in latest.get("wishlist") or []}
        )
        stores = {steam: self.cache.table(f"store/{steam}") for _code, steam in languages}
        written = []
        for appid in appids:
            target = self.out / "data" / "a" / f"{appid}.js"
            sources = [
                self.paths.cache / "schema" / f"{appid}.{steam}.json" for _c, steam in languages
            ]
            sources += [self.paths.cache / "global" / f"{appid}.json"] + [
                self.paths.cache / "store" / f"{steam}.json" for _c, steam in languages
            ]
            if not any(s.is_file() for s in sources):
                continue
            written.append(appid)
            if not self.force and not _stale(target, *sources, self.paths.database / STAMP):
                continue
            data: dict[str, Any] = {
                "schema": {},
                "store": {},
                "rarity": self.cache.read(f"global/{appid}") or {},
            }
            for code, steam in languages:
                schema = self.cache.read(f"schema/{appid}.{steam}")
                if schema:
                    data["schema"][code] = schema.get("achievements", [])
                found, item = stores[steam].get(appid, float("inf"))
                if found and item:
                    data["store"][code] = {
                        "description": item.get("description") or "",
                        "review": (item.get("review") or {}).get("label") or "",
                    }
            write_text(
                target, _script("STEAMLEDGER_APPS", str(appid), _localize(data, self.media_root))
            )
        return written

    def write_index(
        self, ids: list[str], timeline: dict[str, dict[str, int]], apps: list[int]
    ) -> None:
        snapshots = []
        for sid in ids:
            meta = self.db.meta(sid)
            changes = self.db.changes(sid)
            snapshots.append(
                {
                    "id": sid,
                    "collected_at": meta.get("collected_at"),
                    "utc_offset": meta.get("utc_offset"),
                    "summary": meta.get("summary") or {},
                    "sections": {
                        k: v.get("status") for k, v in (meta.get("sections") or {}).items()
                    },
                    "changes": (changes or {}).get("summary"),
                }
            )
        series: dict[str, list[list[int]]] = {}
        for index, sid in enumerate(ids):
            for appid, minutes in timeline.get(sid, {}).items():
                points = series.setdefault(appid, [])
                if not points or points[-1][1] != minutes:
                    points.append([index, minutes])
        names = {}
        for code in available_languages():
            steam = Translator(code).steam_language
            names[code] = {
                "tags": self.cache.read(f"tags.{steam}") or {},
                "categories": self.cache.read(f"categories.{steam}") or {},
            }
        index = {
            "format": SITE_FORMAT,
            "version": __version__,
            "generated_at": iso_utc(utcnow()),
            "steamid": self.db.meta(ids[-1]).get("steamid") if ids else None,
            "snapshots": snapshots,
            "series": series,
            "names": names,
            "apps": apps,
        }
        write_text(
            self.out / "data" / "index.js",
            _script("STEAMLEDGER_INDEX", None, _localize(index, self.media_root)),
        )

    def mirror_media(self) -> None:
        source_root = self.media_root
        if not source_root.is_dir():
            return
        target_root = self.out / "media"
        for directory, _dirs, files in os.walk(source_root):
            for name in files:
                if name == "missing.json":
                    continue
                source = Path(directory) / name
                target = target_root / source.relative_to(source_root)
                try:
                    if target.is_file() and target.stat().st_size == source.stat().st_size:
                        continue
                    link_or_copy(source, target)
                except OSError:
                    continue


def build_site(paths: Paths, db: Database, out: Path | None = None, *, force: bool = False) -> Path:
    return SiteBuilder(paths, db, out, force=force).build()
