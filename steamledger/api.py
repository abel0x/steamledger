# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 abel0x <https://github.com/abel0x>
"""Typed wrappers around the Steam Web API endpoints this project reads.

Each method returns plain Python data close to Steam's own field names and turns
Steam's error conventions (401 for a private friend list, 403 for a bad key or a
private profile, 400 for a game without stats...) into ``SteamError.kind`` values
the collector can act on.
"""

from __future__ import annotations

import json
import xml.etree.ElementTree as ElementTree
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from .net import Http, Response
from .steamid import group64
from .util import as_int, chunks


@dataclass(frozen=True)
class Endpoints:
    api: str = "https://api.steampowered.com"
    community: str = "https://steamcommunity.com"
    store: str = "https://store.steampowered.com"
    store_assets: str = "https://shared.akamai.steamstatic.com/store_item_assets/"
    community_images: str = "https://cdn.akamai.steamstatic.com/steamcommunity/public/images/"
    # Game icons are moving here; some are already gone from the old path.
    community_assets: str = "https://shared.akamai.steamstatic.com/community_assets/images/"

    def app_icon(self, appid: int, icon_hash: str) -> str:
        return f"{self.community_assets}apps/{appid}/{icon_hash}.jpg"

    def store_asset(self, url_format: str, filename: str) -> str:
        return self.store_assets + url_format.replace("${FILENAME}", filename)

    def community_image(self, path: str) -> str:
        return self.community_images + path.lstrip("/")


class SteamError(Exception):
    """kind: forbidden, unauthorized, private, bad_request, not_found, rate_limited,
    http or bad_response."""

    def __init__(self, kind: str, message: str = "", status: int | None = None) -> None:
        super().__init__(f"{kind}: {message}" if message else kind)
        self.kind = kind
        self.status = status
        self.detail = message


_STATUS_KINDS = {
    400: "bad_request",
    401: "unauthorized",
    403: "forbidden",
    404: "not_found",
    429: "rate_limited",
}


