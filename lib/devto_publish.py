#!/usr/bin/env python3
"""devto_publish.py — cross-post a published devtocash article to dev.to via the
Forem REST API (the reliable replacement for the old Playwright browser bot).

Reads a local MDX post, strips its frontmatter, and POSTs it to dev.to with a
`canonical_url` pointing back at the original devtocash.com URL — so Google keeps
devtocash as the canonical source (no duplicate-content penalty) while the post
still gets dev.to reach + a backlink.

Usage:
    python3 devto_publish.py <slug> [--draft]
    python3 devto_publish.py 2026-07-13-some-post          # publish live
    python3 devto_publish.py 2026-07-13-some-post --draft  # create as draft

<slug> is the filename minus .mdx (also the devtocash URL slug).

Env (from /opt/dtc-agent/.env):
    DEVTO_API_KEY   required — Forem API key (dev.to/settings/extensions)

Exit codes: 0 ok, 1 usage/arg error, 2 missing key, 3 file/parse error, 4 API error.
"""
import json
import os
import re
import sys
import time
import urllib.request
import urllib.error

POSTS_DIR = "/opt/devtocash/content/posts"
ENV_FILE = "/opt/dtc-agent/.env"
SITE = "https://devtocash.com"
API = "https://dev.to/api/articles"

# dev.to allows at most 4 tags, lowercase alphanumeric only (no dashes/spaces).
MAX_TAGS = 4


def load_key():
    key = os.environ.get("DEVTO_API_KEY", "").strip()
    if not key and os.path.exists(ENV_FILE):
        with open(ENV_FILE) as f:
            for line in f:
                line = line.strip()
                if line.startswith("DEVTO_API_KEY="):
                    key = line.split("=", 1)[1].strip().strip('"').strip("'")
                    break
    return key


def parse_frontmatter(raw):
    """Split a `---`-delimited YAML frontmatter block from the markdown body.

    Minimal parser (no yaml dep): handles the flat scalar + inline/blocklist
    fields this repo's posts use (title, description, tags, category, etc.).
    """
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)$", raw, re.DOTALL)
    if not m:
        return {}, raw
    fm_text, body = m.group(1), m.group(2)
    fm = {}
    current_list = None
    for line in fm_text.split("\n"):
        if not line.strip():
            continue
        # block-list item ("  - foo") belonging to the previous key
        lm = re.match(r"^\s*-\s+(.*)$", line)
        if lm and current_list is not None:
            fm[current_list].append(lm.group(1).strip().strip('"').strip("'"))
            continue
        km = re.match(r'^(\w[\w-]*):\s*(.*)$', line)
        if not km:
            continue
        key, val = km.group(1), km.group(2).strip()
        if val == "":
            fm[key] = []            # start of a block list
            current_list = key
            continue
        current_list = None
        if val.startswith("[") and val.endswith("]"):
            items = [x.strip().strip('"').strip("'") for x in val[1:-1].split(",") if x.strip()]
            fm[key] = items
        else:
            fm[key] = val.strip('"').strip("'")
    return fm, body


def clean_tag(t):
    return re.sub(r"[^a-z0-9]", "", t.lower())


def absolutize_links(body):
    """Rewrite root-relative markdown links (`](/blog/x)`, `](/tools/x)`) to absolute
    devtocash.com URLs. On dev.to a relative link 404s; making them absolute both
    fixes that AND turns every internal link into a real backlink driving dev.to
    readers to the canonical site."""
    return re.sub(r"\]\((/(?:blog|tools|category|about)[^)]*)\)", rf"]({SITE}\1)", body)


def add_backlink_cta(body, canonical):
    """Wrap the article with an explicit top + bottom CTA back to the original on
    devtocash.com. dev.to only shows a subtle auto "Originally published at ..."
    line from canonical_url; these give readers a clear reason to click through,
    so the original site keeps getting referral traffic (not just the SEO signal)."""
    top = (f"> 💡 **Originally published on [devtocash.com]({canonical})** — where this "
           f"guide stays updated. I write hands-on DevOps/SRE deep-dives there weekly.\n\n")
    bottom = (f"\n\n---\n\n📌 **Read the latest version of this guide — plus the full library "
              f"of DevOps, SRE, Kubernetes, observability & cloud-cost guides — on "
              f"[devtocash.com]({canonical}).**")
    return top + body.strip() + bottom


