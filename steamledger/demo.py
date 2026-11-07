# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 abel0x <https://github.com/abel0x>
"""A made-up Steam account served by an in-process fake of the Web API.

``steamledger demo`` runs the real collector against it to build a database and a
site with several snapshots, so the project can be tried without an API key.
The test suite uses the same fake. Every game, person and group here is
invented; the images are generated patterns.
"""

from __future__ import annotations

import colorsys
import datetime as dt
import json
import random
import struct
import urllib.parse
import zlib
from dataclasses import dataclass, field
from typing import Any

from .net import Response

STEAMID = "76561198000000042"
API_KEY = "0123456789ABCDEF0123456789ABCDEF"
DAY = 86400

GAME_NAMES = [
    "Hollow Signal",
    "Copper Tide",
    "Starfall Tactics",
    "Neon Harbor",
    "Ashen Crown",
    "Paper Lanterns",
    "Glacier Run",
    "Iron Orchard",
    "Quiet Engines",
    "Lantern Keep",
    "Moth & Mirror",
    "Salt Road",
    "Velvet Circuit",
    "Tidebreaker",
    "Cinder Valley",
    "Orbital Gardens",
    "The Long Shift",
    "Brass Cartographer",
    "Low Orbit Diner",
    "Fable Forge",
    "Night Ferry",
    "Rust & Rhyme",
    "Hexfield",
    "Pocket Armada",
    "Silent Meridian",
    "Kettle Island",
    "Ember Protocol",
    "Wildwire",
    "Dune Choir",
    "Signal Garden",
    "Clockwork Tavern",
    "Frostline",
    "Mirage Courier",
    "Pale Harbor",
    "Thunder Atlas",
    "Velvet Rift",
    "Bramble Knights",
    "Neon Tide Racing",
    "Driftwood",
    "Echo Chamber",
]
TAGS = {
    19: ("Action", "Aksiyon"),
    21: ("Adventure", "Macera"),
    9: ("Strategy", "Strateji"),
    122: ("RPG", "RYO"),
    597: ("Casual", "Gündelik"),
    599: ("Simulation", "Simülasyon"),
    492: ("Indie", "Bağımsız"),
    1662: ("Survival", "Hayatta Kalma"),
    1702: ("Crafting", "Üretim"),
    1664: ("Puzzle", "Bulmaca"),
    3871: ("2D", "2B"),
    4182: ("Singleplayer", "Tek Oyunculu"),
    3859: ("Multiplayer", "Çok Oyunculu"),
    1695: ("Open World", "Açık Dünya"),
    4085: ("Anime", "Anime"),
    1684: ("Fantasy", "Fantastik"),
    3942: ("Sci-fi", "Bilim Kurgu"),
    699: ("Racing", "Yarış"),
    1774: ("Shooter", "Nişancı"),
    1667: ("Horror", "Korku"),
}
CATEGORIES = {
    2: ("Single-player", "Tek oyunculu"),
    1: ("Multi-player", "Çok oyunculu"),
    22: ("Steam Achievements", "Steam Başarımları"),
    23: ("Steam Cloud", "Steam Bulut"),
    28: ("Full controller support", "Tam kontrolcü desteği"),
    29: ("Steam Trading Cards", "Steam Koleksiyon Kartları"),
}
ACHIEVEMENT_WORDS = [
    ("First Steps", "İlk Adımlar", "Finish the first chapter.", "İlk bölümü bitir."),
    ("Night Owl", "Gece Kuşu", "Play after midnight.", "Gece yarısından sonra oyna."),
    ("Collector", "Koleksiyoncu", "Find every hidden relic.", "Tüm gizli kalıntıları bul."),
    ("Untouchable", "Dokunulmaz", "Win without taking damage.", "Hasar almadan kazan."),
    ("Speedrunner", "Hızcı", "Finish in under two hours.", "İki saatin altında bitir."),
    ("Cartographer", "Haritacı", "Reveal the whole map.", "Haritanın tamamını aç."),
    ("Pacifist", "Barışçıl", "Finish a level without fighting.", "Bir bölümü savaşmadan bitir."),
    ("Big Spender", "Savurgan", "Spend 10,000 coins.", "10.000 altın harca."),
    ("Old Friend", "Eski Dost", "Meet the hermit again.", "Münzeviyle yeniden karşılaş."),
    ("Perfectionist", "Mükemmeliyetçi", "Get every star rating.", "Tüm yıldızları topla."),
    ("Storm Chaser", "Fırtına Avcısı", "Survive the great storm.", "Büyük fırtınadan sağ çık."),
    ("Craftsman", "Usta", "Craft 100 items.", "100 eşya üret."),
    ("Sharpshooter", "Keskin Nişancı", "Land 50 perfect shots.", "50 kusursuz atış yap."),
    ("Explorer", "Kaşif", "Visit every region.", "Tüm bölgeleri gez."),
    ("Last Light", "Son Işık", "See the true ending.", "Gerçek sonu gör."),
    ("Teamwork", "Takım Ruhu", "Win ten co-op matches.", "On ortak maç kazan."),
    ("Gardener", "Bahçıvan", "Grow every plant.", "Tüm bitkileri yetiştir."),
    ("Iron Will", "Demir İrade", "Finish on the hardest difficulty.", "En zor seviyede bitir."),
]
FRIEND_NAMES = [
    "kestrel",
    "mira_v",
    "Orbit",
    "Tomás",
    "Ayşe K.",
    "nyx",
    "Bjørn",
    "ztrider",
    "Lumen",
    "pixelwitch",
    "Deniz",
    "Haru",
    "quietfox",
    "Mehmet",
    "Ilse",
    "rook",
    "Zeynep",
    "Sol",
    "vantablack",
    "Okan",
    "Juno",
    "Kaito",
    "marrow",
    "Elif",
    "Tavi",
    "wrenn",
    "Can",
    "Noor",
]
COUNTRIES = [
    "TR",
    "DE",
    "US",
    "BR",
    "JP",
    "NO",
    "NL",
    "FR",
    "TR",
    "TR",
    "GB",
    "PL",
    "KR",
    "ES",
    "SE",
    "IT",
]


