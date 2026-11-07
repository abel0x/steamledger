# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 abel0x <https://github.com/abel0x>
import unittest

from steamledger import steamid

ID64 = "76561197960287930"  # account id 22202


class ParseTest(unittest.TestCase):
    def test_every_spelling_of_one_account(self) -> None:
        for text in (
            ID64,
            f"  {ID64}  ",
            "22202",
            "STEAM_0:0:11101",
            "STEAM_1:0:11101",
            "[U:1:22202]",
            "U:1:22202",
            f"https://steamcommunity.com/profiles/{ID64}",
            f"steamcommunity.com/profiles/{ID64}/",
        ):
            with self.subTest(text=text):
                self.assertEqual(steamid.parse(text), steamid.Parsed("steamid64", ID64))

    def test_custom_urls(self) -> None:
        for text in ("gabelogannewell", "https://steamcommunity.com/id/gabelogannewell/"):
            with self.subTest(text=text):
                self.assertEqual(steamid.parse(text), steamid.Parsed("vanity", "gabelogannewell"))

    def test_rejects(self) -> None:
        for text in (
            "",
            "   ",
            "0",
            "x",
            "a b",
            "https://steamcommunity.com/profiles/123",
            "[U:1:0]",
            "STEAM_0:0:0",
            "12345678901",  # too long for a friend code, too short for a SteamID64
            "4294967296",  # past the last account id
        ):
            with self.subTest(text=text), self.assertRaises(steamid.SteamIdError):
                steamid.parse(text)

    def test_steamid64_bounds(self) -> None:
        self.assertTrue(steamid.is_steamid64(ID64))
        self.assertFalse(steamid.is_steamid64(steamid.BASE))
        self.assertFalse(steamid.is_steamid64(steamid.BASE + steamid.ACCOUNT_LIMIT))
        self.assertFalse(steamid.is_steamid64("abc"))

    def test_custom_url_of_a_profile(self) -> None:
        self.assertEqual(steamid.custom_url("https://steamcommunity.com/id/gaben/"), "gaben")
        self.assertIsNone(steamid.custom_url(f"https://steamcommunity.com/profiles/{ID64}/"))
        self.assertIsNone(steamid.custom_url(None))

    def test_conversions(self) -> None:
        self.assertEqual(steamid.account_id(ID64), 22202)
        self.assertEqual(steamid.steam2(ID64), "STEAM_1:0:11101")
        self.assertEqual(steamid.steam3(ID64), "[U:1:22202]")
        self.assertEqual(steamid.group64(1), str(steamid.GROUP_BASE + 1))
        self.assertEqual(steamid.group64(steamid.GROUP_BASE + 1), str(steamid.GROUP_BASE + 1))


if __name__ == "__main__":
    unittest.main()
