#!/usr/bin/env python3
"""bluesky_backfill.py — drip ONE back-catalog tech article to Bluesky per run.

Mirrors devto_backfill.py: posts the strongest not-yet-posted indexable tech
article each run (skips trading/noindex), tracked in a state file, so the back
catalogue gradually gets Bluesky distribution without spamming. Uses a value-first
hook built from the article's frontmatter (title + description teaser), kept under
Bluesky's 300-char limit, with a clickable link + preview card via bluesky_publish.py.

State: /opt/dtc-agent/.dtc/bluesky_backfilled.json
Usage: python3 bluesky_backfill.py [--list]
"""
import json
import os
import re
import subprocess
import sys

POSTS_DIR = "/opt/devtocash/content/posts"
STATE = "/opt/dtc-agent/.dtc/bluesky_backfilled.json"
PUBLISHER = "/opt/dtc-agent/lib/bluesky_publish.py"
SITE = "https://devtocash.com"

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


def frontmatter(raw):
    fm = {}
    m = re.match(r"^---\s*\n(.*?)\n---", raw, re.DOTALL)
    if m:
        for line in m.group(1).split("\n"):
            km = re.match(r'^(\w+):\s*"?(.*?)"?\s*$', line)
            if km:
                fm[km.group(1)] = km.group(2)
    return fm


def candidates(done):
    out = []
    for fn in os.listdir(POSTS_DIR):
        if not fn.endswith(".mdx"):
            continue
        slug = fn[:-4]
        if slug in done or any(h in slug for h in NOINDEX_HINTS):
            continue
        raw = open(os.path.join(POSTS_DIR, fn), encoding="utf-8").read()
        head = raw[:600]
        if "noindex" in head:
            continue
        m = re.search(r'category:\s*["\']?(\w+)', head)
        cat = m.group(1) if m else ""
        if cat not in ("devops", "sre", "cloud", "infrastructure", "platform", "tools"):
            continue
        out.append((slug, len(raw)))
    out.sort(key=lambda x: -x[1])
    return out


def build_hook(slug, fm):
    """Value-first hook under 300 chars: description teaser + link, trim to fit."""
    link = f"{SITE}/blog/{slug}"
    title = fm.get("title", slug)
    desc = fm.get("description", "").strip()
    tail = f"\n\nFull guide 👇\n{link}"
    budget = 300 - len(tail)
    lead = desc or title
    if len(lead) > budget:
        lead = lead[: budget - 1].rstrip() + "…"
    return lead + tail


def main():
    done = load_state()
    cands = candidates(done)
    if "--list" in sys.argv:
        print(f"{len(cands)} tech articles left to backfill to Bluesky:")
        for slug, size in cands[:20]:
            print(f"  {size:6d}B  {slug}")
        return 0
    if not cands:
        print(json.dumps({"ok": True, "done": True, "msg": "bluesky backfill complete"}))
        return 0
    slug = cands[0][0]
    raw = open(os.path.join(POSTS_DIR, f"{slug}.mdx"), encoding="utf-8").read()
    fm = frontmatter(raw)
    hook = build_hook(slug, fm)
    link = f"{SITE}/blog/{slug}"
    r = subprocess.run(["python3", PUBLISHER, "--text", hook, "--link", link, "--slug", slug],
                       capture_output=True, text=True)
    print(r.stdout.strip())
    if r.returncode == 0:
        done.add(slug)
        save_state(done)
        print(json.dumps({"ok": True, "backfilled": slug, "remaining": len(cands) - 1}))
        return 0
    print(json.dumps({"ok": False, "slug": slug, "stderr": r.stderr.strip()[:300]}), file=sys.stderr)
    return 4


if __name__ == "__main__":
    sys.exit(main())
