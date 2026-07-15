#!/usr/bin/env bash
# run_claude.sh — single entrypoint that invokes the local `claude` CLI as the
# agent brain, GROUNDED in devtocash's real content and LOCKED to the Claude
# subscription (never metered API).
#
# Usage:
#   run_claude.sh <role_prompt_file> <allowed_tools> <user_prompt>
#   allowed_tools example: "Read Grep Glob Bash"   (space separated; "" = default)
set -euo pipefail

AGENT_DIR="/opt/dtc-agent"
REPO="/opt/devtocash"
KDIR="/opt/devtocash/.dtc/knowledge"   # knowledge stored inside the project
ROLE_FILE="${1:?role prompt file required}"
ALLOWED="${2:-}"
USER_PROMPT="${3:?user prompt required}"

# --- Force SUBSCRIPTION auth: strip anything that would trigger API billing ---
unset ANTHROPIC_API_KEY ANTHROPIC_AUTH_TOKEN ANTHROPIC_BASE_URL 2>/dev/null || true

# --- Build the system prompt: shared grounding + live KNOWLEDGE.md + role ---
SYS="$(cat "$AGENT_DIR/prompts/common.md")

===== INJECTED GROUNDING (current corpus) =====
$(cat "$KDIR/KNOWLEDGE.md")

===== ROLE =====
$(cat "$ROLE_FILE")"

cd "$REPO"

# Official CLI, standard flags only. --max-turns caps a single run so usage
# stays reasonable (no runaway loops). MAX_TURNS defaults to 30, override per call.
MAX_TURNS="${MAX_TURNS:-30}"
ARGS=(-p "$USER_PROMPT" --append-system-prompt "$SYS" --max-turns "$MAX_TURNS")
if [[ -n "$ALLOWED" ]]; then
  # Tools are newline-separated so a Bash(...) spec may contain spaces without
  # being word-split. Each tool becomes its own --allowedTools value.
  mapfile -t TOOLS <<< "$ALLOWED"
  ARGS+=(--permission-mode acceptEdits)
  for t in "${TOOLS[@]}"; do [[ -n "$t" ]] && ARGS+=(--allowedTools "$t"); done
fi

# Single-flight lock: never run two claude sessions at once (keeps subscription
# usage normal, avoids the concurrent-call hammering that got evonic force-stopped).
exec flock -w 900 /opt/dtc-agent/.claude.lock claude "${ARGS[@]}"
