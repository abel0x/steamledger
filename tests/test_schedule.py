# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 abel0x <https://github.com/abel0x>
"""The scheduler definitions, checked as text: installing them would change
the machine running the tests."""

import datetime as dt
import shlex
import unittest
import xml.etree.ElementTree as ElementTree
from pathlib import PurePosixPath, PureWindowsPath

from steamledger import schedule
from steamledger.paths import Paths

# Pure paths: the same text on every OS the tests run on.
ROOT = Paths(PurePosixPath("/home/me/50% off/it's steam"))  # type: ignore[arg-type]
PYTHON = "/usr/bin/python3"


class PlanTest(unittest.TestCase):
    def test_times(self) -> None:
        self.assertEqual(schedule.Plan.parse("21:00").label, "21:00")
        self.assertEqual(schedule.Plan.parse(" 7:05 ").label, "07:05")
        for bad in ("24:00", "12:60", "noon", "", "7"):
            with self.subTest(bad=bad), self.assertRaises(schedule.ScheduleError):
                schedule.Plan.parse(bad)


class DefinitionTest(unittest.TestCase):
    def test_cron_line_survives_quotes_and_percent_signs(self) -> None:
        line = schedule.cron_line(ROOT, schedule.Plan(9, 30, weekly=True), PYTHON)
        self.assertTrue(line.startswith("30 9 * * 0 cd "))
        self.assertTrue(line.endswith(f"# {schedule.TASK_NAME}"))
        # cron turns a bare % into a newline; every % must be escaped.
        self.assertNotRegex(line, r"(?<!\\)%")
        # What cron hands to /bin/sh, once it drops the backslashes before %.
        command = line.split(" ", 5)[5].rsplit(" # ", 1)[0].replace("\\%", "%")
        words = shlex.split(command)
        self.assertEqual(words[:3], ["cd", str(ROOT.root), "&&"])
        self.assertIn(str(ROOT.database / "collect.log"), words)

    def test_systemd_units(self) -> None:
        units = schedule.systemd_units(ROOT, schedule.Plan(21, 0), PYTHON)
        service = units[f"{schedule.TASK_NAME}.service"]
        timer = units[f"{schedule.TASK_NAME}.timer"]
        self.assertIn("OnCalendar=*-*-* 21:00:00", timer)
        self.assertIn("Persistent=true", timer)
        self.assertIn("WorkingDirectory=/home/me/50%% off/it's steam", service)
        self.assertIn('ExecStart="/usr/bin/python3" "-m" "steamledger" "--root"', service)
        weekly = schedule.systemd_units(ROOT, schedule.Plan(21, 0, weekly=True), PYTHON)
        self.assertIn("OnCalendar=Sun *-*-* 21:00:00", weekly[f"{schedule.TASK_NAME}.timer"])

    def test_windows_task_is_valid_xml_starting_next_time(self) -> None:
        root = Paths(PureWindowsPath("C:/Users/Me/Steam & Co"))  # type: ignore[arg-type]
        now = dt.datetime(2026, 10, 30, 22, 0)
        text = schedule.windows_task_xml(root, schedule.Plan(21, 0), "C:/Python/pythonw.exe", now)
        task = ElementTree.fromstring(text.split("\n", 1)[1])  # drop the UTF-16 declaration
        ns = {"t": "http://schemas.microsoft.com/windows/2004/02/mit/task"}
        self.assertEqual(task.findtext(".//t:StartBoundary", namespaces=ns), "2026-10-31T21:00:00")
        self.assertEqual(task.findtext(".//t:WorkingDirectory", namespaces=ns), str(root.root))
        self.assertIn("--quiet", task.findtext(".//t:Arguments", namespaces=ns))
        self.assertIsNotNone(task.find(".//t:ScheduleByDay", ns))
        weekly = schedule.windows_task_xml(root, schedule.Plan(23, 0, weekly=True), "py", now)
        self.assertIn("<Sunday />", weekly)
        self.assertIn("<StartBoundary>2026-10-30T23:00:00", weekly)


if __name__ == "__main__":
    unittest.main()
