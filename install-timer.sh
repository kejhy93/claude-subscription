#!/usr/bin/env bash
# Install (or remove with --uninstall) a systemd user timer that refreshes the
# Claude usage snapshot in the background every 10 minutes.
set -euo pipefail

unit_dir="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
name="claude-subscription-fetch"

if [[ "${1:-}" == "--uninstall" ]]; then
  systemctl --user disable --now "$name.timer" 2>/dev/null || true
  rm -f "$unit_dir/$name.service" "$unit_dir/$name.timer"
  systemctl --user daemon-reload
  echo "Removed $name timer."
  exit 0
fi

script="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/fetch.py"
mkdir -p "$unit_dir"

cat > "$unit_dir/$name.service" <<EOF
[Unit]
Description=Refresh Claude subscription usage snapshot
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
ExecStart=/usr/bin/python3 -I "$script"
StandardOutput=null
Nice=10
EOF

cat > "$unit_dir/$name.timer" <<EOF
[Unit]
Description=Refresh Claude subscription usage every 10 minutes

[Timer]
OnBootSec=1min
OnUnitActiveSec=10min
RandomizedDelaySec=30s
AccuracySec=1min

[Install]
WantedBy=timers.target
EOF

systemctl --user daemon-reload
systemctl --user enable --now "$name.timer"
echo "Installed $name timer (fetch.py: $script)."
