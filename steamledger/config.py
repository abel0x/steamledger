# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 abel0x <https://github.com/abel0x>
"""config.json: the API key, the Steam account and the collection options.

The file sits in the project folder, is ignored by git and is written with
owner-only permissions on Linux and macOS. STEAM_API_KEY, STEAM_ID and
STEAMLEDGER_LANG override the file without changing it.
"""

from __future__ import annotations

import copy
import json
import os
import re
from pathlib import Path
from typing import Any

from .util import KeyedError, read_json, write_json

API_KEY_PATTERN = re.compile(r"^[0-9A-Fa-f]{32}$")
ACHIEVEMENT_ICON_MODES = ("unlocked", "all", "none")
CSV_DELIMITERS = (",", ";", "\t")

DEFAULTS: dict[str, Any] = {
    "api_key": "",
    "steam_id": "",
    "language": "auto",
    "store_country": "auto",
    "collect": {
        "achievements": True,
        "achievements_of_unplayed_games": False,
        "global_rarity": True,
        "store_details": True,
        "friends": True,
        "friend_levels": True,
        "wishlist": True,
        "groups": True,
    },
    "media": {
        "avatars": True,
        "game_icons": True,
        "game_headers": True,
        "achievement_icons": "unlocked",
        # Skip the icons of games with more achievements than this (0: no limit).
        # Some games have thousands, which would fill the archive with images.
        "achievement_icon_limit": 1500,
    },
    "output": {
        "build_site": True,
        "csv_delimiter": ",",
    },
    "network": {
        "timeout": 30,
        "retries": 4,
        "requests_per_second": 8,
        "workers": 4,
    },
}


class ConfigError(KeyedError):
    """``key`` is the last part of a translation key under cli.config_error."""


def _merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def mask_key(key: str) -> str:
    return f"{key[:4]}…{key[-4:]}" if len(key) >= 12 else ("*" * len(key))


class Config:
    def __init__(self, path: Path, data: dict[str, Any] | None = None) -> None:
        self.path = path
        self.data = _merge(DEFAULTS, data or {})

    # ------------------------------------------------------------------ access

    def get(self, dotted: str, default: Any = None) -> Any:
        node: Any = self.data
        for part in dotted.split("."):
            if not isinstance(node, dict) or part not in node:
                return default
            node = node[part]
        return node

    def set(self, dotted: str, value: Any) -> None:
        parts = dotted.split(".")
        node = self.data
        for part in parts[:-1]:
            node = node.setdefault(part, {})
        node[parts[-1]] = value

    @property
    def api_key(self) -> str:
        return (os.environ.get("STEAM_API_KEY") or self.data.get("api_key") or "").strip()

    @property
    def steam_id(self) -> str:
        return (os.environ.get("STEAM_ID") or self.data.get("steam_id") or "").strip()

    @property
    def language(self) -> str:
        return str(self.data.get("language") or "auto")

    @property
    def is_configured(self) -> bool:
        return bool(self.api_key and self.steam_id)

    # ------------------------------------------------------------------ io

    def validate(self) -> None:
        key = self.api_key
        if key and not API_KEY_PATTERN.match(key):
            raise ConfigError("api_key")
        steam_id = self.steam_id
        if steam_id and not (steam_id.isdigit() and len(steam_id) == 17):
            raise ConfigError("steam_id")
        if self.get("media.achievement_icons") not in ACHIEVEMENT_ICON_MODES:
            raise ConfigError(
                "choice", key="media.achievement_icons", choices=", ".join(ACHIEVEMENT_ICON_MODES)
            )
        limit = self.get("media.achievement_icon_limit")
        if not isinstance(limit, int) or isinstance(limit, bool) or limit < 0:
            raise ConfigError("number", key="media.achievement_icon_limit")
        if self.get("output.csv_delimiter") not in CSV_DELIMITERS:
            raise ConfigError("choice", key="output.csv_delimiter", choices='",", ";", "\\t"')
        for name in ("timeout", "retries", "requests_per_second", "workers"):
            value = self.get(f"network.{name}")
            if not isinstance(value, (int, float)) or isinstance(value, bool) or value < 0:
                raise ConfigError("number", key=f"network.{name}")
        if self.get("network.workers") < 1:
            raise ConfigError("number", key="network.workers")

    def save(self) -> None:
        write_json(self.path, self.data, private=True)


def load_config(path: Path) -> Config:
    try:
        raw = read_json(path, default={})
    except json.JSONDecodeError as exc:
        raise ConfigError("syntax", path=str(path), line=exc.lineno, column=exc.colno) from None
    except OSError as exc:
        raise ConfigError("unreadable", path=str(path), reason=exc.strerror or str(exc)) from None
    if not isinstance(raw, dict):
        raise ConfigError("syntax", path=str(path), line=1, column=1)
    config = Config(path, raw)
    config.validate()
    return config
