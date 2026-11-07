# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 abel0x <https://github.com/abel0x>
"""Static HTML written into the database folder: a report per snapshot and
language, comparison pages and the folder index.

The pages use no JavaScript and no external files, so they open with a double
click on any machine, offline. Images come from database/media when they were
downloaded and from Steam's CDN otherwise.
"""

from __future__ import annotations

import functools
import html
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any

from . import HOMEPAGE, __version__
from .i18n import DEFAULT_LANGUAGE, Translator, available_languages
from .media import local_path
from .util import days_between, parse_iso, write_text

SNAPSHOT_FILES = (
    "meta.json",
    "profile.json",
    "games.json",
    "games.csv",
    "achievements.json",
    "achievements.csv",
    "friends.json",
    "friends.csv",
    "badges.json",
    "badges.csv",
    "wishlist.json",
    "wishlist.csv",
    "recent.json",
    "changes.json",
)


@functools.cache
def translators() -> tuple[Translator, ...]:
    """One translator per shipped language. Cached: every page asks for them."""
    return tuple(Translator(code) for code in available_languages())


def localized_name(stem: str, lang: str, ext: str = "html") -> str:
    return f"{stem}.{ext}" if lang == DEFAULT_LANGUAGE else f"{stem}.{lang}.{ext}"


def esc(value: Any) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def link(url: Any, text: Any) -> str:
    """An escaped link, or plain text when ``url`` is not a web address."""
    href = str(url or "")
    if not href.startswith(("https://", "http://")):
        return esc(text)
    return f'<a href="{esc(href)}">{esc(text)}</a>'


class Images:
    def __init__(self, database: Path, depth: int) -> None:
        self.database = database
        self.prefix = "../" * depth

    def __call__(self, url: str | None) -> str:
        if not url:
            return ""
        rel = local_path(url)
        if rel and (self.database / rel).is_file():
            return self.prefix + rel
        return url

    def tag(self, url: str | None, size: int, cls: str = "") -> str:
        src = self(url)
        if not src:
            return f'<span class="ph {cls}" style="width:{size}px;height:{size}px"></span>'
        return f'<img class="{cls}" src="{esc(src)}" width="{size}" height="{size}" alt="" loading="lazy">'


CSS = """
:root{--bg:#f5f6f8;--panel:#fff;--ink:#16191f;--muted:#5d6675;--line:#e1e4ea;--accent:#1f66d1;
--good:#1c7f45;--bad:#b83232;--chip:#edf0f5;--bar:#c9d6ea;color-scheme:light dark}
@media (prefers-color-scheme:dark){:root{--bg:#0e1115;--panel:#161a20;--ink:#e6e9ee;--muted:#98a2b1;
--line:#262c35;--accent:#73a7ff;--good:#4cc38a;--bad:#ff8080;--chip:#1e242c;--bar:#2c3e5c}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 system-ui,-apple-system,"Segoe UI",Roboto,Ubuntu,"Noto Sans",sans-serif}
main{max-width:1180px;margin:0 auto;padding:24px 16px 48px}
a{color:var(--accent);text-decoration:none}a:hover{text-decoration:underline}
h1{font-size:28px;line-height:1.2;margin:0 0 4px}
h2{font-size:19px;margin:36px 0 12px;padding-bottom:6px;border-bottom:1px solid var(--line)}
h3{font-size:15px;margin:18px 0 6px}
.muted{color:var(--muted)}.good{color:var(--good)}.bad{color:var(--bad)}
.langs{max-width:1180px;margin:0 auto;padding:12px 16px 0;display:flex;gap:12px;justify-content:flex-end;font-size:13px}
.langs [aria-current]{font-weight:700;color:var(--ink)}
.hero{display:flex;gap:18px;align-items:center;flex-wrap:wrap}
.hero img,.hero .ph{border-radius:10px}
.hero p{margin:2px 0}
.ph{display:inline-block;background:var(--chip);border-radius:4px;vertical-align:middle}
.cards{display:grid;grid-template-columns:repeat(auto-fill,minmax(160px,1fr));gap:10px;margin-top:22px}
.card{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:12px 14px}
.card b{display:block;font-size:22px;font-variant-numeric:tabular-nums}
.card span{font-size:13px;color:var(--muted)}
.chips{display:flex;flex-wrap:wrap;gap:8px;margin:8px 0}
.chip{background:var(--chip);border-radius:999px;padding:3px 11px;font-size:13px}
.wrap{overflow-x:auto;background:var(--panel);border:1px solid var(--line);border-radius:10px}
table{border-collapse:collapse;width:100%;font-size:14px}
th,td{text-align:left;padding:7px 10px;border-bottom:1px solid var(--line);vertical-align:middle}
th{font-size:12px;text-transform:uppercase;letter-spacing:.03em;color:var(--muted);white-space:nowrap;background:var(--panel);position:sticky;top:0}
tr:last-child td{border-bottom:0}
td.n,th.n{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}
td img,td .ph{border-radius:4px;vertical-align:middle;margin-right:8px}
.item{display:flex;align-items:center;gap:8px}
.bar{display:inline-block;height:6px;border-radius:3px;background:var(--bar);vertical-align:middle;margin-left:6px}
.bar i{display:block;height:100%;border-radius:3px;background:var(--accent)}
dl{display:grid;grid-template-columns:minmax(140px,max-content) 1fr;gap:6px 18px;margin:0;background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:14px}
dt{color:var(--muted)}dd{margin:0;overflow-wrap:anywhere}
ul.plain{list-style:none;padding:0;margin:0}
ul.plain li{padding:6px 0;border-bottom:1px solid var(--line)}
.note{background:var(--chip);border-radius:8px;padding:10px 12px;font-size:14px}
.foot{max-width:1180px;margin:0 auto;padding:0 16px 32px;font-size:12px;color:var(--muted)}
.files{display:flex;flex-wrap:wrap;gap:6px 14px;font-size:13px}
@media print{.langs{display:none}body{background:#fff}.wrap,.card,dl{border-color:#ccc}}
"""


