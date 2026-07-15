#!/usr/bin/env bash
# self_restart.sh — restart a dtc-agent systemd service while notifying the boss
# on Telegram before/after, WITHOUT the notification dying alongside the restart.
#
# Why this exists: the `claude -p` process that answers the boss over Telegram
# runs inside dtc-telegram.service's own cgroup. If that process restarts the
# service directly, systemd kills the whole cgroup (including itself) before it
# can send a final reply — the boss just sees silence. This script must be
# launched via `systemd-run` (a transient unit OUTSIDE that cgroup) so it
# survives the restart it triggers.
#
# Usage: self_restart.sh [service] [before_msg] [after_msg] [chat_id]
set -euo pipefail

AGENT_DIR="/opt/dtc-agent"
ENV_FILE="$AGENT_DIR/.env"

SERVICE="${1:-dtc-telegram.service}"
MSG_BEFORE="${2:-bentar yah gue reboot dulu 🔧}"
MSG_AFTER="${3:-hi gue balik lagi 👋}"
CHAT_ID="${4:-}"

TOKEN="$(grep -E '^TELEGRAM_BOT_TOKEN=' "$ENV_FILE" | head -1 | cut -d= -f2- | tr -d '"'"'"'')"
ALLOWED="$(grep -E '^TELEGRAM_ALLOWED_CHAT_IDS=' "$ENV_FILE" | head -1 | cut -d= -f2- | tr -d '"'"'"'')"

if [[ -z "$CHAT_ID" ]]; then
  CHAT_IDS="${ALLOWED//,/ }"
else
  CHAT_IDS="$CHAT_ID"
fi

send() {
  local text="$1"
  for cid in $CHAT_IDS; do
    curl -s -X POST "https://api.telegram.org/bot${TOKEN}/sendMessage" \
      -d "chat_id=${cid}" --data-urlencode "text=${text}" >/dev/null || true
  done
}

send "$MSG_BEFORE"

systemctl restart "$SERVICE"

# Wait for the service to report active again (cap ~30s).
ok=0
for _ in $(seq 1 30); do
  if systemctl is-active --quiet "$SERVICE"; then
    ok=1
    sleep 2   # let it finish its startup log line
    break
  fi
  sleep 1
done

if [[ "$ok" -eq 1 ]]; then
  send "$MSG_AFTER"
else
  send "⚠️ $SERVICE gagal balik aktif setelah restart, tolong dicek manual."
fi
