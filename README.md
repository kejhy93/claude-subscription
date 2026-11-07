# Claude Subscription (local Omarchy widget)

A native Omarchy popup for the latest Claude Code subscription usage snapshot: the rolling 5-hour window and 7-day weekly window, including percentage remaining, countdown to reset, the reset time, and detected subscription type. The menu action opens it from Omarchy's main menu; the optional bar widget mirrors OpenRouter Spending.

## Data source and freshness

Claude Code's documented `statusLine` JSON includes `rate_limits.five_hour` and `rate_limits.seven_day` with `used_percentage` and `resets_at`. `statusline.py` stores only those numeric values and a timestamp in `~/.local/state/claude-subscription/usage.json`, with restrictive local permissions. The popup reads that snapshot; it does not poll Anthropic or use private APIs. Claude Code refreshes the snapshot when it runs the status line, typically after assistant responses and at limit reset events. It can therefore be stale when Claude Code is not active. The usage limits are shared across Claude and Claude Code according to Anthropic's plan documentation.

## Install behavior

The plugin configures Claude Code's supported status line in `~/.claude/settings.json`. This adds a small `Claude · 5h: … · 7d: …` line to interactive Claude Code sessions and provides the data the menu reads. Existing settings and hooks are preserved. No OAuth token or prompt/session content is read or transmitted; only the subscription type field is read locally from Claude Code's mode-0600 credentials file.

## Controls

- Left-click bar icon: open/close popup
- Middle-click or popup refresh: reread the local snapshot
- IPC: `omarchy-shell claude.subscription refresh|toggle|open`
- Main menu search: `Claude Subscription`
- Disable bar widget: `omarchy plugin disable claude.subscription`

## Files

- `manifest.json` — plugin registration
- `BarWidget.qml` / `UsagePanel.qml` — bar button and popup
- `statusline.py` — capture Claude Code's documented statusline JSON
- `fetch.py` — validate and read the local snapshot

Privacy: the cache contains only usage percentages, reset epochs, and an update timestamp. No network requests are made.