def page(tr: Translator, title: str, body: str, alternates: Sequence[tuple[str, str, str]]) -> str:
    links = []
    for code, name, href in alternates:
        current = ' aria-current="page"' if code == tr.lang else ""
        links.append(
            f'<a href="{esc(href)}" hreflang="{code}" lang="{code}"{current}>{esc(name)}</a>'
        )
    links = " ".join(links)
    footer = tr.t("report.footer", version=__version__)
    return (
        "<!doctype html>\n"
        f'<html lang="{tr.lang}">\n<head>\n<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f'<meta name="generator" content="steamledger {__version__}">\n'
        f"<title>{esc(title)}</title>\n<style>{CSS}</style>\n</head>\n<body>\n"
        f'<nav class="langs" aria-label="{esc(tr.t("report.language"))}">{links}</nav>\n'
        f"<main>\n{body}\n</main>\n"
        f'<footer class="foot"><p>{esc(footer)} <a href="{HOMEPAGE}">{HOMEPAGE}</a></p></footer>\n'
        "</body>\n</html>\n"
    )


def alternates(stem: str) -> list[tuple[str, str, str]]:
    return [(t.lang, t.name, localized_name(stem, t.lang)) for t in translators()]


def table(headers: Sequence[tuple[str, str]], rows: Iterable[Sequence[str]]) -> str:
    head = "".join(f'<th class="{cls}">{esc(label)}</th>' for label, cls in headers)
    body = "".join(
        "<tr>"
        + "".join(f'<td class="{headers[i][1]}">{cell}</td>' for i, cell in enumerate(row))
        + "</tr>"
        for row in rows
    )
    return f'<div class="wrap"><table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>'


def section_note(tr: Translator, meta: dict[str, Any], name: str) -> str:
    status = ((meta.get("sections") or {}).get(name) or {}).get("status", "ok")
    if status in ("ok", "partial"):
        return ""
    return f'<p class="note">{esc(tr.t(f"data.section.{status}"))}</p>'


def bar(percent: float | None, width: int = 60) -> str:
    if percent is None:
        return ""
    inner = max(0.0, min(100.0, float(percent)))
    return f'<span class="bar" style="width:{width}px"><i style="width:{inner:.1f}%"></i></span>'


# --------------------------------------------------------------------------- snapshot report


