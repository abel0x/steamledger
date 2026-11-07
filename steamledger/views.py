# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 abel0x <https://github.com/abel0x>
"""What the command line prints for snapshots, the snapshot list and comparisons."""

from __future__ import annotations

from typing import Any

from .console import Console
from .i18n import Translator
from .report import badge_name, changes_chips, period
from .store import Database


def summary_line(tr: Translator, changes: dict[str, Any] | None) -> str:
    if not changes or not (changes.get("summary") or {}).get("total"):
        return tr.t("diff.none")
    total = changes["summary"]["total"]
    return ", ".join(changes_chips(changes, tr)) or tr.t("diff.minor", count=total)


def print_list(ui: Console, tr: Translator, db: Database) -> None:
    ids = db.ids()
    if not ids:
        ui.info(tr.t("cli.list.empty"))
        return
    rows = []
    for position, sid in enumerate(ids, start=1):
        meta = db.meta(sid)
        s = meta.get("summary") or {}
        changes = (db.changes(sid) or {}).get("summary") or {}
        delta = []
        if changes.get("playtime"):
            delta.append(tr.signed_playtime(changes["playtime"]))
        if changes.get("achievements"):
            delta.append(f"+{changes['achievements']} ★")
        rows.append(
            [
                str(position),
                tr.datetime(meta.get("collected_at")),
                sid,
                tr.number(s.get("games") or 0),
                tr.playtime(s.get("playtime") or 0),
                tr.number(s.get("achievements") or 0),
                tr.number(s.get("friends") or 0),
                str(s.get("level") if s.get("level") is not None else ""),
                " ".join(delta),
            ]
        )
    ui.table(
        [
            "#",
            tr.t("cli.list.date"),
            tr.t("cli.list.id"),
            tr.t("cli.list.games"),
            tr.t("cli.list.playtime"),
            tr.t("cli.list.achievements"),
            tr.t("cli.list.friends"),
            tr.t("cli.list.level"),
            tr.t("cli.list.change"),
        ],
        rows,
        "><<>>>>><",
    )
    ui.print(ui.dim(tr.t("cli.list.hint")))


def print_snapshot(
    ui: Console, tr: Translator, snapshot: dict[str, Any], changes: dict[str, Any] | None
) -> None:
    meta = snapshot["meta"]
    profile = snapshot.get("profile") or {}
    s = meta.get("summary") or {}
    ui.heading(
        f"{profile.get('personaname', '')}  ·  {tr.datetime(meta.get('collected_at'))}  ·  {meta.get('id')}"
    )
    facts = [
        (tr.t("report.stat.level"), _value("level", profile.get("level"), tr)),
        (
            tr.t("report.stat.games"),
            f"{tr.number(s.get('games', 0))} ({tr.t('report.stat.played', count=s.get('played', 0))})",
        ),
        (tr.t("report.stat.playtime"), tr.playtime(s.get("playtime", 0))),
        (tr.t("report.stat.recent"), tr.playtime(s.get("playtime_2weeks", 0))),
        (
            tr.t("report.stat.achievements"),
            f"{tr.number(s.get('achievements', 0))} / {tr.number(s.get('achievements_total', 0))}",
        ),
        (
            tr.t("report.stat.completion"),
            tr.percent(s["completion"]) if s.get("completion") is not None else "—",
        ),
        (tr.t("report.stat.perfect"), tr.number(s.get("perfect_games", 0))),
        (tr.t("report.stat.friends"), tr.number(s.get("friends", 0))),
        (tr.t("report.stat.badges"), tr.number(s.get("badges", 0))),
    ]
    width = max(len(label) for label, _ in facts)
    for label, value in facts:
        ui.print(f"  {label.ljust(width)}  {ui.bold(value)}")
    games = [g for g in snapshot.get("games") or [] if g.get("playtime_forever")]
    if games:
        ui.print()
        ui.heading(tr.t("cli.show.top_games"))
        rows = [
            [
                g["name"],
                tr.playtime(g["playtime_forever"]),
                f"{g['achievements']['unlocked']}/{g['achievements']['total']}"
                if g.get("achievements")
                else "",
            ]
            for g in games[:10]
        ]
        ui.table(
            [tr.t("report.col.game"), tr.t("report.col.playtime"), tr.t("report.col.achievements")],
            rows,
            "<>>",
        )
    unlocked = sorted(
        (
            (item, entry["name"])
            for entry in (snapshot.get("achievements") or {}).values()
            for item in entry["unlocked"]
        ),
        key=lambda pair: -(pair[0].get("unlocktime") or 0),
    )
    if unlocked:
        ui.print()
        ui.heading(tr.t("cli.show.recent_achievements"))
        for item, game in unlocked[:8]:
            details = [game, tr.date(item["unlocktime"])]
            if item.get("percent") is not None:
                details.append(tr.percent(item["percent"]))
            ui.print(f"  ★ {item['name']} {ui.dim(' · '.join(details))}")
    ui.print()
    ui.print(f"{tr.t('cli.show.since_previous')}: {summary_line(tr, changes)}")
    sections = {
        k: v.get("status")
        for k, v in (meta.get("sections") or {}).items()
        if v.get("status") not in ("ok", "empty")
    }
    for name, status in sections.items():
        ui.warn(f"{tr.t(f'data.section_name.{name}')}: {tr.t(f'data.section.{status}')}")


