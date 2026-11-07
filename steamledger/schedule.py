# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 abel0x <https://github.com/abel0x>
"""Run ``steamledger collect`` on a schedule, so the archive grows by itself.

Windows uses Task Scheduler (a task registered from an XML definition, which,
unlike the schtasks command line, can set the working folder and catch up on a
missed run). Linux uses a systemd user timer and falls back to cron where systemd
is not running; macOS uses cron. Scheduled runs write their output to
database/collect.log.
"""

from __future__ import annotations

import datetime as dt
import os
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from xml.sax.saxutils import escape

from .paths import Paths
from .util import KeyedError

TASK_NAME = "steamledger-collect"
_TIME = re.compile(r"^([01]?\d|2[0-3]):([0-5]\d)$")


class ScheduleError(KeyedError):
    pass


@dataclass(frozen=True)
class Plan:
    hour: int
    minute: int
    weekly: bool = False  # weekly runs happen on Sundays

    @classmethod
    def parse(cls, text: str, weekly: bool = False) -> Plan:
        match = _TIME.match(text.strip())
        if not match:
            raise ScheduleError("cli.schedule.bad_time", value=text)
        return cls(int(match.group(1)), int(match.group(2)), weekly)

    @property
    def label(self) -> str:
        return f"{self.hour:02d}:{self.minute:02d}"


def python_for_tasks() -> str:
    """pythonw.exe on Windows, so a scheduled run does not flash a console window."""
    exe = Path(sys.executable)
    if sys.platform == "win32":
        quiet = exe.with_name("pythonw.exe")
        if quiet.is_file():
            return str(quiet)
    return str(exe)


def collect_args(paths: Paths) -> list[str]:
    log = paths.database / "collect.log"
    return ["-m", "steamledger", "--root", str(paths.root), "--log", str(log), "collect", "--quiet"]


# --------------------------------------------------------------------------- Windows


def windows_task_xml(paths: Paths, plan: Plan, python: str, now: dt.datetime | None = None) -> str:
    now = now or dt.datetime.now()
    start = now.replace(hour=plan.hour, minute=plan.minute, second=0, microsecond=0)
    if start <= now:
        start += dt.timedelta(days=1)
    arguments = subprocess.list2cmdline(collect_args(paths))
    if plan.weekly:
        schedule = "<ScheduleByWeek><DaysOfWeek><Sunday /></DaysOfWeek><WeeksInterval>1</WeeksInterval></ScheduleByWeek>"
    else:
        schedule = "<ScheduleByDay><DaysInterval>1</DaysInterval></ScheduleByDay>"
    return f"""<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo>
    <Description>Collects Steam data into {escape(str(paths.database))} (steamledger)</Description>
  </RegistrationInfo>
  <Triggers>
    <CalendarTrigger>
      <StartBoundary>{start.strftime("%Y-%m-%dT%H:%M:%S")}</StartBoundary>
      <Enabled>true</Enabled>
      {schedule}
    </CalendarTrigger>
  </Triggers>
  <Principals>
    <Principal id="Author">
      <LogonType>InteractiveToken</LogonType>
      <RunLevel>LeastPrivilege</RunLevel>
    </Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <StartWhenAvailable>true</StartWhenAvailable>
    <RunOnlyIfNetworkAvailable>true</RunOnlyIfNetworkAvailable>
    <ExecutionTimeLimit>PT2H</ExecutionTimeLimit>
    <Enabled>true</Enabled>
  </Settings>
  <Actions Context="Author">
    <Exec>
      <Command>{escape(python)}</Command>
      <Arguments>{escape(arguments)}</Arguments>
      <WorkingDirectory>{escape(str(paths.root))}</WorkingDirectory>
    </Exec>
  </Actions>
</Task>
"""


def _run(args: list[str]) -> subprocess.CompletedProcess[str]:
    encoding = "oem" if sys.platform == "win32" else "utf-8"
    return subprocess.run(
        args, capture_output=True, text=True, encoding=encoding, errors="replace", check=False
    )


def _install_windows(paths: Paths, plan: Plan) -> str:
    xml = windows_task_xml(paths, plan, python_for_tasks())
    with tempfile.TemporaryDirectory() as tmp:
        definition = Path(tmp) / "task.xml"
        definition.write_text(xml, encoding="utf-16")
        result = _run(["schtasks", "/Create", "/TN", TASK_NAME, "/XML", str(definition), "/F"])
    if result.returncode != 0:
        raise ScheduleError("cli.schedule.failed", detail=(result.stderr or result.stdout).strip())
    return "windows"


def _remove_windows() -> bool:
    return _run(["schtasks", "/Delete", "/TN", TASK_NAME, "/F"]).returncode == 0


def _status_windows() -> str | None:
    result = _run(["schtasks", "/Query", "/TN", TASK_NAME, "/FO", "CSV", "/NH"])
    if result.returncode != 0:
        return None
    fields = [f.strip('"') for f in result.stdout.strip().split('","')]
    return " · ".join(fields[1:]) if len(fields) > 1 else result.stdout.strip()


# --------------------------------------------------------------------------- systemd


def systemd_dir() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "systemd" / "user"