def render_snapshot_page(
    snapshot: dict[str, Any],
    changes: dict[str, Any] | None,
    tr: Translator,
    *,
    depth: int,
    database: Path,
    files: Iterable[str] = (),
) -> str:
    img = Images(database, depth)
    meta = snapshot.get("meta") or {}
    profile = snapshot.get("profile") or {}
    summary = meta.get("summary") or {}
    name = profile.get("personaname") or meta.get("steamid") or ""
    collected = meta.get("collected_at")
    out: list[str] = []

    facts = [
        profile.get("realname"),
        profile.get("country"),
        tr.t("report.level", level=profile["level"]) if profile.get("level") is not None else None,
    ]
    out.append(
        '<header class="hero">'
        + img.tag(profile.get("avatar"), 96)
        + f'<div><h1>{esc(name)}</h1><p class="muted">{esc(" · ".join(str(f) for f in facts if f))}</p>'
        + f'<p class="muted">{esc(tr.t("report.collected", date=tr.datetime(collected)))} · <code>{esc(meta.get("id"))}</code></p></div></header>'
    )

    cards = [
        (
            tr.t("report.stat.level"),
            str(profile["level"]) if profile.get("level") is not None else "—",
            tr.t("report.percentile", value=tr.percent(profile["level_percentile"]))
            if profile.get("level_percentile")
            else "",
        ),
        (
            tr.t("report.stat.games"),
            tr.number(summary.get("games", 0)),
            tr.t("report.stat.played", count=summary.get("played", 0)),
        ),
        (
            tr.t("report.stat.playtime"),
            tr.playtime(summary.get("playtime", 0)),
            tr.t("report.stat.days", value=tr.number(summary.get("playtime", 0) / 1440, 1)),
        ),
        (tr.t("report.stat.recent"), tr.playtime(summary.get("playtime_2weeks", 0)), ""),
        (
            tr.t("report.stat.achievements"),
            tr.number(summary.get("achievements", 0)),
            tr.t("report.stat.of_total", total=tr.number(summary.get("achievements_total", 0))),
        ),
        (
            tr.t("report.stat.completion"),
            tr.percent(summary["completion"]) if summary.get("completion") is not None else "—",
            "",
        ),
        (tr.t("report.stat.perfect"), tr.number(summary.get("perfect_games", 0)), ""),
        (tr.t("report.stat.friends"), tr.number(summary.get("friends", 0)), ""),
        (tr.t("report.stat.badges"), tr.number(summary.get("badges", 0)), ""),
        (tr.t("report.stat.wishlist"), tr.number(summary.get("wishlist", 0)), ""),
    ]
    out.append(
        '<section class="cards">'
        + "".join(
            f'<div class="card"><span>{esc(label)}</span><b>{esc(value)}</b><span>{esc(extra)}</span></div>'
            for label, value, extra in cards
        )
        + "</section>"
    )

    if changes is not None:
        out.append(f"<h2>{esc(tr.t('report.section.changes'))}</h2>")
        out.append(changes_body(changes, tr, img, brief=True))

    games = snapshot.get("games") or []
    out.append(
        f'<h2>{esc(tr.t("report.section.games"))} <span class="muted">({tr.number(len(games))})</span></h2>'
    )
    out.append(section_note(tr, meta, "games"))
    if games:
        rows = []
        for g in games:
            progress = g.get("achievements")
            store = g.get("store") or {}
            rows.append(
                [
                    f'<span class="item">{img.tag(g.get("icon"), 24)}{esc(g["name"])}</span>',
                    esc(tr.playtime(g["playtime_forever"]))
                    if g["playtime_forever"]
                    else '<span class="muted">—</span>',
                    esc(tr.playtime(g["playtime_2weeks"])) if g.get("playtime_2weeks") else "",
                    esc(tr.date(g.get("last_played")))
                    if g.get("last_played")
                    else '<span class="muted">' + esc(tr.t("report.never")) + "</span>",
                    (
                        f"{progress['unlocked']}/{progress['total']}{bar(progress['percent'])}"
                        if progress
                        else ""
                    ),
                    esc(tr.date(store.get("release"))) if store.get("release") else "",
                    esc(", ".join(store.get("developers") or [])),
                ]
            )
        out.append(
            table(
                [
                    (tr.t("report.col.game"), ""),
                    (tr.t("report.col.playtime"), "n"),
                    (tr.t("report.col.recent"), "n"),
                    (tr.t("report.col.last_played"), "n"),
                    (tr.t("report.col.achievements"), "n"),
                    (tr.t("report.col.release"), "n"),
                    (tr.t("report.col.developer"), ""),
                ],
                rows,
            )
        )

    unlocked = []
    for entry in (snapshot.get("achievements") or {}).values():
        for item in entry["unlocked"]:
            unlocked.append((item, entry["name"]))
    unlocked.sort(key=lambda pair: -(pair[0].get("unlocktime") or 0))
    out.append(f"<h2>{esc(tr.t('report.section.achievements'))}</h2>")
    out.append(section_note(tr, meta, "achievements"))
    if unlocked:
        rows = [
            [
                f'<span class="item">{img.tag(item.get("icon"), 32)}<span><b>{esc(item["name"])}</b><br><span class="muted">{esc(item.get("description"))}</span></span></span>',
                esc(game),
                esc(tr.datetime(item["unlocktime"]))
                if item.get("unlocktime")
                else esc(tr.t("report.unknown_date")),
                esc(tr.percent(item["percent"])) if item.get("percent") is not None else "",
            ]
            for item, game in unlocked[:100]
        ]
        out.append(
            table(
                [
                    (tr.t("report.col.achievement"), ""),
                    (tr.t("report.col.game"), ""),
                    (tr.t("report.col.unlocked"), "n"),
                    (tr.t("report.col.rarity"), "n"),
                ],
                rows,
            )
        )

    friends = snapshot.get("friends") or []
    out.append(
        f'<h2>{esc(tr.t("report.section.friends"))} <span class="muted">({tr.number(len(friends))})</span></h2>'
    )
    out.append(section_note(tr, meta, "friends"))
    if friends:
        rows = []
        for f in sorted(friends, key=lambda f: f.get("friend_since") or 0):
            bans = f.get("bans") or {}
            flags = tr.t("report.banned") if bans.get("vac_bans") or bans.get("game_bans") else ""
            rows.append(
                [
                    f'<span class="item">{img.tag(f.get("avatar"), 28)}{link(f.get("profile_url"), f["name"] or f["steamid"])}</span>',
                    esc(tr.date(f.get("friend_since"))),
                    esc(f.get("country") or ""),
                    esc(f.get("level") if f.get("level") is not None else ""),
                    esc(tr.date(f.get("created"))),
                    f'<span class="bad">{esc(flags)}</span>',
                ]
            )
        out.append(
            table(
                [
                    (tr.t("report.col.friend"), ""),
                    (tr.t("report.col.since"), "n"),
                    (tr.t("report.col.country"), ""),
                    (tr.t("report.col.level"), "n"),
                    (tr.t("report.col.account_created"), "n"),
                    ("", ""),
                ],
                rows,
            )
        )

    badges = snapshot.get("badges") or []
    out.append(
        f'<h2>{esc(tr.t("report.section.badges"))} <span class="muted">({tr.number(len(badges))})</span></h2>'
    )
    out.append(section_note(tr, meta, "badges"))
    if badges:
        rows = [
            [
                esc(badge_name(b, tr))
                + (
                    f' <span class="chip">{esc(tr.t("report.foil"))}</span>'
                    if b.get("foil")
                    else ""
                ),
                esc(b.get("level")),
                esc(tr.number(b.get("xp") or 0)),
                esc(tr.date(b.get("earned"))),
            ]
            for b in badges
        ]
        out.append(
            table(
                [
                    (tr.t("report.col.badge"), ""),
                    (tr.t("report.col.level"), "n"),
                    (tr.t("report.col.xp"), "n"),
                    (tr.t("report.col.earned"), "n"),
                ],
                rows,
            )
        )

    wishlist = snapshot.get("wishlist") or []
    out.append(
        f'<h2>{esc(tr.t("report.section.wishlist"))} <span class="muted">({tr.number(len(wishlist))})</span></h2>'
    )
    out.append(section_note(tr, meta, "wishlist"))
    if wishlist:
        rows = []
        for w in wishlist:
            store = w.get("store") or {}
            review = store.get("review") or {}
            rows.append(
                [
                    f'<a href="https://store.steampowered.com/app/{w["appid"]}/">{esc(w.get("name"))}</a>',
                    esc(tr.date(w.get("added"))),
                    esc(tr.date(store.get("release"))) if store.get("release") else "",
                    esc(tr.percent(review["percent"], 0)) if review.get("percent") else "",
                ]
            )
        out.append(
            table(
                [
                    (tr.t("report.col.name"), ""),
                    (tr.t("report.col.added"), "n"),
                    (tr.t("report.col.release"), "n"),
                    (tr.t("report.col.reviews"), "n"),
                ],
                rows,
            )
        )

    out.append(f"<h2>{esc(tr.t('report.section.details'))}</h2>")
    out.append(profile_details(profile, tr, img))

    present = [f for f in files if f]
    if present:
        out.append(
            f'<h2>{esc(tr.t("report.section.files"))}</h2><p class="muted">{esc(tr.t("report.files_hint"))}</p>'
        )
        out.append(
            '<p class="files">'
            + " ".join(f'<a href="{esc(f)}">{esc(f)}</a>' for f in present)
            + "</p>"
        )

    title = tr.t("report.title", name=name, date=tr.date(collected))
    return page(tr, title, "\n".join(o for o in out if o), alternates("report"))


