# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 abel0x <https://github.com/abel0x>
"""Images kept for offline viewing.

Every remote image maps to one fixed path under ``database/media`` derived from
its URL, so snapshots only store URLs and the reports and the site look for the
local copy (falling back to the URL when an image was never downloaded). Steam's
CDN names avatars and icons by content hash, which means an old snapshot keeps
showing the avatar the account had back then.
"""

from __future__ import annotations

import hashlib
import os
import re
import threading
import time
import urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import TYPE_CHECKING

from .api import Endpoints
from .net import Http, NetworkError
from .util import read_json, write_bytes, write_json

if TYPE_CHECKING:
    from .console import Console
    from .i18n import Translator

# Steam is moving community images (game and achievement icons) to a new path,
# and some files already exist only there. A 404 on the old path tries the new one.
_OLD_COMMUNITY = re.compile(r"^https?://[^/]+/steamcommunity/public/images/(apps/.+)$")
NEW_COMMUNITY = Endpoints.community_assets
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".avif", ".svg"}
MISSING_RETRY_DAYS = 30
# Touched whenever new images arrive, so the site rebuilds pages that can now
# point at a local copy instead of the CDN.
STAMP = "media/updated"
_SAFE = re.compile(r"^[A-Za-z0-9._-]{1,120}$")


def _safe(segment: str) -> str:
    return segment if _SAFE.match(segment) and segment not in (".", "..") else _digest(segment)


def _digest(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:24]


def _owner_after(folders: list[str], word: str) -> tuple[int, str] | None:
    """Position of the last ``word`` folder and the numeric app id right after it."""
    if word not in folders:
        return None
    index = len(folders) - 1 - folders[::-1].index(word)
    owner = folders[index + 1] if index + 1 < len(folders) else ""
    return (index, owner) if owner.isdigit() else None


def local_path(url: str | None) -> str | None:
    """Path relative to the database folder for an image URL, or None for non-images.

    avatars.steamstatic.com/<hash>_full.jpg           -> media/avatars/<hash>_full.jpg
    .../public/images/apps/<appid>/<hash>.jpg         -> media/apps/<appid>/<hash>.jpg
    .../steam/apps/<appid>/header.jpg?t=<version>     -> media/store/<appid>/header_<version>.jpg
    .../public/images/items/<appid>/<file>            -> media/items/<appid>/<file>
    """
    if not url:
        return None
    parts = urllib.parse.urlsplit(url)
    if parts.scheme not in ("http", "https"):
        return None
    segments = [s for s in urllib.parse.unquote(parts.path).split("/") if s]
    if not segments:
        return None
    stem, ext = os.path.splitext(segments[-1])
    ext = ext.lower()
    if ext not in IMAGE_EXTENSIONS:
        return None
    ext = ".jpg" if ext == ".jpeg" else ext
    name = _safe(stem) + ext
    folders = segments[:-1]

    if parts.netloc.lower().startswith("avatars."):
        return f"media/avatars/{name}"
    found = _owner_after(folders, "items")
    if found:
        return f"media/items/{found[1]}/{name}"
    found = _owner_after(folders, "apps")
    if found:
        index, appid = found
        if "store_item_assets" in folders or (index > 0 and folders[index - 1] == "steam"):
            version = urllib.parse.parse_qs(parts.query).get("t", [""])[0]
            if version.isdigit():
                name = f"{_safe(stem)}_{version}{ext}"
            return f"media/store/{appid}/{name}"
        return f"media/apps/{appid}/{name}"
    return f"media/other/{_digest(url)}{ext}"


class MediaStore:
    def __init__(
        self,
        database_dir: Path,
        http: Http | None,
        *,
        workers: int = 8,
        allow_svg: bool = False,
    ) -> None:
        self.base = database_dir
        self.http = http
        self.workers = max(1, workers)
        self.allow_svg = allow_svg
        self.wanted: dict[str, str] = {}
        self.downloaded = 0
        self.failed = 0
        self._missing_path = database_dir / "media" / "missing.json"
        self._missing: dict[str, int] = read_json(self._missing_path, {})
        self._lock = threading.Lock()

    def resolve(self, url: str | None) -> str | None:
        rel = local_path(url)
        return rel if rel and (self.base / rel).is_file() else None

    def want(self, url: str | None) -> None:
        rel = local_path(url)
        if not rel or url in self.wanted or (self.base / rel).is_file():
            return
        failed_at = self._missing.get(url or "", 0)
        if failed_at and time.time() - failed_at < MISSING_RETRY_DAYS * 86400:
            return
        self.wanted[url or ""] = rel

    def _fetch(self, url: str, rel: str) -> bool:
        assert self.http is not None
        try:
            response = self.http.get(url, limit=False)
            moved = _OLD_COMMUNITY.match(url)
            if response.status == 404 and moved:
                response = self.http.get(NEW_COMMUNITY + moved.group(1), limit=False)
        except NetworkError:
            return False
        kind = response.content_type
        acceptable = kind.startswith("image/") and (kind != "image/svg+xml" or self.allow_svg)
        if response.status != 200 or not response.body or not acceptable:
            if response.status == 404:
                with self._lock:
                    self._missing[url] = int(time.time())
            return False
        write_bytes(self.base / rel, response.body)
        return True

    def flush(self, console: Console | None = None, label: str = "") -> None:
        items = list(self.wanted.items())
        self.wanted.clear()
        if not items or self.http is None:
            return
        progress = console.progress(label, len(items)) if console else None
        with ThreadPoolExecutor(max_workers=self.workers) as pool:
            futures = [pool.submit(self._fetch, url, rel) for url, rel in items]
            try:
                for future in as_completed(futures):
                    if future.result():
                        self.downloaded += 1
                    else:
                        self.failed += 1
                    if progress:
                        progress.advance()
            finally:
                for future in futures:
                    future.cancel()
                if self._missing:
                    write_json(self._missing_path, self._missing)
                if self.downloaded:
                    write_bytes(self.base / STAMP, b"")
        if progress:
            progress.finish(self.summary(console.tr if console else None))

    def summary(self, tr: Translator | None) -> str:
        if tr is None:
            return f"{self.downloaded} downloaded, {self.failed} unavailable"
        text = tr.t("cli.collect.images_done", count=self.downloaded)
        if self.failed:
            text += ", " + tr.t("cli.collect.images_failed", count=self.failed)
        return text
