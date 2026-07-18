#!/usr/bin/env python3
"""buffer_thread.py — post a THREAD to Twitter or Threads via Buffer GraphQL.

Buffer models a thread as: createPost.text = the FIRST post, and
metadata.<platform>.thread = an array of ThreadedPostInput ({text, assets:[]})
for the subsequent posts. Threads also supports a `topic` tag; use
type:"post" (NOT "thread") for the thread array.

Input: JSON array of post strings (stdin or --file). First element = lead post,
rest = thread continuation.

Usage:
    echo '["lead","2","3 ... https://devtocash.com/blog/x"]' \
      | python3 buffer_thread.py --platform twitter --channel <id>
    echo '[...]' | python3 buffer_thread.py --platform threads --channel <id> --topic "DevOps"

Env: BUFFER_ACCESS_TOKEN. Exit 0 ok, 2 creds, 3 args, 4 API.
"""
import argparse
import json
import os
import sys
import time
import urllib.request
import urllib.error

ENV_FILE = "/opt/dtc-agent/.env"
URL = "https://api.buffer.com/graphql"

# per-post char ceilings (Buffer/platform)
LIMITS = {"twitter": 280, "threads": 500}


def env(k):
    v = os.environ.get(k, "")
    if not v and os.path.exists(ENV_FILE):
        for line in open(ENV_FILE):
            if line.strip().startswith(f"{k}="):
                return line.strip().split("=", 1)[1].strip().strip('"').strip("'")
    return v


def gql(token, query, variables):
    req = urllib.request.Request(URL, data=json.dumps({"query": query, "variables": variables}).encode(),
                                 method="POST",
                                 headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        return {"errors": [{"message": e.read().decode()[:300]}]}


MUT = """mutation CreatePost($input: CreatePostInput!) {
  createPost(input: $input) {
    __typename
    ... on PostActionSuccess { post { id } }
    ... on InvalidInputError { message }
    ... on UnauthorizedError { message }
    ... on LimitReachedError { message }
  }
}"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--platform", required=True, choices=["twitter", "threads"])
    ap.add_argument("--channel", required=True)
    ap.add_argument("--topic", default="")
    ap.add_argument("--file")
    a = ap.parse_args()

    token = env("BUFFER_ACCESS_TOKEN")
    if not token:
        print("ERROR: BUFFER_ACCESS_TOKEN not set", file=sys.stderr)
        return 2

    raw = open(a.file).read() if a.file else sys.stdin.read()
    try:
        posts = [p for p in json.loads(raw) if p.strip()]
    except Exception as e:
        print(f"ERROR: input must be a JSON array of strings ({e})", file=sys.stderr)
        return 3
    if len(posts) < 2:
        print("ERROR: a thread needs >=2 posts", file=sys.stderr)
        return 3
    lim = LIMITS[a.platform]
    over = [(i, len(p)) for i, p in enumerate(posts) if len(p) > lim]
    if over:
        print(f"ERROR: {a.platform} posts over {lim} chars: {over}", file=sys.stderr)
        return 3

    lead, rest = posts[0], posts[1:]
    thread = [{"text": t, "assets": []} for t in rest]
    if a.platform == "twitter":
        meta = {"twitter": {"thread": thread}}
    else:
        meta = {"threads": {"type": "post", "thread": thread}}
        if a.topic:
            meta["threads"]["topic"] = a.topic

    inp = {"schedulingType": "automatic", "mode": "shareNow", "channelId": a.channel,
           "text": lead, "assets": [], "metadata": meta, "source": "dtc-agent"}
    res = gql(token, MUT, {"input": inp})
    if res.get("errors"):
        print(json.dumps({"ok": False, "errors": res["errors"]}), file=sys.stderr)
        return 4
    cp = res["data"]["createPost"]
    if cp["__typename"] == "PostActionSuccess":
        pid = cp["post"]["id"]
        # Poll until the post reaches a TERMINAL status. Threads publishes async and
        # sits in "sending" for a while; reporting that as success once hid a real
        # Meta-side failure (2026-07-17 multi-agent thread errored silently).
        VERIFY = ('query($i: PostInput!){ post(input:$i){ status externalLink '
                  'error { ... on PostPublishingError { message } } } }')
        p = {}
        for _ in range(10):                      # up to ~60s
            v = gql(token, VERIFY, {"i": {"id": pid}})
            p = v.get("data", {}).get("post") or {}
            if p.get("status") in ("sent", "error"):
                break
            time.sleep(6)
        st = p.get("status")
        out = {"ok": st == "sent", "id": pid, "status": st,
               "externalLink": p.get("externalLink"), "posts": len(posts)}
        err = (p.get("error") or {}).get("message")
        if err:
            out["error"] = err
        if st != "sent":
            out["warning"] = ("publishing failed — retry later" if st == "error"
                              else "still not 'sent' after 60s — verify in Buffer")
            print(json.dumps(out, indent=2), file=sys.stderr)
            return 4
        print(json.dumps(out, indent=2))
        return 0
    print(json.dumps({"ok": False, "type": cp["__typename"], "message": cp.get("message")}), file=sys.stderr)
    return 4


if __name__ == "__main__":
    sys.exit(main())