def _unit_quote(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"').replace("%", "%%") + '"'


def systemd_units(paths: Paths, plan: Plan, python: str) -> dict[str, str]:
    exec_line = " ".join(_unit_quote(part) for part in [python, *collect_args(paths)])
    calendar = f"{'Sun ' if plan.weekly else ''}*-*-* {plan.label}:00"
    return {
        f"{TASK_NAME}.service": (
            "[Unit]\n"
            "Description=Collect Steam data with steamledger\n"
            "Wants=network-online.target\n"
            "After=network-online.target\n\n"
            "[Service]\n"
            "Type=oneshot\n"
            f"WorkingDirectory={str(paths.root).replace('%', '%%')}\n"
            f"ExecStart={exec_line}\n"
        ),
        f"{TASK_NAME}.timer": (
            "[Unit]\n"
            "Description=Run steamledger collect on a schedule\n\n"
            "[Timer]\n"
            f"OnCalendar={calendar}\n"
            "Persistent=true\n"
            "RandomizedDelaySec=300\n\n"
            "[Install]\n"
            "WantedBy=timers.target\n"
        ),
    }


def _systemd_available() -> bool:
    if not shutil.which("systemctl"):
        return False
    result = _run(["systemctl", "--user", "is-system-running"])
    return result.stdout.strip() in ("running", "degraded", "starting")


def _install_systemd(paths: Paths, plan: Plan) -> str:
    folder = systemd_dir()
    folder.mkdir(parents=True, exist_ok=True)
    for name, text in systemd_units(paths, plan, python_for_tasks()).items():
        (folder / name).write_text(text, encoding="utf-8")
    for args in (["daemon-reload"], ["enable", "--now", f"{TASK_NAME}.timer"]):
        result = _run(["systemctl", "--user", *args])
        if result.returncode != 0:
            raise ScheduleError(
                "cli.schedule.failed", detail=(result.stderr or result.stdout).strip()
            )
    return "systemd"


def _remove_systemd() -> bool:
    folder = systemd_dir()
    found = (folder / f"{TASK_NAME}.timer").exists()
    _run(["systemctl", "--user", "disable", "--now", f"{TASK_NAME}.timer"])
    for name in (f"{TASK_NAME}.timer", f"{TASK_NAME}.service"):
        (folder / name).unlink(missing_ok=True)
    _run(["systemctl", "--user", "daemon-reload"])
    return found


def _status_systemd() -> str | None:
    if not (systemd_dir() / f"{TASK_NAME}.timer").exists():
        return None
    result = _run(
        ["systemctl", "--user", "list-timers", f"{TASK_NAME}.timer", "--no-pager", "--no-legend"]
    )
    return re.sub(r"\s{2,}", " · ", result.stdout.strip()) or "installed"


# --------------------------------------------------------------------------- cron


def cron_line(paths: Paths, plan: Plan, python: str) -> str:
    def quote(value: str) -> str:
        # Shell quoting, then cron's own rule: an unescaped % ends the command.
        return ("'" + value.replace("'", "'\\''") + "'").replace("%", "\\%")

    weekday = "0" if plan.weekly else "*"
    command = " ".join(quote(p) for p in [python, *collect_args(paths)])
    return f"{plan.minute} {plan.hour} * * {weekday} cd {quote(str(paths.root))} && {command} # {TASK_NAME}"


def _crontab() -> list[str]:
    result = _run(["crontab", "-l"])
    return result.stdout.splitlines() if result.returncode == 0 else []


def _write_crontab(lines: list[str]) -> None:
    text = "\n".join(lines) + "\n"
    result = subprocess.run(
        ["crontab", "-"], input=text, capture_output=True, text=True, check=False
    )
    if result.returncode != 0:
        raise ScheduleError("cli.schedule.failed", detail=result.stderr.strip())


def _install_cron(paths: Paths, plan: Plan) -> str:
    if not shutil.which("crontab"):
        raise ScheduleError("cli.schedule.unsupported")
    lines = [line for line in _crontab() if not line.endswith(f"# {TASK_NAME}")]
    lines.append(cron_line(paths, plan, python_for_tasks()))
    _write_crontab(lines)
    return "cron"


def _remove_cron() -> bool:
    if not shutil.which("crontab"):
        return False
    lines = _crontab()
    kept = [line for line in lines if not line.endswith(f"# {TASK_NAME}")]
    if len(kept) != len(lines):
        _write_crontab(kept)
        return True
    return False


def _status_cron() -> str | None:
    if not shutil.which("crontab"):
        return None
    for line in _crontab():
        if line.endswith(f"# {TASK_NAME}"):
            return line
    return None


# --------------------------------------------------------------------------- public


def install(paths: Paths, plan: Plan) -> str:
    if sys.platform == "win32":
        return _install_windows(paths, plan)
    if sys.platform.startswith("linux") and _systemd_available():
        return _install_systemd(paths, plan)
    return _install_cron(paths, plan)


def remove() -> bool:
    if sys.platform == "win32":
        return _remove_windows()
    removed = False
    if sys.platform.startswith("linux") and shutil.which("systemctl"):
        removed = _remove_systemd()
    return _remove_cron() or removed


def status() -> str | None:
    if sys.platform == "win32":
        return _status_windows()
    if sys.platform.startswith("linux"):
        found = _status_systemd()
        if found:
            return found
    return _status_cron()
