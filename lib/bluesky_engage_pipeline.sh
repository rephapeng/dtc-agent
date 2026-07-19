#!/usr/bin/env bash
# bluesky_engage_pipeline.sh — daily Bluesky community engagement. Hands a
# headless claude (bluesky_engage role) the candidate posts; it writes value-first
# replies (no links, <=5/day) and posts them to grow reach. State (already-replied
# URIs) lives in /opt/dtc-agent/.dtc/bluesky_replied.json via bluesky_reply.py.
set -uo pipefail

AGENT_DIR="/opt/dtc-agent"
LIB="$AGENT_DIR/lib"
LOG="$AGENT_DIR/logs/bluesky_engage.log"
PATH="/root/.local/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
export PATH

ts()  { date -u '+%Y-%m-%d %H:%M:%S UTC'; }
say() { echo "[$(ts)] $*" | tee -a "$LOG"; }

exec 8>"$AGENT_DIR/.bluesky_engage.lock"
if ! flock -n 8; then say "another bluesky_engage run is active — abort"; exit 0; fi

say "=== bluesky_engage start ==="
MAX_TURNS=30 "$LIB/run_claude.sh" "$AGENT_DIR/prompts/bluesky_engage.md" \
  $'Bash' \
  "Run the daily Bluesky community engagement now. Reply value-first to at most 5 genuinely relevant posts." >>"$LOG" 2>&1 \
  && say "bluesky_engage done" || say "WARN: bluesky_engage returned non-zero — see $LOG"
say "=== bluesky_engage end ==="
