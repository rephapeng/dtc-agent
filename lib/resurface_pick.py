#!/usr/bin/env python3
"""resurface_pick.py — pick ONE older indexable tech article to re-promote on
social, rotating so the whole back catalogue gets resurfaced over time.

Selection: indexable tech posts (devops/sre/cloud/infra/platform/tools, no
`noindex`), EXCLUDING anything published in the last 10 days (those are freshly
promoted by the daily pipeline), ordered by least-recently-resurfaced (never
resurfaced first, then oldest). State tracked in /opt/dtc-agent/.dtc/resurfaced.json
{slug: iso-date}. Prints the chosen slug on stdout (empty if none) and records
today's date for it (pass a date via arg since scripts here can't call now()).

Usage: python3 resurface_pick.py <today-YYYY-MM-DD>   (records pick)
       python3 resurface_pick.py --list                (show queue, no record)
"""
import json
import os
import re
import sys
from datetime import date, timedelta

POSTS_DIR = "/opt/devtocash/content/posts"
STATE = "/opt/dtc-agent/.dtc/resurfaced.json"
NOINDEX_HINTS = [
    "trading", "bitcoin", "options", "dividend", "position-sizing", "swing",
    "ihsg", "moving-average", "freelance", "salary", "passive-income",
    "backtest", "side-income", "invest",
]
TECH_CATS = ("devops", "sre", "cloud", "infrastructure", "platform", "tools")
FRESH_DAYS = 10  # don't resurface articles newer than this (daily job handles them)


def load_state():
    if os.path.exists(STATE):
        try:
            return json.load(open(STATE))
        except Exception:
            return {}
    return {}


def save_state(s):
    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    json.dump(s, open(STATE, "w"), indent=2, sort_keys=True)


def file_date(slug, fm):
    m = re.search(r"\d{4}-\d{2}-\d{2}", slug)
    if m:
        return m.group(0)
    return fm.get("date", "2026-01-01")


def frontmatter(raw):
    fm = {}
    m = re.match(r"^---\s*\n(.*?)\n---", raw, re.DOTALL)
    if m:
        for line in m.group(1).split("\n"):
            km = re.match(r'^(\w+):\s*"?(.*?)"?\s*$', line)
            if km:
                fm[km.group(1)] = km.group(2)
    return fm


def eligible(today):
    cutoff = today - timedelta(days=FRESH_DAYS)
    out = []
    for fn in os.listdir(POSTS_DIR):
        if not fn.endswith(".mdx"):
            continue
        slug = fn[:-4]
        if any(h in slug for h in NOINDEX_HINTS):
            continue
        raw = open(os.path.join(POSTS_DIR, fn), encoding="utf-8").read()
        head = raw[:600]
        if "noindex" in head:
            continue
        m = re.search(r'category:\s*["\']?(\w+)', head)
        if (m.group(1) if m else "") not in TECH_CATS:
            continue
        d = file_date(slug, frontmatter(raw))
        try:
            if date.fromisoformat(d) > cutoff:
                continue  # too fresh
        except Exception:
            pass
        out.append(slug)
    return out


def main():
    args = [a for a in sys.argv[1:] if a]
    state = load_state()
    if "--list" in args:
        today = date.today() if False else date(2026, 1, 1)  # date.today unavailable? use arg
        # for --list just use a far-future cutoff via a fixed old date
        elig = eligible(date(2999, 1, 1))
        ranked = sorted(elig, key=lambda s: state.get(s, "0000-00-00"))
        print(f"{len(ranked)} eligible; next up: {ranked[0] if ranked else '(none)'}")
        for s in ranked[:15]:
            print(f"  last={state.get(s, 'never'):10s}  {s}")
        return 0
    if not args:
        print("", end="")
        print("usage: resurface_pick.py <YYYY-MM-DD>", file=sys.stderr)
        return 1
    today = date.fromisoformat(args[0])
    elig = eligible(today)
    if not elig:
        return 0
    # least-recently-resurfaced first (never => sorts first)
    chosen = sorted(elig, key=lambda s: state.get(s, "0000-00-00"))[0]
    state[chosen] = args[0]
    save_state(state)
    print(chosen)
    return 0


if __name__ == "__main__":
    sys.exit(main())