def build_payload(slug, fm, body, published):
    canonical = f"{SITE}/blog/{slug}"
    body = add_backlink_cta(absolutize_links(body), canonical)
    raw_tags = fm.get("tags", [])
    if isinstance(raw_tags, str):
        raw_tags = [raw_tags]
    tags = []
    for t in raw_tags:
        ct = clean_tag(t)
        if ct and ct not in tags:
            tags.append(ct)
        if len(tags) >= MAX_TAGS:
            break
    article = {
        "title": fm.get("title", slug),
        "body_markdown": body.strip(),
        "published": published,
        "canonical_url": canonical,
        "tags": tags,
    }
    if fm.get("description"):
        article["description"] = fm["description"]
    return {"article": article}


def post_article(key, payload, max_retries=4):
    """POST to dev.to, honoring the strict Forem create rate limit.

    dev.to caps article creation aggressively (429 with a `retry-after`, and
    sometimes 403 under burst). Retry with backoff so an automated pipeline
    posting back-to-back doesn't fail spuriously.
    """
    data = json.dumps(payload).encode()
    delay = 5
    for attempt in range(max_retries):
        req = urllib.request.Request(API, data=data, method="POST", headers={
            "api-key": key,
            "Content-Type": "application/json",
            "Accept": "application/vnd.forem.api-v1+json",
            # dev.to sits behind Cloudflare, which 403s the default
            # "Python-urllib/x.y" User-Agent as a bot signature. A real UA is
            # REQUIRED for POST /articles to succeed (learned 2026-07-14).
            "User-Agent": "dtc-agent/1.0 (+https://devtocash.com)",
        })
        try:
            with urllib.request.urlopen(req, timeout=45) as resp:
                return resp.status, json.loads(resp.read())
        except urllib.error.HTTPError as e:
            body = e.read().decode()[:500]
            if e.code in (429, 403) and attempt < max_retries - 1:
                wait = int(e.headers.get("retry-after") or 0) or delay
                time.sleep(min(wait, 60))
                delay = min(delay * 2, 60)
                continue
            return e.code, {"error": body or f"HTTP {e.code}"}
    return 429, {"error": "rate-limited after retries"}


def main():
    args = [a for a in sys.argv[1:] if a]
    if not args:
        print("usage: devto_publish.py <slug> [--draft]", file=sys.stderr)
        return 1
    draft = "--draft" in args
    slugs = [a for a in args if not a.startswith("--")]
    if not slugs:
        print("usage: devto_publish.py <slug> [--draft]", file=sys.stderr)
        return 1
    slug = slugs[0]

    key = load_key()
    if not key:
        print("ERROR: DEVTO_API_KEY not set in env or .env", file=sys.stderr)
        return 2

    path = os.path.join(POSTS_DIR, f"{slug}.mdx")
    if not os.path.exists(path):
        print(f"ERROR: post not found: {path}", file=sys.stderr)
        return 3
    with open(path, encoding="utf-8") as f:
        raw = f.read()
    fm, body = parse_frontmatter(raw)
    if not body.strip():
        print("ERROR: empty body after frontmatter", file=sys.stderr)
        return 3

    payload = build_payload(slug, fm, body, published=not draft)
    status, resp = post_article(key, payload)
    if status in (200, 201):
        print(json.dumps({
            "ok": True,
            "devto_url": resp.get("url"),
            "id": resp.get("id"),
            "canonical_url": payload["article"]["canonical_url"],
            "published": payload["article"]["published"],
            "tags": payload["article"]["tags"],
        }, indent=2))
        return 0
    print(json.dumps({"ok": False, "status": status, "resp": resp}, indent=2), file=sys.stderr)
    return 4


if __name__ == "__main__":
    sys.exit(main())
