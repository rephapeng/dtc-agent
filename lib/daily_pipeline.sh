#!/usr/bin/env bash
# daily_pipeline.sh — the full autonomous daily job, run by a systemd timer.
#
# Sequential by design so each `claude` step acquires/releases /opt/dtc-agent/.claude.lock
# in turn (never nested → no deadlock, and subscription usage stays sane):
#   1. `dtc post`  — write -> quality-gate -> build -> commit -> push -> restart
#   2. detect the slug it just published (from posted_topics.json)
#   3. daily_ops role — GA/GSC report + Buffer(Twitter/Threads) + dev.to crosspost + Telegram
#
# Safe to run from cron/systemd: absolute paths, own log, no interactive prompts.
set -uo pipefail

AGENT_DIR="/opt/dtc-agent"
REPO="/opt/devtocash"
LIB="$AGENT_DIR/lib"
LOG="$AGENT_DIR/logs/daily_pipeline.log"
POSTED="$REPO/.dtc/knowledge/posted_topics.json"
PATH="/root/.local/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
export PATH

ts()  { date -u '+%Y-%m-%d %H:%M:%S UTC'; }
say() { echo "[$(ts)] $*" | tee -a "$LOG"; }

# One daily pipeline at a time (independent of the inner .claude.lock).
exec 8>"$AGENT_DIR/.daily_pipeline.lock"
if ! flock -n 8; then say "another daily_pipeline is running — abort"; exit 0; fi

say "=== daily_pipeline start ==="

# --- Step 1: publish today's article (self-contained; own locks) -------------
PREV_SLUG="$(python3 -c 'import json,os;p="'"$POSTED"'";d=json.load(open(p)) if os.path.exists(p) else [];print(d[-1]["slug"] if d else "")' 2>/dev/null || echo "")"
say "publishing via dtc post (prev slug: ${PREV_SLUG:-none})..."
if "$AGENT_DIR/bin/dtc" post >>"$LOG" 2>&1; then
  say "dtc post exited 0"
else
  say "dtc post exited non-zero (gate reject / build fail / etc.) — will still report"
fi

# --- Step 2: figure out what (if anything) got published ---------------------
NEW_SLUG="$(python3 -c 'import json,os;p="'"$POSTED"'";d=json.load(open(p)) if os.path.exists(p) else [];print(d[-1]["slug"] if d else "")' 2>/dev/null || echo "")"
if [[ -n "$NEW_SLUG" && "$NEW_SLUG" != "$PREV_SLUG" ]]; then
  PUBLISHED_SLUG="$NEW_SLUG"
  say "published new slug: $PUBLISHED_SLUG"
else
  PUBLISHED_SLUG="NONE"
  say "no new article published today"
fi

# --- Step 3: report + cross-post (single claude turn, one lock acquisition) ---
say "running daily_ops (report + crosspost + telegram)..."
MAX_TURNS=40 "$LIB/run_claude.sh" "$AGENT_DIR/prompts/daily_ops.md" \
  $'Read\nGrep\nGlob\nBash\nWebSearch\nWebFetch' \
  "Run the daily ops. PUBLISHED_SLUG=$PUBLISHED_SLUG" >>"$LOG" 2>&1 \
  && say "daily_ops done" || say "WARN: daily_ops returned non-zero — see $LOG"

say "=== daily_pipeline done ==="
