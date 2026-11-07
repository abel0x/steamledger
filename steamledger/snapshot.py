# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 abel0x <https://github.com/abel0x>
"""The snapshot: one collection run, stored as one folder of files.

A snapshot is a dict with these parts, each written to ``<part>.json``:

    meta          id, time, versions, per-section status, summary numbers
    profile       account, level, XP, bans, groups, equipped items
    games         owned games with playtime, achievement progress, store details
    achievements  unlocked achievements per game (app id as string key)
    friends       friend list with each friend's public profile at that moment
    badges        community and game badges
    recent        games played in the last two weeks
    wishlist      wishlisted apps

collect.py builds every part; its normalizing functions show each field.
"""

from __future__ import annotations

from typing import Any

FORMAT = "steamledger-snapshot"
SCHEMA_VERSION = 1

PARTS: dict[str, type] = {
    "profile": dict,
    "games": list,
    "achievements": dict,
    "friends": list,
    "badges": list,
    "recent": list,
    "wishlist": list,
}

# A section is comparable between two snapshots only in these states.
USABLE = ("ok", "empty", "partial")


def section_status(snapshot: dict[str, Any], name: str) -> str:
    sections = (snapshot.get("meta") or {}).get("sections") or {}
    return str((sections.get(name) or {}).get("status", "ok"))


def failed_apps(snapshot: dict[str, Any]) -> set[int]:
    """Games whose achievements this snapshot could not read: failed requests,
    and games Steam keeps hidden (``hidden``). Comparisons leave them out."""
    section = ((snapshot.get("meta") or {}).get("sections") or {}).get("achievements") or {}
    return {int(a) for a in [*section.get("failed", []), *section.get("hidden", [])]}


def summarize(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Headline numbers stored in meta.json, so lists and charts never need to
    load every snapshot in full."""
    profile = snapshot.get("profile") or {}
    games = snapshot.get("games") or []
    progress = [g["achievements"] for g in games if g.get("achievements")]
    started = [p for p in progress if p["unlocked"] > 0]
    return {
        "persona": profile.get("personaname"),
        "avatar": profile.get("avatar_medium") or profile.get("avatar"),
        "level": profile.get("level"),
        "xp": (profile.get("xp") or {}).get("current"),
        "games": len(games),
        "played": sum(1 for g in games if g.get("playtime_forever", 0) > 0),
        "playtime": sum(g.get("playtime_forever", 0) for g in games),
        "playtime_2weeks": sum(g.get("playtime_2weeks", 0) for g in games),
        "achievements": sum(p["unlocked"] for p in progress),
        "achievements_total": sum(p["total"] for p in progress),
        "perfect_games": sum(1 for p in started if p["unlocked"] >= p["total"]),
        "completion": round(sum(p["percent"] for p in started) / len(started), 2)
        if started
        else None,
        "friends": len(snapshot.get("friends") or []),
        "badges": len(snapshot.get("badges") or []),
        "wishlist": len(snapshot.get("wishlist") or []),
        "groups": len(profile.get("groups") or []),
    }
