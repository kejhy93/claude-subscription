#!/usr/bin/env python3
"""Persist Claude Code's documented statusline rate-limit snapshot locally."""
import json
import math
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fetch  # noqa: E402

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

    # Share fetch.py's lock and newer-wins rule so an in-flight API refresh
    # and this write cannot clobber each other.
    with fetch.state_lock():
        fetch.save_cache_if_newer(snapshot)

    print("Claude · " + " · ".join(shown))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        # Statusline scripts must not disrupt the Claude Code prompt.
        pass
