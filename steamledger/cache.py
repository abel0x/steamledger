# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 abel0x <https://github.com/abel0x>
"""Slow-changing Steam data kept between runs in ``database/cache``.

Achievement schemas, global unlock rates, store details and tag names change
rarely; caching them keeps a daily collection down to a handful of API calls.
Deleting the folder is always safe: the next run fetches everything again.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Any

from .util import read_json, write_json

DAY = 86400


class Table:
    """A JSON file of ``key -> {"at": unix_time, "value": ...}`` rows."""

    def __init__(self, path: Path) -> None:
        self.path = path
        raw = read_json(path, {})
        self.rows: dict[str, dict[str, Any]] = raw.get("rows", {}) if isinstance(raw, dict) else {}
        self.dirty = False
        self._lock = threading.Lock()

    def get(self, key: Any, max_age_days: float) -> tuple[bool, Any]:
        with self._lock:
            row = self.rows.get(str(key))
        if not row or time.time() - row.get("at", 0) > max_age_days * DAY:
            return False, None
        return True, row.get("value")

    def put(self, key: Any, value: Any) -> None:
        with self._lock:
            self.rows[str(key)] = {"at": int(time.time()), "value": value}
            self.dirty = True

    def save(self) -> None:
        with self._lock:
            if self.dirty:
                write_json(self.path, {"rows": self.rows}, compact=True)
                self.dirty = False


class Cache:
    def __init__(self, root: Path) -> None:
        self.root = root
        self._tables: dict[str, Table] = {}
        self._lock = threading.Lock()

    def table(self, name: str) -> Table:
        with self._lock:
            if name not in self._tables:
                self._tables[name] = Table(self.root / f"{name}.json")
            return self._tables[name]

    def read(self, name: str, max_age_days: float | None = None) -> Any:
        entry = read_json(self.root / f"{name}.json", None)
        if not isinstance(entry, dict) or "value" not in entry:
            return None
        if max_age_days is not None and time.time() - entry.get("at", 0) > max_age_days * DAY:
            return None
        return entry["value"]

    def write(self, name: str, value: Any) -> None:
        write_json(
            self.root / f"{name}.json", {"at": int(time.time()), "value": value}, compact=True
        )

    def save(self) -> None:
        for table in list(self._tables.values()):
            table.save()
