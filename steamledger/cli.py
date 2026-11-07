# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 abel0x <https://github.com/abel0x>
"""Command line interface. ``steamledger <command>``; without a command on a terminal
it shows a menu, which is also what a double-click on steamledger.cmd opens."""

from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import functools
import http.server
import json
import os
import shutil
import signal
import subprocess
import sys
import threading
import webbrowser
from collections.abc import Callable
from pathlib import Path
from typing import Any

from . import HOMEPAGE, __version__, schedule, views
from . import diff as diffs
from . import steamid as ids
from .api import SteamApi, SteamError
from .cache import Cache
from .collect import CollectError, Collector
from .config import API_KEY_PATTERN, Config, ConfigError, load_config, mask_key
from .console import Console, is_interactive, is_terminal
from .i18n import Translator, available_languages, detect_language
from .media import MediaStore
from .net import Cancelled, Http, NetworkError
from .paths import Paths, default_root
from .report import localized_name
from .site import SiteError, build_site
from .store import Database, SnapshotNotFound
from .util import UTC, dir_size, human_bytes, remove_tree

CANCEL = threading.Event()
DEFAULT_PORT = 8765


# --------------------------------------------------------------------------- argparse in the user's language

# argparse builds its own messages through gettext; these are the ones a user sees.
_ARGPARSE_MESSAGES = {
    "usage: ": "argparse.usage",
    "positional arguments": "argparse.positional",
    "options": "argparse.options",
    "optional arguments": "argparse.options",
    "show this help message and exit": "argparse.help",
    "show program's version number and exit": "argparse.version",
    "the following arguments are required: %s": "argparse.required",
    "unrecognized arguments: %s": "argparse.unrecognized",
    "invalid choice: %(value)r (choose from %(choices)s)": "argparse.invalid_choice",
    "argument %(argument_name)s: %(message)s": "argparse.argument",
    "expected one argument": "argparse.expected_one",
    "invalid %(type)s value: %(value)r": "argparse.invalid_value",
    "%(prog)s: error: %(message)s\n": "argparse.error",
}


def translate_argparse(tr: Translator) -> None:
    def gettext(message: str) -> str:
        key = _ARGPARSE_MESSAGES.get(message)
        return tr.t(key) if key and tr.has(key) else message

    argparse._ = gettext  # type: ignore[attr-defined]


