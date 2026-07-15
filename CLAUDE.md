# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

`/opt/dtc-agent` is the **autonomous SEO/content agent** for **devtocash.com** — a
Next.js 14 blog (DevOps/SRE + Trading/Finance, monetized with Google AdSense). The
site's own repo lives separately at **`/opt/devtocash`** (`$REPO`); this repo is the
*operator* that writes/publishes content, cross-posts, reports analytics, and answers
its owner ("the boss") over Telegram.

The agent's "brain" is the local **`claude` CLI**, invoked headlessly with role prompts.
It is deliberately locked to the **Claude subscription** (never metered API) and to
**single-flight** execution — subscription hygiene is a first-class design constraint,
not an afterthought (a prior sibling project, "evonic", was force-stopped for concurrent
API hammering; several comments reference this).

## Commands

```bash
bin/dtc index                 # rebuild grounding knowledge from live /opt/devtocash content
bin/dtc ask "<question>"      # read-only SEO/GSC Q&A (seo_analyst role, real GSC data)
bin/dtc post [--dry-run]      # generate ONE article; --dry-run = write+gate only (no publish)
bin/dtc gsc [args...]         # passthrough to /opt/devtocash/gsc_api.py (Search Console)

# Site build/validation always runs in the SITE repo, not here:
cd /opt/devtocash && npm run build   # validates all MDX; a post that breaks build is never committed
```

There is no test suite, linter, or package manifest in this repo — it is bash + stdlib
Python 3 (no external deps except `requests` for the Telegram bot). "Testing" a change
means running the relevant pipeline/script and reading its log under `logs/`.

## Architecture: how a run actually flows

**Everything routes through `lib/run_claude.sh`** (and its interactive sibling
`lib/agent_run.sh`). These are the ONLY places the `claude` CLI is invoked. They:
1. Strip `ANTHROPIC_API_KEY` / `ANTHROPIC_AUTH_TOKEN` / `ANTHROPIC_BASE_URL` to force
   subscription auth.
2. Build the system prompt = `prompts/common.md` + injected `KNOWLEDGE.md` grounding +
   the role prompt file.
3. `cd /opt/devtocash` (the agent works *in the site repo*).
4. Run under `flock -w 900 .claude.lock` — the single-flight lock shared by *every*
   claude invocation across the whole system, so two sessions never run at once.

**Grounding ("don't leave context").** `lib/build_knowledge.py` scans the real
`/opt/devtocash/content/{posts,pages}` MDX and emits
`/opt/devtocash/.dtc/knowledge/KNOWLEDGE.md` + `knowledge.json` — every real slug,
category, tag, and internal-link edge. This is injected into every prompt so the agent
can only reference content that actually exists (no invented slugs/metrics). It is
regenerated (cheaply) at the start of nearly every entry point. **Note the two `.dtc`
dirs:** knowledge + `posted_topics.json` live in `$REPO/.dtc/` (source of truth);
`/opt/dtc-agent/.dtc/` only holds backfill state JSON.

**Roles** (`prompts/*.md`) are just system-prompt fragments passed to `run_claude.sh`
with a tailored allowed-tools list:
- `common.md` — shared grounding + non-negotiable rules, prepended to every role.
- `writer.md` — writes ONE article, emits a JSON summary line (`{"file":...}`).
- `quality_gate.md` — strict AdSense guardrail; emits `{"pass":bool,...}`. Replaces human review.
- `seo_analyst.md` — read-only Q&A (the `dtc ask` role).
- `agent.md` — the interactive Telegram persona (full tools, does things, not a FAQ bot).
- `daily_ops.md` / `weekly_report.md` — headless cron reporting + cross-posting.

Scripts parse role output by **grepping for the last JSON line** the model emitted
(`grep -oE '{.*"pass".*}' | tail -1`), with filesystem fallbacks. When editing a role
prompt's output contract, keep the JSON-last-line convention or update the parser in the
calling `.sh`.

## The publishing pipeline (`lib/autopost.sh`, = `dtc post`)