# --------------------------------------------------------------------------- images


def _png(width: int, height: int, pixel: Any) -> bytes:
    rows = bytearray()
    for y in range(height):
        rows.append(0)
        for x in range(width):
            rows.extend(pixel(x, y))

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + tag
            + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        )

    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(bytes(rows), 9))
        + chunk(b"IEND", b"")
    )


def _palette(seed: str) -> tuple[tuple[int, int, int], tuple[int, int, int]]:
    rng = random.Random(seed)
    hue = rng.random()

    def hsl(h: float, s: float, light: float) -> tuple[int, int, int]:
        r, g, b = colorsys.hls_to_rgb(h % 1.0, light, s)
        return int(r * 255), int(g * 255), int(b * 255)

    return hsl(hue, 0.55, 0.42), hsl(hue + 0.08, 0.65, 0.72)


def identicon(seed: str, size: int) -> bytes:
    rng = random.Random(seed + "/cells")
    cells = [[rng.random() < 0.5 for _ in range(3)] for _ in range(5)]
    dark, light = _palette(seed)
    step = size / 5

    def pixel(x: int, y: int) -> tuple[int, int, int]:
        col, row = min(4, int(x / step)), min(4, int(y / step))
        on = cells[row][col if col < 3 else 4 - col]
        return dark if on else light

    return _png(size, size, pixel)


def banner(seed: str, width: int = 460, height: int = 215) -> bytes:
    dark, light = _palette(seed)
    rng = random.Random(seed + "/banner")
    cx, cy, radius = (
        rng.uniform(0.2, 0.8) * width,
        rng.uniform(0.2, 0.8) * height,
        rng.uniform(40, 90),
    )

    def pixel(x: int, y: int) -> tuple[int, int, int]:
        t = (x / width) * 0.7 + (y / height) * 0.3
        base = tuple(int(dark[i] * (1 - t) + light[i] * t) for i in range(3))
        if (x - cx) ** 2 + (y - cy) ** 2 < radius**2:
            return tuple(min(255, c + 38) for c in base)  # type: ignore[return-value]
        return base  # type: ignore[return-value]

    return _png(width, height, pixel)


