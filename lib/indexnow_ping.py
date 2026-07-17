#!/usr/bin/env python3
"""indexnow_ping.py — notify Bing / Yandex / DuckDuckGo (via Bing) / Seznam of new
or updated URLs instantly via the IndexNow protocol.

IndexNow does NOT reach Google (Google doesn't participate), but it gets pages in
front of Bing + Yandex fast, and DuckDuckGo sources from Bing. Ownership is proven
by a key file served at https://devtocash.com/<key>.txt (via nginx).

Usage:
    python3 indexnow_ping.py <url> [<url> ...]      # ping specific URLs
    python3 indexnow_ping.py --slug <slug>          # -> https://devtocash.com/blog/<slug>

Env (/opt/dtc-agent/.env): INDEXNOW_KEY. Exit 0 ok, 2 no key, 3 args, 4 API error.
"""
import json
import os
import sys
import urllib.request
import urllib.error

ENV_FILE = "/opt/dtc-agent/.env"
HOST = "devtocash.com"
SITE = "https://devtocash.com"
ENDPOINT = "https://api.indexnow.org/indexnow"  # shared endpoint -> fans out to all engines
UA = "dtc-agent/1.0 (+https://devtocash.com)"


def env(k):
    v = os.environ.get(k, "")
    if not v and os.path.exists(ENV_FILE):
        for line in open(ENV_FILE):
            if line.strip().startswith(f"{k}="):
                return line.strip().split("=", 1)[1].strip().strip('"').strip("'")
    return v


def main():
    args = [a for a in sys.argv[1:] if a]
    key = env("INDEXNOW_KEY")
    if not key:
        print("ERROR: INDEXNOW_KEY not set", file=sys.stderr)
        return 2

    urls = []
    i = 0
    while i < len(args):
        if args[i] == "--slug" and i + 1 < len(args):
            urls.append(f"{SITE}/blog/{args[i+1]}")
            i += 2
        else:
            urls.append(args[i] if args[i].startswith("http") else f"{SITE}{args[i]}")
            i += 1
    if not urls:
        print("usage: indexnow_ping.py <url|--slug slug> [...]", file=sys.stderr)
        return 3

    payload = {
        "host": HOST,
        "key": key,
        "keyLocation": f"{SITE}/{key}.txt",
        "urlList": urls,
    }
    req = urllib.request.Request(ENDPOINT, data=json.dumps(payload).encode(), method="POST",
                                 headers={"Content-Type": "application/json; charset=utf-8",
                                          "User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            # IndexNow: 200 = accepted, 202 = accepted/pending validation
            print(json.dumps({"ok": True, "status": r.status, "submitted": len(urls), "urls": urls}))
            return 0
    except urllib.error.HTTPError as e:
        body = e.read().decode()[:200]
        # 200/202 never raise; common failures: 403 key mismatch, 422 invalid url
        print(json.dumps({"ok": False, "status": e.code, "error": body, "urls": urls}), file=sys.stderr)
        return 4


if __name__ == "__main__":
    sys.exit(main())
