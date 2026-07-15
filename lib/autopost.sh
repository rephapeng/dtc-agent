#!/usr/bin/env bash
# autopost.sh — generate ONE grounded article, gate it, validate the build,
# then commit to main and restart the live site. Conservative & sequential so
# subscription usage stays normal (official CLI, single-flight, capped turns).
#
#   autopost.sh            full run: write -> gate -> build -> commit+push -> restart
#   autopost.sh --dry-run  write -> gate only; leaves the draft on disk, no commit/build/restart
set -euo pipefail

AGENT_DIR="/opt/dtc-agent"
REPO="/opt/devtocash"
LIB="$AGENT_DIR/lib"
KDIR="$REPO/.dtc/knowledge"
LOG="$AGENT_DIR/logs/autopost.log"
PATH="/root/.local/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
export PATH

DRY=0; [[ "${1:-}" == "--dry-run" ]] && DRY=1

ts() { date -u '+%Y-%m-%d %H:%M:%S UTC'; }
say() { echo "[$(ts)] $*" | tee -a "$LOG"; }

# Only one autopost pipeline at a time.
exec 9>"$AGENT_DIR/.autopost.lock"
if ! flock -n 9; then say "another autopost is running — abort"; exit 0; fi

cd "$REPO"
DATE="$(date +%F)"
say "=== autopost start (dry=$DRY) date=$DATE ==="

# 1. Fresh grounding
python3 "$LIB/build_knowledge.py" >>"$LOG" 2>&1

# 2. Write one article (writer role). Higher turn budget for a full article.
say "generating article..."
WRITER_OUT="$(MAX_TURNS=45 "$LIB/run_claude.sh" "$AGENT_DIR/prompts/writer.md" \
    $'Read\nWrite\nGrep\nGlob\nBash(python3 /opt/devtocash/gsc_api.py:*)' \
    "Write today's article. The date to use in the filename is: $DATE")" || { say "writer failed"; exit 1; }

# Extract the last JSON line the writer emitted -> the new file path.
FILE="$(printf '%s\n' "$WRITER_OUT" | grep -oE '\{.*"file".*\}' | tail -1 \
        | python3 -c 'import sys,json;print(json.load(sys.stdin).get("file",""))' 2>/dev/null || true)"
# Fallback: newest untracked mdx in content/posts
if [[ -z "${FILE:-}" || ! -f "$REPO/$FILE" ]]; then
  FILE="$(git -C "$REPO" status --porcelain content/posts | awk '/^\?\?/{print $2}' | tail -1)"
fi
if [[ -z "${FILE:-}" || ! -f "$REPO/$FILE" ]]; then
  say "ERROR: could not locate the new article file"; exit 1
fi
say "new draft: $FILE"

# 3. Quality gate (automated AdSense guardrail) — BEFORE any heavy build.
say "quality gate..."
GATE_OUT="$(MAX_TURNS=15 "$LIB/run_claude.sh" "$AGENT_DIR/prompts/quality_gate.md" \
    "Read Grep Glob" "Review this draft for publish safety: $FILE")" || { say "gate call failed"; exit 1; }
GATE_JSON="$(printf '%s\n' "$GATE_OUT" | grep -oE '\{.*"pass".*\}' | tail -1)"
PASS="$(printf '%s' "$GATE_JSON" | python3 -c 'import sys,json;d=json.load(sys.stdin);print("1" if d.get("pass") else "0")' 2>/dev/null || echo 0)"
say "gate verdict: $GATE_JSON"

if [[ "$PASS" != "1" ]]; then
  say "REJECTED by quality gate — removing draft, nothing published."
  git -C "$REPO" checkout -- "$FILE" 2>/dev/null || rm -f "$REPO/$FILE"
  exit 3
fi

if [[ "$DRY" == "1" ]]; then
  say "DRY-RUN passed gate. Draft left on disk for review: $REPO/$FILE (no build/commit/restart)."
  exit 0
fi

# 4. Validate + build (also produces the deploy artifact).
say "npm run build (validate)..."
if ! npm run build >>"$LOG" 2>&1; then
  say "BUILD FAILED — removing draft and restoring clean build."
  rm -f "$REPO/$FILE"
  npm run build >>"$LOG" 2>&1 || say "WARN: cleanup rebuild also failed — check $LOG"
  exit 4
fi

# 5. Commit + push to main.
say "committing to main..."
git -C "$REPO" add "$FILE"
git -C "$REPO" commit -q -m "content: add ${FILE##*/} (dtc-agent auto-post)" || { say "nothing to commit?"; exit 5; }
git -C "$REPO" push -q origin main 2>>"$LOG" && say "pushed to origin/main" || say "WARN: push failed (committed locally) — see $LOG"

# 6. Restart live site so the post goes public. The site is managed by pm2 (app
# "devtocash") via scripts/resource_monitor.sh — restart THROUGH pm2 so it serves
# the freshly-built .next. Do NOT kill + nohup npm start: that races pm2 (which
# auto-respawns) and leaves a stale process serving old chunk hashes → client-side
# exception / blank page for all users (this exact bug took the site down 2026-07-13).
say "restarting production via pm2 (serves fresh build)..."
sudo -u ubuntu pm2 restart devtocash --update-env >>"$LOG" 2>&1 \
  || pm2 restart devtocash --update-env >>"$LOG" 2>&1 \
  || say "WARN: pm2 restart failed — check pm2 list"
sleep 5
code=$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:3000 || echo 000)
say "prod http=$code"
# Guard: verify the served HTML's JS chunk actually resolves (catches stale-build).
chunk=$(curl -s http://127.0.0.1:3000/ | grep -oE 'page-[a-f0-9]+\.js' | head -1)
if [[ -n "$chunk" ]]; then
  cc=$(curl -s -o /dev/null -w '%{http_code}' "http://127.0.0.1:3000/_next/static/chunks/app/$chunk")
  say "chunk $chunk -> HTTP $cc $([[ "$cc" == "200" ]] && echo OK || echo 'STALE BUILD — needs clean pm2 restart')"
fi

# 7. Record in memory so we never repeat this topic.
python3 - "$FILE" "$DATE" <<'PY' >>"$LOG" 2>&1 || true
import json,os,sys
f,date=sys.argv[1],sys.argv[2]
p="/opt/devtocash/.dtc/knowledge/posted_topics.json"
data=json.load(open(p)) if os.path.exists(p) else []
data.append({"file":f,"slug":os.path.basename(f)[:-4],"date":date})
json.dump(data,open(p,"w"),indent=2)
PY

say "=== autopost done: published $FILE ==="
