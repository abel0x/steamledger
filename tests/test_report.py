# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 abel0x <https://github.com/abel0x>
"""The HTML reports treat everything from Steam as untrusted text, and images
map to stable local paths."""

import tempfile
import unittest
from pathlib import Path

from steamledger import report
from steamledger.i18n import Translator
from steamledger.media import local_path
from steamledger.views import summary_line
from tests.helpers import game, snapshot

HOSTILE = '<script>alert("x")</script>'


class ReportTest(unittest.TestCase):
    def render(self, data: dict) -> str:
        with tempfile.TemporaryDirectory() as tmp:
            return report.render_snapshot_page(
                data, None, Translator("en"), depth=2, database=Path(tmp)
            )

    def test_names_from_steam_are_escaped(self) -> None:
        page = self.render(
            snapshot(
                "2026-10-01_10-00-00",
                "2026-10-01T07:00:00Z",
                games=[game(10, HOSTILE, 60)],
                friends=[
                    {"steamid": "1", "name": HOSTILE, "profile_url": "javascript:alert(1)"},
                    {
                        "steamid": "2",
                        "name": "ok",
                        "profile_url": "https://steamcommunity.com/id/ok/",
                    },
                ],
                profile={"personaname": HOSTILE, "profile_url": "javascript:alert(2)"},
            )
        )
        self.assertNotIn("<script>alert", page)
        self.assertIn("&lt;script&gt;", page)
        self.assertNotIn('href="javascript:', page)  # shown as text, never a link
        self.assertIn('href="https://steamcommunity.com/id/ok/"', page)

    def test_missing_level_is_a_dash(self) -> None:
        page = self.render(
            snapshot("2026-10-01_10-00-00", "2026-10-01T07:00:00Z", profile={"level": None})
        )
        self.assertNotIn("None", page)

    def test_link_helper(self) -> None:
        self.assertEqual(
            report.link("https://a.test/?x=1&y=2", "<b>"),
            '<a href="https://a.test/?x=1&amp;y=2">&lt;b&gt;</a>',
        )
        self.assertEqual(report.link("data:text/html,hi", "text"), "text")
        self.assertEqual(report.link(None, "text"), "text")

    def test_empty_database_index(self) -> None:
        page = report.render_database_index([], [], Translator("tr"))
        self.assertIn('lang="tr"', page)

    def test_terminal_summary_matches_the_html_chips(self) -> None:
        tr = Translator("en")
        changes = {
            "summary": {"total": 3, "playtime": 90, "achievements": 2, "friends_added": 1},
            "level": {"from": 1, "to": 2},
        }
        self.assertEqual(summary_line(tr, changes), ", ".join(report.changes_chips(changes, tr)))
        self.assertEqual(summary_line(tr, None), tr.t("diff.none"))
        self.assertEqual(summary_line(tr, {"summary": {"total": 4}}), tr.t("diff.minor", count=4))


class MediaPathTest(unittest.TestCase):
    def test_known_cdn_layouts(self) -> None:
        for url, path in (
            ("https://avatars.steamstatic.com/abc_full.jpg", "media/avatars/abc_full.jpg"),
            (
                "https://cdn.akamai.steamstatic.com/steamcommunity/public/images/apps/10/ab.jpg",
                "media/apps/10/ab.jpg",
            ),
            (
                "https://shared.akamai.steamstatic.com/community_assets/images/apps/10/ab.jpg",
                "media/apps/10/ab.jpg",
            ),
            (
                "https://shared.akamai.steamstatic.com/store_item_assets/steam/apps/10/header.jpg?t=123",
                "media/store/10/header_123.jpg",
            ),
            (
                "https://cdn.akamai.steamstatic.com/steamcommunity/public/images/items/730/f.png",
                "media/items/730/f.png",
            ),
            ("https://x.test/pic.JPEG", None),
        ):
            with self.subTest(url=url):
                found = local_path(url)
                if path is None:
                    self.assertTrue(
                        found and found.startswith("media/other/") and found.endswith(".jpg")
                    )
                else:
                    self.assertEqual(found, path)

    def test_not_images_or_not_web(self) -> None:
        for url in (
            None,
            "",
            "https://x.test/page.html",
            "file:///etc/passwd.jpg",
            "https://x.test/",
        ):
            with self.subTest(url=url):
                self.assertIsNone(local_path(url))

    def test_paths_cannot_escape_the_media_folder(self) -> None:
        found = local_path("https://cdn.test/public/images/apps/10/..%2F..%2Fevil.jpg")
        self.assertTrue(found.startswith("media/apps/10/"))
        self.assertNotIn("..", found)


if __name__ == "__main__":
    unittest.main()
