# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 abel0x <https://github.com/abel0x>
"""The HTTP policy (retries, cancellation, redaction) and how SteamApi turns
Steam's status codes into error kinds, without touching the network."""

import json
import threading
import unittest
from unittest import mock

from steamledger.api import SteamApi, SteamError
from steamledger.net import Cancelled, Http, NetworkError, Response, redact

KEY = "0123456789ABCDEF0123456789ABCDEF"


class Script:
    """A transport that plays back a list of responses (or errors) in order."""

    def __init__(self, *replies: object) -> None:
        self.replies = list(replies)
        self.urls: list[str] = []

    def fetch(self, url: str, timeout: float) -> Response:
        self.urls.append(url)
        reply = self.replies.pop(0) if len(self.replies) > 1 else self.replies[0]
        if isinstance(reply, Exception):
            raise reply
        return reply  # type: ignore[return-value]


def ok(data: object) -> Response:
    return Response(200, json.dumps(data).encode(), {"content-type": "application/json"})


def status(code: int, headers: dict[str, str] | None = None) -> Response:
    return Response(code, b"<html><body>nope</body></html>", headers or {})


def http(transport: Script, **options: object) -> Http:
    return Http(transport, per_second=0, secrets=[KEY], **options)  # type: ignore[arg-type]


@mock.patch.object(Http, "_backoff", staticmethod(lambda attempt: 0.0))
class HttpTest(unittest.TestCase):
    def test_retries_server_errors_then_succeeds(self) -> None:
        transport = Script(status(503), status(502), ok({"a": 1}))
        client = http(transport, retries=4)
        self.assertEqual(client.get("https://x.test/a").json(), {"a": 1})
        self.assertEqual(client.requests, 3)

    def test_gives_up_after_the_last_retry(self) -> None:
        transport = Script(status(503))
        response = http(transport, retries=2).get("https://x.test/a")
        self.assertEqual(response.status, 503)
        self.assertEqual(len(transport.urls), 3)

    def test_client_errors_are_not_retried(self) -> None:
        transport = Script(status(403), ok({}))
        self.assertEqual(http(transport).get("https://x.test/a").status, 403)
        self.assertEqual(len(transport.urls), 1)

    def test_rate_limit_pushes_every_thread_back(self) -> None:
        transport = Script(status(429, {"retry-after": "0"}), ok({}))
        client = http(transport)
        with mock.patch.object(client.limiter, "back_off") as back_off:
            client.get("https://x.test/a")
        back_off.assert_called_once()

    def test_network_errors_are_retried_and_reported_without_the_key(self) -> None:
        transport = Script(NetworkError("timed out"))
        with self.assertRaises(NetworkError) as caught:
            http(transport, retries=1).get("https://x.test/a", {"key": KEY, "x": 1})
        self.assertEqual(len(transport.urls), 2)
        self.assertNotIn(KEY, str(caught.exception))
        self.assertIn("key=***", str(caught.exception))

    def test_the_answered_url_is_redacted(self) -> None:
        response = http(Script(ok({}))).get("https://x.test/a", {"key": KEY})
        self.assertNotIn(KEY, response.url)

    def test_cancel_stops_before_the_next_request(self) -> None:
        cancel = threading.Event()
        cancel.set()
        transport = Script(ok({}))
        with self.assertRaises(Cancelled):
            http(transport, cancel=cancel).get("https://x.test/a")
        self.assertEqual(transport.urls, [])

    def test_parameters_are_encoded(self) -> None:
        transport = Script(ok({}))
        http(transport).get("https://x.test/a?z=1", {"flag": True, "skip": None, "n": 2})
        self.assertEqual(transport.urls, ["https://x.test/a?z=1&flag=true&n=2"])


class RedactTest(unittest.TestCase):
    def test_key_parameter_and_known_secrets(self) -> None:
        text = f"GET /x?key={KEY}&steamid=1 failed; header {KEY}"
        self.assertEqual(redact(text, [KEY]), "GET /x?key=***&steamid=1 failed; header ***")

    def test_short_secrets_are_left_alone(self) -> None:
        self.assertEqual(redact("abc", ["ab"]), "abc")


class ApiErrorTest(unittest.TestCase):
    def api(self, *replies: object) -> SteamApi:
        return SteamApi(http(Script(*replies), retries=0), KEY)

    def test_bad_key(self) -> None:
        with self.assertRaises(SteamError) as caught:
            self.api(status(403)).player_summaries(["76561197960287930"])
        self.assertEqual(caught.exception.kind, "forbidden")

    def test_private_friend_list(self) -> None:
        with self.assertRaises(SteamError) as caught:
            self.api(status(401)).friend_list("76561197960287930")
        self.assertEqual(caught.exception.kind, "private")

    def test_game_without_stats(self) -> None:
        self.assertIsNone(self.api(status(400)).player_achievements("1", 10))
        reply = ok({"playerstats": {"success": False, "error": "Requested app has no stats"}})
        self.assertIsNone(self.api(reply).player_achievements("1", 10))

    def test_game_that_hides_achievements(self) -> None:
        reply = ok({"playerstats": {"success": False, "error": "Profile is not public"}})
        with self.assertRaises(SteamError) as caught:
            self.api(reply).player_achievements("1", 10)
        self.assertEqual(caught.exception.kind, "private")

    def test_hidden_library(self) -> None:
        self.assertIsNone(self.api(ok({"response": {}})).owned_games("1"))
        self.assertEqual(self.api(ok({"response": {"game_count": 0}})).owned_games("1"), [])

    def test_garbage_body(self) -> None:
        with self.assertRaises(SteamError) as caught:
            self.api(Response(200, b"<html>maintenance</html>")).steam_level("1")
        self.assertEqual(caught.exception.kind, "bad_response")

    def test_vanity_and_groups(self) -> None:
        reply = ok({"response": {"success": 1, "steamid": "76561197960287930"}})
        self.assertEqual(self.api(reply).resolve_vanity("gaben"), "76561197960287930")
        self.assertIsNone(self.api(ok({"response": {"success": 42}})).resolve_vanity("nobody"))
        groups = ok({"response": {"success": True, "groups": [{"gid": "1"}, {"gid": "x"}]}})
        self.assertEqual(self.api(groups).user_groups("1"), ["103582791429521409"])


if __name__ == "__main__":
    unittest.main()
