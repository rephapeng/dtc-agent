#!/usr/bin/env bash
# agent_run.sh — drive the devtocash agent as a REAL Claude Code session (not the
# read-only `dtc ask` FAQ). Full tools + bypassPermissions so the boss can have
# it EXECUTE things over Telegram, with per-chat conversation memory (--resume)
# and the same subscription-lock + single-flight discipline as the rest of dtc.
#
#   agent_run.sh <chat_id> <user_message>
# Emits the raw `claude --output-format json` object on stdout.
set -euo pipefail

AGENT_DIR="/opt/dtc-agent"
REPO="/opt/devtocash"
KDIR="$REPO/.dtc/knowledge"
CHAT_ID="${1:?chat id required}"
USER_MSG="${2:?user message required}"

# --- Hybrid tier: cheap Sonnet for trivial chit-chat, escalate to Opus +
# extended-thinking budget for substantive work (investigation / decisions /
# writing / ops). Keeps subscription usage sane while giving the agent real
# depth when it matters. Override with DTC_AGENT_MODEL to force a tier. --------
MODEL="${DTC_AGENT_MODEL:-}"
if [[ -z "$MODEL" ]]; then
  msg_lc="$(printf '%s' "$USER_MSG" | tr '[:upper:]' '[:lower:]')"
  wc_words="$(printf '%s' "$msg_lc" | wc -w)"
  # Short greetings / acks / pings -> Sonnet, no thinking budget.
  if [[ "$wc_words" -le 4 ]] && printf '%s' "$msg_lc" | grep -qE \
      '^\s*(hai|halo|hallo|hi|hello|hey|yo|p|ping|test|tes|thanks|thx|makasih|mksh|ok|oke|okay|sip|siph|good|nice|pagi|siang|sore|malam|mantap|👍|🙏)\b'; then
    MODEL="sonnet"
  else
    MODEL="opus"
    export MAX_THINKING_TOKENS="${DTC_THINK_TOKENS:-10000}"
  fi
fi

SESS_DIR="$AGENT_DIR/.sessions"
mkdir -p "$SESS_DIR"
SID_FILE="$SESS_DIR/${CHAT_ID}.sid"

# --- Force SUBSCRIPTION auth + avoid nested-session detection ---------------
unset ANTHROPIC_API_KEY ANTHROPIC_AUTH_TOKEN ANTHROPIC_BASE_URL CLAUDECODE 2>/dev/null || true

# Keep grounding fresh (cheap), then build the system prompt.
python3 "$AGENT_DIR/lib/build_knowledge.py" >/dev/null 2>&1 || true
SYS="$(cat "$AGENT_DIR/prompts/common.md")

===== INJECTED GROUNDING (current corpus) =====
$(cat "$KDIR/KNOWLEDGE.md" 2>/dev/null)

===== ROLE =====
$(cat "$AGENT_DIR/prompts/agent.md")"

cd "$REPO"

# NB: --permission-mode bypassPermissions is REFUSED when running as root. Instead
# pre-authorize a broad tool set (like refan-agentic does) so the agent executes
# without prompts under the normal permission model. acceptEdits auto-applies edits.
ARGS=(--model "$MODEL" -p "$USER_MSG"
      --append-system-prompt "$SYS"
      --permission-mode acceptEdits
      --allowedTools Read Write Edit Grep Glob Bash WebSearch WebFetch Task
      --output-format json)

# Per-chat conversation memory: resume an existing session, else start one with
# a stable id we control.
if [[ -f "$SID_FILE" ]] && [[ -s "$SID_FILE" ]]; then
  ARGS+=(--resume "$(cat "$SID_FILE")")
else
  SID="$(cat /proc/sys/kernel/random/uuid)"
  printf '%s' "$SID" > "$SID_FILE"
  ARGS+=(--session-id "$SID")
fi

echo "[agent_run] chat=$CHAT_ID tier=$MODEL think=${MAX_THINKING_TOKENS:-0} words=${wc_words:-?}" >&2

# Single-flight: never two claude sessions at once (subscription hygiene).
exec flock -w 890 "$AGENT_DIR/.claude.lock" claude "${ARGS[@]}"
