# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 abel0x <https://github.com/abel0x>
"""One collection run: everything the Steam Web API tells us about the account,
normalized into a snapshot (see snapshot.py).

Runs are incremental. Achievements are only requested again for games whose
playtime or last-played time moved since the previous snapshot, and schemas,
global unlock rates, store details and tag names come from the cache while they
are fresh, so a daily run needs few API calls. ``full=True`` ignores all of that.
"""

from __future__ import annotations

import datetime as dt
import threading
import time
from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Any

from . import __version__
from . import steamid as ids
from .api import SteamApi, SteamError
from .cache import Cache
from .config import Config
from .console import Console
from .i18n import Translator, available_languages, load_catalog
from .media import MediaStore
from .net import NetworkError
from .snapshot import FORMAT, SCHEMA_VERSION, USABLE, failed_apps, section_status, summarize
from .util import KeyedError, as_int, chunks, iso_utc, utc_offset, utcnow

STORE_TTL_DAYS = 14
SCHEMA_TTL_DAYS = 30
GLOBAL_TTL_DAYS = 7
NO_STATS_TTL_DAYS = 30
NAMES_TTL_DAYS = 30
GROUP_TTL_DAYS = 30
# Games in a row that refuse achievements, none readable, before the profile counts as private.
PRIVATE_AFTER = 8

STORE_TYPES = {
    0: "game",
    1: "demo",
    2: "mod",
    4: "dlc",
    6: "software",
    11: "music",
    12: "beta",
    13: "tool",
}
EQUIPPED_SLOTS = {
    "avatar_frame": "avatar_frame",
    "animated_avatar": "animated_avatar",
    "profile_background": "background",
    "mini_profile_background": "mini_background",
}


class CollectError(KeyedError):
    """Stops the run (bad key, unknown account...). ``key`` is a translation key."""


@dataclass
class Section:
    status: str = "ok"  # ok | empty | partial | private | error | skipped
    detail: str = ""
    failed: list[int] = field(default_factory=list)
    hidden: list[int] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"status": self.status}
        if self.detail:
            out["detail"] = self.detail
        if self.failed:
            out["failed"] = sorted(self.failed)
        if self.hidden:
            out["hidden"] = sorted(self.hidden)
        return out


def content_languages() -> list[str]:
    """Steam language names of every UI language. Achievement names and store
    texts are stored in each of them so the site can switch language offline."""
    names: list[str] = []
    for code in available_languages():
        steam = load_catalog(code).get("_meta", {}).get("steam")
        if steam and steam not in names:
            names.append(steam)
    return names or ["english"]


def normalize_bans(row: dict[str, Any] | None) -> dict[str, Any] | None:
    if not row:
        return None
    return {
        "vac_banned": bool(row.get("VACBanned")),
        "vac_bans": as_int(row.get("NumberOfVACBans")),
        "game_bans": as_int(row.get("NumberOfGameBans")),
        "community_banned": bool(row.get("CommunityBanned")),
        "economy_ban": str(row.get("EconomyBan") or "none"),
        "days_since_last_ban": as_int(row.get("DaysSinceLastBan")),
    }


def slim_store_item(
    item: dict[str, Any] | None, asset: Callable[[str, str], str]
) -> dict[str, Any] | None:
    """The part of an IStoreBrowseService item worth caching."""
    if not item:
        return None
    basic = item.get("basic_info") or {}
    review = (item.get("reviews") or {}).get("summary_filtered") or {}
    release = item.get("release") or {}
    platforms = item.get("platforms") or {}
    assets = item.get("assets") or {}
    categories = item.get("categories") or {}
    tags = sorted(item.get("tags") or [], key=lambda t: -as_int(t.get("weight")))
    url_format = assets.get("asset_url_format") or ""
    header = asset(url_format, assets["header"]) if url_format and assets.get("header") else None
    return {
        "name": item.get("name") or "",
        "type": as_int(item.get("type"), -1),
        "is_free": bool(item.get("is_free")),
        "release": as_int(release.get("steam_release_date"))
        or as_int(release.get("original_release_date"))
        or None,
        "coming_soon": bool(release.get("is_coming_soon")),
        "developers": [d["name"] for d in basic.get("developers") or [] if d.get("name")],
        "publishers": [p["name"] for p in basic.get("publishers") or [] if p.get("name")],
        "franchises": [f["name"] for f in basic.get("franchises") or [] if f.get("name")],
        "description": basic.get("short_description") or "",
        "tags": [as_int(t["tagid"]) for t in tags if "tagid" in t]
        or [as_int(t) for t in item.get("tagids") or []],
        "categories": sorted(
            {
                as_int(c)
                for key in (
                    "supported_player_categoryids",
                    "feature_categoryids",
                    "controller_categoryids",
                )
                for c in categories.get(key) or []
            }
        ),
        "review": {
            "score": as_int(review.get("review_score")),
            "percent": as_int(review.get("percent_positive")),
            "count": as_int(review.get("review_count")),
            "label": review.get("review_score_label") or "",
        }
        if review
        else None,
        "platforms": {
            "windows": bool(platforms.get("windows")),
            "mac": bool(platforms.get("mac")),
            "linux": bool(platforms.get("steamos_linux")),
        },
        "deck": as_int(platforms.get("steam_deck_compat_category")),
        "vr": bool(platforms.get("vr_support")),
        "header": header,
    }


