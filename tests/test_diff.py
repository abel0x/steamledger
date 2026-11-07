# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 abel0x <https://github.com/abel0x>
"""Rules of the comparison that the demo account does not happen to exercise."""

import unittest

from steamledger.diff import compare
from tests.helpers import game, snapshot, unlocked

A, B = "2026-10-01_10-00-00", "2026-10-02_10-00-00"
WHEN_A, WHEN_B = "2026-10-01T07:00:00Z", "2026-10-02T07:00:00Z"


def entry(name: str, total: int, *apinames: str) -> dict:
    return {"name": name, "total": total, "unlocked": [unlocked(a) for a in apinames]}


class CompareTest(unittest.TestCase):
    def test_nothing_changed(self) -> None:
        same = snapshot(A, WHEN_A, games=[game(10, "Ten", 60)])
        result = compare(same, snapshot(B, WHEN_B, games=[game(10, "Ten", 60)]))
        self.assertEqual(result["summary"]["total"], 0)
        self.assertEqual(result["unavailable"], [])

    def test_private_section_is_not_reported_as_removed(self) -> None:
        before = snapshot(A, WHEN_A, games=[game(10, "Ten", 60)])
        after = snapshot(B, WHEN_B, sections={"games": {"status": "private"}})
        result = compare(before, after)
        self.assertEqual(result["games_removed"], [])
        self.assertIn("games", result["unavailable"])
        self.assertIn("achievements", result["unavailable"])

    def test_games_playtime_and_order(self) -> None:
        before = snapshot(A, WHEN_A, games=[game(10, "Ten", 60), game(20, "Twenty", 0)])
        after = snapshot(
            B,
            WHEN_B,
            games=[game(10, "Ten", 90), game(20, "Twenty", 120), game(30, "Thirty", 15)],
        )
        result = compare(before, after)
        self.assertEqual([r["appid"] for r in result["playtime"]], [20, 10])
        self.assertEqual(result["games_added"], [{"appid": 30, "name": "Thirty", "playtime": 15}])
        self.assertEqual(result["summary"]["playtime"], 120 + 30 + 15)
        self.assertEqual(result["summary"]["games_played"], 2)

    def test_achievements_completion_and_hidden_games(self) -> None:
        games = [game(10, "Ten", 60), game(20, "Twenty", 60)]
        before = snapshot(
            A,
            WHEN_A,
            games=games,
            achievements={"10": entry("Ten", 2, "a"), "20": entry("Twenty", 3, "x")},
        )
        after = snapshot(
            B,
            WHEN_B,
            games=games,
            achievements={"10": entry("Ten", 2, "a", "b")},
            sections={"achievements": {"status": "ok", "hidden": [20]}},
        )
        result = compare(before, after)
        self.assertEqual([i["apiname"] for i in result["achievements"][0]["items"]], ["b"])
        self.assertEqual(result["completed"], [{"appid": 10, "name": "Ten"}])
        # Game 20 hid its achievements in the newer snapshot: not "lost".
        self.assertEqual(result["achievements_lost"], [])

    def test_friends_profile_level_and_bans(self) -> None:
        friend = {"steamid": "1", "name": "old name", "avatar": None}
        before = snapshot(
            A,
            WHEN_A,
            friends=[friend, {"steamid": "2", "name": "gone"}],
            profile={"level": 5, "bans": {"vac_bans": 0, "game_bans": 0}, "country": "TR"},
        )
        after = snapshot(
            B,
            WHEN_B,
            friends=[friend | {"name": "new name"}, {"steamid": "3", "name": "new"}],
            profile={"level": 7, "bans": {"vac_bans": 1, "game_bans": 0}, "country": "DE"},
        )
        result = compare(before, after)
        self.assertEqual(
            result["friends_renamed"], [{"steamid": "1", "from": "old name", "to": "new name"}]
        )
        self.assertEqual([f["steamid"] for f in result["friends_added"]], ["3"])
        self.assertEqual([f["steamid"] for f in result["friends_removed"]], ["2"])
        self.assertEqual(result["level"], {"from": 5, "to": 7})
        self.assertEqual(result["summary"]["level"], 2)
        self.assertEqual(result["profile"], [{"field": "country", "from": "TR", "to": "DE"}])
        self.assertEqual(result["bans"], [{"field": "vac_bans", "from": 0, "to": 1}])


if __name__ == "__main__":
    unittest.main()
