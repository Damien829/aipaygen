#!/usr/bin/env python3
"""Publish marketing posts to Dev.to. Run: python publish_marketing.py"""
import os
import sys
import requests

DEVTO_API_KEY = os.getenv("DEVTO_API_KEY", "")
if not DEVTO_API_KEY:
    # Try loading from .env
    env_path = os.path.join(os.path.dirname(__file__), ".env")
    if os.path.exists(env_path):
        for line in open(env_path):
            if line.startswith("DEVTO_API_KEY="):
                DEVTO_API_KEY = line.strip().split("=", 1)[1]
                break

if not DEVTO_API_KEY:
    print("DEVTO_API_KEY not found.")
    print("1. Go to https://dev.to/settings/extensions")
    print("2. Generate an API key")
    print("3. Add to .env: DEVTO_API_KEY=your_key_here")
    print("4. Run this script again")
    sys.exit(1)

MARKETING_DIR = os.path.join(os.path.dirname(__file__), "marketing")

POSTS = [
    {
        "file": "devto_built_on_pi5.md",
        "tags": ["ai", "raspberrypi", "python", "marketplace"],
    },
    {
        "file": "devto_cheapest_ai.md",
        "tags": ["ai", "api", "python", "webdev"],
    },
]

def publish(filename, tags):
    filepath = os.path.join(MARKETING_DIR, filename)
    if not os.path.exists(filepath):
        print(f"  SKIP: {filename} not found")
        return

    content = open(filepath).read()

    # Extract title from first # heading
    title = "AiPayGen"
    for line in content.split("\n"):
        if line.startswith("# "):
            # Skip the "r/SubredditName Post" style titles
            continue
        if line.startswith("**Title:**"):
            title = line.replace("**Title:**", "").strip()
            break
        if line.startswith("## ") and not title.startswith("AiPayGen"):
            title = line.replace("## ", "").strip()
            break

    # Strip the markdown header metadata (subreddit info, etc.)
    body_lines = []
    in_body = False
    for line in content.split("\n"):
        if line.startswith("**Body:**") or line.startswith("---"):
            in_body = True
            continue
        if in_body:
            body_lines.append(line)

    body = "\n".join(body_lines).strip() if body_lines else content

    article = {
        "article": {
            "title": title,
            "published": True,
            "body_markdown": body,
            "tags": tags[:4],
        }
    }

    resp = requests.post(
        "https://dev.to/api/articles",
        json=article,
        headers={"api-key": DEVTO_API_KEY, "Content-Type": "application/json"},
        timeout=15,
    )

    if resp.status_code in (200, 201):
        data = resp.json()
        print(f"  PUBLISHED: {data.get('url', 'unknown')}")
    elif resp.status_code == 422:
        print(f"  ALREADY EXISTS or validation error: {resp.text[:200]}")
    else:
        print(f"  FAILED ({resp.status_code}): {resp.text[:200]}")


if __name__ == "__main__":
    print("=== Publishing to Dev.to ===")
    print(f"API Key: {DEVTO_API_KEY[:8]}...")
    print()

    # Check if key works
    me = requests.get("https://dev.to/api/users/me", headers={"api-key": DEVTO_API_KEY}, timeout=10)
    if me.status_code == 200:
        user = me.json()
        print(f"Logged in as: @{user.get('username', '?')} ({user.get('name', '?')})")
    else:
        print(f"API key invalid ({me.status_code}). Get a new one from dev.to/settings/extensions")
        sys.exit(1)

    print()
    for post in POSTS:
        print(f"Publishing: {post['file']}")
        publish(post["file"], post["tags"])

    print("\nDone! Check your Dev.to profile.")