def badge_name(badge: dict[str, Any], tr: Translator) -> str:
    key = f"data.badge.{badge['badgeid']}"
    if not badge.get("appid") and tr.has(key):
        return tr.t(key)
    if badge.get("name"):
        return str(badge["name"])
    if badge.get("appid"):
        return tr.t("report.badge_app", appid=badge["appid"])
    return tr.t("report.badge_id", id=badge["badgeid"])


def profile_details(profile: dict[str, Any], tr: Translator, img: Images) -> str:
    bans = profile.get("bans") or {}
    rows: list[tuple[str, str]] = [
        ("SteamID64", esc(profile.get("steamid"))),
        ("SteamID3", esc(profile.get("steamid3"))),
        ("SteamID", esc(profile.get("steamid2"))),
        (tr.t("report.details.account_id"), esc(profile.get("account_id"))),
        (
            tr.t("report.details.profile"),
            link(profile.get("profile_url"), profile.get("profile_url")),
        ),
        (
            tr.t("report.details.visibility"),
            esc(tr.t(f"data.visibility.{profile.get('visibility', 0)}")),
        ),
        (tr.t("report.details.created"), esc(tr.date(profile.get("created")))),
        (tr.t("report.details.last_online"), esc(tr.datetime(profile.get("last_online")))),
        (
            tr.t("report.details.state"),
            esc(tr.t(f"data.state.{profile.get('state', 0)}"))
            + (f" — {esc(profile['playing']['name'])}" if profile.get("playing") else ""),
        ),
    ]
    if bans:
        clean = not (
            bans.get("vac_bans")
            or bans.get("game_bans")
            or bans.get("community_banned")
            or bans.get("economy_ban") not in ("none", None)
        )
        text = (
            tr.t("report.details.no_bans")
            if clean
            else tr.t(
                "report.details.bans_summary",
                vac=bans.get("vac_bans", 0),
                game=bans.get("game_bans", 0),
                days=bans.get("days_since_last_ban", 0),
            )
        )
        rows.append((tr.t("report.details.bans"), esc(text)))
    groups = profile.get("groups") or []
    if groups:
        rows.append(
            (
                tr.t("report.details.groups"),
                ", ".join(link(g.get("url"), g.get("name") or g["gid"]) for g in groups),
            )
        )
    for slot, item in (profile.get("equipped") or {}).items():
        rows.append(
            (
                tr.t(f"data.equipped.{slot}"),
                f'<span class="item">{img.tag(item.get("image"), 32)}{esc(item.get("name"))}</span>',
            )
        )
    return (
        "<dl>"
        + "".join(f"<dt>{esc(label)}</dt><dd>{value}</dd>" for label, value in rows)
        + "</dl>"
    )