# --------------------------------------------------------------------------- world


# Like some real games (Forza Horizon), refuses achievements on a public profile.
HIDDEN_ACHIEVEMENTS = {9100120}  # Salt Road
# An achievement icon that, like some real ones, only exists under the new CDN path.
MOVED_ICON = "/9100160/ach_9100160_00.jpg"  # Orbital Gardens, unlocked


@dataclass
class Game:
    appid: int
    name: str
    icon: str
    playtime: int = 0
    recent: int = 0
    windows: int = 0
    linux: int = 0
    deck: int = 0
    last_played: int = 0
    achievements: list[str] = field(default_factory=list)
    unlocked: dict[str, int] = field(default_factory=dict)
    tags: list[int] = field(default_factory=list)
    release: int = 0
    developer: str = ""
    review: int = 80


@dataclass
class Friend:
    steamid: str
    name: str
    since: int
    country: str
    level: int
    created: int
    avatar: str
    vac: int = 0


class FakeSteam:
    """State of the invented account; ``advance`` moves time forward and plays."""

    def __init__(self, now: dt.datetime, seed: int = 42) -> None:
        self.rng = random.Random(seed)
        self.now = int(now.timestamp())
        self.persona = "Wanderer"
        self.avatar = self._hash("avatar-1")
        self.level = 23
        self.xp = 4180
        self.games: list[Game] = []
        self.friends: list[Friend] = []
        self.wishlist: dict[int, int] = {}
        self.groups = ["103582791460000001", "103582791460000002", "103582791460000003"]
        self.badges: list[dict[str, Any]] = [
            {
                "badgeid": 1,
                "level": 9,
                "xp": 450,
                "completion_time": self.now - 400 * DAY,
                "scarcity": 9123456,
            },
            {
                "badgeid": 13,
                "level": 32,
                "xp": 320,
                "completion_time": self.now - 200 * DAY,
                "scarcity": 5123456,
            },
        ]
        self.private_friends = False
        self.steps = 0
        self.releases = {
            9_100_010 + index * 10: self.now + (90 + index) * DAY
            if index >= 36
            else self.now - self.rng.randint(200, 3600) * DAY
            for index in range(len(GAME_NAMES))
        }
        self._make_world()

    def _hash(self, text: str) -> str:
        return format(zlib.crc32(text.encode()), "08x") * 5

    def _make_world(self) -> None:
        rng = self.rng
        for index, name in enumerate(GAME_NAMES[:32]):
            appid = 9_100_010 + index * 10
            count = rng.choice([0, 0, 8, 12, 15, 18, 24, 30, 42])
            game = Game(
                appid=appid,
                name=name,
                icon=self._hash(f"icon-{appid}"),
                achievements=[f"ACH_{appid}_{n:02d}" for n in range(count)],
                tags=rng.sample(sorted(TAGS), 5),
                release=self.releases[appid],
                developer=rng.choice(
                    [
                        "Lowlight Studio",
                        "Paper Moth",
                        "Northbound Games",
                        "Kettle & Co.",
                        "Ironbark",
                    ]
                ),
                review=rng.choice([95, 88, 81, 74, 67, 52, 91]),
            )
            if index < 22:
                hours = int(rng.paretovariate(1.2) * 6 * 60)
                when = self.now - rng.randint(5, 700) * DAY
                # Steam only splits playtime by platform for recent years.
                self._play(
                    game,
                    min(hours, 900 * 60),
                    when=when,
                    recent=False,
                    tracked=rng.uniform(0.4, 1.0),
                )
            self.games.append(game)
        perfect = next(g for g in self.games[1:] if g.achievements and g.playtime)
        for apiname in perfect.achievements:
            perfect.unlocked.setdefault(apiname, perfect.last_played - rng.randint(0, 30) * DAY)
        for index, name in enumerate(FRIEND_NAMES[:24]):
            self.friends.append(self._friend(index, name, self.now - rng.randint(30, 3000) * DAY))
        for game in GAME_NAMES[32:38]:
            self.wishlist[9_100_010 + GAME_NAMES.index(game) * 10] = (
                self.now - rng.randint(1, 600) * DAY
            )

    def _friend(self, index: int, name: str, since: int) -> Friend:
        rng = self.rng
        return Friend(
            steamid=str(76561198000100000 + index * 7),
            name=name,
            since=since,
            country=rng.choice(COUNTRIES),
            level=rng.randint(1, 90),
            created=since - rng.randint(100, 2000) * DAY,
            avatar=self._hash(f"friend-{index}"),
            vac=1 if index == 5 else 0,
        )

    def _play(
        self, game: Game, minutes: int, *, when: int, recent: bool, tracked: float = 1.0
    ) -> None:
        rng = self.rng
        game.playtime += minutes
        split_minutes = int(minutes * tracked)
        windows = int(split_minutes * rng.random())
        linux = split_minutes - windows
        game.windows += windows
        game.linux += linux  # like Steam, Linux time includes Steam Deck time
        game.deck += int(linux * rng.uniform(0.3, 0.8))
        game.last_played = when
        if recent:
            game.recent += minutes
        if game.achievements:
            locked = [a for a in game.achievements if a not in game.unlocked]
            share = min(1.0, game.playtime / (40 * 60))
            target = int(len(game.achievements) * share * rng.uniform(0.6, 1.0))
            for apiname in locked[: max(0, target - len(game.unlocked))]:
                game.unlocked[apiname] = when - rng.randint(0, 3 * DAY)

    def advance(self, days: int) -> None:
        """Move the clock and live a little: play, unlock, make and lose friends."""
        rng = self.rng
        self.now += days * DAY
        self.steps += 1
        for game in self.games:
            game.recent = 0
        for game in rng.sample(self.games[:26], 4):
            self._play(
                game, rng.randint(60, 1200), when=self.now - rng.randint(0, days) * DAY, recent=True
            )
        if rng.random() < 0.6 and len(self.games) < len(GAME_NAMES):
            index = len(self.games)
            appid = 9_100_010 + index * 10
            new = Game(
                appid=appid,
                name=GAME_NAMES[index],
                icon=self._hash(f"icon-{appid}"),
                achievements=[f"ACH_{appid}_{n:02d}" for n in range(rng.choice([10, 20]))],
                tags=rng.sample(sorted(TAGS), 5),
                release=self.releases[appid],
                developer="Paper Moth",
                review=86,
            )
            self.games.append(new)
            self.wishlist.pop(appid, None)
            self._play(new, rng.randint(90, 600), when=self.now, recent=True)
        if rng.random() < 0.5:
            index = len(self.friends)
            self.friends.append(
                self._friend(
                    index, FRIEND_NAMES[index % len(FRIEND_NAMES)] + str(index), self.now - DAY
                )
            )
        if rng.random() < 0.3 and len(self.friends) > 10:
            self.friends.pop(rng.randrange(len(self.friends)))
        if rng.random() < 0.3:
            self.friends[0].name = rng.choice(["kestrel", "k3strel", "Kestrel"])
        self.xp += rng.randint(100, 600)
        while self.xp >= self._level_floor(self.level + 1):
            self.level += 1
        if self.steps == 2:
            self.persona = "Wanderer of Ash"
            self.avatar = self._hash("avatar-2")
        if self.steps == 3:
            started = [
                g
                for g in self.games
                if g.achievements and 0 < len(g.unlocked) < len(g.achievements)
            ]
            if started:
                closest = max(
                    started, key=lambda g: (len(g.unlocked) / len(g.achievements), g.appid)
                )
                self._play(closest, rng.randint(120, 400), when=self.now - DAY, recent=True)
                for apiname in closest.achievements:
                    closest.unlocked.setdefault(apiname, self.now - rng.randint(1, days) * DAY)
        if rng.random() < 0.5:
            self.badges.append(
                {
                    "badgeid": 1,
                    "appid": rng.choice(self.games[:10]).appid,
                    "level": 1,
                    "xp": 100,
                    "completion_time": self.now - DAY,
                    "scarcity": rng.randint(10000, 900000),
                }
            )
        self.badges[1]["level"] = len(self.games)

    @staticmethod
    def _level_floor(level: int) -> int:
        total, step = 0, 100
        for n in range(1, level):
            total += step * (1 + n // 10)
        return total

    # ------------------------------------------------------------------ transport

    def transport(self) -> FakeTransport:
        return FakeTransport(self)


class FakeTransport:
    def __init__(self, world: FakeSteam) -> None:
        self.world = world
        self.calls: list[str] = []

    def fetch(self, url: str, timeout: float) -> Response:
        parts = urllib.parse.urlsplit(url)
        query = {k: v[0] for k, v in urllib.parse.parse_qs(parts.query).items()}
        self.calls.append(parts.path)
        host = parts.netloc
        if host == "api.steampowered.com":
            return self.api(parts.path.strip("/"), query, url)
        if host == "steamcommunity.com":
            return self.community(parts.path, url)
        return self.image(parts.path, url)

    @staticmethod
    def ok(data: Any, url: str) -> Response:
        return Response(200, json.dumps(data).encode(), {"content-type": "application/json"}, url)

    def api(self, path: str, q: dict[str, str], url: str) -> Response:
        needs_key = not path.startswith(("IStore", "ISteamUserStats/GetGlobal"))
        if needs_key and q.get("key") != API_KEY:
            return Response(
                403,
                b"<html><body>Forbidden. Please verify your key= parameter.</body></html>",
                {},
                url,
            )
        method = path.split("/")[1]
        handler = getattr(self, f"m_{method}", None)
        if handler is None:
            return Response(404, b"Not Found", {}, url)
        result = handler(q)
        if isinstance(result, Response):
            result.url = url
            return result
        return self.ok(result, url)

    # ISteamUser
    def m_GetPlayerSummaries(self, q: dict[str, str]) -> Any:
        w = self.world
        players = []
        for steamid in q.get("steamids", "").split(","):
            if steamid == STEAMID:
                players.append(
                    {
                        "steamid": STEAMID,
                        "communityvisibilitystate": 3,
                        "profilestate": 1,
                        "personaname": w.persona,
                        "commentpermission": 1,
                        "profileurl": "https://steamcommunity.com/id/wanderer/",
                        "avatar": f"https://avatars.steamstatic.com/{w.avatar}.jpg",
                        "avatarmedium": f"https://avatars.steamstatic.com/{w.avatar}_medium.jpg",
                        "avatarfull": f"https://avatars.steamstatic.com/{w.avatar}_full.jpg",
                        "avatarhash": w.avatar,
                        "lastlogoff": w.now - 3600,
                        "personastate": 1,
                        "realname": "Demo Account",
                        "primaryclanid": w.groups[0],
                        "timecreated": w.now - 4200 * DAY,
                        "personastateflags": 0,
                        "loccountrycode": "TR",
                        "gameid": str(w.games[0].appid),
                        "gameextrainfo": w.games[0].name,
                    }
                )
            for f in w.friends:
                if f.steamid == steamid:
                    players.append(
                        {
                            "steamid": f.steamid,
                            "communityvisibilitystate": 3,
                            "personaname": f.name,
                            "profileurl": f"https://steamcommunity.com/profiles/{f.steamid}/",
                            "avatarmedium": f"https://avatars.steamstatic.com/{f.avatar}_medium.jpg",
                            "avatarhash": f.avatar,
                            "personastate": int(f.steamid[-1]) % 4,
                            "lastlogoff": w.now - int(f.steamid[-2:]) * 3600,
                            "timecreated": f.created,
                            "loccountrycode": f.country,
                        }
                    )
        return {"response": {"players": players}}

    def m_ResolveVanityURL(self, q: dict[str, str]) -> Any:
        if q.get("vanityurl", "").lower() == "wanderer":
            return {"response": {"steamid": STEAMID, "success": 1}}
        return {"response": {"success": 42, "message": "No match"}}

    def m_GetFriendList(self, q: dict[str, str]) -> Any:
        w = self.world
        if w.private_friends:
            return Response(401, b"<html><body>Unauthorized</body></html>", {})
        return {
            "friendslist": {
                "friends": [
                    {"steamid": f.steamid, "relationship": "friend", "friend_since": f.since}
                    for f in w.friends
                ]
            }
        }

    def m_GetPlayerBans(self, q: dict[str, str]) -> Any:
        w = self.world
        vac = {f.steamid: f.vac for f in w.friends}
        return {
            "players": [
                {
                    "SteamId": s,
                    "CommunityBanned": False,
                    "VACBanned": bool(vac.get(s)),
                    "NumberOfVACBans": vac.get(s, 0),
                    "DaysSinceLastBan": 400 if vac.get(s) else 0,
                    "NumberOfGameBans": 0,
                    "EconomyBan": "none",
                }
                for s in q.get("steamids", "").split(",")
                if s
            ]
        }

    def m_GetUserGroupList(self, q: dict[str, str]) -> Any:
        return {
            "response": {
                "success": True,
                "groups": [{"gid": str(int(g) - 103582791429521408)} for g in self.world.groups],
            }
        }

    # IPlayerService
    def m_GetOwnedGames(self, q: dict[str, str]) -> Any:
        w = self.world
        games = []
        for g in w.games:
            row = {
                "appid": g.appid,
                "name": g.name,
                "playtime_forever": g.playtime,
                "img_icon_url": g.icon,
                "has_community_visible_stats": bool(g.achievements),
                "playtime_windows_forever": g.windows,
                "playtime_mac_forever": 0,
                "playtime_linux_forever": g.linux,
                "playtime_deck_forever": g.deck,
                "rtime_last_played": g.last_played,
                "playtime_disconnected": 0,
            }
            if g.recent:
                row["playtime_2weeks"] = g.recent
            games.append(row)
        return {"response": {"game_count": len(games), "games": games}}

    def m_GetRecentlyPlayedGames(self, q: dict[str, str]) -> Any:
        recent = [g for g in self.world.games if g.recent]
        return {
            "response": {
                "total_count": len(recent),
                "games": [
                    {
                        "appid": g.appid,
                        "name": g.name,
                        "playtime_2weeks": g.recent,
                        "playtime_forever": g.playtime,
                        "img_icon_url": g.icon,
                    }
                    for g in recent
                ],
            }
        }

    def m_GetSteamLevel(self, q: dict[str, str]) -> Any:
        w = self.world
        if q.get("steamid") == STEAMID:
            return {"response": {"player_level": w.level}}
        for f in w.friends:
            if f.steamid == q.get("steamid"):
                return {"response": {"player_level": f.level}}
        return {"response": {}}

    def m_GetSteamLevelDistribution(self, q: dict[str, str]) -> Any:
        level = int(q.get("player_level", "0"))
        return {"response": {"player_level_percentile": round(min(99.9, 40 + level * 1.7), 1)}}

    def m_GetBadges(self, q: dict[str, str]) -> Any:
        w = self.world
        floor = FakeSteam._level_floor(w.level)
        return {
            "response": {
                "badges": w.badges,
                "player_xp": w.xp,
                "player_level": w.level,
                "player_xp_needed_to_level_up": FakeSteam._level_floor(w.level + 1) - w.xp,
                "player_xp_needed_current_level": floor,
            }
        }

    def m_GetProfileItemsEquipped(self, q: dict[str, str]) -> Any:
        return {
            "response": {
                "avatar_frame": {
                    "communityitemid": "1",
                    "image_small": "items/9100010/frame_small.png",
                    "image_large": "items/9100010/frame.png",
                    "name": "Ember Ring",
                    "item_title": "Ember Ring",
                    "appid": 9100010,
                },
                "profile_background": {},
                "mini_profile_background": {},
                "animated_avatar": {},
            }
        }

    def m_GetWishlist(self, q: dict[str, str]) -> Any:
        items = [
            {"appid": appid, "priority": i + 1, "date_added": added}
            for i, (appid, added) in enumerate(self.world.wishlist.items())
        ]
        return {"response": {"items": items}}

    # ISteamUserStats
    def _game(self, q: dict[str, str]) -> Game | None:
        appid = int(q.get("appid") or q.get("gameid") or 0)
        return next((g for g in self.world.games if g.appid == appid), None)

    def m_GetPlayerAchievements(self, q: dict[str, str]) -> Any:
        game = self._game(q)
        if game is not None and game.appid in HIDDEN_ACHIEVEMENTS:
            return Response(
                403,
                json.dumps(
                    {"playerstats": {"error": "Profile is not public", "success": False}}
                ).encode(),
                {},
            )
        if game is None or not game.achievements:
            return Response(
                400,
                json.dumps(
                    {"playerstats": {"error": "Requested app has no stats", "success": False}}
                ).encode(),
                {},
            )
        return {
            "playerstats": {
                "steamID": STEAMID,
                "gameName": game.name,
                "success": True,
                "achievements": [
                    {
                        "apiname": a,
                        "achieved": int(a in game.unlocked),
                        "unlocktime": game.unlocked.get(a, 0),
                    }
                    for a in game.achievements
                ],
            }
        }

    def m_GetSchemaForGame(self, q: dict[str, str]) -> Any:
        game = self._game(q)
        if game is None:
            return {"game": {}}
        turkish = q.get("l") == "turkish"
        rows = []
        for n, apiname in enumerate(game.achievements):
            en, tr_name, en_desc, tr_desc = ACHIEVEMENT_WORDS[
                (n + game.appid) % len(ACHIEVEMENT_WORDS)
            ]
            hidden = n % 7 == 6
            row = {
                "name": apiname,
                "defaultvalue": 0,
                "displayName": tr_name if turkish else en,
                "hidden": int(hidden),
                "icon": f"https://cdn.akamai.steamstatic.com/steamcommunity/public/images/apps/{game.appid}/{apiname.lower()}.jpg",
                "icongray": f"https://cdn.akamai.steamstatic.com/steamcommunity/public/images/apps/{game.appid}/{apiname.lower()}_gray.jpg",
            }
            if not hidden:
                row["description"] = tr_desc if turkish else en_desc
            rows.append(row)
        return {
            "game": {
                "gameName": game.name,
                "gameVersion": "3",
                "availableGameStats": {"achievements": rows},
            }
        }

    def m_GetGlobalAchievementPercentagesForApp(self, q: dict[str, str]) -> Any:
        game = self._game(q)
        if game is None:
            return Response(403, b"", {})
        rng = random.Random(game.appid)
        rates = sorted((round(rng.uniform(0.4, 78), 1) for _ in game.achievements), reverse=True)
        return {
            "achievementpercentages": {
                "achievements": [
                    {"name": a, "percent": str(p)}
                    for a, p in zip(game.achievements, rates, strict=True)
                ]
            }
        }

    # Store
    def m_GetItems(self, q: dict[str, str]) -> Any:
        request = json.loads(q["input_json"])
        turkish = request["context"]["language"] == "turkish"
        known = {g.appid: g for g in self.world.games}
        for index, name in enumerate(GAME_NAMES):
            appid = 9_100_010 + index * 10
            if appid not in known:
                known[appid] = Game(
                    appid=appid,
                    name=name,
                    icon="",
                    tags=[19, 492, 4182],
                    release=self.world.releases[appid],
                    developer="Ironbark",
                )
        items = []
        for entry in request["ids"]:
            game = known.get(entry["appid"])
            if game is None:
                items.append({"item_type": 0, "id": 0, "success": 15})
                continue
            label = (
                ("Çok Olumlu" if turkish else "Very Positive")
                if game.review >= 80
                else ("Karışık" if turkish else "Mixed")
            )
            items.append(
                {
                    "item_type": 0,
                    "id": game.appid,
                    "success": 1,
                    "visible": True,
                    "name": game.name,
                    "appid": game.appid,
                    "type": 0,
                    "is_free": game.appid % 3 == 0,
                    "tagids": game.tags,
                    "categories": {
                        "supported_player_categoryids": [2],
                        "feature_categoryids": [22, 23, 29],
                        "controller_categoryids": [28],
                    },
                    "reviews": {
                        "summary_filtered": {
                            "review_count": 1000 + game.appid % 9000,
                            "percent_positive": game.review,
                            "review_score": 8 if game.review >= 80 else 5,
                            "review_score_label": label,
                        }
                    },
                    "basic_info": {
                        "short_description": (
                            "Uydurma bir oyun: " if turkish else "An invented game: "
                        )
                        + game.name,
                        "publishers": [{"name": game.developer}],
                        "developers": [{"name": game.developer}],
                    },
                    "tags": [
                        {"tagid": t, "weight": 1000 - i * 50} for i, t in enumerate(game.tags)
                    ],
                    "assets": {
                        "asset_url_format": f"steam/apps/{game.appid}/${{FILENAME}}?t=1700000000",
                        "header": "header.jpg",
                    },
                    "release": {
                        "steam_release_date": game.release,
                        "is_coming_soon": game.release > self.world.now,
                    },
                    "platforms": {
                        "windows": True,
                        "steamos_linux": game.appid % 2 == 0,
                        "steam_deck_compat_category": game.appid % 4,
                    },
                }
            )
        return {"response": {"store_items": items}}

    def m_GetTagList(self, q: dict[str, str]) -> Any:
        turkish = q.get("language") == "turkish"
        return {
            "response": {
                "tags": [{"tagid": k, "name": v[1] if turkish else v[0]} for k, v in TAGS.items()]
            }
        }

    def m_GetStoreCategories(self, q: dict[str, str]) -> Any:
        turkish = q.get("language") == "turkish"
        return {
            "response": {
                "categories": [
                    {"categoryid": k, "display_name": v[1] if turkish else v[0]}
                    for k, v in CATEGORIES.items()
                ]
            }
        }

    # Community and CDN
    def community(self, path: str, url: str) -> Response:
        gid = path.split("/")[2] if path.startswith("/gid/") else ""
        names = {
            "103582791460000001": "Night Ferry Society",
            "103582791460000002": "Linux Gamers TR",
            "103582791460000003": "Achievement Hunters",
        }
        if gid not in names:
            return Response(404, b"", {}, url)
        avatar = f"https://avatars.fastly.steamstatic.com/{self.world._hash(gid)}_full.jpg"
        body = (
            f'<?xml version="1.0" encoding="UTF-8"?><memberList><groupID64>{gid}</groupID64><groupDetails>'
            f"<groupName><![CDATA[{names[gid]}]]></groupName><groupURL><![CDATA[{names[gid].replace(' ', '')}]]></groupURL>"
            f"<headline><![CDATA[]]></headline><avatarFull><![CDATA[{avatar}]]></avatarFull>"
            f"<memberCount>{len(names[gid]) * 37}</memberCount><membersOnline>12</membersOnline></groupDetails></memberList>"
        )
        return Response(200, body.encode(), {"content-type": "text/xml"}, url)

    def image(self, path: str, url: str) -> Response:
        if path.startswith("/steamcommunity/public/images/") and MOVED_ICON in path:
            return Response(404, b"Not Found", {}, url)
        # Same picture under Steam's old and new community image paths.
        path = path.replace("/community_assets/images/", "/steamcommunity/public/images/")
        name = path.rsplit("/", 1)[-1]
        if "header" in name:
            data = banner(path)
        elif "_full" in name or "frame" in name:
            data = identicon(path.replace("_full", "").replace("_medium", ""), 184)
        elif "_medium" in name:
            data = identicon(path.replace("_medium", ""), 64)
        else:
            data = identicon(path, 64)
        return Response(200, data, {"content-type": "image/png"}, url)
