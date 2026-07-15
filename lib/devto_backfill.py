#!/usr/bin/env python3
"""devto_backfill.py — drip ONE back-catalog tech article to dev.to per run.

dev.to rate-limits article creation hard (a young account has a low daily cap),
so the 79-article back catalogue can't be mass-posted. This posts the single
best not-yet-crossposted indexable tech article each run, tracked in a state
file, newest-strongest first. Paired with a once-daily timer it drains the
backlog over ~2-3 months without tripping the cap.

Skips: trading/finance/career posts (intentionally noindex — see the noindex
policy) and anything already recorded as posted.

State: /opt/dtc-agent/.dtc/devto_backfilled.json  (list of slugs already sent)
Usage: python3 devto_backfill.py            # post the next one
       python3 devto_backfill.py --list     # show what's left, post nothing
"""
import json
import os
import re
import subprocess
import sys

POSTS_DIR = "/opt/devtocash/content/posts"
STATE = "/opt/dtc-agent/.dtc/devto_backfilled.json"
PUBLISHER = "/opt/dtc-agent/lib/devto_publish.py"

# Slug substrings that mark intentionally-noindex trading/finance/career content
# to exclude from SEO distribution (mirrors project_trading-content-noindex-policy).
NOINDEX_HINTS = [
    "trading", "bitcoin", "options", "dividend", "position-sizing", "swing",
    "ihsg", "moving-average", "freelance", "salary", "passive-income",
    "backtest", "side-income", "invest",
]


def load_state():
    if os.path.exists(STATE):
        try:
            return set(json.load(open(STATE)))
        except Exception:
            return set()
    return set()


def save_state(done):
    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    json.dump(sorted(done), open(STATE, "w"), indent=2)


def candidates(done):
    """Return [(slug, score)] of eligible tech posts not yet backfilled, best first."""
    out = []
    for fn in os.listdir(POSTS_DIR):
        if not fn.endswith(".mdx"):
            continue
        slug = fn[:-4]
        if slug in done:
            continue
        if any(h in slug for h in NOINDEX_HINTS):
            continue
        raw = open(os.path.join(POSTS_DIR, fn), encoding="utf-8").read()
        head = raw[:600]
        if "noindex" in head:            # respect explicit noindex frontmatter
            continue
        m = re.search(r'category:\s*["\']?(\w+)', head)
        cat = m.group(1) if m else ""
        if cat not in ("devops", "sre", "cloud", "infrastructure", "platform", "tools"):
            continue
        # Score by length (proxy for depth/value) — post the strongest first.
        out.append((slug, len(raw)))
    out.sort(key=lambda x: -x[1])
    return out


def main():
    done = load_state()
    cands = candidates(done)
    if "--list" in sys.argv:
        print(f"{len(cands)} tech articles left to backfill to dev.to:")
        for slug, size in cands[:20]:
            print(f"  {size:6d}B  {slug}")
        return 0
    if not cands:
        print(json.dumps({"ok": True, "done": True, "msg": "backfill complete — no tech articles left"}))
        return 0
    slug = cands[0][0]
    r = subprocess.run(["python3", PUBLISHER, slug], capture_output=True, text=True)
    print(r.stdout.strip())
    if r.returncode == 0:
        done.add(slug)
        save_state(done)
        print(json.dumps({"ok": True, "backfilled": slug, "remaining": len(cands) - 1}))
        return 0
    # Do NOT mark done on failure (e.g. rate-limited) — retry next run.
    print(json.dumps({"ok": False, "slug": slug, "stderr": r.stderr.strip()[:300]}), file=sys.stderr)
    return 4


if __name__ == "__main__":
    sys.exit(main())