# --------------------------------------------------------------------------- changes


SUMMARY_COUNTS = (
    "achievements",
    "completed",
    "games_added",
    "games_removed",
    "friends_added",
    "friends_removed",
    "badges",
    "wishlist_added",
    "wishlist_removed",
    "profile",
)


def changes_chips(changes: dict[str, Any], tr: Translator) -> list[str]:
    """The headline changes as short phrases: '+3.5 h played', '2 achievements'..."""
    s = changes.get("summary") or {}
    chips = []
    if s.get("playtime"):
        chips.append(tr.t("diff.summary.playtime", value=tr.signed_playtime(s["playtime"])))
    for key in SUMMARY_COUNTS:
        if s.get(key):
            chips.append(tr.t(f"diff.summary.{key}", count=s[key]))
    if changes.get("level"):
        chips.append(
            tr.t(
                "diff.summary.level",
                **{"from": changes["level"]["from"], "to": changes["level"]["to"]},
            )
        )
    return chips


def field_value(field: str, value: Any, tr: Translator, img: Images) -> str:
    if value is None or value == "":
        return '<span class="muted">—</span>'
    if field == "avatar":
        return img.tag(value, 48)
    if field == "visibility":
        return esc(tr.t(f"data.visibility.{value}"))
    if isinstance(value, bool):
        return esc(tr.t("report.yes" if value else "report.no"))
    return esc(value)


