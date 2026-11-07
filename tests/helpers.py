# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 abel0x <https://github.com/abel0x>
"""Small hand-made snapshots for unit tests."""

from typing import Any

from steamledger.snapshot import summarize


def game(appid: int, name: str, minutes: int = 0) -> dict[str, Any]:
    return {
        "appid": appid,
        "name": name,
        "playtime_forever": minutes,
        "playtime_2weeks": 0,
        "playtime_windows": minutes,
        "playtime_mac": 0,
        "playtime_linux": 0,
        "playtime_deck": 0,
        "last_played": None,
        "achievements": None,
        "store": None,
    }


def unlocked(apiname: str, when: int = 1_700_000_000) -> dict[str, Any]:
    return {
        "apiname": apiname,
        "name": apiname.title(),
        "description": "",
        "unlocktime": when,
        "percent": 10.0,
        "icon": None,
    }


def snapshot(
    sid: str,
    collected_at: str,
    *,
    games: list[dict[str, Any]] | None = None,
    achievements: dict[str, Any] | None = None,
    friends: list[dict[str, Any]] | None = None,
    profile: dict[str, Any] | None = None,
    sections: dict[str, Any] | None = None,
) -> dict[str, Any]:
    data: dict[str, Any] = {
        "profile": {"steamid": "76561197960287930", "personaname": "Tester", "level": 5}
        | (profile or {}),
        "games": games or [],
        "achievements": achievements or {},
        "friends": friends or [],
        "badges": [],
        "recent": [],
        "wishlist": [],
    }
    data["meta"] = {
        "id": sid,
        "collected_at": collected_at,
        "sections": sections or {},
        "summary": summarize(data),
    }
    return data
