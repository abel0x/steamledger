# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 abel0x <https://github.com/abel0x>
"""Terminal output: colours (including the Windows console), progress lines,
prompts and aligned tables that keep wide characters in their columns."""

from __future__ import annotations

import getpass
import os
import shutil
import sys
import threading
import time
import unicodedata
from collections.abc import Sequence
from typing import TYPE_CHECKING, TextIO

if TYPE_CHECKING:
    from .i18n import Translator


def _windows_console_mode(stream: TextIO) -> int | None:
    """Console mode of ``stream`` on Windows; None when it is not a console."""
    try:
        import ctypes
        import msvcrt

        handle = msvcrt.get_osfhandle(stream.fileno())  # type: ignore[attr-defined]
        mode = ctypes.c_uint32()
        if not ctypes.windll.kernel32.GetConsoleMode(handle, ctypes.byref(mode)):  # type: ignore[attr-defined]
            return None
        return mode.value
    except Exception:
        return None


def _enable_windows_vt(stream: TextIO) -> bool:
    """Turn on ANSI escape handling in a classic Windows console (Windows 10+)."""
    mode = _windows_console_mode(stream)
    if mode is None:
        return False
    if mode & 0x0004:  # ENABLE_VIRTUAL_TERMINAL_PROCESSING
        return True
    try:
        import ctypes
        import msvcrt

        handle = msvcrt.get_osfhandle(stream.fileno())  # type: ignore[attr-defined]
        return bool(ctypes.windll.kernel32.SetConsoleMode(handle, mode | 0x0004))  # type: ignore[attr-defined]
    except Exception:
        return False


def is_terminal(stream: TextIO | None) -> bool:
    """A person is at the other end. On Windows the NUL device also answers
    isatty() with True, so a console is asked for its mode as well."""
    try:
        if stream is None or not stream.isatty():
            return False
    except (AttributeError, ValueError):  # no isatty, or closed
        return False
    return sys.platform != "win32" or _windows_console_mode(stream) is not None


def supports_color(stream: TextIO) -> bool:
    if os.environ.get("NO_COLOR"):
        return False
    if os.environ.get("FORCE_COLOR"):
        return True
    if not is_terminal(stream) or os.environ.get("TERM") == "dumb":
        return False
    if sys.platform == "win32":
        return _enable_windows_vt(stream)
    return True


def is_interactive() -> bool:
    return is_terminal(sys.stdin)


def text_width(text: str) -> int:
    width = 0
    for char in text:
        if unicodedata.combining(char) or char in "\u200b\u200d\ufe0e\ufe0f":
            continue
        width += 2 if unicodedata.east_asian_width(char) in ("W", "F") else 1
    return width


def fit(text: str, width: int) -> str:
    if text_width(text) <= width:
        return text
    out, used = [], 0
    for char in text:
        size = text_width(char)
        if used + size > width - 1:
            break
        out.append(char)
        used += size
    return "".join(out) + "…"


def pad(text: str, width: int, align: str = "<") -> str:
    gap = " " * max(0, width - text_width(text))
    return gap + text if align == ">" else text + gap


