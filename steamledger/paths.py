# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 abel0x <https://github.com/abel0x>
"""Where everything lives. All data stays inside the project folder so the whole
archive can be copied, backed up or moved between Windows and Linux as one tree."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parent
WEB_DIR = PACKAGE_DIR / "web"
LOCALES_DIR = PACKAGE_DIR / "locales"


@dataclass(frozen=True)
class Paths:
    root: Path

    @property
    def config(self) -> Path:
        return self.root / "config.json"

    @property
    def database(self) -> Path:
        return self.root / "database"

    @property
    def latest(self) -> Path:
        return self.database / "latest"

    @property
    def archive(self) -> Path:
        return self.database / "archive"

    @property
    def changes(self) -> Path:
        return self.database / "changes"

    @property
    def media(self) -> Path:
        return self.database / "media"

    @property
    def cache(self) -> Path:
        return self.database / "cache"

    @property
    def site(self) -> Path:
        return self.root / "site"


def default_root() -> Path:
    """STEAMLEDGER_HOME, else the source checkout this package runs from, else the cwd."""
    env = os.environ.get("STEAMLEDGER_HOME", "").strip()
    if env:
        return Path(env).expanduser().resolve()
    checkout = PACKAGE_DIR.parent
    if (checkout / "pyproject.toml").is_file():
        return checkout
    return Path.cwd().resolve()