def store_summary(
    slim: dict[str, Any] | None, tags: dict[int, str], categories: dict[int, str]
) -> dict[str, Any] | None:
    """Language-neutral store details stored with each game (English names)."""
    if not slim:
        return None
    review = slim.get("review")
    return {
        "type": STORE_TYPES.get(slim["type"], "other"),
        "is_free": slim["is_free"],
        "release": slim["release"],
        "developers": slim["developers"],
        "publishers": slim["publishers"],
        "franchises": slim["franchises"],
        "tag_ids": slim["tags"][:20],
        "tags": [tags[t] for t in slim["tags"][:10] if t in tags],
        "category_ids": slim["categories"],
        "categories": [categories[c] for c in slim["categories"] if c in categories],
        "review": {k: review[k] for k in ("score", "percent", "count")} if review else None,
        "platforms": slim["platforms"],
        "deck": slim["deck"],
        "vr": slim["vr"],
        "header": slim["header"],
    }


class Collector:
    def __init__(
        self,
        *,
        config: Config,
        api: SteamApi,
        media: MediaStore,
        cache: Cache,
        console: Console,
        tr: Translator,
        previous: dict[str, Any] | None = None,
        full: bool = False,
        now: dt.datetime | None = None,
    ) -> None:
        self.config = config
        self.api = api
        self.media = media
        self.cache = cache
        self.ui = console
        self.tr = tr
        self.previous = previous
        self.full = full
        self.now = now or utcnow()
        self.languages = content_languages()
        self.workers = int(config.get("network.workers") or 4)
        self.sections: dict[str, Section] = {}
        self.warnings: list[str] = []
        self.schemas: dict[tuple[int, str], dict[str, Any]] = {}
        self.rarity: dict[int, dict[str, float]] = {}

    # ------------------------------------------------------------------ helpers

    def ttl(self, days: float) -> float:
        return 0 if self.full else days

    def warn(self, where: str, exc: Exception | str) -> None:
        text = f"{where}: {exc}"
        self.warnings.append(text)
        self.ui.warn(self.tr.t("cli.collect.warning", where=where, detail=str(exc)))

    def optional(self, where: str, func: Callable[..., Any], *args: Any) -> Any:
        """Extras that must not stop the run when Steam refuses them."""
        try:
            return func(*args)
        except (SteamError, NetworkError) as exc:
            self.warn(where, exc)
            return None

    def step(self, label: str, value: str) -> None:
        self.ui.print(f"  {label:<22} {value}")

    def cached_names(
        self, name: str, fetch: Callable[[str], dict[int, str]], language: str
    ) -> dict[int, str]:
        cached = self.cache.read(f"{name}.{language}", self.ttl(NAMES_TTL_DAYS))
        if cached is None:
            try:
                cached = {str(k): v for k, v in fetch(language).items()}
                self.cache.write(f"{name}.{language}", cached)
            except (SteamError, NetworkError) as exc:
                self.warn(name, exc)
                cached = self.cache.read(f"{name}.{language}") or {}
        return {int(k): v for k, v in cached.items()}

    # ------------------------------------------------------------------ run

    def run(self) -> dict[str, Any]:
        started = time.monotonic()
        steamid = self.config.steam_id
        profile, badges_reply = self.collect_profile(steamid)
        country = str(self.config.get("store_country") or "auto")
        if country == "auto":
            country = profile.get("country") or "US"

        games = self.collect_games(steamid)
        recent = self.collect_recent(steamid)
        wishlist = self.collect_wishlist(steamid)
        store, tags, categories = self.collect_store(
            [g["appid"] for g in games] + [w["appid"] for w in wishlist], country
        )
        english = store.get("english", {})
        for game in games:
            game["store"] = store_summary(
                english.get(game["appid"]), tags.get("english", {}), categories.get("english", {})
            )
        for item in wishlist:
            slim = english.get(item["appid"]) or {}
            item["name"] = slim.get("name") or item.get("name") or f"App {item['appid']}"
            item["store"] = store_summary(
                slim or None, tags.get("english", {}), categories.get("english", {})
            )

        achievements = self.collect_achievements(steamid, games)
        friends = self.collect_friends(steamid)
        badges = self.normalize_badges(badges_reply, games, profile["visibility"] == 3)
        profile["groups"] = self.collect_groups(steamid, profile.get("primary_group"))

        snapshot: dict[str, Any] = {
            "meta": {},
            "profile": profile,
            "games": games,
            "achievements": achievements,
            "friends": friends,
            "badges": badges,
            "recent": recent,
            "wishlist": wishlist,
        }
        self.queue_media(snapshot)
        self.media.flush(self.ui, self.tr.t("cli.collect.images"))
        self.cache.save()

        local = self.now.astimezone()
        snapshot["meta"] = {
            "format": FORMAT,
            "schema_version": SCHEMA_VERSION,
            "id": local.strftime("%Y-%m-%d_%H-%M-%S"),
            "collected_at": iso_utc(self.now),
            "utc_offset": utc_offset(self.now),
            "duration_seconds": round(time.monotonic() - started, 1),
            "app": {"name": "steamledger", "version": __version__},
            "steamid": steamid,
            "languages": self.languages,
            "requests": self.api.http.requests,
            "sections": {
                name: section.as_dict() for name, section in sorted(self.sections.items())
            },
            "warnings": self.warnings,
            "summary": summarize(snapshot),
        }
        return snapshot

    # ------------------------------------------------------------------ profile

    def collect_profile(self, steamid: str) -> tuple[dict[str, Any], dict[str, Any] | None]:
        try:
            players = self.api.player_summaries([steamid])
        except SteamError as exc:
            if exc.kind == "forbidden":
                raise CollectError("cli.errors.invalid_key") from None
            raise CollectError("cli.errors.api", detail=str(exc)) from None
        except NetworkError as exc:
            raise CollectError("cli.errors.network", detail=str(exc)) from None
        if not players:
            raise CollectError("cli.errors.unknown_account", steamid=steamid)
        player = players[0]

        level = self.optional("level", self.api.steam_level, steamid)
        badges = self.optional("badges", self.api.badges, steamid)
        if level is None and badges:
            level = badges.get("player_level")
        bans = self.optional("bans", self.api.player_bans, [steamid]) or []
        percentile = self.optional("level", self.api.level_percentile, level) if level else None
        items = self.optional("items", self.api.profile_items, steamid) or {}

        xp = None
        if badges and "player_xp" in badges:
            xp = {
                "current": as_int(badges.get("player_xp")),
                "level_start": as_int(badges.get("player_xp_needed_current_level")),
                "to_next": as_int(badges.get("player_xp_needed_to_level_up")),
            }
        gameid = as_int(player.get("gameid"))
        profile = {
            "steamid": steamid,
            "account_id": ids.account_id(steamid),
            "steamid2": ids.steam2(steamid),
            "steamid3": ids.steam3(steamid),
            "personaname": str(player.get("personaname") or ""),
            "realname": player.get("realname") or None,
            "profile_url": player.get("profileurl"),
            "custom_url": ids.custom_url(player.get("profileurl")),
            "avatar": player.get("avatarfull") or player.get("avatarmedium"),
            "avatar_medium": player.get("avatarmedium") or player.get("avatar"),
            "avatar_hash": player.get("avatarhash"),
            "visibility": as_int(player.get("communityvisibilitystate")),
            "profile_configured": as_int(player.get("profilestate")) == 1,
            "comments": as_int(player.get("commentpermission")) == 1,
            "state": as_int(player.get("personastate")),
            "playing": {"appid": gameid, "name": player.get("gameextrainfo") or ""}
            if gameid
            else None,
            "last_online": as_int(player.get("lastlogoff")) or None,
            "created": as_int(player.get("timecreated")) or None,
            "country": player.get("loccountrycode") or None,
            "region": player.get("locstatecode") or None,
            "city_id": as_int(player.get("loccityid")) or None,
            "primary_group": str(player["primaryclanid"]) if player.get("primaryclanid") else None,
            "level": as_int(level) if level is not None else None,
            "level_percentile": percentile,
            "xp": xp,
            "bans": normalize_bans(bans[0] if bans else None),
            "equipped": self.normalize_items(items),
            "groups": [],
        }
        self.sections["profile"] = Section()
        self.step(self.tr.t("cli.collect.profile"), profile["personaname"])
        return profile, badges

    def normalize_items(self, reply: dict[str, Any]) -> dict[str, Any]:
        out = {}
        for source, name in EQUIPPED_SLOTS.items():
            item = reply.get(source) or {}
            image = item.get("image_large") or item.get("image_small")
            if image:
                out[name] = {
                    "name": item.get("item_title") or item.get("name") or "",
                    "appid": as_int(item.get("appid")) or None,
                    "image": self.api.endpoints.community_image(image),
                }
        return out

    def normalize_badges(
        self, reply: dict[str, Any] | None, games: list[dict[str, Any]], public: bool
    ) -> list[dict[str, Any]]:
        if reply is None:
            # GetBadges answers an empty object for profiles that are not public.
            self.sections["badges"] = Section("error" if public else "private")
            return []
        names = {g["appid"]: g["name"] for g in games}
        english = Translator("en")
        badges = []
        for row in reply.get("badges") or []:
            badgeid = as_int(row.get("badgeid"))
            appid = as_int(row.get("appid")) or None
            if appid:
                name = names.get(appid)
            else:
                key = f"data.badge.{badgeid}"
                name = english.t(key) if english.has(key) else None
            badges.append(
                {
                    "badgeid": badgeid,
                    "appid": appid,
                    "name": name,
                    "level": as_int(row.get("level")),
                    "xp": as_int(row.get("xp")),
                    "earned": as_int(row.get("completion_time")) or None,
                    "scarcity": as_int(row.get("scarcity")) or None,
                    "foil": bool(as_int(row.get("border_color"))),
                }
            )
        badges.sort(key=lambda b: (-(b["earned"] or 0), b["badgeid"], b["appid"] or 0))
        self.sections["badges"] = Section("ok" if badges else "empty")
        return badges

    # ------------------------------------------------------------------ library

    def collect_games(self, steamid: str) -> list[dict[str, Any]]:
        try:
            rows = self.api.owned_games(steamid)
        except (SteamError, NetworkError) as exc:
            self.sections["games"] = Section("error", str(exc))
            self.warn("games", exc)
            return []
        if rows is None:
            self.sections["games"] = Section("private")
            self.ui.warn(self.tr.t("cli.collect.games_private"))
            return []
        games = [self.game(row) for row in rows if as_int(row.get("appid"))]
        games.sort(key=lambda g: (-g["playtime_forever"], g["name"].casefold(), g["appid"]))
        self.sections["games"] = Section("ok" if games else "empty")
        hours = self.tr.playtime(sum(g["playtime_forever"] for g in games))
        self.step(
            self.tr.t("cli.collect.games"),
            self.tr.t("cli.collect.games_done", count=len(games), hours=hours),
        )
        return games

    def game(self, row: dict[str, Any]) -> dict[str, Any]:
        appid = as_int(row["appid"])
        icon = row.get("img_icon_url") or ""
        return {
            "appid": appid,
            "name": str(row.get("name") or f"App {appid}"),
            "playtime_forever": as_int(row.get("playtime_forever")),
            "playtime_2weeks": as_int(row.get("playtime_2weeks")),
            "playtime_windows": as_int(row.get("playtime_windows_forever")),
            "playtime_mac": as_int(row.get("playtime_mac_forever")),
            "playtime_linux": as_int(row.get("playtime_linux_forever")),
            "playtime_deck": as_int(row.get("playtime_deck_forever")),
            "playtime_offline": as_int(row.get("playtime_disconnected")),
            "last_played": as_int(row.get("rtime_last_played")) or None,
            "has_stats": bool(row.get("has_community_visible_stats")),
            "has_workshop": bool(row.get("has_workshop")),
            "has_market": bool(row.get("has_market")),
            "has_dlc": bool(row.get("has_dlc")),
            "icon": self.api.endpoints.app_icon(appid, icon) if icon else None,
            "achievements": None,
            "store": None,
        }

    def collect_recent(self, steamid: str) -> list[dict[str, Any]]:
        rows = self.optional("recent", self.api.recently_played, steamid) or []
        recent = []
        for row in rows:
            appid = as_int(row.get("appid"))
            if not appid:
                continue
            icon = row.get("img_icon_url") or ""
            recent.append(
                {
                    "appid": appid,
                    "name": str(row.get("name") or f"App {appid}"),
                    "playtime_2weeks": as_int(row.get("playtime_2weeks")),
                    "playtime_forever": as_int(row.get("playtime_forever")),
                    "icon": self.api.endpoints.app_icon(appid, icon) if icon else None,
                }
            )
        recent.sort(key=lambda r: (-r["playtime_2weeks"], r["appid"]))
        return recent

    def collect_wishlist(self, steamid: str) -> list[dict[str, Any]]:
        if not self.config.get("collect.wishlist"):
            self.sections["wishlist"] = Section("skipped")
            return []
        try:
            rows = self.api.wishlist(steamid)
        except (SteamError, NetworkError) as exc:
            private = isinstance(exc, SteamError) and exc.kind in (
                "private",
                "forbidden",
                "unauthorized",
            )
            self.sections["wishlist"] = Section("private" if private else "error", str(exc))
            return []
        items = [
            {
                "appid": as_int(r.get("appid")),
                "priority": as_int(r.get("priority")),
                "added": as_int(r.get("date_added")) or None,
            }
            for r in rows
            if as_int(r.get("appid"))
        ]
        items.sort(
            key=lambda w: (w["priority"] == 0, w["priority"], -(w["added"] or 0), w["appid"])
        )
        self.sections["wishlist"] = Section("ok" if items else "empty")
        return items

    def collect_store(
        self, appids: Iterable[int], country: str
    ) -> tuple[dict[str, dict[int, Any]], dict[str, dict[int, str]], dict[str, dict[int, str]]]:
        unique = sorted(set(appids))
        if not self.config.get("collect.store_details") or not unique:
            self.sections["store"] = Section("skipped" if unique else "empty")
            return {}, {}, {}
        details: dict[str, dict[int, Any]] = {}
        failed = False
        for language in self.languages:
            table = self.cache.table(f"store/{language}")
            stale = [a for a in unique if not table.get(a, self.ttl(STORE_TTL_DAYS))[0]]
            if stale:
                progress = self.ui.progress(
                    self.tr.t("cli.collect.store", language=language), len(stale)
                )
                for batch in chunks(stale, 50):
                    try:
                        found = self.api.store_items(batch, language, country)
                    except (SteamError, NetworkError) as exc:
                        self.warn("store", exc)
                        failed = True
                        break
                    for appid in batch:
                        table.put(
                            appid, slim_store_item(found.get(appid), self.api.endpoints.store_asset)
                        )
                    progress.advance(len(batch))
                progress.finish()
                table.save()
            details[language] = {a: table.get(a, float("inf"))[1] for a in unique}
        tags = {
            lang: self.cached_names("tags", self.api.tag_names, lang) for lang in self.languages
        }
        categories = {
            lang: self.cached_names("categories", self.api.store_categories, lang)
            for lang in self.languages
        }
        self.sections["store"] = Section("partial" if failed else "ok")
        return details, tags, categories

    # ------------------------------------------------------------------ achievements

    def collect_achievements(self, steamid: str, games: list[dict[str, Any]]) -> dict[str, Any]:
        games_status = self.sections.get("games", Section("error")).status
        if not self.config.get("collect.achievements") or games_status not in USABLE:
            self.sections["achievements"] = Section("skipped")
            return {}
        section = Section()
        self.sections["achievements"] = section
        unplayed = bool(self.config.get("collect.achievements_of_unplayed_games")) or self.full
        no_stats = self.cache.table("no-stats")

        previous = self.previous or {}
        reuse_ok = section_status(previous, "achievements") in USABLE
        before_games = {g["appid"]: g for g in previous.get("games") or []}
        before_achievements = (previous.get("achievements") or {}) if reuse_ok else {}
        before_failed = failed_apps(previous) if previous else set()

        state: dict[int, dict[str, Any]] = {}
        to_fetch: list[int] = []
        for game in games:
            if not game["has_stats"] or (game["playtime_forever"] == 0 and not unplayed):
                continue
            appid = game["appid"]
            if not self.full:
                if no_stats.get(appid, NO_STATS_TTL_DAYS)[0]:
                    continue
                before = before_games.get(appid)
                old = before_achievements.get(str(appid))
                if (
                    before
                    and old is not None
                    and appid not in before_failed
                    and before["playtime_forever"] == game["playtime_forever"]
                    and before.get("last_played") == game.get("last_played")
                ):
                    state[appid] = {
                        "unlocked": {
                            u["apiname"]: as_int(u.get("unlocktime"))
                            for u in old.get("unlocked") or []
                        },
                        "total": as_int(old.get("total")),
                    }
                    continue
            to_fetch.append(appid)
        unchanged = len(state)

        # Steam answers "Profile is not public" for some games even on a public
        # profile (Forza Horizon, for one). Only when every game answers that way
        # is the profile itself private.
        private = threading.Event()
        readable = 0

        def fetch(appid: int) -> tuple[int, str, Any]:
            if private.is_set():
                return appid, "skipped", None
            try:
                return appid, "ok", self.api.player_achievements(steamid, appid)
            except SteamError as exc:
                if exc.kind == "private":
                    return appid, "private", None
                return appid, "error", exc
            except NetworkError as exc:
                return appid, "error", exc

        progress = self.ui.progress(self.tr.t("cli.collect.achievements"), len(to_fetch))
        with ThreadPoolExecutor(max_workers=self.workers) as pool:
            for future in as_completed([pool.submit(fetch, a) for a in to_fetch]):
                appid, outcome, rows = future.result()
                progress.advance()
                if outcome == "private":
                    section.hidden.append(appid)
                    if not readable and len(section.hidden) >= PRIVATE_AFTER:
                        private.set()
                elif outcome == "ok":
                    readable += 1
                    if not rows:
                        no_stats.put(appid, True)
                        continue
                    state[appid] = {
                        "unlocked": {
                            str(r["apiname"]): as_int(r.get("unlocktime"))
                            for r in rows
                            if as_int(r.get("achieved")) and r.get("apiname")
                        },
                        "total": len(rows),
                    }
                elif outcome == "error":
                    section.failed.append(appid)
                    self.warnings.append(f"achievements {appid}: {rows}")
        no_stats.save()
        progress.finish(
            self.tr.t("cli.collect.achievements_done", count=len(to_fetch), unchanged=unchanged)
        )

        if private.is_set() or (section.hidden and not readable and not state):
            self.sections["achievements"] = Section("private")
            self.ui.warn(self.tr.t("cli.collect.achievements_private"))
            return {}
        if section.hidden:
            names = {g["appid"]: g["name"] for g in games}
            shown = sorted(names.get(a) or str(a) for a in section.hidden)
            listed = ", ".join(shown[:3]) + (", …" if len(shown) > 3 else "")
            self.ui.info(
                self.tr.t("cli.collect.achievements_hidden", count=len(shown), games=listed)
            )
        if section.failed:
            section.status = "partial"
            self.ui.warn(self.tr.t("cli.collect.achievements_failed", count=len(section.failed)))

        self.load_achievement_details(state)

        names = {g["appid"]: g for g in games}
        result: dict[str, Any] = {}
        for appid in sorted(state):
            definitions = {
                a["apiname"]: a for a in self.schema(appid, "english").get("achievements", [])
            }
            unlocked = state[appid]["unlocked"]
            total = len(definitions) or state[appid]["total"] or len(unlocked)
            if not total:
                continue
            rarity = self.rarity.get(appid, {})
            entries = []
            for apiname, unlocktime in sorted(unlocked.items(), key=lambda kv: (-kv[1], kv[0])):
                definition = definitions.get(apiname, {})
                entries.append(
                    {
                        "apiname": apiname,
                        "unlocktime": unlocktime,
                        "name": definition.get("name") or apiname,
                        "description": definition.get("description") or "",
                        "percent": rarity.get(apiname),
                        "icon": definition.get("icon"),
                    }
                )
            times = [e["unlocktime"] for e in entries if e["unlocktime"]]
            game = names[appid]
            game["achievements"] = {
                "unlocked": len(entries),
                "total": total,
                "percent": round(100 * len(entries) / total, 2),
                "first_unlock": min(times) if times else None,
                "last_unlock": max(times) if times else None,
            }
            result[str(appid)] = {"name": game["name"], "total": total, "unlocked": entries}
        return result

    def schema(self, appid: int, language: str) -> dict[str, Any]:
        found = self.schemas.get((appid, language))
        if found is None:
            found = self.cache.read(f"schema/{appid}.{language}") or {}
            self.schemas[(appid, language)] = found
        return found

    def load_achievement_details(self, state: dict[int, dict[str, Any]]) -> None:
        """Achievement names, descriptions and icons in every language, plus global
        unlock rates, from the cache or the API."""
        jobs: list[tuple[str, int, str]] = []
        for appid, entry in state.items():
            for language in self.languages:
                schema = self.cache.read(f"schema/{appid}.{language}", self.ttl(SCHEMA_TTL_DAYS))
                count = len((schema or {}).get("achievements", []))
                if schema is None or (entry["total"] and count != entry["total"]):
                    jobs.append(("schema", appid, language))
                else:
                    self.schemas[(appid, language)] = schema
            if not self.config.get("collect.global_rarity"):
                self.rarity[appid] = self.cache.read(f"global/{appid}") or {}
                continue
            rarity = self.cache.read(f"global/{appid}", self.ttl(GLOBAL_TTL_DAYS))
            if rarity is None:
                jobs.append(("global", appid, ""))
            else:
                self.rarity[appid] = rarity

        def run(job: tuple[str, int, str]) -> tuple[tuple[str, int, str], Any]:
            kind, appid, language = job
            try:
                if kind == "schema":
                    return job, self.api.game_schema(appid, language)
                return job, self.api.global_percentages(appid)
            except (SteamError, NetworkError) as exc:
                return job, exc

        if not jobs:
            return
        progress = self.ui.progress(self.tr.t("cli.collect.details"), len(jobs))
        with ThreadPoolExecutor(max_workers=self.workers) as pool:
            for future in as_completed([pool.submit(run, j) for j in jobs]):
                (kind, appid, language), value = future.result()
                progress.advance()
                if isinstance(value, Exception):
                    self.warnings.append(f"{kind} {appid} {language}: {value}")
                    if kind == "schema":
                        self.schemas[(appid, language)] = (
                            self.cache.read(f"schema/{appid}.{language}") or {}
                        )
                    else:
                        self.rarity[appid] = self.cache.read(f"global/{appid}") or {}
                    continue
                if kind == "schema":
                    slim = {
                        "name": value["name"],
                        "achievements": [
                            {
                                "apiname": str(a.get("name")),
                                "name": a.get("displayName") or str(a.get("name")),
                                "description": a.get("description") or "",
                                "hidden": bool(as_int(a.get("hidden"))),
                                "icon": a.get("icon"),
                                "icon_gray": a.get("icongray"),
                            }
                            for a in value["achievements"]
                            if a.get("name")
                        ],
                    }
                    self.cache.write(f"schema/{appid}.{language}", slim)
                    self.schemas[(appid, language)] = slim
                else:
                    self.cache.write(f"global/{appid}", value)
                    self.rarity[appid] = value
        progress.finish()

    # ------------------------------------------------------------------ people

    def collect_friends(self, steamid: str) -> list[dict[str, Any]]:
        if not self.config.get("collect.friends"):
            self.sections["friends"] = Section("skipped")
            return []
        try:
            rows = self.api.friend_list(steamid)
        except SteamError as exc:
            if exc.kind == "private":
                self.sections["friends"] = Section("private")
                self.ui.warn(self.tr.t("cli.collect.friends_private"))
            else:
                self.sections["friends"] = Section("error", str(exc))
                self.warn("friends", exc)
            return []
        except NetworkError as exc:
            self.sections["friends"] = Section("error", str(exc))
            self.warn("friends", exc)
            return []

        since = {
            str(r["steamid"]): as_int(r.get("friend_since")) or None
            for r in rows
            if r.get("steamid")
        }
        friend_ids = list(since)
        summaries = {
            p["steamid"]: p
            for p in self.optional("friends", self.api.player_summaries, friend_ids) or []
        }
        bans = {
            str(b.get("SteamId")): b
            for b in self.optional("friends", self.api.player_bans, friend_ids) or []
        }
        levels: dict[str, int | None] = {}
        if self.config.get("collect.friend_levels") and friend_ids:
            progress = self.ui.progress(self.tr.t("cli.collect.friend_levels"), len(friend_ids))

            def level(fid: str) -> tuple[str, int | None]:
                try:
                    return fid, self.api.steam_level(fid)
                except (SteamError, NetworkError):
                    return fid, None

            with ThreadPoolExecutor(max_workers=self.workers) as pool:
                for future in as_completed([pool.submit(level, f) for f in friend_ids]):
                    fid, value = future.result()
                    levels[fid] = value
                    progress.advance()
            progress.finish()

        friends = []
        for fid in friend_ids:
            player = summaries.get(fid, {})
            gameid = as_int(player.get("gameid"))
            friends.append(
                {
                    "steamid": fid,
                    "name": str(player.get("personaname") or ""),
                    "realname": player.get("realname") or None,
                    "profile_url": player.get("profileurl")
                    or f"{self.api.endpoints.community}/profiles/{fid}/",
                    "avatar": player.get("avatarmedium") or player.get("avatar"),
                    "friend_since": since[fid],
                    "visibility": as_int(player.get("communityvisibilitystate")),
                    "state": as_int(player.get("personastate")),
                    "playing": {"appid": gameid, "name": player.get("gameextrainfo") or ""}
                    if gameid
                    else None,
                    "last_online": as_int(player.get("lastlogoff")) or None,
                    "created": as_int(player.get("timecreated")) or None,
                    "country": player.get("loccountrycode") or None,
                    "level": levels.get(fid),
                    "bans": normalize_bans(bans.get(fid)),
                }
            )
        friends.sort(key=lambda f: (f["name"].casefold(), f["steamid"]))
        self.sections["friends"] = Section("ok" if friends else "empty")
        self.step(
            self.tr.t("cli.collect.friends"),
            self.tr.t("cli.collect.friends_done", count=len(friends)),
        )
        return friends

    def collect_groups(self, steamid: str, primary: str | None) -> list[dict[str, Any]]:
        if not self.config.get("collect.groups"):
            self.sections["groups"] = Section("skipped")
            return []
        try:
            group_ids = self.api.user_groups(steamid)
        except (SteamError, NetworkError) as exc:
            private = isinstance(exc, SteamError) and exc.kind == "private"
            self.sections["groups"] = Section(
                "private" if private else "error", "" if private else str(exc)
            )
            return []
        table = self.cache.table("groups")
        stale = [g for g in group_ids if not table.get(g, self.ttl(GROUP_TTL_DAYS))[0]]
        if stale:
            progress = self.ui.progress(self.tr.t("cli.collect.groups"), len(stale))
            for gid in stale:
                try:
                    info = self.api.group_info(gid)
                except (SteamError, NetworkError) as exc:
                    self.warnings.append(f"group {gid}: {exc}")
                else:
                    table.put(gid, info)
                progress.advance()
            progress.finish()
            table.save()
        groups = []
        for gid in group_ids:
            info = table.get(gid, float("inf"))[1] or {}
            groups.append(
                {
                    "gid": gid,
                    "name": info.get("name") or None,
                    "url": f"{self.api.endpoints.community}/groups/{info['url']}"
                    if info.get("url")
                    else f"{self.api.endpoints.community}/gid/{gid}",
                    "avatar": info.get("avatar") or None,
                    "members": info.get("members"),
                    "primary": gid == primary,
                }
            )
        groups.sort(key=lambda g: (not g["primary"], (g["name"] or "").casefold(), g["gid"]))
        self.sections["groups"] = Section("ok" if groups else "empty")
        return groups

    # ------------------------------------------------------------------ media

    def queue_media(self, snapshot: dict[str, Any]) -> None:
        options = self.config.get("media") or {}
        want = self.media.want
        profile = snapshot["profile"]
        if options.get("avatars"):
            want(profile.get("avatar"))
            want(profile.get("avatar_medium"))
            for item in profile.get("equipped", {}).values():
                want(item.get("image"))
            for group in profile.get("groups", []):
                want(group.get("avatar"))
            for friend in snapshot["friends"]:
                want(friend.get("avatar"))
        if options.get("game_icons"):
            for game in snapshot["games"]:
                want(game.get("icon"))
            for game in snapshot["recent"]:
                want(game.get("icon"))
        if options.get("game_headers"):
            for game in snapshot["games"] + snapshot["wishlist"]:
                want((game.get("store") or {}).get("header"))
        mode = options.get("achievement_icons")
        limit = int(options.get("achievement_icon_limit") or 0)
        for appid, entry in snapshot["achievements"].items():
            if limit and entry["total"] > limit:
                continue
            if mode == "unlocked":
                for item in entry["unlocked"]:
                    want(item.get("icon"))
            elif mode == "all":
                for item in self.schema(int(appid), "english").get("achievements", []):
                    want(item.get("icon"))
