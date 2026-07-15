#!/usr/bin/env python3
"""bluesky_thread.py — post a multi-post THREAD (reply chain) to Bluesky.

Threads outperform single posts for tech content: each post is its own impression,
the 🧵 format signals depth, and the chain dwells readers to the link at the end.
AT Protocol threads = each post's record carries a `reply` with {root, parent}
refs (uri+cid) pointing back up the chain.

Input: a JSON array of post strings on stdin, OR --file <path> to a JSON array.
The devtocash link (in the LAST post, on its own line) gets a clickable facet +
preview card. Each post must be <=300 chars.

Usage:
    echo '["hook 🧵","point 1","point 2","... 👇\\nhttps://devtocash.com/blog/x"]' \
        | python3 bluesky_thread.py --link https://devtocash.com/blog/x --slug x

Env: BLUESKY_HANDLE, BLUESKY_APP_PASSWORD. Exit 0 ok, 2 creds, 3 args, 4 API.
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
UA = "dtc-agent/1.0 (+https://devtocash.com)"


def env(k):
    v = os.environ.get(k, "")
    if not v and os.path.exists(ENV_FILE):
        for line in open(ENV_FILE):
            if line.strip().startswith(f"{k}="):
                return line.strip().split("=", 1)[1].strip().strip('"').strip("'")
    return v


def api(path, payload, token=None):
    headers = {"Content-Type": "application/json", "User-Agent": UA}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(f"{PDS}/xrpc/{path}", data=json.dumps(payload).encode(),
                                 method="POST", headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, {"error": e.read().decode()[:300]}


def link_facets(text, url):
    idx = text.find(url)
    if idx < 0:
        return []
    bs = len(text[:idx].encode("utf-8"))
    return [{"index": {"byteStart": bs, "byteEnd": bs + len(url.encode("utf-8"))},
             "features": [{"$type": "app.bsky.richtext.facet#link", "uri": url}]}]


def frontmatter(slug):
    path = os.path.join(POSTS_DIR, f"{slug}.mdx")
    if not slug or not os.path.exists(path):
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
    ap.add_argument("--link", default="")
    ap.add_argument("--slug", default="")
    ap.add_argument("--file")
    a = ap.parse_args()

    handle, app_pw = env("BLUESKY_HANDLE"), env("BLUESKY_APP_PASSWORD")
    if not handle or not app_pw:
        print("ERROR: BLUESKY_HANDLE / BLUESKY_APP_PASSWORD not set", file=sys.stderr)
        return 2

    raw = open(a.file).read() if a.file else sys.stdin.read()
    try:
        posts = [p for p in json.loads(raw) if p.strip()]
    except Exception as e:
        print(f"ERROR: input must be a JSON array of strings ({e})", file=sys.stderr)
        return 3
    if not posts:
        print("ERROR: empty thread", file=sys.stderr)
        return 3
    over = [(i, len(p)) for i, p in enumerate(posts) if len(p) > 300]
    if over:
        print(f"ERROR: posts over 300 chars: {over}", file=sys.stderr)
        return 3

    st, sess = api("com.atproto.server.createSession", {"identifier": handle, "password": app_pw})
    if "accessJwt" not in sess:
        print(json.dumps({"ok": False, "stage": "login", "resp": sess}), file=sys.stderr)
        return 4
    jwt, did = sess["accessJwt"], sess["did"]
    fm = frontmatter(a.slug)
    link = a.link or (f"{SITE}/blog/{a.slug}" if a.slug else "")

    root = None      # {uri, cid} of first post
    parent = None    # {uri, cid} of previous post
    urls = []
    for i, text in enumerate(posts):
        rec = {"$type": "app.bsky.feed.post", "text": text,
               "createdAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
               "langs": ["en"]}
        if parent:
            rec["reply"] = {"root": root, "parent": parent}
        f = link_facets(text, link) if link else []
        if f:
            rec["facets"] = f
        # preview card only on the post that actually contains the link
        if link and link in text:
            rec["embed"] = {"$type": "app.bsky.embed.external", "external": {
                "uri": link, "title": fm.get("title", "devtocash.com")[:300],
                "description": (fm.get("description", "") or "DevOps, SRE & cloud engineering.")[:1000]}}
        st, res = api("com.atproto.repo.createRecord",
                      {"repo": did, "collection": "app.bsky.feed.post", "record": rec}, token=jwt)
        if st != 200 or not res.get("uri"):
            print(json.dumps({"ok": False, "at_post": i, "status": st, "resp": res}), file=sys.stderr)
            return 4
        ref = {"uri": res["uri"], "cid": res["cid"]}
        if root is None:
            root = ref
        parent = ref
        rkey = res["uri"].split("/")[-1]
        urls.append(f"https://bsky.app/profile/{handle}/post/{rkey}")

    print(json.dumps({"ok": True, "posts": len(urls), "thread_url": urls[0], "all": urls}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
