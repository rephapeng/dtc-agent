#!/usr/bin/env bash
# resurface_pipeline.sh — daily 13:00 WIB job: re-promote ONE older article on
# social to revive its traffic. Picks a rotating back-catalogue slug, then hands
# it to a headless claude (resurface_ops role) that crafts the gimmick + posts to
# Bluesky/Twitter/Threads + IndexNow + Telegram.
set -uo pipefail

AGENT_DIR="/opt/dtc-agent"
LIB="$AGENT_DIR/lib"
LOG="$AGENT_DIR/logs/resurface.log"
PATH="/root/.local/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
export PATH

ts()  { date -u '+%Y-%m-%d %H:%M:%S UTC'; }
say() { echo "[$(ts)] $*" | tee -a "$LOG"; }

exec 8>"$AGENT_DIR/.resurface.lock"
if ! flock -n 8; then say "another resurface run is active — abort"; exit 0; fi

TODAY="$(date +%F)"
say "=== resurface start ($TODAY) ==="

SLUG="$(python3 "$LIB/resurface_pick.py" "$TODAY" 2>>"$LOG")"
if [[ -z "$SLUG" ]]; then
  say "no eligible article to resurface today — done"; exit 0
fi
say "resurfacing: $SLUG"

MAX_TURNS=30 "$LIB/run_claude.sh" "$AGENT_DIR/prompts/resurface_ops.md" \
  $'Read\nGrep\nGlob\nBash' \
  "Resurface this older article now. RESURFACE_SLUG=$SLUG" >>"$LOG" 2>&1 \
  && say "resurface done: $SLUG" || say "WARN: resurface returned non-zero — see $LOG"

say "=== resurface end ==="