def changes_body(
    changes: dict[str, Any], tr: Translator, img: Images, *, brief: bool = False
) -> str:
    out: list[str] = []
    chips = changes_chips(changes, tr)
    if not changes.get("summary", {}).get("total"):
        out.append(f'<p class="muted">{esc(tr.t("diff.none"))}</p>')
    elif chips:
        out.append(
            '<div class="chips">'
            + "".join(f'<span class="chip">{esc(c)}</span>' for c in chips)
            + "</div>"
        )
    limit = 8 if brief else None

    def heading(key: str, count: int | None = None) -> str:
        label = tr.t(f"diff.section.{key}")
        return (
            f"<h3>{esc(label)}"
            + (f' <span class="muted">({tr.number(count)})</span>' if count else "")
            + "</h3>"
        )

    if changes.get("profile"):
        out.append(heading("profile"))
        rows = [
            [
                esc(tr.t(f"data.profile_field.{c['field']}")),
                field_value(c["field"], c["from"], tr, img),
                field_value(c["field"], c["to"], tr, img),
            ]
            for c in changes["profile"]
        ]
        out.append(
            table(
                [
                    (tr.t("report.col.field"), ""),
                    (tr.t("report.col.before"), ""),
                    (tr.t("report.col.after"), ""),
                ],
                rows,
            )
        )
    if changes.get("level") or changes.get("xp"):
        out.append(heading("level"))
        items = []
        if changes.get("level"):
            items.append(
                tr.t(
                    "diff.level", **{"from": changes["level"]["from"], "to": changes["level"]["to"]}
                )
            )
        if changes.get("xp"):
            items.append(
                tr.t("diff.xp", value=tr.number(changes["xp"]["to"] - changes["xp"]["from"]))
            )
        out.append('<ul class="plain">' + "".join(f"<li>{esc(i)}</li>" for i in items) + "</ul>")
    playtime = changes.get("playtime") or []
    if playtime:
        out.append(heading("playtime", len(playtime)))
        top = max(abs(r["delta"]) for r in playtime) or 1
        rows = [
            [
                esc(r["name"]),
                f'<span class="{"good" if r["delta"] > 0 else "bad"}">{esc(tr.signed_playtime(r["delta"]))}</span>{bar(100 * abs(r["delta"]) / top, 90)}',
                esc(tr.playtime(r["to"])),
            ]
            for r in playtime[:limit]
        ]
        out.append(
            table(
                [
                    (tr.t("report.col.game"), ""),
                    (tr.t("report.col.change"), "n"),
                    (tr.t("report.col.total"), "n"),
                ],
                rows,
            )
        )
    for key, cls in (("games_added", "good"), ("games_removed", "bad")):
        items = changes.get(key) or []
        if items:
            out.append(heading(key, len(items)))
            out.append(
                '<ul class="plain">'
                + "".join(f'<li class="{cls}">{esc(g["name"])}</li>' for g in items[:limit])
                + "</ul>"
            )
    groups = changes.get("achievements") or []
    if groups:
        out.append(heading("achievements", sum(len(g["items"]) for g in groups)))
        for group in groups[:limit]:
            out.append(
                f'<p><b>{esc(group["name"])}</b> <span class="muted">({len(group["items"])})</span></p>'
            )
            out.append(
                '<ul class="plain">'
                + "".join(
                    f'<li class="item">{img.tag(i.get("icon"), 28)}<span>{esc(i["name"])} <span class="muted">· {esc(tr.datetime(i["unlocktime"]) if i["unlocktime"] else tr.t("report.unknown_date"))}'
                    + (
                        f" · {esc(tr.percent(i['percent']))}"
                        if i.get("percent") is not None
                        else ""
                    )
                    + "</span></span></li>"
                    for i in (group["items"][:limit] if limit else group["items"])
                )
                + "</ul>"
            )
    lost = changes.get("achievements_lost") or []
    if lost:
        out.append(heading("achievements_lost", sum(len(g["items"]) for g in lost)))
        out.append(
            '<ul class="plain">'
            + "".join(
                f"<li>{esc(g['name'])}: {esc(', '.join(i['name'] for i in g['items']))}</li>"
                for g in lost
            )
            + "</ul>"
        )
    if changes.get("completed"):
        out.append(heading("completed", len(changes["completed"])))
        out.append(
            '<ul class="plain">'
            + "".join(f'<li class="good">{esc(g["name"])}</li>' for g in changes["completed"])
            + "</ul>"
        )
    for key, cls in (("friends_added", "good"), ("friends_removed", "bad")):
        people = changes.get(key) or []
        if people:
            out.append(heading(key, len(people)))
            out.append(
                '<ul class="plain">'
                + "".join(
                    f'<li class="item {cls}">{img.tag(p.get("avatar"), 28)}{esc(p["name"] or p["steamid"])}</li>'
                    for p in people[:limit]
                )
                + "</ul>"
            )
    if changes.get("friends_renamed"):
        out.append(heading("friends_renamed", len(changes["friends_renamed"])))
        out.append(
            '<ul class="plain">'
            + "".join(
                f"<li>{esc(r['from'])} → {esc(r['to'])}</li>"
                for r in changes["friends_renamed"][:limit]
            )
            + "</ul>"
        )
    badge_rows = [
        tr.t("diff.badge_new", name=badge_name(b, tr), level=b.get("level"))
        for b in changes.get("badges_added") or []
    ] + [
        tr.t(
            "diff.badge_level", name=badge_name(b, tr), **{"from": b.get("from"), "to": b.get("to")}
        )
        for b in changes.get("badges_changed") or []
    ]
    if badge_rows:
        out.append(heading("badges", len(badge_rows)))
        out.append(
            '<ul class="plain">'
            + "".join(f"<li>{esc(r)}</li>" for r in badge_rows[:limit])
            + "</ul>"
        )
    wish = [("+", w["name"]) for w in changes.get("wishlist_added") or []] + [
        ("−", w["name"]) for w in changes.get("wishlist_removed") or []
    ]
    if wish:
        out.append(heading("wishlist", len(wish)))
        out.append(
            '<ul class="plain">'
            + "".join(f"<li>{sign} {esc(n)}</li>" for sign, n in wish[:limit])
            + "</ul>"
        )
    group_rows = [("+", g.get("name") or g["gid"]) for g in changes.get("groups_joined") or []] + [
        ("−", g.get("name") or g["gid"]) for g in changes.get("groups_left") or []
    ]
    if group_rows:
        out.append(heading("groups", len(group_rows)))
        out.append(
            '<ul class="plain">'
            + "".join(f"<li>{sign} {esc(n)}</li>" for sign, n in group_rows)
            + "</ul>"
        )
    if changes.get("bans"):
        out.append(heading("bans"))
        rows = [
            [
                esc(tr.t(f"data.ban_field.{b['field']}")),
                field_value("", b["from"], tr, img),
                field_value("", b["to"], tr, img),
            ]
            for b in changes["bans"]
        ]
        out.append(
            table(
                [
                    (tr.t("report.col.field"), ""),
                    (tr.t("report.col.before"), ""),
                    (tr.t("report.col.after"), ""),
                ],
                rows,
            )
        )
    if changes.get("unavailable"):
        names = ", ".join(tr.t(f"data.section_name.{n}") for n in changes["unavailable"])
        out.append(f'<p class="note">{esc(tr.t("diff.unavailable", sections=names))}</p>')
    if brief and changes.get("summary", {}).get("total"):
        out.append(
            f'<p class="muted">{esc(tr.t("report.compare_more", **{"from": changes["from"]["id"], "to": changes["to"]["id"]}))}</p>'
        )
    return "\n".join(out)


