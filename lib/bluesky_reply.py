#!/usr/bin/env python3
"""bluesky_reply.py — helper for value-first community engagement on Bluesky.

Two modes:
  --search   Print candidate posts to reply to (JSON), across our topic terms.
             Filters: English, not our own account, has real substance, not
             already replied to (state), and dedupes by author (one per author).
  --reply    Post a single reply to a target post URI.

GROWTH TACTIC (boss-approved 2026-07-19): reply with GENUINE technical value to
relevant DevOps/SRE conversations — NO link (link-drops to strangers = spam and
get a small account labeled). Max ~5/day. Establishes expertise so people click
through to the profile themselves.

State: /opt/dtc-agent/.dtc/bluesky_replied.json  (list of replied-to post URIs)
Env: BLUESKY_HANDLE, BLUESKY_APP_PASSWORD. Exit 0 ok, 2 creds, 3 args, 4 API.
"""
import argparse
import json
import os
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timezone

ENV_FILE = "/opt/dtc-agent/.env"
STATE = "/opt/dtc-agent/.dtc/bluesky_replied.json"
APPVIEW = "https://api.bsky.app"
PDS = "https://bsky.social"

# topic terms mirror our corpus strengths / content pillars
TERMS = [
    "kubernetes OOMKilled", "CrashLoopBackOff", "kubernetes cost", "kubecost",
    "platform engineering", "internal developer platform", "ebpf observability",
    "cilium", "docker image size", "multi-stage build", "AI agent devops",
    "MCP server kubernetes", "SRE incident", "opentelemetry tracing",
    "argocd gitops", "terraform", "finops kubernetes",
]
MAX_CANDIDATES = 12


def env(k):
    v = os.environ.get(k, "")
    if not v and os.path.exists(ENV_FILE):
        for line in open(ENV_FILE):
            if line.strip().startswith(f"{k}="):
                return line.strip().split("=", 1)[1].strip().strip('"').strip("'")
    return v


def load_state():
    if os.path.exists(STATE):
        try:
            return set(json.load(open(STATE)))
        except Exception:
            return set()
    return set()


def save_state(s):
    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    json.dump(sorted(s), open(STATE, "w"), indent=2)


def login():
    h = env("BLUESKY_HANDLE"); p = env("BLUESKY_APP_PASSWORD")
    if not h or not p:
        print("ERROR: BLUESKY creds not set", file=sys.stderr); sys.exit(2)
    r = api_post(f"{PDS}/xrpc/com.atproto.server.createSession",
                 {"identifier": h, "password": p})
    return h, r["accessJwt"], r["did"]


def api_post(url, data, tok=None):
    hdr = {"Content-Type": "application/json"}
    if tok:
        hdr["Authorization"] = f"Bearer {tok}"
    return json.loads(urllib.request.urlopen(
        urllib.request.Request(url, json.dumps(data).encode(), hdr), timeout=25).read())


def api_get(url, tok):
    return json.loads(urllib.request.urlopen(
        urllib.request.Request(url, headers={"Authorization": f"Bearer {tok}"}), timeout=25).read())


def do_search(handle, tok):
    seen_state = load_state()
    out, authors = [], set()
    for term in TERMS:
        url = (f"{APPVIEW}/xrpc/app.bsky.feed.searchPosts?q="
               f"{urllib.parse.quote(term)}&limit=8&sort=latest")
        try:
            posts = api_get(url, tok).get("posts", [])
        except Exception:
            continue
        for p in posts:
            uri = p["uri"]
            a = p["author"]["handle"]
            rec = p.get("record", {})
            txt = (rec.get("text") or "").strip()
            if a == handle:                      # never reply to ourselves
                continue
            if uri in seen_state:                # already replied
                continue
            if a in authors:                     # one per author per run
                continue
            if len(txt) < 40:                    # skip empty/thin posts
                continue
            if rec.get("langs") and "en" not in rec.get("langs", []):
                continue
            authors.add(a)
            out.append({
                "uri": uri, "cid": p["cid"], "author": a,
                "text": txt[:280], "term": term,
                "likes": p.get("likeCount", 0), "replies": p.get("replyCount", 0),
            })
        if len(out) >= MAX_CANDIDATES:
            break
    print(json.dumps(out[:MAX_CANDIDATES], indent=2))
    return 0


def do_reply(handle, tok, did, uri, text):
    if len(text) > 300:
        print(json.dumps({"ok": False, "error": f"text {len(text)}>300"}), file=sys.stderr)
        return 3
    state = load_state()
    if uri in state:
        print(json.dumps({"ok": False, "error": "already replied to this uri"}), file=sys.stderr)
        return 3
    posts = api_get(f"{APPVIEW}/xrpc/app.bsky.feed.getPosts?uris={urllib.parse.quote(uri)}", tok).get("posts", [])
    if not posts:
        print(json.dumps({"ok": False, "error": "target not found"}), file=sys.stderr)
        return 4
    p = posts[0]
    strong = {"uri": p["uri"], "cid": p["cid"]}
    rec = p.get("record", {})
    root = rec["reply"]["root"] if isinstance(rec.get("reply"), dict) else strong
    record = {"$type": "app.bsky.feed.post", "text": text,
              "createdAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
              "langs": ["en"], "reply": {"root": root, "parent": strong}}
    r = api_post(f"{PDS}/xrpc/com.atproto.repo.createRecord",
                 {"repo": did, "collection": "app.bsky.feed.post", "record": record}, tok)
    state.add(uri); save_state(state)
    rkey = r["uri"].split("/")[-1]
    print(json.dumps({"ok": True, "url": f"https://bsky.app/profile/{handle}/post/{rkey}",
                      "replied_to": uri}))
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--search", action="store_true")
    ap.add_argument("--reply", action="store_true")
    ap.add_argument("--uri")
    ap.add_argument("--text")
    a = ap.parse_args()
    handle, tok, did = login()
    if a.search:
        return do_search(handle, tok)
    if a.reply:
        if not a.uri or not a.text:
            print("ERROR: --reply needs --uri and --text", file=sys.stderr); return 3
        return do_reply(handle, tok, did, a.uri, a.text)
    print("ERROR: pass --search or --reply", file=sys.stderr); return 3


if __name__ == "__main__":
    sys.exit(main())
