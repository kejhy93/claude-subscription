#!/usr/bin/env python3
"""Fetch Claude subscription usage and persist a minimal local snapshot.

The OAuth usage endpoint is used by Claude Code itself but is not a public,
documented Anthropic API. Keep the request isolated here and store only the
aggregate percentages, reset times, and fetch timestamp.
"""
import datetime
import email.utils
import json
import math
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener

API_URL = "https://api.anthropic.com/api/oauth/usage"
API_BETA = "oauth-2025-04-20"
MAX_RESPONSE_BYTES = 64 * 1024
MAX_CACHE_BYTES = 4096
MAX_CREDENTIAL_BYTES = 64 * 1024
TIMEOUT_SECONDS = 10
MIN_REQUEST_INTERVAL = 300
# The background timer refreshes every 10 minutes; older snapshots are stale.
STALE_AFTER = 1500


class UsageError(RuntimeError):
    def __init__(self, message, retry_after=None):
        super().__init__(message)
        self.retry_after = retry_after


class NoRedirectHandler(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def open_request(request, timeout):
    return build_opener(NoRedirectHandler()).open(request, timeout=timeout)


def cache_path():
    override = os.environ.get("CLAUDE_SUBSCRIPTION_CACHE", "").strip()
    return Path(override) if override else Path.home() / ".local/state/claude-subscription/usage.json"


def cooldown_path():
    return cache_path().with_name("usage-cooldown.json")


def credentials_path():
    override = os.environ.get("CLAUDE_SUBSCRIPTION_CREDENTIALS", "").strip()
    if override:
        return Path(override)
    config_dir = os.environ.get("CLAUDE_CONFIG_DIR", "").strip()
    return (Path(config_dir).expanduser() if config_dir else Path.home() / ".claude") / ".credentials.json"


def safe_percentage(value):
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if not math.isfinite(number) or number < 0 or number > 100:
        return None
    return round(number, 2)


def safe_timestamp(value):
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        try:
            stamp = float(value)
        except (TypeError, ValueError, OverflowError):
            return None
        if not math.isfinite(stamp):
            return None
        if stamp > 100_000_000_000:
            stamp /= 1000
        stamp = int(stamp)
    elif isinstance(value, str) and len(value) <= 64:
        try:
            stamp = int(value)
        except ValueError:
            try:
                normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
                parsed = datetime.datetime.fromisoformat(normalized)
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=datetime.timezone.utc)
                stamp = int(parsed.timestamp())
            except (ValueError, OverflowError, OSError):
                return None
    else:
        return None
    if stamp < 0 or stamp > 4_102_444_800:
        return None
    return stamp


def subscription_type(credentials=None):
    try:
        oauth = (credentials or {}).get("claudeAiOauth", {})
        value = oauth.get("subscriptionType", "") if isinstance(oauth, dict) else ""
        if isinstance(value, str) and value and len(value) <= 32 and value.replace("-", "").replace("_", "").isalnum():
            return value.replace("_", " ").replace("-", " ").title()
    except (AttributeError, TypeError):
        pass
    return "Claude subscription"


def read_credentials():
    path = credentials_path()
    try:
        info = path.stat()
        if stat.S_IMODE(info.st_mode) & 0o077:
            raise ValueError("Credential file permissions are too open")
        if info.st_size > MAX_CREDENTIAL_BYTES:
            raise ValueError("Credential file is unexpectedly large")
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise RuntimeError("Claude Code OAuth credentials were not found. Sign in to Claude Code first.") from exc
    except (OSError, json.JSONDecodeError, UnicodeDecodeError, ValueError) as exc:
        raise RuntimeError("Could not safely read Claude Code OAuth credentials.") from exc

    oauth = data.get("claudeAiOauth", {}) if isinstance(data, dict) else {}
    token = oauth.get("accessToken") if isinstance(oauth, dict) else None
    if not isinstance(token, str) or not token or len(token) > 8192:
        raise RuntimeError("Claude Code OAuth credentials do not contain an access token.")
    scopes = oauth.get("scopes") if isinstance(oauth, dict) else None
    if isinstance(scopes, list) and scopes and "user:profile" not in scopes:
        raise RuntimeError("The saved Claude Code sign-in does not include usage access. Sign in again with Claude Code.")
    return data, token


def claude_user_agent():
    executable = shutil.which("claude")
    if executable:
        try:
            result = subprocess.run([executable, "--version"], capture_output=True, text=True, timeout=2, check=False)
            match = re.search(r"\b(\d+\.\d+\.\d+)\b", result.stdout[:256])
            if match:
                return "claude-code/" + match.group(1)
        except (OSError, subprocess.SubprocessError):
            pass
    return "claude-code/2.1.319"