def period(changes: dict[str, Any], tr: Translator) -> str:
    start, end = changes["from"].get("collected_at"), changes["to"].get("collected_at")
    span = tr.span(days_between(parse_iso(start), parse_iso(end))) if start and end else ""
    return tr.t("diff.period", **{"from": tr.datetime(start), "to": tr.datetime(end), "span": span})


def render_changes_page(
    changes: dict[str, Any], tr: Translator, *, depth: int, database: Path
) -> str:
    img = Images(database, depth)
    name = f"{changes['from']['id']}__{changes['to']['id']}"
    body = (
        f'<h1>{esc(tr.t("diff.title"))}</h1><p class="muted">{esc(period(changes, tr))}</p>'
        + changes_body(changes, tr, img)
    )
    return page(tr, f"{tr.t('diff.title')} · {period(changes, tr)}", body, alternates(name))


# --------------------------------------------------------------------------- database index


def render_database_index(entries: list[dict[str, Any]], saved: list[str], tr: Translator) -> str:
    latest = entries[-1]["summary"] if entries else {}
    name = latest.get("persona") or "Steam"
    out = [f"<h1>{esc(tr.t('report.index_title', name=name))}</h1>"]
    if not entries:
        out.append(f'<p class="note">{esc(tr.t("report.index_empty"))}</p>')
    else:
        report = localized_name("report", tr.lang)
        out.append(
            f'<p><a href="latest/{report}">{esc(tr.t("report.index_latest"))}</a> · '
            f'<a href="../site/index.html">{esc(tr.t("report.index_site"))}</a></p>'
        )
        rows = []
        for position, entry in reversed(list(enumerate(entries, start=1))):
            s = entry.get("summary") or {}
            sid = entry["id"]
            rows.append(
                [
                    str(position),
                    f'<a href="archive/{esc(sid)}/{report}">{esc(tr.datetime(entry.get("collected_at")))}</a>',
                    esc(s.get("persona") or ""),
                    esc(tr.number(s.get("games") or 0)),
                    esc(tr.playtime(s.get("playtime") or 0)),
                    esc(tr.number(s.get("achievements") or 0)),
                    esc(tr.number(s.get("friends") or 0)),
                    esc(s.get("level") if s.get("level") is not None else ""),
                    f'<a href="archive/{esc(sid)}/">{esc(sid)}</a>',
                ]
            )
        out.append(
            f'<h2>{esc(tr.t("report.section.snapshots"))} <span class="muted">({tr.number(len(entries))})</span></h2>'
        )
        out.append(
            table(
                [
                    ("#", "n"),
                    (tr.t("report.col.date"), ""),
                    (tr.t("report.col.name"), ""),
                    (tr.t("report.stat.games"), "n"),
                    (tr.t("report.col.playtime"), "n"),
                    (tr.t("report.col.achievements"), "n"),
                    (tr.t("report.stat.friends"), "n"),
                    (tr.t("report.col.level"), "n"),
                    (tr.t("report.col.folder"), ""),
                ],
                rows,
            )
        )
    if saved:
        arrow = " → "
        out.append(f'<h2>{esc(tr.t("report.index_saved"))}</h2><ul class="plain">')
        for stem in reversed(saved):
            label = stem.replace("__", arrow)
            out.append(
                f'<li><a href="changes/{esc(localized_name(stem, tr.lang))}">{esc(label)}</a></li>'
            )
        out.append("</ul>")
    out.append(f'<p class="note">{esc(tr.t("report.index_hint"))}</p>')
    return page(tr, tr.t("report.index_title", name=name), "\n".join(out), alternates("index"))


def database_readme() -> str:
    parts = []
    for tr in translators():
        lines = tr.raw("report.readme")
        parts.append("\n".join(lines))
    return ("\n\n" + "-" * 72 + "\n\n").join(parts) + "\n"


# --------------------------------------------------------------------------- writers


def write_snapshot_reports(
    folder: Path,
    snapshot: dict[str, Any],
    changes: dict[str, Any] | None,
    *,
    depth: int,
    database: Path,
) -> None:
    files = [name for name in SNAPSHOT_FILES if (folder / name).is_file()]
    for tr in translators():
        html_text = render_snapshot_page(
            snapshot, changes, tr, depth=depth, database=database, files=files
        )
        write_text(folder / localized_name("report", tr.lang), html_text)
