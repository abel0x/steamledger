# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 abel0x <https://github.com/abel0x>
"""HTTP for the Steam Web API and the Steam CDN.

A transport performs single requests; ``Http`` adds the policy around it:
a shared rate limit, retries with backoff for 429/5xx and dropped connections,
cancellation for Ctrl+C, and redaction so the API key never shows up in an
error message, a log line or a file.
"""

from __future__ import annotations

import gzip
import http.client
import json
import random
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol

from . import HOMEPAGE, __version__

USER_AGENT = f"steamledger/{__version__} (+{HOMEPAGE})"
RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})
_KEY_PARAM = re.compile(r"(?i)\b(key=)[^&\s\"']+")


def redact(text: str, secrets: Iterable[str] = ()) -> str:
    text = _KEY_PARAM.sub(r"\1***", text)
    for secret in secrets:
        if secret and len(secret) >= 6:
            text = text.replace(secret, "***")
    return text


class NetworkError(Exception):
    """The request never got an HTTP answer (DNS, TLS, timeout, reset...)."""


class Cancelled(Exception):
    """The user interrupted the run."""


@dataclass
class Response:
    status: int
    body: bytes
    headers: Mapping[str, str] = field(default_factory=dict)
    url: str = ""

    @property
    def content_type(self) -> str:
        return self.headers.get("content-type", "").split(";")[0].strip().lower()

    def json(self) -> Any:
        return json.loads(self.body.decode("utf-8-sig") or "null")

    def text(self, limit: int = 300) -> str:
        """Short, tag-free excerpt of the body for error messages."""
        raw = self.body[:4000].decode("utf-8", "replace")
        raw = re.sub(r"<[^>]+>", " ", raw)
        return re.sub(r"\s+", " ", raw).strip()[:limit]


class Transport(Protocol):
    def fetch(self, url: str, timeout: float) -> Response: ...


class UrllibTransport:
    """The real network, through urllib (honours HTTPS_PROXY and the OS certificate store)."""

    def fetch(self, url: str, timeout: float) -> Response:
        request = urllib.request.Request(
            url,
            headers={"User-Agent": USER_AGENT, "Accept-Encoding": "gzip", "Accept": "*/*"},
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as reply:
                status, headers, body = reply.status, reply.headers, reply.read()
        except urllib.error.HTTPError as exc:
            status, headers = exc.code, exc.headers
            try:
                body = exc.read()
            except (OSError, http.client.HTTPException):
                body = b""
        except (urllib.error.URLError, http.client.HTTPException, OSError, ValueError) as exc:
            raise NetworkError(str(getattr(exc, "reason", exc))) from None
        lowered = {k.lower(): v for k, v in (headers.items() if headers else [])}
        if lowered.get("content-encoding", "").lower() == "gzip":
            try:
                body = gzip.decompress(body)
            except (OSError, EOFError) as exc:
                raise NetworkError(f"corrupt gzip body: {exc}") from None
        return Response(status, body, lowered, url)


class RateLimiter:
    """Spaces requests evenly across threads; a 429 pushes everyone back."""

    def __init__(self, per_second: float) -> None:
        self.interval = 1.0 / per_second if per_second > 0 else 0.0
        self._next = 0.0
        self._lock = threading.Lock()

    def wait(self, cancel: threading.Event | None = None) -> None:
        with self._lock:
            now = time.monotonic()
            slot = max(now, self._next)
            self._next = slot + self.interval
        delay = slot - now
        if delay > 0:
            if cancel is not None:
                if cancel.wait(delay):
                    raise Cancelled()
            else:
                time.sleep(delay)

    def back_off(self, seconds: float) -> None:
        with self._lock:
            self._next = max(self._next, time.monotonic() + seconds)


def _clean(params: Mapping[str, Any]) -> dict[str, str]:
    out = {}
    for key, value in params.items():
        if value is None:
            continue
        if isinstance(value, bool):
            value = "true" if value else "false"
        out[key] = str(value)
    return out


class Http:
    def __init__(
        self,
        transport: Transport | None = None,
        *,
        timeout: float = 30.0,
        retries: int = 4,
        per_second: float = 8.0,
        secrets: Iterable[str] = (),
        cancel: threading.Event | None = None,
    ) -> None:
        self.transport = transport or UrllibTransport()
        self.timeout = timeout
        self.retries = max(0, retries)
        self.limiter = RateLimiter(per_second)
        self.secrets = tuple(s for s in secrets if s)
        self.cancel = cancel or threading.Event()
        self.requests = 0

    def redact(self, text: str) -> str:
        return redact(text, self.secrets)

    def get(
        self, url: str, params: Mapping[str, Any] | None = None, *, limit: bool = True
    ) -> Response:
        full = url
        if params:
            full += ("&" if "?" in url else "?") + urllib.parse.urlencode(_clean(params))
        attempt = 0
        while True:
            if self.cancel.is_set():
                raise Cancelled()
            if limit:
                self.limiter.wait(self.cancel)
            self.requests += 1
            try:
                response = self.transport.fetch(full, self.timeout)
            except NetworkError as exc:
                if attempt >= self.retries:
                    raise NetworkError(self.redact(f"{exc} [{full}]")) from None
                self._pause(self._backoff(attempt))
                attempt += 1
                continue
            if response.status in RETRY_STATUSES and attempt < self.retries:
                delay = self._retry_after(response) or self._backoff(attempt)
                if response.status == 429:
                    self.limiter.back_off(delay)
                self._pause(delay)
                attempt += 1
                continue
            response.url = self.redact(full)
            return response

    @staticmethod
    def _backoff(attempt: int) -> float:
        return min(30.0, 1.5 * 2**attempt) * random.uniform(0.8, 1.2)

    @staticmethod
    def _retry_after(response: Response) -> float:
        try:
            return min(120.0, max(0.0, float(response.headers.get("retry-after", ""))))
        except ValueError:
            return 0.0

    def _pause(self, seconds: float) -> None:
        if self.cancel.wait(seconds):
            raise Cancelled()
