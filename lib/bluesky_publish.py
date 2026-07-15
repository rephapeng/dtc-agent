#!/usr/bin/env python3
"""bluesky_publish.py — post to Bluesky (AT Protocol) with a clickable link + preview card.

Bluesky needs the link made clickable via a "facet" indexed by UTF-8 BYTE offsets
(not char offsets), and a nice preview needs an external embed. This handles both.

Usage:
    python3 bluesky_publish.py --text "<post text incl the URL>" --link "<url>"
    # or derive a simple post from an article:
    python3 bluesky_publish.py --slug <slug>

Env (/opt/dtc-agent/.env): BLUESKY_HANDLE, BLUESKY_APP_PASSWORD
Text limit: 300 graphemes. Exit: 0 ok, 2 no creds, 3 bad args, 4 API error.
"""
import argparse
import json
import os
import re
import sys
import urllib.request
import urllib.error
from datetime import datetime, timezone

ENV_FILE = "/opt/dtc-agent/.env"
POSTS_DIR = "/opt/devtocash/content/posts"
SITE = "https://devtocash.com"
PDS = "https://bsky.social"


def env(k):
    v = os.environ.get(k, "")
    if not v and os.path.exists(ENV_FILE):
        for line in open(ENV_FILE):
            if line.strip().startswith(f"{k}="):
                return line.strip().split("=", 1)[1].strip().strip('"').strip("'")
    return v


def api(path, payload, token=None):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(f"{PDS}/xrpc/{path}", data=json.dumps(payload).encode(),
                                 method="POST", headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, {"error": e.read().decode()[:300]}


def make_link_facets(text, url):
    """Facet the FIRST occurrence of url in text, using UTF-8 byte offsets."""
    idx = text.find(url)
    if idx < 0:
        return []
    byte_start = len(text[:idx].encode("utf-8"))
    byte_end = byte_start + len(url.encode("utf-8"))
    return [{
        "index": {"byteStart": byte_start, "byteEnd": byte_end},
        "features": [{"$type": "app.bsky.richtext.facet#link", "uri": url}],
    }]


def frontmatter(slug):
    path = os.path.join(POSTS_DIR, f"{slug}.mdx")
    if not os.path.exists(path):
        return {}
    raw = open(path, encoding="utf-8").read()
    fm = {}
    m = re.match(r"^---\s*\n(.*?)\n---", raw, re.DOTALL)
    if m:
        for line in m.group(1).split("\n"):
            km = re.match(r'^(\w+):\s*"?(.*?)"?\s*$', line)
            if km:
                fm[km.group(1)] = km.group(2)
    return fm


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--text")
    ap.add_argument("--link")
    ap.add_argument("--slug")
    a = ap.parse_args()

    handle = env("BLUESKY_HANDLE")
    app_pw = env("BLUESKY_APP_PASSWORD")
    if not handle or not app_pw:
        print("ERROR: BLUESKY_HANDLE / BLUESKY_APP_PASSWORD not set", file=sys.stderr)
        return 2

    fm = frontmatter(a.slug) if a.slug else {}
    link = a.link or (f"{SITE}/blog/{a.slug}" if a.slug else "")
    if a.text:
        text = a.text
    elif a.slug:
        title = fm.get("title", a.slug)
        text = f"{title}\n\n{link}"
    else:
        print("ERROR: need --text or --slug", file=sys.stderr)
        return 3

    if len(text) > 300:
        print(f"ERROR: text is {len(text)} chars, Bluesky max is 300", file=sys.stderr)
        return 3

    st, sess = api("com.atproto.server.createSession",
                   {"identifier": handle, "password": app_pw})
    if "accessJwt" not in sess:
        print(json.dumps({"ok": False, "stage": "login", "resp": sess}), file=sys.stderr)
        return 4
    jwt, did = sess["accessJwt"], sess["did"]

    record = {
        "$type": "app.bsky.feed.post",
        "text": text,
        "createdAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "langs": ["en"],
    }
    facets = make_link_facets(text, link) if link else []
    if facets:
        record["facets"] = facets
    # Rich preview card (no thumb — avoids a blob upload; still shows title/desc).
    if link:
        record["embed"] = {
            "$type": "app.bsky.embed.external",
            "external": {
                "uri": link,
                "title": fm.get("title", "devtocash.com")[:300],
                "description": (fm.get("description", "") or "DevOps, SRE & cloud engineering.")[:1000],
            },
        }

    st, res = api("com.atproto.repo.createRecord",
                  {"repo": did, "collection": "app.bsky.feed.post", "record": record}, token=jwt)
    if st == 200 and res.get("uri"):
        rkey = res["uri"].split("/")[-1]
        url = f"https://bsky.app/profile/{handle}/post/{rkey}"
        print(json.dumps({"ok": True, "bsky_url": url, "uri": res["uri"]}, indent=2))
        return 0
    print(json.dumps({"ok": False, "status": st, "resp": res}, indent=2), file=sys.stderr)
    return 4


if __name__ == "__main__":
    sys.exit(main())
