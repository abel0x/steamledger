# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 abel0x <https://github.com/abel0x>
"""What changed between two snapshots.

The site's compare page runs the same rules in ``web/assets/diff.js``. A test
(tests/test_demo.py) runs both on every pair of demo snapshots and requires the
same output, so the command line, the saved reports and the browser always
agree. Every list is sorted by numbers or ids only, never by names, so the order
does not depend on the language or the collation rules of either runtime.

A section that was private, failed or switched off in either snapshot is listed
under ``unavailable`` instead of being reported as everything added or removed.
"""

from __future__ import annotations

from typing import Any

from .snapshot import USABLE, failed_apps, section_status

PROFILE_FIELDS = (
    "personaname",
    "realname",
    "avatar",
    "country",
    "custom_url",
    "visibility",
    "primary_group",
)
BAN_FIELDS = ("vac_bans", "game_bans", "community_banned", "economy_ban")


def _point(snapshot: dict[str, Any]) -> dict[str, Any]:
    meta = snapshot.get("meta") or {}
    return {"id": meta.get("id"), "collected_at": meta.get("collected_at")}


def _usable(a: dict[str, Any], b: dict[str, Any], section: str) -> bool:
    return section_status(a, section) in USABLE and section_status(b, section) in USABLE


def _achievement(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "apiname": item["apiname"],
        "name": item.get("name") or item["apiname"],
        "unlocktime": item.get("unlocktime") or 0,
        "percent": item.get("percent"),
        "icon": item.get("icon"),
    }


def _profile_changes(pa: dict[str, Any], pb: dict[str, Any]) -> list[dict[str, Any]]:
    changes = []
    for field in PROFILE_FIELDS:
        if field == "avatar":
            if pa.get("avatar_hash") != pb.get("avatar_hash"):
                changes.append(
                    {
                        "field": "avatar",
                        "from": pa.get("avatar_medium"),
                        "to": pb.get("avatar_medium"),
                    }
                )
        elif pa.get(field) != pb.get(field):
            changes.append({"field": field, "from": pa.get(field), "to": pb.get(field)})
    return changes