def request_usage(token):
    request = Request(API_URL, headers={
        "Authorization": "Bearer " + token,
        "Accept": "application/json",
        "Content-Type": "application/json",
        "Cache-Control": "no-cache",
        "anthropic-beta": API_BETA,
        "User-Agent": claude_user_agent(),
    }, method="GET")
    try:
        with open_request(request, timeout=TIMEOUT_SECONDS) as response:
            raw = response.read(MAX_RESPONSE_BYTES + 1)
    except HTTPError as exc:
        if exc.code in (401, 403):
            raise UsageError("Claude sign-in expired or does not allow usage access. Open Claude Code and refresh your sign-in.") from None
        if exc.code == 429:
            retry_after = parse_retry_after(exc.headers.get("Retry-After") if exc.headers else None)
            raise UsageError("Claude usage API rate-limited this refresh. Wait before retrying.", retry_after) from None
        raise RuntimeError("Claude usage API returned HTTP " + str(exc.code) + ".") from None
    except (URLError, TimeoutError, OSError):
        raise RuntimeError("Could not reach the Claude usage API. The last saved snapshot is shown if available.") from None

    if len(raw) > MAX_RESPONSE_BYTES:
        raise RuntimeError("Claude usage API response was unexpectedly large.")
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise RuntimeError("Claude usage API returned invalid data.") from None
    if not isinstance(data, dict):
        raise RuntimeError("Claude usage API returned invalid data.")
    return data


def parse_retry_after(value):
    if not isinstance(value, str) or len(value) > 128:
        return None
    try:
        return max(0, int(value.strip()))
    except ValueError:
        try:
            parsed = email.utils.parsedate_to_datetime(value)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=datetime.timezone.utc)
            return max(0, int(parsed.timestamp() - time.time()))
        except (TypeError, ValueError, OverflowError):
            return None


def read_cooldown():
    path = cooldown_path()
    try:
        info = path.stat()
        if stat.S_IMODE(info.st_mode) & 0o077 or info.st_size > 1024:
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        until = safe_timestamp(data.get("retry_after_at")) if isinstance(data, dict) else None
        last_attempt = safe_timestamp(data.get("last_attempt_at")) if isinstance(data, dict) else None
        count = data.get("consecutive_429", 0) if isinstance(data, dict) else 0
        if isinstance(count, bool) or not isinstance(count, int) or count < 0 or count > 16:
            count = 0
        return {"retry_after_at": until, "last_attempt_at": last_attempt, "consecutive_429": count} if until or last_attempt else None
    except (OSError, json.JSONDecodeError, UnicodeDecodeError, ValueError):
        return None


def write_cooldown(retry_after=None):
    previous = read_cooldown() or {"consecutive_429": 0}
    count = min(16, previous["consecutive_429"] + 1)
    backoff = min(3600, 300 * (2 ** min(4, count - 1)))
    delay = max(300, backoff, min(3600, retry_after or 0))
    now = int(time.time())
    write_refresh_state({"last_attempt_at": now, "retry_after_at": now + delay, "consecutive_429": count})


def mark_request_attempt():
    previous = read_cooldown() or {}
    write_refresh_state({
        "last_attempt_at": int(time.time()),
        "retry_after_at": previous.get("retry_after_at"),
        "consecutive_429": previous.get("consecutive_429", 0),
    })


def write_refresh_state(state):
    path = cooldown_path()
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    try:
        path.parent.chmod(0o700)
    except OSError:
        pass
    fd, temp_name = tempfile.mkstemp(prefix=".cooldown-", dir=path.parent)
    try:
        os.fchmod(fd, stat.S_IRUSR | stat.S_IWUSR)
        with os.fdopen(fd, "w", encoding="utf-8") as out:
            json.dump(state, out, separators=(",", ":"))
            out.write("\n")
        os.replace(temp_name, path)
    finally:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass


def clear_cooldown():
    previous = read_cooldown()
    if previous and previous.get("last_attempt_at"):
        write_refresh_state({"last_attempt_at": previous["last_attempt_at"], "retry_after_at": None, "consecutive_429": 0})
    else:
        try:
            cooldown_path().unlink()
        except FileNotFoundError:
            pass


