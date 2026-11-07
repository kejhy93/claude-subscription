#!/usr/bin/env python3
"""Read the latest locally cached Claude Code subscription usage snapshot."""
import json
import math
import os
import stat
import time
from pathlib import Path

MAX_CACHE_BYTES = 4096


def cache_path():
    override = os.environ.get("CLAUDE_SUBSCRIPTION_CACHE", "").strip()
    return Path(override) if override else Path.home() / ".local/state/claude-subscription/usage.json"


def safe_percentage(value):
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if not math.isfinite(number) or number < 0 or number > 1000:
        return None
    return round(number, 2)


def safe_timestamp(value):
    if isinstance(value, bool):
        return None
    try:
        stamp = int(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if stamp < 0 or stamp > 4_102_444_800:
        return None
    return stamp


def subscription_type():
    path = Path.home() / ".claude/.credentials.json"
    try:
        if stat.S_IMODE(path.stat().st_mode) & 0o077:
            return "Claude subscription"
        if path.stat().st_size > 64 * 1024:
            return "Claude subscription"
        credentials = json.loads(path.read_text(encoding="utf-8"))
        oauth = credentials.get("claudeAiOauth", {}) if isinstance(credentials, dict) else {}
        value = oauth.get("subscriptionType", "") if isinstance(oauth, dict) else ""
        if isinstance(value, str) and value and len(value) <= 32 and value.replace("-", "").replace("_", "").isalnum():
            return value.replace("_", " ").replace("-", " ").title()
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        pass
    return "Claude subscription"


def main():
    path = cache_path()
    try:
        if stat.S_IMODE(path.stat().st_mode) & 0o077:
            raise ValueError("Usage snapshot permissions are too open")
        if path.stat().st_size > MAX_CACHE_BYTES:
            raise ValueError("Usage snapshot is unexpectedly large")
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        print(json.dumps({"error": "No usage snapshot yet. Open Claude Code and complete a response to populate it."}))
        return
    except (OSError, json.JSONDecodeError, UnicodeDecodeError, ValueError):
        print(json.dumps({"error": "Could not read the local Claude Code usage snapshot."}))
        return

    if not isinstance(data, dict):
        print(json.dumps({"error": "The local Claude Code usage snapshot is invalid."}))
        return

    result = {"plan": subscription_type(), "updated_at": safe_timestamp(data.get("updated_at"))}
    for key in ("five_hour", "seven_day"):
        row = data.get(key)
        if not isinstance(row, dict):
            continue
        used = safe_percentage(row.get("used_percentage"))
        if used is not None:
            result[key] = {"used_percentage": used, "resets_at": safe_timestamp(row.get("resets_at"))}
    if not any(key in result for key in ("five_hour", "seven_day")):
        result = {"error": "The snapshot contains no usable subscription limits."}
    print(json.dumps(result, separators=(",", ":")))


if __name__ == "__main__":
    main()