def compare(a: dict[str, Any], b: dict[str, Any]) -> dict[str, Any]:
    pa, pb = a.get("profile") or {}, b.get("profile") or {}
    unavailable: list[str] = []
    result: dict[str, Any] = {"from": _point(a), "to": _point(b)}

    result["profile"] = _profile_changes(pa, pb)

    la, lb = pa.get("level"), pb.get("level")
    result["level"] = (
        {"from": la, "to": lb} if la is not None and lb is not None and la != lb else None
    )
    xa, xb = (pa.get("xp") or {}).get("current"), (pb.get("xp") or {}).get("current")
    result["xp"] = (
        {"from": xa, "to": xb} if xa is not None and xb is not None and xa != xb else None
    )

    # ------------------------------------------------------------------ games
    playtime: list[dict[str, Any]] = []
    added: list[dict[str, Any]] = []
    removed: list[dict[str, Any]] = []
    if _usable(a, b, "games"):
        ga = {g["appid"]: g for g in a.get("games") or []}
        gb = {g["appid"]: g for g in b.get("games") or []}
        for appid in sorted(gb.keys() - ga.keys()):
            game = gb[appid]
            added.append(
                {"appid": appid, "name": game["name"], "playtime": game.get("playtime_forever", 0)}
            )
        for appid in sorted(ga.keys() - gb.keys()):
            removed.append({"appid": appid, "name": ga[appid]["name"]})
        for appid in ga.keys() & gb.keys():
            before, after = (
                ga[appid].get("playtime_forever", 0),
                gb[appid].get("playtime_forever", 0),
            )
            if before != after:
                playtime.append(
                    {
                        "appid": appid,
                        "name": gb[appid]["name"],
                        "from": before,
                        "to": after,
                        "delta": after - before,
                    }
                )
        playtime.sort(key=lambda row: (-row["delta"], row["appid"]))
    else:
        unavailable.append("games")
    result["playtime"] = playtime
    result["games_added"] = added
    result["games_removed"] = removed

    # ------------------------------------------------------------------ achievements
    unlocked: list[dict[str, Any]] = []
    lost: list[dict[str, Any]] = []
    completed: list[dict[str, Any]] = []
    if _usable(a, b, "achievements") and _usable(a, b, "games"):
        aa, ab = a.get("achievements") or {}, b.get("achievements") or {}
        skip = failed_apps(a) | failed_apps(b)
        for key in sorted(ab, key=int):
            appid = int(key)
            if appid in skip:
                continue
            after_entry = ab[key]
            before_entry = aa.get(key) or {}
            ea = {u["apiname"]: u for u in before_entry.get("unlocked") or []}
            eb = {u["apiname"]: u for u in after_entry.get("unlocked") or []}
            name = after_entry.get("name") or before_entry.get("name") or str(appid)
            new = sorted(
                (_achievement(eb[k]) for k in eb.keys() - ea.keys()),
                key=lambda i: (i["unlocktime"], i["apiname"]),
            )
            gone = sorted(
                (_achievement(ea[k]) for k in ea.keys() - eb.keys()),
                key=lambda i: (i["unlocktime"], i["apiname"]),
            )
            if new:
                unlocked.append({"appid": appid, "name": name, "items": new})
            if gone:
                lost.append({"appid": appid, "name": name, "items": gone})
            total_after = after_entry.get("total") or 0
            total_before = before_entry.get("total") or 0
            perfect_after = total_after > 0 and len(eb) >= total_after
            perfect_before = bool(before_entry) and total_before > 0 and len(ea) >= total_before
            if perfect_after and not perfect_before:
                completed.append({"appid": appid, "name": name})
    else:
        unavailable.append("achievements")
    result["achievements"] = unlocked
    result["achievements_lost"] = lost
    result["completed"] = completed

    # ------------------------------------------------------------------ friends
    friends_added: list[dict[str, Any]] = []
    friends_removed: list[dict[str, Any]] = []
    renamed: list[dict[str, Any]] = []
    if _usable(a, b, "friends"):
        fa = {f["steamid"]: f for f in a.get("friends") or []}
        fb = {f["steamid"]: f for f in b.get("friends") or []}
        for fid in sorted(fb.keys() - fa.keys()):
            f = fb[fid]
            friends_added.append(
                {
                    "steamid": fid,
                    "name": f.get("name") or "",
                    "avatar": f.get("avatar"),
                    "friend_since": f.get("friend_since"),
                }
            )
        for fid in sorted(fa.keys() - fb.keys()):
            f = fa[fid]
            friends_removed.append(
                {"steamid": fid, "name": f.get("name") or "", "avatar": f.get("avatar")}
            )
        for fid in sorted(fa.keys() & fb.keys()):
            old, new_name = fa[fid].get("name") or "", fb[fid].get("name") or ""
            if old and new_name and old != new_name:
                renamed.append({"steamid": fid, "from": old, "to": new_name})
    else:
        unavailable.append("friends")
    result["friends_added"] = friends_added
    result["friends_removed"] = friends_removed
    result["friends_renamed"] = renamed

    # ------------------------------------------------------------------ badges
    badges_added: list[dict[str, Any]] = []
    badges_changed: list[dict[str, Any]] = []
    if _usable(a, b, "badges"):

        def key(badge: dict[str, Any]) -> tuple[int, int, int]:
            return (badge["badgeid"], badge.get("appid") or 0, 1 if badge.get("foil") else 0)

        ba = {key(x): x for x in a.get("badges") or []}
        bb = {key(x): x for x in b.get("badges") or []}
        for k in sorted(bb.keys() - ba.keys()):
            x = bb[k]
            badges_added.append(
                {
                    "badgeid": x["badgeid"],
                    "appid": x.get("appid"),
                    "name": x.get("name"),
                    "level": x.get("level"),
                    "foil": bool(x.get("foil")),
                }
            )
        for k in sorted(ba.keys() & bb.keys()):
            if ba[k].get("level") != bb[k].get("level"):
                x = bb[k]
                badges_changed.append(
                    {
                        "badgeid": x["badgeid"],
                        "appid": x.get("appid"),
                        "name": x.get("name"),
                        "foil": bool(x.get("foil")),
                        "from": ba[k].get("level"),
                        "to": x.get("level"),
                    }
                )
    else:
        unavailable.append("badges")
    result["badges_added"] = badges_added
    result["badges_changed"] = badges_changed

    # ------------------------------------------------------------------ wishlist
    wish_added: list[dict[str, Any]] = []
    wish_removed: list[dict[str, Any]] = []
    if _usable(a, b, "wishlist"):
        wa = {w["appid"]: w for w in a.get("wishlist") or []}
        wb = {w["appid"]: w for w in b.get("wishlist") or []}
        wish_added = [
            {"appid": i, "name": wb[i].get("name") or str(i)} for i in sorted(wb.keys() - wa.keys())
        ]
        wish_removed = [
            {"appid": i, "name": wa[i].get("name") or str(i)} for i in sorted(wa.keys() - wb.keys())
        ]
    else:
        unavailable.append("wishlist")
    result["wishlist_added"] = wish_added
    result["wishlist_removed"] = wish_removed

    # ------------------------------------------------------------------ groups
    joined: list[dict[str, Any]] = []
    left: list[dict[str, Any]] = []
    if _usable(a, b, "groups"):
        ra = {g["gid"]: g for g in pa.get("groups") or []}
        rb = {g["gid"]: g for g in pb.get("groups") or []}
        joined = [{"gid": g, "name": rb[g].get("name")} for g in sorted(rb.keys() - ra.keys())]
        left = [{"gid": g, "name": ra[g].get("name")} for g in sorted(ra.keys() - rb.keys())]
    else:
        unavailable.append("groups")
    result["groups_joined"] = joined
    result["groups_left"] = left

    # ------------------------------------------------------------------ bans
    bans: list[dict[str, Any]] = []
    ban_a, ban_b = pa.get("bans"), pb.get("bans")
    if ban_a and ban_b:
        bans = [
            {"field": f, "from": ban_a.get(f), "to": ban_b.get(f)}
            for f in BAN_FIELDS
            if ban_a.get(f) != ban_b.get(f)
        ]
    result["bans"] = bans

    result["unavailable"] = unavailable
    result["summary"] = _summary(result)
    return result