def build_parser(tr: Translator) -> argparse.ArgumentParser:
    t = tr.t
    parser = argparse.ArgumentParser(
        prog="steamledger",
        description=t("cli.help.description"),
        epilog=t("cli.help.epilog", url=HOMEPAGE),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("-V", "--version", action="version", version=f"steamledger {__version__}")
    parser.add_argument("--lang", choices=available_languages(), help=t("cli.help.lang"))
    parser.add_argument("--root", metavar="DIR", help=t("cli.help.root"))
    parser.add_argument("--log", metavar="FILE", help=t("cli.help.log"))
    parser.add_argument("-q", "--quiet", action="store_true", help=t("cli.help.quiet"))
    parser.add_argument("--no-color", action="store_true", help=t("cli.help.no_color"))
    sub = parser.add_subparsers(
        dest="command", metavar=t("cli.help.command"), title=t("cli.help.commands")
    )

    p = sub.add_parser("setup", help=t("cli.help.setup"), description=t("cli.help.setup"))
    p.add_argument("--api-key", help=t("cli.help.api_key"))
    p.add_argument("--steam-id", help=t("cli.help.steam_id"))
    p.add_argument(
        "--language", choices=["auto", *available_languages()], help=t("cli.help.language")
    )
    p.set_defaults(handler=cmd_setup)

    p = sub.add_parser(
        "collect", aliases=["update"], help=t("cli.help.collect"), description=t("cli.help.collect")
    )
    p.add_argument("--full", action="store_true", help=t("cli.help.full"))
    p.add_argument("--no-media", action="store_true", help=t("cli.help.no_media"))
    p.add_argument("--no-site", action="store_true", help=t("cli.help.no_site"))
    p.set_defaults(handler=cmd_collect)

    p = sub.add_parser("build", help=t("cli.help.build"), description=t("cli.help.build"))
    p.add_argument("--out", metavar="DIR", help=t("cli.help.out"))
    p.add_argument("--force", action="store_true", help=t("cli.help.force"))
    p.add_argument("--reports", action="store_true", help=t("cli.help.reports"))
    p.add_argument("--open", action="store_true", help=t("cli.help.open_after"))
    p.set_defaults(handler=cmd_build)

    p = sub.add_parser(
        "list", aliases=["history"], help=t("cli.help.list"), description=t("cli.help.list")
    )
    p.set_defaults(handler=cmd_list)

    p = sub.add_parser("show", help=t("cli.help.show"), description=t("cli.help.show"))
    p.add_argument("snapshot", nargs="?", default="latest", help=t("cli.help.snapshot"))
    p.set_defaults(handler=cmd_show)

    p = sub.add_parser(
        "diff", aliases=["compare"], help=t("cli.help.diff"), description=t("cli.help.diff_long")
    )
    p.add_argument("older", help=t("cli.help.snapshot"))
    p.add_argument("newer", nargs="?", default="latest", help=t("cli.help.snapshot"))
    p.add_argument("--save", action="store_true", help=t("cli.help.save"))
    p.add_argument("--json", action="store_true", help=t("cli.help.json"))
    p.add_argument("--open", action="store_true", help=t("cli.help.open_after"))
    p.set_defaults(handler=cmd_diff)

    p = sub.add_parser("open", help=t("cli.help.open"), description=t("cli.help.open"))
    p.add_argument(
        "target",
        nargs="?",
        default="site",
        choices=["site", "database", "report"],
        help=t("cli.help.target"),
    )
    p.add_argument("snapshot", nargs="?", default="latest", help=t("cli.help.snapshot"))
    p.set_defaults(handler=cmd_open)

    p = sub.add_parser("serve", help=t("cli.help.serve"), description=t("cli.help.serve"))
    p.add_argument("--port", type=int, default=DEFAULT_PORT, help=t("cli.help.port"))
    p.add_argument("--host", default="127.0.0.1", help=t("cli.help.host"))
    p.add_argument("--no-open", action="store_true", help=t("cli.help.no_open"))
    p.set_defaults(handler=cmd_serve)

    p = sub.add_parser("prune", help=t("cli.help.prune"), description=t("cli.help.prune"))
    group = p.add_mutually_exclusive_group(required=True)
    group.add_argument("--keep", type=int, metavar="N", help=t("cli.help.keep"))
    group.add_argument("--before", metavar="YYYY-MM-DD", help=t("cli.help.before"))
    p.add_argument("--dry-run", action="store_true", help=t("cli.help.dry_run"))
    p.add_argument("-y", "--yes", action="store_true", help=t("cli.help.yes"))
    p.set_defaults(handler=cmd_prune)

    p = sub.add_parser("schedule", help=t("cli.help.schedule"), description=t("cli.help.schedule"))
    p.add_argument(
        "action",
        nargs="?",
        default="status",
        choices=["install", "remove", "status"],
        help=t("cli.help.schedule_action"),
    )
    p.add_argument("--time", default="21:00", metavar="HH:MM", help=t("cli.help.time"))
    p.add_argument("--weekly", action="store_true", help=t("cli.help.weekly"))
    p.set_defaults(handler=cmd_schedule)

    p = sub.add_parser("config", help=t("cli.help.config"), description=t("cli.help.config"))
    p.add_argument(
        "action",
        nargs="?",
        default="show",
        choices=["show", "set", "path"],
        help=t("cli.help.config_action"),
    )
    p.add_argument("key", nargs="?", help=t("cli.help.config_key"))
    p.add_argument("value", nargs="?", help=t("cli.help.config_value"))
    p.set_defaults(handler=cmd_config)

    p = sub.add_parser("doctor", help=t("cli.help.doctor"), description=t("cli.help.doctor"))
    p.set_defaults(handler=cmd_doctor)

    p = sub.add_parser("demo", help=t("cli.help.demo"), description=t("cli.help.demo_long"))
    p.add_argument(
        "--snapshots", type=int, default=6, metavar="N", help=t("cli.help.demo_snapshots")
    )
    p.add_argument("--no-open", action="store_true", help=t("cli.help.no_open"))
    p.set_defaults(handler=cmd_demo)
    return parser


# --------------------------------------------------------------------------- context


class Context:
    def __init__(
        self, args: argparse.Namespace, tr: Translator, ui: Console, paths: Paths, config: Config
    ) -> None:
        self.args = args
        self.tr = tr
        self.ui = ui
        self.paths = paths
        self.config = config
        self.db = Database(paths, csv_delimiter=str(config.get("output.csv_delimiter") or ","))

    def t(self, key: str, /, **params: Any) -> str:
        return self.tr.t(key, **params)

    def http(self, key: str = "") -> Http:
        net = self.config.get("network") or {}
        return Http(
            timeout=float(net.get("timeout", 30)),
            retries=int(net.get("retries", 4)),
            per_second=float(net.get("requests_per_second", 8)),
            secrets=[key or self.config.api_key],
            cancel=CANCEL,
        )

    def api(self) -> SteamApi:
        key = self.config.api_key
        return SteamApi(self.http(key), key)

    def show_path(self, path: Path) -> str:
        with contextlib.suppress(ValueError):
            return str(path.relative_to(Path.cwd()))
        return str(path)

    def resolve(self, ref: str) -> str:
        return self.db.resolve(ref)

    def require_setup(self) -> bool:
        if self.config.is_configured:
            return True
        self.ui.error(self.t("cli.errors.not_configured"))
        self.ui.print("  steamledger setup")
        return False


def open_path(path: Path | str) -> None:
    target = str(path)
    if target.endswith(".html") or target.startswith(("http://", "https://")):
        url = target if target.startswith("http") else Path(target).resolve().as_uri()
        if sys.platform.startswith("linux") and shutil.which("xdg-open"):
            # The browser's own startup messages would otherwise land in our terminal.
            subprocess.Popen(
                ["xdg-open", url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
        else:
            webbrowser.open(url)
        return
    if sys.platform == "win32":
        os.startfile(target)  # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        subprocess.Popen(["open", target])
    else:
        subprocess.Popen(["xdg-open", target], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


# --------------------------------------------------------------------------- setup


def cmd_setup(ctx: Context) -> int:
    args, ui, t, config = ctx.args, ctx.ui, ctx.t, ctx.config
    interactive = is_interactive()
    ui.heading(t("cli.setup.title"))
    ui.print(ui.dim(t("cli.setup.where", path=ctx.show_path(config.path))))

    if args.language:
        config.data["language"] = args.language
    elif interactive:
        choices = ["auto", *available_languages()]
        answer = ui.ask(t("cli.setup.language", choices="/".join(choices)), config.language).lower()
        if answer in choices:
            config.data["language"] = answer
            if answer != "auto":
                ctx.tr = Translator(answer)
                ui.tr = ctx.tr
                t = ctx.tr.t

    key = (args.api_key or "").strip()
    steam_input = (args.steam_id or "").strip()
    for _attempt in range(5):
        if not key:
            current = str(config.data.get("api_key") or "")
            if not interactive:
                key = current
            else:
                ui.print()
                ui.info(t("cli.setup.key_hint", url="https://steamcommunity.com/dev/apikey"))
                prompt = (
                    t("cli.setup.key_prompt_keep", masked=mask_key(current))
                    if current
                    else t("cli.setup.key_prompt")
                )
                key = ui.ask_secret(prompt) or current
            if not API_KEY_PATTERN.match(key or ""):
                ui.error(t("cli.setup.key_format"))
                key = ""
                if not interactive:
                    return 2
                continue
        if not steam_input:
            current = str(config.data.get("steam_id") or "")
            if not interactive:
                steam_input = current
            else:
                ui.print()
                ui.info(t("cli.setup.id_hint"))
                steam_input = ui.ask(t("cli.setup.id_prompt"), current)
            if not steam_input:
                ui.error(t("cli.setup.id_missing"))
                if not interactive:
                    return 2
                continue

        api = SteamApi(ctx.http(key), key)
        try:
            parsed = ids.parse(steam_input)
            steamid = (
                parsed.value if parsed.kind == "steamid64" else api.resolve_vanity(parsed.value)
            )
            players = api.player_summaries([steamid]) if steamid else []
        except ids.SteamIdError:
            ui.error(t("cli.setup.id_invalid", value=steam_input))
            if not interactive or args.steam_id:
                return 2
            steam_input = ""
            continue
        except SteamError as exc:
            if exc.kind == "forbidden":
                ui.error(t("cli.errors.invalid_key"))
                if not interactive or args.api_key:
                    return 2
                key = ""
                continue
            ui.error(t("cli.errors.api", detail=str(exc)))
            return 1
        except NetworkError as exc:
            ui.error(t("cli.errors.network", detail=str(exc)))
            return 1
        if not players:
            ui.error(t("cli.setup.id_not_found", value=steam_input))
            if not interactive or args.steam_id:
                return 2
            steam_input = ""
            continue
        player = players[0]
        break
    else:
        return 2

    config.data["api_key"] = key
    config.data["steam_id"] = steamid
    config.save()
    ui.print()
    ui.ok(t("cli.setup.found", name=player.get("personaname", ""), steamid=steamid))
    if int(player.get("communityvisibilitystate") or 0) != 3:
        ui.warn(t("cli.setup.profile_private"))
    else:
        try:
            if api.owned_games(steamid) is None:
                ui.warn(t("cli.setup.games_private"))
        except (SteamError, NetworkError):
            pass
    ui.ok(t("cli.setup.saved", path=ctx.show_path(config.path)))
    ui.print(t("cli.setup.next"))
    ui.print("  steamledger collect")
    return 0


# --------------------------------------------------------------------------- collect / build


def cmd_collect(ctx: Context) -> int:
    ui, t, args = ctx.ui, ctx.t, ctx.args
    if not ctx.require_setup():
        return 2
    http = ctx.http()
    api = SteamApi(http, ctx.config.api_key)
    media = MediaStore(ctx.paths.database, None if args.no_media else http)
    try:
        previous = ctx.db.load_latest()
    except (OSError, ValueError, SnapshotNotFound) as exc:
        ui.warn(t("cli.collect.previous_unreadable", detail=str(exc)))
        previous = None
    ui.heading(t("cli.collect.title", steamid=ctx.config.steam_id))
    collector = Collector(
        config=ctx.config,
        api=api,
        media=media,
        cache=Cache(ctx.paths.cache),
        console=ui,
        tr=ctx.tr,
        previous=previous,
        full=args.full,
    )
    try:
        snapshot = collector.run()
    except CollectError as exc:
        ui.error(t(exc.key, **exc.params))
        return 1
    sid = ctx.db.write(snapshot)
    ui.print()
    ui.ok(t("cli.collect.saved", id=sid, path=ctx.show_path(ctx.paths.archive / sid)))
    changes = ctx.db.changes(sid)
    if changes:
        ui.info(t("cli.collect.since", summary=views.summary_line(ctx.tr, changes)))
    if ctx.db.locked:
        ui.warn(t("cli.collect.locked", files=", ".join(ctx.db.locked)))
    if ctx.config.get("output.build_site") and not args.no_site:
        return _build(ctx, None, force=False)
    return 0


def _build(ctx: Context, out: str | None, *, force: bool, open_after: bool = False) -> int:
    try:
        index = build_site(ctx.paths, ctx.db, Path(out).resolve() if out else None, force=force)
    except SiteError as exc:
        ctx.ui.error(ctx.t(exc.key, **exc.params))
        return 1
    ctx.ui.ok(ctx.t("cli.build.done", path=ctx.show_path(index)))
    if open_after:
        open_path(index)
    return 0


def cmd_build(ctx: Context) -> int:
    if ctx.args.reports:
        ctx.db.rebuild_reports()
        ctx.ui.ok(ctx.t("cli.build.reports", path=ctx.show_path(ctx.paths.database / "index.html")))
    return _build(ctx, ctx.args.out, force=ctx.args.force, open_after=ctx.args.open)


# --------------------------------------------------------------------------- reading the archive


def cmd_list(ctx: Context) -> int:
    views.print_list(ctx.ui, ctx.tr, ctx.db)
    return 0


def cmd_show(ctx: Context) -> int:
    sid = ctx.resolve(ctx.args.snapshot)
    views.print_snapshot(ctx.ui, ctx.tr, ctx.db.load(sid), ctx.db.changes(sid))
    report = ctx.paths.archive / sid / localized_name("report", ctx.tr.lang)
    ctx.ui.print(ctx.ui.dim(ctx.t("cli.show.report", path=ctx.show_path(report))))
    return 0


def cmd_diff(ctx: Context) -> int:
    args, ui = ctx.args, ctx.ui
    older, newer = ctx.resolve(args.older), ctx.resolve(args.newer)
    if older == newer:
        ui.error(ctx.t("cli.diff.same", id=older))
        return 2
    if ctx.db.meta(older).get("collected_at", "") > ctx.db.meta(newer).get("collected_at", ""):
        older, newer = newer, older
    changes = diffs.compare(ctx.db.load(older), ctx.db.load(newer))
    if args.json:
        sys.stdout.write(json.dumps(changes, ensure_ascii=False, indent=2) + "\n")
    else:
        views.print_changes(ui, ctx.tr, changes)
    if args.save or args.open:
        page = ctx.db.save_comparison(changes)
        ctx.db.write_index()
        localized = page.with_name(localized_name(page.name[: -len(".html")], ctx.tr.lang))
        ui.ok(ctx.t("cli.diff.saved", path=ctx.show_path(localized)))
        if args.open:
            open_path(localized)
    return 0


def cmd_open(ctx: Context) -> int:
    target = ctx.args.target
    if target == "database":
        ctx.paths.database.mkdir(parents=True, exist_ok=True)
        open_path(ctx.paths.database)
        return 0
    if target == "report":
        sid = ctx.resolve(ctx.args.snapshot)
        open_path(ctx.paths.archive / sid / localized_name("report", ctx.tr.lang))
        return 0
    index = ctx.paths.site / "index.html"
    if not index.is_file():
        code = _build(ctx, None, force=False)
        if code:
            return code
    open_path(index)
    return 0


def cmd_serve(ctx: Context) -> int:
    args, ui = ctx.args, ctx.ui
    if not (ctx.paths.site / "index.html").is_file() and _build(ctx, None, force=False):
        return 1
    handler = functools.partial(_QuietHandler, directory=str(ctx.paths.site))
    try:
        server = http.server.ThreadingHTTPServer((args.host, args.port), handler)
    except OSError as exc:
        ui.error(ctx.t("cli.serve.failed", port=args.port, detail=exc.strerror or str(exc)))
        return 1
    url = f"http://{args.host}:{server.server_address[1]}/"
    ui.ok(ctx.t("cli.serve.running", url=url))
    ui.print(ui.dim(ctx.t("cli.serve.stop")))
    if not args.no_open:
        threading.Timer(0.4, webbrowser.open, (url,)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


class _QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        pass

    def end_headers(self) -> None:
        self.send_header("Cache-Control", "no-cache")
        super().end_headers()


def cmd_prune(ctx: Context) -> int:
    args, ui, t = ctx.args, ctx.ui, ctx.t
    all_ids = ctx.db.ids()
    if args.keep is not None:
        if args.keep < 1:
            ui.error(t("cli.prune.keep_one"))
            return 2
        doomed = all_ids[: max(0, len(all_ids) - args.keep)]
    else:
        try:
            limit = dt.date.fromisoformat(args.before)
        except ValueError:
            ui.error(t("cli.prune.bad_date", value=args.before))
            return 2
        doomed = [sid for sid in all_ids if sid[:10] < limit.isoformat()]
        if len(doomed) == len(all_ids):
            doomed = doomed[:-1]  # never delete the newest snapshot
    if not doomed:
        ui.info(t("cli.prune.nothing"))
        return 0
    size = sum(dir_size(ctx.paths.archive / sid) for sid in doomed)
    ui.print(t("cli.prune.plan", count=len(doomed), size=human_bytes(size)))
    for sid in doomed:
        ui.print(f"  {sid}  {ctx.tr.datetime(ctx.db.meta(sid).get('collected_at'))}")
    if args.dry_run:
        return 0
    if not args.yes and not (
        is_interactive() and ui.confirm(t("cli.prune.confirm", count=len(doomed)))
    ):
        ui.info(t("cli.prune.aborted"))
        return 1
    ctx.db.delete(doomed)
    ui.ok(t("cli.prune.done", count=len(doomed)))
    if (ctx.paths.site / "index.html").is_file():
        return _build(ctx, None, force=False)
    return 0


def cmd_schedule(ctx: Context) -> int:
    args, ui, t = ctx.args, ctx.ui, ctx.t
    try:
        if args.action == "install":
            if not ctx.require_setup():
                return 2
            plan = schedule.Plan.parse(args.time, args.weekly)
            backend = schedule.install(ctx.paths, plan)
            key = "cli.schedule.installed_weekly" if plan.weekly else "cli.schedule.installed"
            ui.ok(t(key, time=plan.label, backend=t(f"cli.schedule.backend.{backend}")))
            ui.print(
                ui.dim(
                    t("cli.schedule.log", path=ctx.show_path(ctx.paths.database / "collect.log"))
                )
            )
            if backend == "systemd":
                ui.print(ui.dim(t("cli.schedule.linger")))
        elif args.action == "remove":
            if schedule.remove():
                ui.ok(t("cli.schedule.removed"))
            else:
                ui.info(t("cli.schedule.none"))
        else:
            state = schedule.status()
            if state:
                ui.ok(t("cli.schedule.active", detail=state))
            else:
                ui.info(t("cli.schedule.none"))
                ui.print(ui.dim("  steamledger schedule install --time 21:00"))
    except schedule.ScheduleError as exc:
        ui.error(t(exc.key, **exc.params))
        return 1
    return 0


def _coerce(value: str) -> Any:
    try:
        return json.loads(value)
    except ValueError:
        return value


def cmd_config(ctx: Context) -> int:
    args, ui, t, config = ctx.args, ctx.ui, ctx.t, ctx.config
    if args.action == "path":
        ui.print(str(config.path), force=True)
        return 0
    if args.action == "set":
        if not args.key or args.value is None:
            ui.error(t("cli.config.usage"))
            return 2
        if config.get(args.key) is None and args.key not in ("api_key", "steam_id"):
            ui.error(t("cli.config.unknown", key=args.key))
            return 2
        value = (
            args.value
            if args.key in ("api_key", "steam_id", "language", "store_country")
            else _coerce(args.value)
        )
        if args.key == "steam_id":
            try:
                parsed = ids.parse(value)
            except ids.SteamIdError:
                parsed = None
            if parsed is None or parsed.kind != "steamid64":
                ui.error(t("cli.config.steam_id"))
                return 2
            value = parsed.value
        previous = config.get(args.key)
        config.set(args.key, value)
        try:
            config.validate()
        except ConfigError as exc:
            config.set(args.key, previous)
            ui.error(t(f"cli.config_error.{exc.key}", **exc.params))
            return 2
        config.save()
        ui.ok(t("cli.config.saved", key=args.key))
        return 0
    shown = json.loads(json.dumps(config.data))
    if shown.get("api_key"):
        shown["api_key"] = mask_key(shown["api_key"])
    ui.print(ui.dim(ctx.show_path(config.path)), force=True)
    ui.print(json.dumps(shown, ensure_ascii=False, indent=2), force=True)
    for env in ("STEAM_API_KEY", "STEAM_ID", "STEAMLEDGER_LANG"):
        if os.environ.get(env):
            ui.info(t("cli.config.env", name=env))
    return 0


def cmd_doctor(ctx: Context) -> int:
    ui, t, config, paths = ctx.ui, ctx.t, ctx.config, ctx.paths
    problems = 0

    def good(text: str) -> None:
        ui.ok(text)

    def bad(text: str) -> None:
        nonlocal problems
        problems += 1
        ui.error(text)

    ui.heading(t("cli.doctor.title"))
    good(
        t(
            "cli.doctor.python",
            version=".".join(map(str, sys.version_info[:3])),
            platform=sys.platform,
        )
    )
    try:
        paths.database.mkdir(parents=True, exist_ok=True)
        probe = paths.database / ".write-test"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        good(t("cli.doctor.writable", path=ctx.show_path(paths.root)))
    except OSError as exc:
        bad(t("cli.doctor.not_writable", path=str(paths.root), detail=exc.strerror or str(exc)))
    if not config.path.is_file():
        bad(t("cli.doctor.no_config"))
    elif not config.is_configured:
        bad(t("cli.errors.not_configured"))
    else:
        good(t("cli.doctor.config", key=mask_key(config.api_key), steamid=config.steam_id))
        api = ctx.api()
        try:
            players = api.player_summaries([config.steam_id])
        except SteamError as exc:
            bad(
                t("cli.errors.invalid_key")
                if exc.kind == "forbidden"
                else t("cli.errors.api", detail=str(exc))
            )
            players = None
        except NetworkError as exc:
            bad(t("cli.errors.network", detail=str(exc)))
            players = None
        if players:
            player = players[0]
            good(t("cli.doctor.account", name=player.get("personaname", "")))
            if int(player.get("communityvisibilitystate") or 0) == 3:
                good(t("cli.doctor.profile_public"))
            else:
                bad(t("cli.setup.profile_private"))
            checks = (
                ("games", lambda: api.owned_games(config.steam_id) is not None),
                ("friends", lambda: api.friend_list(config.steam_id) is not None),
            )
            for name, check in checks:
                try:
                    public = check()
                except SteamError as exc:
                    public = False if exc.kind == "private" else None  # None: unknown
                except NetworkError:
                    public = None
                if public:
                    good(t(f"cli.doctor.{name}_public"))
                elif public is False:
                    bad(t(f"cli.doctor.{name}_private"))
        elif players == []:
            bad(t("cli.errors.unknown_account", steamid=config.steam_id))
    snapshot_ids = ctx.db.ids()
    count = len(snapshot_ids)
    if count:
        last = ctx.db.meta(snapshot_ids[-1]).get("collected_at")
        good(
            t(
                "cli.doctor.snapshots",
                count=count,
                date=ctx.tr.datetime(last),
                size=human_bytes(dir_size(paths.database)),
            )
        )
    else:
        ui.info(t("cli.list.empty"))
    if (paths.site / "index.html").is_file():
        good(t("cli.doctor.site", path=ctx.show_path(paths.site / "index.html")))
    state = schedule.status()
    ui.info(t("cli.schedule.active", detail=state) if state else t("cli.schedule.none"))
    ui.print()
    if problems:
        ui.error(t("cli.doctor.problems", count=problems))
        return 1
    ui.ok(t("cli.doctor.fine"))
    return 0


def cmd_demo(ctx: Context) -> int:
    from .demo import API_KEY, STEAMID, FakeSteam

    ui, t = ctx.ui, ctx.t
    paths = Paths(ctx.paths.root / "demo")
    remove_tree(paths.database)
    if (paths.site / ".steamledger-site").is_file():
        remove_tree(paths.site)
    count = max(2, min(30, ctx.args.snapshots))
    days = 9
    start = dt.datetime.now(UTC) - dt.timedelta(days=days * (count - 1))
    world = FakeSteam(start)
    config = Config(paths.config, {"api_key": API_KEY, "steam_id": STEAMID})
    db = Database(paths)
    quiet = Console(quiet=True, tr=ctx.tr)
    ui.heading(t("cli.demo.title"))
    progress = ui.progress(t("cli.demo.snapshots"), count)
    for step in range(count):
        if step:
            world.advance(days)
        http = Http(world.transport(), per_second=0, retries=0, cancel=CANCEL)
        api = SteamApi(http, API_KEY)
        collector = Collector(
            config=config,
            api=api,
            media=MediaStore(paths.database, http),
            cache=Cache(paths.cache),
            console=quiet,
            tr=ctx.tr,
            previous=db.load_latest(),
            now=dt.datetime.fromtimestamp(world.now, UTC),
        )
        db.write(collector.run())
        progress.advance()
    progress.finish()
    index = build_site(paths, db)
    ui.ok(t("cli.demo.done", path=ctx.show_path(index)))
    ui.print(ui.dim(t("cli.demo.database", path=ctx.show_path(paths.database / "index.html"))))
    if not ctx.args.no_open:
        open_path(index)
    return 0


# --------------------------------------------------------------------------- menu


def menu(ctx: Context) -> int:
    ui, t = ctx.ui, ctx.t
    actions: list[tuple[str, Callable[[], int]]] = [
        (t("cli.menu.collect"), lambda: run_menu_command(ctx, ["collect"])),
        (t("cli.menu.open_site"), lambda: run_menu_command(ctx, ["open", "site"])),
        (t("cli.menu.open_database"), lambda: run_menu_command(ctx, ["open", "database"])),
        (t("cli.menu.list"), lambda: run_menu_command(ctx, ["list"])),
        (t("cli.menu.compare"), lambda: menu_compare(ctx)),
        (t("cli.menu.setup"), lambda: run_menu_command(ctx, ["setup"])),
        (t("cli.menu.schedule"), lambda: menu_schedule(ctx)),
        (t("cli.menu.doctor"), lambda: run_menu_command(ctx, ["doctor"])),
        (t("cli.menu.demo"), lambda: run_menu_command(ctx, ["demo"])),
    ]
    while True:
        ui.print()
        title = f"steamledger {__version__}"
        latest = ctx.db.latest_id()
        meta = ctx.db.meta(latest) if latest else {}
        persona = (meta.get("summary") or {}).get("persona")
        if persona:
            when = t("cli.menu.latest", date=ctx.tr.datetime(meta.get("collected_at")))
            title += f"  ·  {persona}  ·  {when}"
        ui.heading(title)
        if not ctx.config.is_configured:
            ui.warn(t("cli.menu.not_configured"))
        for number, (label, _action) in enumerate(actions, start=1):
            ui.print(f"  {ui.bold(str(number))}  {label}")
        ui.print(f"  {ui.bold('0')}  {t('cli.menu.exit')}")
        try:
            choice = input(f"{t('cli.menu.choose')}: ").strip()
        except EOFError:
            return 0
        if choice in ("0", "q", "x", ""):
            return 0
        if choice.isdigit() and 1 <= int(choice) <= len(actions):
            try:
                actions[int(choice) - 1][1]()
            except (SnapshotNotFound, Cancelled, KeyboardInterrupt) as exc:
                CANCEL.clear()
                if isinstance(exc, SnapshotNotFound):
                    ui.error(t("cli.errors.snapshot", ref=exc.ref))
            ctx.config = _reload_config(ctx)


def _reload_config(ctx: Context) -> Config:
    try:
        return load_config(ctx.paths.config)
    except ConfigError:
        return ctx.config


def run_menu_command(ctx: Context, argv: list[str]) -> int:
    parser = build_parser(ctx.tr)
    args = parser.parse_args(["--lang", ctx.tr.lang, *argv])
    args.quiet, args.no_color = False, False
    sub = Context(args, ctx.tr, ctx.ui, ctx.paths, _reload_config(ctx))
    return args.handler(sub)


def menu_compare(ctx: Context) -> int:
    views.print_list(ctx.ui, ctx.tr, ctx.db)
    if len(ctx.db.ids()) < 2:
        return 0
    older = ctx.ui.ask(ctx.t("cli.menu.compare_from"), "previous")
    newer = ctx.ui.ask(ctx.t("cli.menu.compare_to"), "latest")
    return run_menu_command(ctx, ["diff", older, newer, "--save"])


def menu_schedule(ctx: Context) -> int:
    run_menu_command(ctx, ["schedule", "status"])
    if not ctx.ui.confirm(ctx.t("cli.menu.schedule_install"), default=True):
        return 0
    when = ctx.ui.ask(ctx.t("cli.menu.schedule_time"), "21:00")
    weekly = ctx.ui.confirm(ctx.t("cli.menu.schedule_weekly"), default=False)
    return run_menu_command(
        ctx, ["schedule", "install", "--time", when, *(["--weekly"] if weekly else [])]
    )


# --------------------------------------------------------------------------- entry point


def _prescan(argv: list[str]) -> dict[str, str]:
    """--lang, --root and --log are needed before the parser exists."""
    found: dict[str, str] = {}
    for index, item in enumerate(argv):
        for name in ("--lang", "--root", "--log"):
            if item == name and index + 1 < len(argv):
                found[name] = argv[index + 1]
            elif item.startswith(name + "="):
                found[name] = item.split("=", 1)[1]
    return found


def _streams(log: str | None) -> None:
    if log:
        path = Path(log)
        path.parent.mkdir(parents=True, exist_ok=True)
        handle = open(path, "a", encoding="utf-8", buffering=1)  # noqa: SIM115 - lives as long as the process
        handle.write(
            f"\n--- {dt.datetime.now().isoformat(timespec='seconds')} steamledger {__version__}\n"
        )
        sys.stdout = sys.stderr = handle
        return
    for stream in (sys.stdout, sys.stderr):
        if stream is not None and hasattr(stream, "reconfigure"):
            # A pipe or a file gets UTF-8 (on Windows it would otherwise get the
            # legacy code page and lose every Turkish letter); a console keeps its
            # own encoding. Characters it cannot show are replaced, never fatal.
            utf8 = not is_terminal(stream) and not os.environ.get("PYTHONIOENCODING")
            with contextlib.suppress(ValueError, OSError):
                stream.reconfigure(errors="replace", **({"encoding": "utf-8"} if utf8 else {}))
    if sys.stdout is None or sys.stderr is None:  # pythonw.exe without --log
        sink = open(os.devnull, "w", encoding="utf-8")  # noqa: SIM115
        sys.stdout = sys.stdout or sink
        sys.stderr = sys.stderr or sink


def _interrupt(signum: int, frame: Any) -> None:
    CANCEL.set()
    raise KeyboardInterrupt


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    early = _prescan(argv)
    _streams(early.get("--log"))
    root = Path(early["--root"]).expanduser().resolve() if early.get("--root") else default_root()
    paths = Paths(root)
    config_error: ConfigError | None = None
    try:
        config = load_config(paths.config)
    except ConfigError as exc:
        config, config_error = Config(paths.config), exc
    tr = Translator(
        detect_language(early.get("--lang"), os.environ.get("STEAMLEDGER_LANG"), config.language)
    )
    translate_argparse(tr)
    parser = build_parser(tr)
    args = parser.parse_args(argv)
    ui = Console(quiet=args.quiet, color=False if args.no_color else None, tr=tr)
    if config_error is not None:
        ui.error(tr.t(f"cli.config_error.{config_error.key}", **config_error.params))
        if getattr(args, "handler", None) not in (cmd_setup, cmd_config, cmd_demo):
            return 2
    ctx = Context(args, tr, ui, paths, config)
    CANCEL.clear()
    with contextlib.suppress(ValueError):  # not the main thread (tests)
        signal.signal(signal.SIGINT, _interrupt)
    try:
        if getattr(args, "handler", None) is None:
            if is_interactive():
                return menu(ctx)
            parser.print_help()
            return 0
        return int(args.handler(ctx) or 0)
    except SnapshotNotFound as exc:
        ui.error(tr.t("cli.errors.snapshot", ref=exc.ref))
        ui.print(ui.dim(tr.t("cli.errors.snapshot_hint")))
        return 2
    except (KeyboardInterrupt, Cancelled):
        ui.print()
        ui.error(tr.t("cli.cancelled"))
        return 130
    except BrokenPipeError:
        # The reader went away (`steamledger list | head`); silence the flush at exit.
        os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())
        return 1
    except OSError as exc:
        ui.error(tr.t("cli.errors.os", detail=f"{exc.strerror or exc} ({exc.filename or ''})"))
        return 1
