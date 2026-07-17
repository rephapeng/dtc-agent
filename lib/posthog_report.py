#!/usr/bin/env python3
"""posthog_report.py — pull a compact PostHog product-analytics snapshot for
devtocash and print it, to fold into the daily/weekly report alongside GA4+GSC.

PostHog complements GA4: it's the source of truth for TOP PAGES, REFERRERS, and
on-site tool/engagement events that GA4 buckets less cleanly. Numbers run lower
than GA4 (adblockers hit the JS SDK harder) — treat it as directional + for the
breakdowns, not as the headline session count.

Creds from /opt/dtc-agent/.env: POSTHOG_PERSONAL_API_KEY, POSTHOG_PROJECT_ID,
POSTHOG_HOST (default https://us.posthog.com). Queries via the HogQL query API.

Usage:  python3 posthog_report.py           # human-readable text
        python3 posthog_report.py --json     # machine-readable JSON
        python3 posthog_report.py --days 28  # window for top-pages/referrers (default 7)
Exit 0 ok, 2 creds, 4 API.
"""
import argparse
import json
import os
import sys
import urllib.request
import urllib.error

ENV_FILE = "/opt/dtc-agent/.env"


def env(k, default=""):
    v = os.environ.get(k, "")
    if not v and os.path.exists(ENV_FILE):
        for line in open(ENV_FILE):
            if line.strip().startswith(f"{k}="):
                return line.strip().split("=", 1)[1].strip().strip('"').strip("'")
    return v or default


def hogql(host, pid, key, query):
    url = f"{host.rstrip('/')}/api/projects/{pid}/query/"
    body = json.dumps({"query": {"kind": "HogQLQuery", "query": query}}).encode()
    req = urllib.request.Request(
        url, data=body, method="POST",
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=45) as r:
            return json.loads(r.read()).get("results", [])
    except urllib.error.HTTPError as e:
        raise SystemExit(f"PostHog API error {e.code}: {e.read().decode()[:200]}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--days", type=int, default=7)
    a = ap.parse_args()

    key = env("POSTHOG_PERSONAL_API_KEY")
    pid = env("POSTHOG_PROJECT_ID")
    host = env("POSTHOG_HOST", "https://us.posthog.com")
    if not key or not pid:
        print("ERROR: POSTHOG_PERSONAL_API_KEY / POSTHOG_PROJECT_ID not set", file=sys.stderr)
        return 2
    d = a.days

    daily = hogql(host, pid, key,
        "SELECT toString(toDate(timestamp)) AS d, count() AS pv, uniq(person_id) AS visitors "
        "FROM events WHERE event='$pageview' AND timestamp >= now() - INTERVAL 7 DAY "
        "GROUP BY d ORDER BY d")
    pages = hogql(host, pid, key,
        f"SELECT properties.$pathname AS path, count() AS views FROM events "
        f"WHERE event='$pageview' AND timestamp >= now() - INTERVAL {d} DAY "
        f"GROUP BY path ORDER BY views DESC LIMIT 12")
    refs = hogql(host, pid, key,
        f"SELECT coalesce(nullIf(properties.$referring_domain,''),'(direct)') AS ref, count() AS views "
        f"FROM events WHERE event='$pageview' AND timestamp >= now() - INTERVAL {d} DAY "
        f"GROUP BY ref ORDER BY views DESC LIMIT 10")
    # non-pageview custom events (tool usage, clicks) — engagement signal GA4 misses
    events = hogql(host, pid, key,
        f"SELECT event, count() AS n FROM events "
        f"WHERE event NOT IN ('$pageview','$pageleave','$autocapture','$web_vitals') "
        f"AND timestamp >= now() - INTERVAL {d} DAY GROUP BY event ORDER BY n DESC LIMIT 10")

    data = {
        "window_days": d,
        "daily_pageviews": [{"date": r[0], "pageviews": r[1], "visitors": r[2]} for r in daily],
        "top_pages": [{"path": r[0], "views": r[1]} for r in pages],
        "referrers": [{"ref": r[0], "views": r[1]} for r in refs],
        "custom_events": [{"event": r[0], "count": r[1]} for r in events],
    }

    if a.json:
        print(json.dumps(data, indent=2))
        return 0

    print("=== PostHog snapshot (product analytics — complements GA4) ===")
    print(f"\nDaily pageviews / visitors (last 7d):")
    for r in data["daily_pageviews"]:
        print(f"  {r['date']}  pv={r['pageviews']:>4}  visitors={r['visitors']:>3}")
    print(f"\nTop pages (last {d}d):")
    for r in data["top_pages"]:
        print(f"  {r['views']:>4}  {r['path']}")
    print(f"\nReferrers (last {d}d):")
    for r in data["referrers"]:
        print(f"  {r['views']:>4}  {r['ref']}")
    if data["custom_events"]:
        print(f"\nCustom events (engagement, last {d}d):")
        for r in data["custom_events"]:
            print(f"  {r['count']:>4}  {r['event']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