def _summary(d: dict[str, Any]) -> dict[str, Any]:
    achievements = sum(len(group["items"]) for group in d["achievements"])
    lost = sum(len(group["items"]) for group in d["achievements_lost"])
    summary = {
        "playtime": sum(row["delta"] for row in d["playtime"])
        + sum(g["playtime"] for g in d["games_added"]),
        "games_played": len([row for row in d["playtime"] if row["delta"] > 0]),
        "achievements": achievements,
        "achievements_lost": lost,
        "completed": len(d["completed"]),
        "games_added": len(d["games_added"]),
        "games_removed": len(d["games_removed"]),
        "friends_added": len(d["friends_added"]),
        "friends_removed": len(d["friends_removed"]),
        "badges": len(d["badges_added"]) + len(d["badges_changed"]),
        "level": (d["level"]["to"] - d["level"]["from"]) if d["level"] else 0,
        "xp": (d["xp"]["to"] - d["xp"]["from"]) if d["xp"] else 0,
        "wishlist_added": len(d["wishlist_added"]),
        "wishlist_removed": len(d["wishlist_removed"]),
        "profile": len(d["profile"]),
    }
    summary["total"] = (
        len(d["profile"])
        + (1 if d["level"] else 0)
        + (1 if d["xp"] else 0)
        + len(d["playtime"])
        + len(d["games_added"])
        + len(d["games_removed"])
        + achievements
        + lost
        + len(d["friends_added"])
        + len(d["friends_removed"])
        + len(d["friends_renamed"])
        + len(d["badges_added"])
        + len(d["badges_changed"])
        + len(d["wishlist_added"])
        + len(d["wishlist_removed"])
        + len(d["groups_joined"])
        + len(d["groups_left"])
        + len(d["bans"])
    )
    return summary