class Console:
    def __init__(
        self,
        *,
        quiet: bool = False,
        color: bool | None = None,
        tr: Translator | None = None,
        out: TextIO | None = None,
        err: TextIO | None = None,
    ) -> None:
        self.out = out or sys.stdout
        self.err = err or sys.stderr
        self.quiet = quiet
        self.color = supports_color(self.out) if color is None else color
        self.tr = tr
        self.lock = threading.RLock()
        self.active: Progress | None = None

    # ------------------------------------------------------------------ styling

    def style(self, text: str, code: str) -> str:
        return f"\x1b[{code}m{text}\x1b[0m" if self.color and text else text

    def bold(self, text: str) -> str:
        return self.style(text, "1")

    def dim(self, text: str) -> str:
        return self.style(text, "2")

    def green(self, text: str) -> str:
        return self.style(text, "32")

    def yellow(self, text: str) -> str:
        return self.style(text, "33")

    def red(self, text: str) -> str:
        return self.style(text, "31")

    def cyan(self, text: str) -> str:
        return self.style(text, "36")

    # ------------------------------------------------------------------ output

    def _write(self, stream: TextIO, text: str) -> None:
        with self.lock:
            active = self.active
            if active is not None:
                active.clear()
            stream.write(text + "\n")
            stream.flush()
            if active is not None:
                active.redraw()

    def print(self, text: str = "", *, force: bool = False) -> None:
        if force or not self.quiet:
            self._write(self.out, text)

    def heading(self, text: str) -> None:
        self.print(self.bold(text))

    def ok(self, text: str) -> None:
        self.print(self.green("√ ") + text)

    def info(self, text: str) -> None:
        self.print(self.cyan("• ") + text)

    def warn(self, text: str) -> None:
        if not self.quiet:
            self._write(self.err, self.yellow("! ") + text)

    def error(self, text: str) -> None:
        self._write(self.err, self.red("× ") + text)

    def progress(self, label: str, total: int) -> Progress:
        return Progress(self, label, total)

    def table(self, headers: Sequence[str], rows: Sequence[Sequence[str]], align: str = "") -> None:
        if self.quiet:
            return
        count = len(headers)
        align = align.ljust(count, "<")
        widths = [text_width(h) for h in headers]
        for row in rows:
            for i, cell in enumerate(row):
                widths[i] = max(widths[i], text_width(cell))
        # Shrink the widest column until the table fits the terminal.
        room = shutil.get_terminal_size((100, 24)).columns - 2 * (count - 1) - 1
        while sum(widths) > room and max(widths) > 12:
            widths[widths.index(max(widths))] -= 1

        def line(cells: Sequence[str]) -> str:
            return "  ".join(
                pad(fit(c, widths[i]), widths[i], align[i]) for i, c in enumerate(cells)
            )

        self.print(self.bold(line(headers)))
        for row in rows:
            self.print(line(row))

    # ------------------------------------------------------------------ input

    def ask(self, prompt: str, default: str = "") -> str:
        suffix = f" [{default}]" if default else ""
        try:
            answer = input(f"{prompt}{suffix}: ").strip()
        except EOFError:
            answer = ""
        return answer or default

    def ask_secret(self, prompt: str) -> str:
        try:
            return getpass.getpass(f"{prompt}: ").strip()
        except EOFError:
            return ""

    def confirm(self, prompt: str, *, default: bool = False) -> bool:
        tr = self.tr
        hint = tr.t("cli.confirm_hint_yes" if default else "cli.confirm_hint_no") if tr else ""
        yes = tr.raw("cli.yes_words") if tr else ["y", "yes"]
        no = tr.raw("cli.no_words") if tr else ["n", "no"]
        while True:
            try:
                answer = input(f"{prompt} {hint} ").strip().casefold()
            except EOFError:
                return default
            if not answer:
                return default
            if answer in yes:
                return True
            if answer in no:
                return False


class Progress:
    """A single self-updating line on a terminal; one summary line otherwise."""

    def __init__(self, console: Console, label: str, total: int) -> None:
        self.console = console
        self.label = label
        self.total = max(0, total)
        self.done = 0
        self.live = is_terminal(console.out) and not console.quiet
        self._drawn = 0
        self._last = 0.0
        if self.live:
            with console.lock:
                console.active = self
                self.redraw()

    def advance(self, step: int = 1) -> None:
        with self.console.lock:
            self.done += step
            now = time.monotonic()
            if self.live and (now - self._last > 0.08 or self.done >= self.total):
                self._last = now
                self.redraw()

    def _text(self) -> str:
        columns = shutil.get_terminal_size((80, 24)).columns
        fraction = self.done / self.total if self.total else 1.0
        bar_width = max(10, min(28, columns - 46))
        filled = int(bar_width * min(1.0, fraction))
        bar = "█" * filled + "░" * (bar_width - filled)
        return fit(f"  {self.label}  {bar}  {self.done}/{self.total}", columns - 1)

    def redraw(self) -> None:
        text = self._text()
        width = text_width(text)
        self.console.out.write("\r" + text + " " * max(0, self._drawn - width))
        self.console.out.flush()
        self._drawn = width

    def clear(self) -> None:
        if self._drawn:
            self.console.out.write("\r" + " " * self._drawn + "\r")
            self.console.out.flush()
            self._drawn = 0

    def finish(self, summary: str = "") -> None:
        console = self.console
        with console.lock:
            if self.live:
                self.clear()
                console.active = None
        tail = summary or f"{self.done}/{self.total}"
        console.print(f"  {pad(self.label, 22)} {tail}")
