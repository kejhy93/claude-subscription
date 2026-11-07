# Claude Subscription (local Omarchy widget)

A native Omarchy popup for Claude subscription usage: the rolling 5-hour window and 7-day weekly window, including percentage remaining, countdown to reset, reset time, and detected subscription type. The menu action opens it from Omarchy's main menu; the optional bar widget mirrors OpenRouter Spending.

## Install on a new machine

The repo is private, so the machine needs GitHub access over SSH first (`gh auth login --git-protocol ssh` can generate and upload a key).

```sh
# Download and enable the plugin (lands in ~/.config/omarchy/plugins/claude.subscription)
omarchy plugin add git@github.com:kejhy93/claude-subscription.git --enable
```

Then enable the background refresh, a systemd user timer that calls the usage API every 10 minutes and stores the result locally:

```sh
~/.config/omarchy/plugins/claude.subscription/install-timer.sh            # enable
~/.config/omarchy/plugins/claude.subscription/install-timer.sh --uninstall  # disable
```

The widget itself makes no network requests on load, on open, or from its timer: it reads the local snapshot written by the timer (and by the optional status line). The manual refresh button, a middle-click, or `omarchy-shell claude.subscription refresh` requests a live API read. API requests are rate-limited locally to no more than one every five minutes, with backoff after HTTP 429. A snapshot older than 25 minutes is marked stale. Open the widget in the bar or run `omarchy-shell claude.subscription open`.

### Updating

```sh
omarchy plugin update claude.subscription
```

To change the plugin, edit it in `~/.config/omarchy/plugins/claude.subscription/` (it hot-reloads), then `git commit` and `git push` from there.

## Data source and freshness

`fetch.py` calls `https://api.anthropic.com/api/oauth/usage` using the existing Claude Code OAuth access token from `~/.claude/.credentials.json` (or `$CLAUDE_CONFIG_DIR/.credentials.json`). This endpoint is used by Claude Code but is not a publicly documented Anthropic API; Anthropic can change it without notice. The helper uses HTTPS with redirects disabled, and enforces a five-minute minimum interval plus a persisted backoff after HTTP 429 responses. No API key or token is added to widget settings. It stores only the 5-hour/7-day percentages, reset epochs, and successful fetch time in `~/.local/state/claude-subscription/usage.json`, with directory mode `0700` and file mode `0600`. On refresh failure, the UI keeps the last successful snapshot and marks it stale. It does not store OAuth credentials or transmit prompt/session content. It never renews or rewrites the OAuth token (Claude Code owns that); if the saved token has expired, refreshes pause until Claude Code renews it.

The optional `statusline.py` integration remains as a local fallback: Claude Code's documented `statusLine` JSON can update the same snapshot after assistant responses if you choose to configure it. Periodic API reads come only from the `claude-subscription-fetch.timer` systemd user timer (every 10 minutes, see `systemctl --user list-timers`); the widget reads the stored snapshot. The widget does not need the status-line integration for live API reads.

## Install behavior

The status line integration is optional for live API reads. If configured, it adds a small `Claude · 5h: … · 7d: …` line to interactive Claude Code sessions and provides a local fallback snapshot. The OAuth access token is read from the protected local Claude Code credentials file and sent only to Anthropic's fixed HTTPS usage endpoint. The subscription type is read locally.

## Controls

- Left-click bar icon: open/close popup
- Middle-click or popup refresh: request a live API refresh
- IPC: `omarchy-shell claude.subscription refresh|toggle|open`
- Main menu search: `Claude Subscription`
- Disable bar widget: `omarchy plugin disable claude.subscription`

## Files

- `manifest.json` — plugin registration
- `BarWidget.qml` / `UsagePanel.qml` — bar button and popup
- `statusline.py` — optional local fallback from Claude Code's documented status-line JSON
- `fetch.py` — read the local usage snapshot (default, no network); `--live` refreshes it from the API; `--service` is the timer's mode (logs to the journal, exits non-zero on failure)
- `install-timer.sh` — install/remove the 10-minute background refresh timer

Privacy: the cache contains only usage percentages, reset epochs, and an update timestamp. Each refresh makes one HTTPS request to Anthropic's undocumented OAuth usage endpoint. The status-line fallback performs no network requests.