class SteamApi:
    def __init__(self, http: Http, key: str = "", endpoints: Endpoints | None = None) -> None:
        self.http = http
        self.key = key
        self.endpoints = endpoints or Endpoints()

    # ------------------------------------------------------------------ plumbing

    def _get(self, path: str, params: dict[str, Any] | None = None, *, keyed: bool = True) -> Any:
        query = dict(params or {})
        if keyed and self.key:
            query["key"] = self.key
        response = self.http.get(f"{self.endpoints.api}/{path}", query)
        return self._decode(response)

    def _decode(self, response: Response) -> Any:
        if response.status == 200:
            try:
                return response.json() or {}
            except ValueError:
                raise SteamError("bad_response", self.http.redact(response.text()), 200) from None
        kind = _STATUS_KINDS.get(response.status, "http")
        raise SteamError(kind, self.http.redact(response.text()), response.status)

    # ------------------------------------------------------------------ ISteamUser

    def player_summaries(self, steamids: Iterable[str]) -> list[dict[str, Any]]:
        players: list[dict[str, Any]] = []
        for batch in chunks(list(dict.fromkeys(steamids)), 100):
            data = self._get("ISteamUser/GetPlayerSummaries/v2/", {"steamids": ",".join(batch)})
            players.extend((data.get("response") or {}).get("players") or [])
        return players

    def resolve_vanity(self, name: str) -> str | None:
        data = self._get("ISteamUser/ResolveVanityURL/v1/", {"vanityurl": name, "url_type": 1})
        reply = data.get("response") or {}
        if reply.get("success") == 1 and reply.get("steamid"):
            return str(reply["steamid"])
        return None

    def friend_list(self, steamid: str) -> list[dict[str, Any]]:
        """Raises SteamError('private') when the friend list is not public."""
        try:
            data = self._get(
                "ISteamUser/GetFriendList/v1/", {"steamid": steamid, "relationship": "friend"}
            )
        except SteamError as exc:
            if exc.kind in ("unauthorized", "forbidden"):
                raise SteamError("private", exc.detail, exc.status) from None
            raise
        return (data.get("friendslist") or {}).get("friends") or []

    def player_bans(self, steamids: Iterable[str]) -> list[dict[str, Any]]:
        players: list[dict[str, Any]] = []
        for batch in chunks(list(dict.fromkeys(steamids)), 100):
            data = self._get("ISteamUser/GetPlayerBans/v1/", {"steamids": ",".join(batch)})
            players.extend(data.get("players") or [])
        return players

    def user_groups(self, steamid: str) -> list[str]:
        try:
            data = self._get("ISteamUser/GetUserGroupList/v1/", {"steamid": steamid})
        except SteamError as exc:
            if exc.kind in ("unauthorized", "forbidden"):
                raise SteamError("private", exc.detail, exc.status) from None
            raise
        reply = data.get("response") or {}
        if reply.get("success") is False:
            raise SteamError("private", str(reply.get("error", "")))
        return [
            group64(g["gid"]) for g in reply.get("groups") or [] if str(g.get("gid", "")).isdigit()
        ]

    # ------------------------------------------------------------------ IPlayerService

    def owned_games(self, steamid: str) -> list[dict[str, Any]] | None:
        """None when the profile's game details are not public."""
        data = self._get(
            "IPlayerService/GetOwnedGames/v1/",
            {
                "steamid": steamid,
                "include_appinfo": True,
                "include_played_free_games": True,
                "include_extended_appinfo": True,
                "skip_unvetted_apps": False,
            },
        )
        reply = data.get("response") or {}
        if "games" not in reply and "game_count" not in reply:
            return None
        return reply.get("games") or []

    def recently_played(self, steamid: str) -> list[dict[str, Any]]:
        data = self._get(
            "IPlayerService/GetRecentlyPlayedGames/v1/", {"steamid": steamid, "count": 0}
        )
        return (data.get("response") or {}).get("games") or []

    def steam_level(self, steamid: str) -> int | None:
        data = self._get("IPlayerService/GetSteamLevel/v1/", {"steamid": steamid})
        level = (data.get("response") or {}).get("player_level")
        return None if level is None else as_int(level)

    def level_percentile(self, level: int) -> float | None:
        data = self._get("IPlayerService/GetSteamLevelDistribution/v1/", {"player_level": level})
        value = (data.get("response") or {}).get("player_level_percentile")
        try:
            return None if value is None else round(float(value), 2)
        except (TypeError, ValueError):
            return None

    def badges(self, steamid: str) -> dict[str, Any] | None:
        data = self._get("IPlayerService/GetBadges/v1/", {"steamid": steamid})
        return data.get("response") or None

    def profile_items(self, steamid: str) -> dict[str, Any]:
        data = self._get(
            "IPlayerService/GetProfileItemsEquipped/v1/",
            {"steamid": steamid, "language": "english"},
        )
        return data.get("response") or {}

    # ------------------------------------------------------------------ ISteamUserStats

    def player_achievements(self, steamid: str, appid: int) -> list[dict[str, Any]] | None:
        """None when the game has no stats. Raises SteamError('private') for a
        profile whose game details are hidden."""
        try:
            data = self._get(
                "ISteamUserStats/GetPlayerAchievements/v1/", {"steamid": steamid, "appid": appid}
            )
        except SteamError as exc:
            if exc.kind == "bad_request":
                return None
            if exc.kind in ("forbidden", "unauthorized"):
                raise SteamError("private", exc.detail, exc.status) from None
            raise
        stats = data.get("playerstats") or {}
        if stats.get("success") is False:
            error = str(stats.get("error", ""))
            if "not public" in error.lower():
                raise SteamError("private", error)
            return None
        return stats.get("achievements") or []

    def game_schema(self, appid: int, language: str) -> dict[str, Any]:
        data = self._get("ISteamUserStats/GetSchemaForGame/v2/", {"appid": appid, "l": language})
        game = data.get("game") or {}
        stats = game.get("availableGameStats") or {}
        return {
            "name": game.get("gameName") or "",
            "version": game.get("gameVersion"),
            "achievements": stats.get("achievements") or [],
        }

    def global_percentages(self, appid: int) -> dict[str, float]:
        data = self._get(
            "ISteamUserStats/GetGlobalAchievementPercentagesForApp/v2/",
            {"gameid": appid},
            keyed=False,
        )
        rows = (data.get("achievementpercentages") or {}).get("achievements") or []
        out: dict[str, float] = {}
        for row in rows:
            try:
                out[str(row["name"])] = round(float(row["percent"]), 2)
            except (KeyError, TypeError, ValueError):
                continue
        return out

    # ------------------------------------------------------------------ store

    def wishlist(self, steamid: str) -> list[dict[str, Any]]:
        data = self._get("IWishlistService/GetWishlist/v1/", {"steamid": steamid})
        return (data.get("response") or {}).get("items") or []

    def store_items(
        self, appids: Iterable[int], language: str, country: str
    ) -> dict[int, dict[str, Any]]:
        found: dict[int, dict[str, Any]] = {}
        for batch in chunks(sorted(set(appids)), 50):
            payload = {
                "ids": [{"appid": appid} for appid in batch],
                "context": {"language": language, "country_code": country, "steam_realm": 1},
                "data_request": {
                    "include_assets": True,
                    "include_release": True,
                    "include_platforms": True,
                    "include_basic_info": True,
                    "include_reviews": True,
                    "include_tag_count": 20,
                },
            }
            data = self._get(
                "IStoreBrowseService/GetItems/v1/",
                {"input_json": json.dumps(payload, separators=(",", ":"))},
                keyed=False,
            )
            for item in (data.get("response") or {}).get("store_items") or []:
                appid = as_int(item.get("appid") or item.get("id"))
                if item.get("success") == 1 and appid:
                    found[appid] = item
        return found

    def tag_names(self, language: str) -> dict[int, str]:
        data = self._get("IStoreService/GetTagList/v1/", {"language": language}, keyed=False)
        tags = (data.get("response") or {}).get("tags") or []
        return {as_int(t["tagid"]): str(t.get("name", "")) for t in tags if "tagid" in t}

    def store_categories(self, language: str) -> dict[int, str]:
        data = self._get(
            "IStoreBrowseService/GetStoreCategories/v1/", {"language": language}, keyed=False
        )
        rows = (data.get("response") or {}).get("categories") or []
        return {
            as_int(c["categoryid"]): str(c.get("display_name") or c.get("internal_name") or "")
            for c in rows
            if "categoryid" in c
        }

    # ------------------------------------------------------------------ community

    def group_info(self, gid: str) -> dict[str, Any] | None:
        """Name, URL, avatar and member counts from the public group XML feed."""
        response = self.http.get(
            f"{self.endpoints.community}/gid/{gid}/memberslistxml/", {"xml": 1}
        )
        if response.status != 200:
            raise SteamError(_STATUS_KINDS.get(response.status, "http"), "", response.status)
        try:
            root = ElementTree.fromstring(response.body)
        except ElementTree.ParseError:
            return None
        details = root.find("groupDetails")
        if details is None:
            return None

        def text(tag: str) -> str:
            node = details.find(tag)
            return (node.text or "").strip() if node is not None else ""

        return {
            "gid": gid,
            "name": text("groupName"),
            "url": text("groupURL"),
            "headline": text("headline"),
            "avatar": text("avatarFull") or text("avatarMedium"),
            "members": as_int(text("memberCount")),
            "online": as_int(text("membersOnline")),
        }