def normalize_usage(payload):
    snapshot = {"updated_at": int(time.time())}
    for source, target in (("five_hour", "five_hour"), ("seven_day", "seven_day")):
        item = payload.get(source)
        if not isinstance(item, dict):
            continue
        used = safe_percentage(item.get("utilization"))
        reset = safe_timestamp(item.get("resets_at"))
        if used is not None:
            snapshot[target] = {"used_percentage": used, "resets_at": reset}
    if not any(key in snapshot for key in ("five_hour", "seven_day")):
        raise RuntimeError("Claude usage API returned no usable subscription limits.")
    return snapshot


def save_cache(snapshot):
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


def read_cache():
    path = cache_path()
    try:
        info = path.stat()
        if stat.S_IMODE(info.st_mode) & 0o077:
            raise ValueError("Usage snapshot permissions are too open")
        if info.st_size > MAX_CACHE_BYTES:
            raise ValueError("Usage snapshot is unexpectedly large")
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, json.JSONDecodeError, UnicodeDecodeError, ValueError):
        return None
    if not isinstance(data, dict):
        return None

    result = {"updated_at": safe_timestamp(data.get("updated_at"))}
    for key in ("five_hour", "seven_day"):
        row = data.get(key)
        if not isinstance(row, dict):
            continue
        used = safe_percentage(row.get("used_percentage"))
        if used is not None:
            result[key] = {"used_percentage": used, "resets_at": safe_timestamp(row.get("resets_at"))}
    return result if any(key in result for key in ("five_hour", "seven_day")) else None


def read_plan():
    try:
        path = credentials_path()
        info = path.stat()
        if stat.S_IMODE(info.st_mode) & 0o077 or info.st_size > MAX_CREDENTIAL_BYTES:
            return subscription_type(None)
        return subscription_type(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError, ValueError):
        return subscription_type(None)


def is_stale(snapshot, now=None):
    stamp = snapshot.get("updated_at") if snapshot else None
    if not stamp:
        return True
    return (now or int(time.time())) - stamp > STALE_AFTER


def cached_result():
    """Return the stored snapshot without any network access."""
    cached = read_cache()
    if not cached:
        return {"error": "No Claude usage snapshot yet. The background refresh fills it within 10 minutes."}
    result = {"plan": read_plan(), **cached, "stale": is_stale(cached)}
    if result["stale"]:
        result["error"] = "Snapshot is older than " + str(STALE_AFTER // 60) + " min; the background refresh may not be running."
    return result


def main():
    if "--cached" in sys.argv[1:]:
        print(json.dumps(cached_result(), separators=(",", ":")))
        return
    credentials = None
    try:
        credentials, token = read_credentials()
        cooldown = read_cooldown()
        now = int(time.time())
        if cooldown and cooldown["retry_after_at"] and cooldown["retry_after_at"] > now:
            remaining = max(1, (cooldown["retry_after_at"] - now + 59) // 60)
            raise UsageError("Claude usage API is cooling down after rate limiting. Try again in about " + str(remaining) + " min.")
        if cooldown and cooldown["last_attempt_at"] and now - cooldown["last_attempt_at"] < MIN_REQUEST_INTERVAL:
            remaining = max(1, (MIN_REQUEST_INTERVAL - (now - cooldown["last_attempt_at"]) + 59) // 60)
            cached = read_cache()
            if cached and not is_stale(cached, now):
                print(json.dumps({"plan": subscription_type(credentials), **cached, "stale": False}, separators=(",", ":")))
                return
            raise UsageError("Claude usage was checked recently. Try again in about " + str(remaining) + " min.")
        mark_request_attempt()
        snapshot = normalize_usage(request_usage(token))
        save_cache(snapshot)
        clear_cooldown()
        result = {"plan": subscription_type(credentials), **snapshot, "stale": False}
    except UsageError as exc:
        if exc.retry_after is not None:
            try:
                write_cooldown(exc.retry_after)
            except OSError:
                pass
        cached = read_cache()
        if cached:
            result = {"plan": subscription_type(credentials), **cached, "stale": True, "error": str(exc)}
        else:
            result = {"error": str(exc)}
    except RuntimeError as exc:
        cached = read_cache()
        if cached:
            result = {"plan": subscription_type(credentials), **cached, "stale": True, "error": str(exc)}
        else:
            result = {"error": str(exc)}
    except Exception:
        cached = read_cache()
        message = "Could not update Claude usage. The last saved snapshot is shown if available."
        if cached:
            result = {"plan": subscription_type(credentials), **cached, "stale": True, "error": message}
        else:
            result = {"error": message}
    print(json.dumps(result, separators=(",", ":")))


if __name__ == "__main__":
    main()
