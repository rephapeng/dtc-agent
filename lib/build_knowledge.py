#!/usr/bin/env python3
"""
build_knowledge.py — scans the REAL devtocash content and emits a compact
grounding manifest so the agent never "leaves context": it can only reference
slugs, categories, tags and internal links that already exist.

Outputs:
  /opt/dtc-agent/knowledge/KNOWLEDGE.md   (human/LLM-readable, injected into every prompt)
  /opt/dtc-agent/knowledge/knowledge.json (machine-readable)

No external deps (no gray-matter/pyyaml needed) — we parse the simple, flat
frontmatter used across content/posts.
"""
import json
import os
import re
import sys

POSTS_DIR = "/opt/devtocash/content/posts"
PAGES_DIR = "/opt/devtocash/content/pages"
# Knowledge lives INSIDE the devtocash project (primary store); selfmem MCP backs it up.
OUT_DIR = "/opt/devtocash/.dtc/knowledge"


def parse_frontmatter(text):
    """Parse the leading --- ... --- block. Values are strings, quoted strings,
    or simple ["a","b"] lists. Good enough for this repo's flat schema."""
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n", text, re.DOTALL)
    if not m:
        return {}
    fm = {}
    for line in m.group(1).splitlines():
        if not line.strip() or ":" not in line:
            continue
        key, _, val = line.partition(":")
        key = key.strip()
        val = val.strip()
        if val.startswith("[") and val.endswith("]"):
            items = re.findall(r'"([^"]*)"|\'([^\']*)\'|([^,\[\]]+)', val[1:-1])
            cleaned = [ (a or b or c).strip().strip('"').strip("'").strip() for (a, b, c) in items ]
            fm[key] = [ t for t in cleaned if t ]
        else:
            fm[key] = val.strip('"').strip("'")
    return fm


def collect(dir_path):
    posts = []
    if not os.path.isdir(dir_path):
        return posts
    for name in sorted(os.listdir(dir_path)):
        if not name.endswith(".mdx"):
            continue
        path = os.path.join(dir_path, name)
        with open(path, encoding="utf-8", errors="replace") as f:
            text = f.read()
        fm = parse_frontmatter(text)
        body = re.sub(r"^---\s*\n.*?\n---\s*\n", "", text, flags=re.DOTALL)
        slug = name[:-4]  # filename minus .mdx == URL slug
        # internal links this post already points to (/blog/<slug>)
        links = sorted(set(re.findall(r"/blog/([a-z0-9\-]+)", body)))
        # H2/H3 headings = what the post actually covers
        headings = re.findall(r"^#{2,3}\s+(.+)$", body, re.MULTILINE)
        posts.append({
            "slug": slug,
            "url": f"/blog/{slug}",
            "title": fm.get("title", ""),
            "description": fm.get("description", ""),
            "date": fm.get("date", ""),
            "category": fm.get("category", ""),
            "tags": fm.get("tags", []) if isinstance(fm.get("tags"), list) else [],
            "words": len(body.split()),
            "internal_links": links,
            "headings": headings[:12],
        })
    return posts


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    posts = collect(POSTS_DIR)
    pages = collect(PAGES_DIR)

    categories = {}
    tags = {}
    for p in posts:
        categories[p["category"]] = categories.get(p["category"], 0) + 1
        for t in p["tags"]:
            tags[t] = tags.get(t, 0) + 1

    data = {
        "posts_dir": POSTS_DIR,
        "post_count": len(posts),
        "categories": categories,
        "tags": tags,
        "posts": posts,
        "pages": [{"slug": p["slug"], "title": p["title"]} for p in pages],
    }
    with open(os.path.join(OUT_DIR, "knowledge.json"), "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    # ---- KNOWLEDGE.md : compact grounding doc ----
    lines = []
    lines.append("# devtocash — GROUNDING KNOWLEDGE (auto-generated, do not edit by hand)")
    lines.append("")
    lines.append(f"Total published posts: **{len(posts)}**. Live path: `{POSTS_DIR}`.")
    lines.append("URL pattern: `/blog/<filename-without-.mdx>`. New file: `content/posts/YYYY-MM-DD-kebab-slug.mdx`.")
    lines.append("")
    lines.append("## Categories in use (count)")
    lines.append(", ".join(f"`{c or '(none)'}`={n}" for c, n in sorted(categories.items(), key=lambda x: -x[1])))
    lines.append("")
    lines.append("## Top tags in use (count)")
    top_tags = sorted(tags.items(), key=lambda x: -x[1])[:40]
    lines.append(", ".join(f"`{t}`({n})" for t, n in top_tags))
    lines.append("")
    lines.append("## Existing posts (slug — title — category) — link/duplicate ONLY against these")
    for p in posts:
        lines.append(f"- `{p['slug']}` — {p['title']} — [{p['category']}] ({p['words']}w)")
    lines.append("")
    lines.append("## Static pages")
    for p in pages:
        lines.append(f"- `{p['slug']}` — {p['title']}")
    lines.append("")
    lines.append("## Hard grounding rules")
    lines.append("- Cover topics that FIT this niche (DevOps/SRE + Trading/Finance + career/tools). Do NOT drift outside it.")
    lines.append("- Do NOT duplicate an existing slug/topic above. Check the list before proposing a title.")
    lines.append("- Internal links MUST point to a slug that exists above (`/blog/<slug>`). Never invent a slug.")
    lines.append("- Category MUST be one already in use above. Tags SHOULD reuse existing tags where sensible.")
    with open(os.path.join(OUT_DIR, "KNOWLEDGE.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")

    print(f"[build_knowledge] {len(posts)} posts, {len(pages)} pages, "
          f"{len(categories)} categories, {len(tags)} tags -> {OUT_DIR}/KNOWLEDGE.md")


if __name__ == "__main__":
    sys.exit(main())
