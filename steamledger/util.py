# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 abel0x <https://github.com/abel0x>
"""Helpers shared by every module: time handling, JSON and crash-safe file writes."""

from __future__ import annotations

import contextlib
import datetime as dt
import json
import os
import shutil
import sys
import tempfile
import time
from collections.abc import Iterator, Sequence
from pathlib import Path
from typing import Any, TypeVar

T = TypeVar("T")

UTC = dt.timezone.utc
IS_WINDOWS = sys.platform == "win32"

_MISSING: Any = object()


class KeyedError(Exception):
    """An error the user sees. ``key`` is a translation key and ``params`` fill its
    placeholders. Both are positional-only, so a placeholder may itself be named
    ``key``."""

    def __init__(self, key: str, /, **params: Any) -> None:
        super().__init__(key)
        self.key = key
        self.params = params


# --------------------------------------------------------------------------- time


def utcnow() -> dt.datetime:
    return dt.datetime.now(UTC).replace(microsecond=0)


def iso_utc(value: dt.datetime) -> str:
    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_iso(text: str) -> dt.datetime:
    """Parse the ISO 8601 stamps this project writes. Python 3.10 cannot read a trailing 'Z'."""
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    value = dt.datetime.fromisoformat(text)
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def utc_offset(value: dt.datetime) -> str:
    """Offset of the local time zone at ``value`` as '+03:00'."""
    offset = value.astimezone().utcoffset() or dt.timedelta(0)
    minutes = int(offset.total_seconds() // 60)
    sign = "-" if minutes < 0 else "+"
    minutes = abs(minutes)
    return f"{sign}{minutes // 60:02d}:{minutes % 60:02d}"


def from_unix(stamp: Any) -> dt.datetime | None:
    """Local, timezone-aware datetime for a Unix timestamp; None for 0, None or garbage."""
    try:
        seconds = int(stamp)
    except (TypeError, ValueError):
        return None
    if seconds <= 0:
        return None
    try:
        return dt.datetime.fromtimestamp(seconds, UTC).astimezone()
    except (OverflowError, OSError, ValueError):
        return None


def local_stamp(stamp: Any, *, with_time: bool = True) -> str:
    """'2026-10-30 19:54:12' in local time, the form spreadsheets parse on their own."""
    value = from_unix(stamp)
    if value is None:
        return ""
    return value.strftime("%Y-%m-%d %H:%M:%S" if with_time else "%Y-%m-%d")


def days_between(start: dt.datetime, end: dt.datetime) -> float:
    return (end - start).total_seconds() / 86400


# --------------------------------------------------------------------------- json


def dump_json(data: Any, *, compact: bool = False) -> str:
    if compact:
        return json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    return json.dumps(data, ensure_ascii=False, indent=2) + "\n"


def dump_js(data: Any) -> str:
    """JSON that is also safe to embed in a <script>: line separators and '</' are escaped."""
    text = dump_json(data, compact=True)
    return text.replace("\u2028", "\\u2028").replace("\u2029", "\\u2029").replace("</", "<\\/")


def read_json(path: Path, default: Any = _MISSING) -> Any:
    """Read JSON written by us or by a text editor (utf-8-sig tolerates Notepad's BOM)."""
    try:
        with open(path, encoding="utf-8-sig") as handle:
            return json.load(handle)
    except FileNotFoundError:
        if default is _MISSING:
            raise
        return default


def write_json(path: Path, data: Any, *, compact: bool = False, private: bool = False) -> None:
    write_text(path, dump_json(data, compact=compact), private=private)


# --------------------------------------------------------------------------- files


def write_text(path: Path, text: str, *, encoding: str = "utf-8", private: bool = False) -> None:
    write_bytes(path, text.encode(encoding), private=private)


def write_bytes(path: Path, data: bytes, *, private: bool = False) -> None:
    """Write through a temp file and rename, so a crash never leaves half a file behind."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
        if not IS_WINDOWS:
            os.chmod(tmp, 0o600 if private else 0o644)
        replace(tmp, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise


def replace(src: str | Path, dst: str | Path, attempts: int = 6) -> None:
    """os.replace with a short retry: on Windows a virus scanner or an open
    spreadsheet can hold the target for a moment."""
    for attempt in range(attempts):
        try:
            os.replace(src, dst)
            return
        except PermissionError:
            if attempt == attempts - 1:
                raise
            time.sleep(0.15 * (attempt + 1))


def remove_tree(path: Path) -> None:
    """rmtree that also clears the read-only bit Windows sets on some copied files."""

    def _retry(func: Any, target: str, _exc: Any) -> None:
        with contextlib.suppress(OSError):
            os.chmod(target, 0o700)
            func(target)

    if not path.exists():
        return
    if sys.version_info >= (3, 12):
        shutil.rmtree(path, onexc=_retry)
    else:  # pragma: no cover - exercised on 3.10/3.11
        shutil.rmtree(path, onerror=_retry)


def link_or_copy(src: Path, dst: Path) -> None:
    """Hard-link when the filesystem allows it (no extra disk space), copy otherwise."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    with contextlib.suppress(FileNotFoundError):
        dst.unlink()
    try:
        os.link(src, dst)
    except OSError:
        shutil.copy2(src, dst)


def dir_size(path: Path) -> int:
    total = 0
    for root, _dirs, files in os.walk(path):
        for name in files:
            with contextlib.suppress(OSError):
                total += os.path.getsize(os.path.join(root, name))
    return total


# --------------------------------------------------------------------------- misc


def chunks(items: Sequence[T], size: int) -> Iterator[Sequence[T]]:
    for start in range(0, len(items), size):
        yield items[start : start + size]


def as_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def human_bytes(size: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} GB"  # pragma: no cover
