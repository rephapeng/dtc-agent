#!/usr/bin/env bash
# weekly_pipeline.sh — read-only weekly GA/GSC report, run by a systemd timer.
set -uo pipefail

AGENT_DIR="/opt/dtc-agent"
LIB="$AGENT_DIR/lib"
LOG="$AGENT_DIR/logs/weekly_pipeline.log"
PATH="/root/.local/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
export PATH

ts()  { date -u '+%Y-%m-%d %H:%M:%S UTC'; }
say() { echo "[$(ts)] $*" | tee -a "$LOG"; }

exec 8>"$AGENT_DIR/.weekly_pipeline.lock"
if ! flock -n 8; then say "another weekly_pipeline is running — abort"; exit 0; fi

say "=== weekly_pipeline start ==="
MAX_TURNS=25 "$LIB/run_claude.sh" "$AGENT_DIR/prompts/weekly_report.md" \
  $'Read\nGrep\nGlob\nBash' \
  "Run the weekly report now." >>"$LOG" 2>&1 \
  && say "weekly report done" || say "WARN: weekly report returned non-zero — see $LOG"
say "=== weekly_pipeline done ==="