Strictly sequential, each step gated on the previous:
`build_knowledge → writer (MAX_TURNS=45) → quality_gate (MAX_TURNS=15) → npm build →
git commit main → git push → pm2 restart → record in posted_topics.json`.
`--dry-run` stops after the gate and leaves the draft on disk. Gate reject / build fail
removes the draft and restores a clean build (distinct exit codes 3/4/5).

**pm2 gotcha (load-bearing comment):** the live site is served by **pm2** (app
`devtocash`, run as user `ubuntu`). Always restart *through* pm2 (`pm2 restart devtocash
--update-env`), never `kill + nohup npm start` — that races pm2's auto-respawn and serves
stale chunk hashes → blank page for all users. autopost verifies the served JS chunk
resolves (HTTP 200) after restart to catch exactly this.

## Scheduling & entry points

Driven by **systemd timers** (all UTC), each service just runs a `lib/*.sh` script that
takes the `.claude.lock` in turn:
- `dtc-daily.timer` (01:04 daily) → `daily_pipeline.sh`: `dtc post`, then `daily_ops`
  role (GA4/GSC report + cross-post the new article to Twitter/Threads via Buffer, dev.to,
  Bluesky + Telegram report to the boss).
- `dtc-weekly.timer` (Mon 01:34) → `weekly_pipeline.sh`: read-only weekly analytics
  report to Telegram.
- `dtc-devto-backfill.timer` (13:07) / `dtc-bluesky-backfill.timer` (17:22): drip ONE
  back-catalogue tech article per run to dev.to / Bluesky (rate-limit friendly; skips
  trading/noindex posts; state in `/opt/dtc-agent/.dtc/*_backfilled.json`).
- `dtc-telegram.service` (long-running) → `telegram_bot.py`: pure long-polling Bot API,
  no framework. Allow-listed chat IDs (`TELEGRAM_ALLOWED_CHAT_IDS`) only. Freeform
  messages route to `agent_run.sh` (a real Claude Code session with per-chat `--resume`
  memory in `.sessions/<chat_id>.sid`); `/status`, `/reset`, `/help`, `/whoami` are
  local. Incoming photos/docs are saved to `incoming/` and handed to the agent.

`agent_run.sh` picks a **model tier by message**: short greetings/acks → `sonnet` (no
thinking budget); everything substantive → `opus` + `MAX_THINKING_TOKENS`. Override with
`DTC_AGENT_MODEL`. It uses `--permission-mode acceptEdits` + a broad `--allowedTools`
list because `bypassPermissions` is refused when running as root.

`lib/self_restart.sh` restarts a dtc service from *outside* its cgroup (via
`systemd-run`) so the Telegram reply survives the restart it triggers — restarting
`dtc-telegram.service` from within would kill the very process sending the confirmation.

## Cross-posting distribution (see `prompts/daily_ops.md` for the full contract)

Helpers in `lib/`, all emitting JSON: `bluesky_publish.py` / `bluesky_thread.py`
(300-char/post hard limit), `buffer_thread.py` (Twitter 280 / Threads 500 per post, via
Buffer GraphQL), `devto_publish.py` (Forem API, handles canonical_url + rate limits).
Article *shape* decides format: list/"N mistakes"/Q&A → **thread**; single deep-dive →
**single post**. Copy is always **value-first** (real command/number/gotcha from the
article, link as payoff) — never just "title + link".

## Conventions & guardrails

- **Absolute paths everywhere** (`AGENT_DIR=/opt/dtc-agent`, `REPO=/opt/devtocash`) — scripts run headless from cron with a pinned `PATH`.
- **Never commit `.env`** (gitignored; chmod 600). It holds Telegram / dev.to / Buffer / Bluesky secrets. Scripts read it but must never echo secret values.
- **Trading/finance content is intentionally `noindex`** — analytics recommendations and cross-posting target tech/DevOps only; don't propose optimizing the trading content for search.
- The **quality gate is the AdSense guardrail**: reject thin/duplicate/off-niche (< 1000 words, invalid internal links, duplicate slug). When unsure, dry-run and show the boss.
- Each pipeline has its own single-instance `flock` lock file (`.daily_pipeline.lock`, `.autopost.lock`, etc.) *in addition to* the shared `.claude.lock`.
- `MAX_TURNS` env caps each claude run (defaults 30) — keep runs bounded; no runaway loops.
