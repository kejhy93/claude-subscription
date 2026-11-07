import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

PLUGIN = Path(__file__).resolve().parents[1]
STATUSLINE = PLUGIN / "statusline.py"
FETCH = PLUGIN / "fetch.py"


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
        self.assertEqual(json.loads(result.stdout)["error"].startswith("No usage snapshot"), True)
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


if __name__ == "__main__":
    unittest.main()