def print_changes(ui: Console, tr: Translator, changes: dict[str, Any]) -> None:
    ui.heading(f"{tr.t('diff.title')}  {period(changes, tr)}")
    ui.print(f"  {summary_line(tr, changes)}")
    if not changes["summary"]["total"]:
        return

    def section(key: str, lines: list[str]) -> None:
        if lines:
            ui.print()
            ui.heading(tr.t(f"diff.section.{key}"))
            for line in lines:
                ui.print(f"  {line}")

    section("profile", [_change_line(tr, "data.profile_field", c) for c in changes["profile"]])
    level_lines = []
    if changes.get("level"):
        level_lines.append(
            tr.t("diff.level", **{"from": changes["level"]["from"], "to": changes["level"]["to"]})
        )
    if changes.get("xp"):
        level_lines.append(
            tr.t("diff.xp", value=tr.number(changes["xp"]["to"] - changes["xp"]["from"]))
        )
    section("level", level_lines)
    playtime_lines = []
    for row in changes["playtime"]:
        delta = tr.signed_playtime(row["delta"])
        delta = ui.green(delta) if row["delta"] > 0 else ui.red(delta)
        total = ui.dim(f"({tr.playtime(row['to'])})")
        playtime_lines.append(f"{delta}  {row['name']} {total}")
    section("playtime", playtime_lines)
    section("games_added", [ui.green("+ ") + g["name"] for g in changes["games_added"]])
    section("games_removed", [ui.red("− ") + g["name"] for g in changes["games_removed"]])
    lines = []
    for group in changes["achievements"]:
        lines.append(ui.bold(f"{group['name']} ({len(group['items'])})"))
        for item in group["items"]:
            when = (
                tr.datetime(item["unlocktime"])
                if item["unlocktime"]
                else tr.t("report.unknown_date")
            )
            rare = f" · {tr.percent(item['percent'])}" if item.get("percent") is not None else ""
            lines.append(f"  ★ {item['name']} {ui.dim(when + rare)}")
    section("achievements", lines)
    section(
        "achievements_lost",
        [
            f"{g['name']}: {', '.join(i['name'] for i in g['items'])}"
            for g in changes["achievements_lost"]
        ],
    )
    section("completed", [ui.green("✓ ") + g["name"] for g in changes["completed"]])
    section(
        "friends_added",
        [ui.green("+ ") + (f["name"] or f["steamid"]) for f in changes["friends_added"]],
    )
    section(
        "friends_removed",
        [ui.red("− ") + (f["name"] or f["steamid"]) for f in changes["friends_removed"]],
    )
    section("friends_renamed", [f"{r['from']} → {r['to']}" for r in changes["friends_renamed"]])
    section(
        "badges",
        [
            tr.t("diff.badge_new", name=badge_name(b, tr), level=b.get("level"))
            for b in changes["badges_added"]
        ]
        + [
            tr.t("diff.badge_level", name=badge_name(b, tr), **{"from": b["from"], "to": b["to"]})
            for b in changes["badges_changed"]
        ],
    )
    section(
        "wishlist",
        [ui.green("+ ") + w["name"] for w in changes["wishlist_added"]]
        + [ui.red("− ") + w["name"] for w in changes["wishlist_removed"]],
    )
    section(
        "groups",
        [ui.green("+ ") + (g.get("name") or g["gid"]) for g in changes["groups_joined"]]
        + [ui.red("− ") + (g.get("name") or g["gid"]) for g in changes["groups_left"]],
    )
    section("bans", [_change_line(tr, "data.ban_field", b) for b in changes["bans"]])
    if changes.get("unavailable"):
        ui.print()
        names = ", ".join(tr.t(f"data.section_name.{n}") for n in changes["unavailable"])
        ui.warn(tr.t("diff.unavailable", sections=names))


def _change_line(tr: Translator, prefix: str, change: dict[str, Any]) -> str:
    field = change["field"]
    label = tr.t(f"{prefix}.{field}")
    return f"{label}: {_value(field, change['from'], tr)} → {_value(field, change['to'], tr)}"


def _value(field: str, value: Any, tr: Translator) -> str:
    if value is None or value == "":
        return "—"
    if field == "visibility":
        return tr.t(f"data.visibility.{value}")
    if field == "avatar":
        return tr.t("diff.avatar_image")
    if isinstance(value, bool):
        return tr.t("report.yes" if value else "report.no")
    return str(value)
