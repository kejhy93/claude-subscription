#!/usr/bin/env python3
"""Persist Claude Code's documented statusline rate-limit snapshot locally."""
import json
import math
import os
import stat
import sys
import tempfile
import time
from pathlib import Path

MAX_INPUT = 16 * 1024
MAX_PERCENTAGE = 1000.0


def safe_number(value):
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if not math.isfinite(number) or number < 0 or number > MAX_PERCENTAGE:
        return None
    return round(number, 2)


def safe_timestamp(value):
    if isinstance(value, bool):
        return None
    try:
        stamp = int(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if stamp < 0 or stamp > 4_102_444_800:  # 2100-01-01 UTC
        return None
    return stamp


def cache_path():
    return Path.home() / ".local/state/claude-subscription/usage.json"


def main():
    raw = sys.stdin.buffer.read(MAX_INPUT + 1)
    if len(raw) > MAX_INPUT:
        return
    try:
        payload = json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return
    if not isinstance(payload, dict):
        return

    limits = payload.get("rate_limits")
    if not isinstance(limits, dict):
        return

    snapshot = {"updated_at": int(time.time())}
    shown = []
    for source, target, label in (("five_hour", "five_hour", "5h"), ("seven_day", "seven_day", "7d")):
        item = limits.get(source)
        if not isinstance(item, dict):
            continue
        used = safe_number(item.get("used_percentage"))
        reset = safe_timestamp(item.get("resets_at"))
        if used is None:
            continue
        snapshot[target] = {"used_percentage": used, "resets_at": reset}
        shown.append(f"{label}: {used:g}%")
    if not shown:
        return

    path = cache_path()
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    try:
        path.parent.chmod(0o700)
    except OSError:
        pass
    fd, temp_name = tempfile.mkstemp(prefix=".usage-", dir=path.parent)
    try:
        os.fchmod(fd, stat.S_IRUSR | stat.S_IWUSR)
        with os.fdopen(fd, "w", encoding="utf-8") as out:
            json.dump(snapshot, out, separators=(",", ":"))
            out.write("\n")
        os.replace(temp_name, path)
    finally:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass

    print("Claude · " + " · ".join(shown))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        # Statusline scripts must not disrupt the Claude Code prompt.
        pass
