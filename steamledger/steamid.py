# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 abel0x <https://github.com/abel0x>
"""Steam account identifiers.

People know their account by many names: the 17-digit SteamID64, a profile URL,
a custom URL name, the "Friend Code" shown in the Steam client, or the legacy
STEAM_X:Y:Z and [U:1:N] forms. ``parse`` turns any of them into either a
SteamID64 or a custom URL name that still has to be resolved through the API.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# SteamID64 of account id 0 for an individual account in the public universe.
BASE = 76561197960265728
GROUP_BASE = 103582791429521408
ACCOUNT_LIMIT = 2**32

_PROFILE_URL = re.compile(
    r"^(?:https?://)?(?:www\.)?steamcommunity\.com/(profiles|id)/([^/?#\s]+)", re.IGNORECASE
)
_STEAM2 = re.compile(r"^STEAM_([0-5]):([01]):(\d+)$", re.IGNORECASE)
_STEAM3 = re.compile(r"^\[?U:1:(\d+)\]?$", re.IGNORECASE)
_VANITY = re.compile(r"^[A-Za-z0-9_-]{2,32}$")


class SteamIdError(ValueError):
    pass


@dataclass(frozen=True)
class Parsed:
    kind: str  # "steamid64" or "vanity"
    value: str


def is_steamid64(value: str | int) -> bool:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return False
    return BASE < number < BASE + ACCOUNT_LIMIT


def parse(text: str) -> Parsed:
    raw = (text or "").strip()
    if not raw:
        raise SteamIdError("empty")

    match = _PROFILE_URL.match(raw)
    if match:
        kind, value = match.group(1).lower(), match.group(2)
        if kind == "profiles":
            if not is_steamid64(value):
                raise SteamIdError(raw)
            return Parsed("steamid64", str(int(value)))
        raw = value  # custom URL name, validated below

    match = _STEAM2.match(raw)
    if match:
        account = int(match.group(3)) * 2 + int(match.group(2))
        if account <= 0 or account >= ACCOUNT_LIMIT:
            raise SteamIdError(raw)
        return Parsed("steamid64", str(BASE + account))

    match = _STEAM3.match(raw)
    if match:
        account = int(match.group(1))
        if account <= 0 or account >= ACCOUNT_LIMIT:
            raise SteamIdError(raw)
        return Parsed("steamid64", str(BASE + account))

    if raw.isdigit():
        if is_steamid64(raw):
            return Parsed("steamid64", str(int(raw)))
        number = int(raw)
        if 0 < number < ACCOUNT_LIMIT and len(raw) <= 10:  # "Friend Code" = account id
            return Parsed("steamid64", str(BASE + number))
        raise SteamIdError(raw)

    if _VANITY.match(raw):
        return Parsed("vanity", raw)
    raise SteamIdError(raw)


def account_id(steamid64: str | int) -> int:
    return int(steamid64) - BASE


def steam2(steamid64: str | int) -> str:
    account = account_id(steamid64)
    return f"STEAM_1:{account & 1}:{account >> 1}"


def steam3(steamid64: str | int) -> str:
    return f"[U:1:{account_id(steamid64)}]"


def group64(gid: str | int) -> str:
    """GetUserGroupList returns 32-bit group ids; community URLs want the 64-bit form."""
    number = int(gid)
    return str(number + GROUP_BASE if number < ACCOUNT_LIMIT else number)


def custom_url(profile_url: str | None) -> str | None:
    """'https://steamcommunity.com/id/name/' -> 'name'."""
    match = _PROFILE_URL.match(profile_url or "")
    if match and match.group(1).lower() == "id":
        return match.group(2)
    return None
