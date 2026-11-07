import json
import io
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock
from contextlib import redirect_stdout

PLUGIN = Path(__file__).resolve().parents[1]
STATUSLINE = PLUGIN / "statusline.py"
FETCH = PLUGIN / "fetch.py"
sys.path.insert(0, str(PLUGIN))
import fetch as live_fetch


class UsageSnapshotTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.home = Path(self.temp.name)
        self.env = os.environ.copy()
        self.env["HOME"] = str(self.home)

    def tearDown(self):
        self.temp.cleanup()

    def run_statusline(self, payload):
        return subprocess.run(
            [sys.executable, str(STATUSLINE)], input=payload, text=True,
            capture_output=True, env=self.env, check=False,
        )

    def test_persists_only_valid_rates_with_private_permissions(self):
        result = self.run_statusline(json.dumps({"rate_limits": {
            "five_hour": {"used_percentage": 27.5, "resets_at": 1900000000},
            "seven_day": {"used_percentage": 61, "resets_at": 1900100000},
        }}))
        self.assertEqual(result.returncode, 0)
        self.assertIn("5h: 27.5%", result.stdout)
        cache = self.home / ".local/state/claude-subscription/usage.json"
        data = json.loads(cache.read_text())
        self.assertEqual(data["five_hour"], {"used_percentage": 27.5, "resets_at": 1900000000})
        self.assertEqual(data["seven_day"]["used_percentage"], 61)
        self.assertEqual(stat.S_IMODE(cache.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(cache.parent.stat().st_mode), 0o700)

    def test_ignores_missing_or_invalid_rates(self):
        self.run_statusline('{"model":{"display_name":"Claude"}}')
        cache = self.home / ".local/state/claude-subscription/usage.json"
        self.assertFalse(cache.exists())
        self.run_statusline(json.dumps({"rate_limits": {
            "five_hour": {"used_percentage": "nan", "resets_at": 9999999999}
        }}))
        self.assertFalse(cache.exists())

    def test_fetch_reads_cache_and_handles_missing_snapshot(self):
        cache = self.home / "test-usage.json"
        result = subprocess.run(
            [sys.executable, str(FETCH)], text=True, capture_output=True,
            env={**self.env, "CLAUDE_SUBSCRIPTION_CACHE": str(cache)}, check=False,
        )
        self.assertIn("error", json.loads(result.stdout))
        cache.write_text(json.dumps({"updated_at": 1900000000,
                                     "five_hour": {"used_percentage": 27, "resets_at": 1900000100}}))
        cache.chmod(0o600)
        result = subprocess.run(
            [sys.executable, str(FETCH)], text=True, capture_output=True,
            env={**self.env, "CLAUDE_SUBSCRIPTION_CACHE": str(cache)}, check=False,
        )
        data = json.loads(result.stdout)
        self.assertEqual(data["five_hour"]["used_percentage"], 27)
        self.assertEqual(data["plan"], "Claude subscription")
        self.assertTrue(data["stale"])

    def test_api_payload_is_normalized_and_cache_is_private(self):
        payload = {
            "five_hour": {"utilization": 37.5, "resets_at": "2026-11-08T12:30:00Z"},
            "seven_day": {"utilization": 62, "resets_at": "2026-11-12T00:00:00+00:00"},
            "seven_day_opus": None,
            "extra_usage": {"is_enabled": True, "used_credits": 99},
        }
        snapshot: dict = live_fetch.normalize_usage(payload)
        self.assertEqual(snapshot["five_hour"]["used_percentage"], 37.5)
        self.assertEqual(snapshot["seven_day"]["used_percentage"], 62)
        self.assertNotIn("extra_usage", snapshot)
        cache = self.home / "usage.json"
        with mock.patch.dict(os.environ, {"CLAUDE_SUBSCRIPTION_CACHE": str(cache)}):
            live_fetch.save_cache(snapshot)
            saved = live_fetch.read_cache()
        self.assertEqual(saved, snapshot)
        self.assertEqual(stat.S_IMODE(cache.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(cache.parent.stat().st_mode), 0o700)

    def test_api_request_uses_fixed_anthropic_endpoint_and_expected_headers(self):
        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self, _limit):
                return b'{"five_hour":{"utilization":12,"resets_at":"2026-11-08T12:00:00Z"}}'

        captured = {}

        def fake_urlopen(request, timeout):
            captured["url"] = request.full_url
            captured["headers"] = request.header_items()
            captured["timeout"] = timeout
            return FakeResponse()

        with mock.patch.object(live_fetch, "open_request", side_effect=fake_urlopen), \
                mock.patch.object(live_fetch, "claude_user_agent", return_value="claude-code/test"):
            data = live_fetch.request_usage("test-token")
        headers = {key.lower(): value for key, value in captured["headers"]}
        self.assertEqual(captured["url"], "https://api.anthropic.com/api/oauth/usage")
        self.assertEqual(headers["authorization"], "Bearer test-token")
        self.assertEqual(headers["anthropic-beta"], "oauth-2025-04-20")
        self.assertEqual(headers["user-agent"], "claude-code/test")
        self.assertEqual(headers["cache-control"], "no-cache")
        self.assertEqual(captured["timeout"], live_fetch.TIMEOUT_SECONDS)
        self.assertEqual(data["five_hour"]["utilization"], 12)

    def test_main_fetches_and_persists_fresh_api_snapshot(self):
        cache = self.home / "state/usage.json"
        payload = {
            "five_hour": {"utilization": 18.5, "resets_at": "2026-11-08T12:00:00Z"},
            "seven_day": {"utilization": 29, "resets_at": "2026-11-12T00:00:00Z"},
        }
        output = io.StringIO()
        with mock.patch.dict(os.environ, {"CLAUDE_SUBSCRIPTION_CACHE": str(cache)}), \
                mock.patch.object(live_fetch, "read_credentials", return_value=({"claudeAiOauth": {}}, "dummy-token")), \
                mock.patch.object(live_fetch, "request_usage", return_value=payload), \
                redirect_stdout(output):
            live_fetch.main()
        result = json.loads(output.getvalue())
        self.assertFalse(result["stale"])
        self.assertEqual(result["five_hour"]["used_percentage"], 18.5)
        self.assertEqual(json.loads(cache.read_text())["seven_day"]["used_percentage"], 29)
        self.assertEqual(stat.S_IMODE(cache.stat().st_mode), 0o600)

    def test_rate_limit_retry_after_is_parsed_and_cooldown_is_private(self):
        cache = self.home / "state/usage.json"
        with mock.patch.dict(os.environ, {"CLAUDE_SUBSCRIPTION_CACHE": str(cache)}):
            live_fetch.write_cooldown(900)
            cooldown = live_fetch.read_cooldown()
        assert cooldown is not None
        self.assertGreaterEqual(cooldown["retry_after_at"], int(__import__("time").time()) + 899)
        self.assertEqual(cooldown["consecutive_429"], 1)
        self.assertEqual(stat.S_IMODE(cache.with_name("usage-cooldown.json").stat().st_mode), 0o600)
        self.assertEqual(live_fetch.parse_retry_after("120"), 120)
        self.assertEqual(live_fetch.parse_retry_after("bogus"), None)

    def test_cached_mode_never_touches_network_and_flags_old_snapshots(self):
        cache = self.home / "state/usage.json"
        cache.parent.mkdir()
        now = int(__import__("time").time())
        env = {**self.env, "CLAUDE_SUBSCRIPTION_CACHE": str(cache)}
        with mock.patch.object(live_fetch, "request_usage", side_effect=AssertionError("network")):
            result = subprocess.run([sys.executable, str(FETCH), "--cached"], text=True,
                                    capture_output=True, env=env, check=False)
            self.assertIn("error", json.loads(result.stdout))
        for age, stale in ((60, False), (live_fetch.STALE_AFTER + 60, True)):
            cache.write_text(json.dumps({"updated_at": now - age,
                                         "five_hour": {"used_percentage": 12, "resets_at": now + 600}}))
            cache.chmod(0o600)
            result = subprocess.run([sys.executable, str(FETCH), "--cached"], text=True,
                                    capture_output=True, env=env, check=False)
            data = json.loads(result.stdout)
            self.assertEqual(data["five_hour"]["used_percentage"], 12)
            self.assertEqual(data["stale"], stale)

    def test_recent_check_returns_fresh_cache_without_request(self):
        cache = self.home / "state/usage.json"
        creds = self.home / "creds.json"
        creds.write_text(json.dumps({"claudeAiOauth": {"accessToken": "t", "subscriptionType": "max"}}))
        creds.chmod(0o600)
        now = int(__import__("time").time())
        env = {"CLAUDE_SUBSCRIPTION_CACHE": str(cache), "CLAUDE_SUBSCRIPTION_CREDENTIALS": str(creds)}
        with mock.patch.dict(os.environ, env):
            live_fetch.save_cache({"updated_at": now - 30, "seven_day": {"used_percentage": 40, "resets_at": now + 999}})
            live_fetch.mark_request_attempt()
            out = io.StringIO()
            with mock.patch.object(live_fetch, "request_usage", side_effect=AssertionError("network")), redirect_stdout(out):
                live_fetch.main()
        data = json.loads(out.getvalue())
        self.assertFalse(data["stale"])
        self.assertEqual(data["plan"], "Max")
        self.assertEqual(data["seven_day"]["used_percentage"], 40)


if __name__ == "__main__":
    unittest.main()
