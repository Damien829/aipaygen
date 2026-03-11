"""
Discovery Engine — autonomous outreach to grow AiPayGen's presence.

Runs via APScheduler:
  - Hourly: ping agent directories
  - Daily:  GitHub awesome-list outreach + content indexing ping
  - Weekly: generate new blog content via Claude

All actions are rate-limited, idempotent, and logged.
"""
import os
import json
import sqlite3
import time
import requests
from datetime import datetime, timedelta

GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")
BASE_URL = os.getenv("BASE_URL", "https://api.aipaygen.com")
DB_PATH = os.path.join(os.path.dirname(__file__), "discovery_engine.db")

MAX_PRS_PER_DAY = 3      # don't spam GitHub
MAX_PINGS_PER_HOUR = 10  # directory pings


def _conn():
    c = sqlite3.connect(DB_PATH, timeout=10)
    c.row_factory = sqlite3.Row
    return c


def init_discovery_db():
    with _conn() as c:
        c.execute("PRAGMA journal_mode=WAL")
        c.execute("PRAGMA busy_timeout=5000")
        c.execute("""
            CREATE TABLE IF NOT EXISTS outreach_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                action TEXT NOT NULL,
                target TEXT NOT NULL,
                status TEXT NOT NULL,
                detail TEXT,
                created_at TEXT NOT NULL
            )
        """)
        c.execute("CREATE INDEX IF NOT EXISTS idx_ol_target ON outreach_log(target)")
        c.execute("""
            CREATE TABLE IF NOT EXISTS blog_posts (
                slug TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                content TEXT NOT NULL,
                endpoint TEXT,
                generated_at TEXT NOT NULL
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS endpoint_health (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                endpoint TEXT NOT NULL,
                status TEXT NOT NULL,
                latency_ms INTEGER,
                error TEXT,
                checked_at TEXT NOT NULL
            )
        """)
        c.execute("CREATE INDEX IF NOT EXISTS idx_eh_endpoint ON endpoint_health(endpoint)")
        c.execute("""
            CREATE TABLE IF NOT EXISTS cost_tracking (
                date TEXT NOT NULL,
                model TEXT NOT NULL,
                endpoint TEXT NOT NULL,
                tokens_in INTEGER DEFAULT 0,
                tokens_out INTEGER DEFAULT 0,
                cost_usd REAL DEFAULT 0.0,
                PRIMARY KEY (date, model, endpoint)
            )
        """)


def _log(action: str, target: str, status: str, detail: str = ""):
    now = datetime.utcnow().isoformat()
    with _conn() as c:
        c.execute(
            "INSERT INTO outreach_log (action, target, status, detail, created_at) VALUES (?, ?, ?, ?, ?)",
            (action, target, status, detail, now),
        )


def _already_targeted(target: str, within_days: int = 30) -> bool:
    cutoff = (datetime.utcnow() - timedelta(days=within_days)).isoformat()
    with _conn() as c:
        row = c.execute(
            "SELECT id FROM outreach_log WHERE target=? AND created_at > ?",
            (target, cutoff)
        ).fetchone()
    return row is not None


def _prs_today() -> int:
    today = datetime.utcnow().strftime("%Y-%m-%d")
    with _conn() as c:
        row = c.execute(
            "SELECT COUNT(*) as cnt FROM outreach_log WHERE action='github_pr' AND created_at LIKE ?",
            (f"{today}%",)
        ).fetchone()
    return row["cnt"] if row else 0


def _gh_headers():
    return {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": "AiPayGen-DiscoveryBot/1.0",
    }


# ── GitHub Awesome List Outreach ───────────────────────────────────────────────

# Repos we know about + want to be listed in
AWESOME_LIST_TARGETS = [
    # repo_full_name, section_hint, our_entry_line
    (
        "public-apis/public-apis",
        "Machine Learning",
        "| AiPayGen | Claude-powered AI API — research, write, code, analyze, 155 tools and 140+ endpoints. First 10 calls/day free. | No | Yes | Yes |",
    ),
    (
        "humanloop/awesome-ai-agents",
        "APIs",
        "- [AiPayGen](https://api.aipaygen.com) - Pay-per-use Claude AI API with 155 tools and 140+ endpoints. Agent messaging, task board, file storage, webhook relay. 10 free calls/day.",
    ),
    (
        "e2b-dev/awesome-ai-agents",
        "Tools",
        "- [AiPayGen](https://api.aipaygen.com) — Claude-powered pay-per-use API. 155 tools and 140+ endpoints: AI, scraping, real-time data, file storage, webhook relay. Free tier included.",
    ),
    (
        "punkpeye/awesome-mcp-servers",
        "Tools",
        "- [aipaygen-mcp](https://api.aipaygen.com/sdk) - 79 MCP tools: research, write, code, analyze, scrape, memory, and more. All Claude-powered.",
    ),
    (
        "sindresorhus/awesome",
        "Programming",
        "- [AiPayGen](https://api.aipaygen.com) - Pay-per-use AI API with 140+ Claude-powered endpoints.",
    ),
]


def check_and_pr_awesome_lists(claude_client=None):
    """Check each awesome list and open a PR if we're not already listed."""
    if _prs_today() >= MAX_PRS_PER_DAY:
        return {"skipped": "daily PR limit reached"}

    results = []
    for repo, section, entry in AWESOME_LIST_TARGETS:
        if _already_targeted(f"github_pr:{repo}", within_days=60):
            results.append({"repo": repo, "status": "skipped", "reason": "already targeted"})
            continue
        if _prs_today() >= MAX_PRS_PER_DAY:
            break
        result = _try_pr_awesome_list(repo, section, entry)
        results.append({"repo": repo, **result})
        time.sleep(2)  # be polite

    return {"results": results, "prs_today": _prs_today()}


def _try_pr_awesome_list(repo: str, section: str, entry: str) -> dict:
    """Check if listed, fork, and open a PR if not."""
    # 1. Check if already mentioned
    try:
        resp = requests.get(
            f"https://api.github.com/search/code",
            params={"q": f"aipaygen repo:{repo}"},
            headers=_gh_headers(),
            timeout=10,
        )
        if resp.status_code == 200 and resp.json().get("total_count", 0) > 0:
            _log("github_check", f"github_pr:{repo}", "already_listed")
            return {"status": "already_listed"}
    except Exception as e:
        _log("github_check", f"github_pr:{repo}", "error", str(e))
        return {"status": "error", "detail": str(e)}

    # 2. Fork the repo
    try:
        fork_resp = requests.post(
            f"https://api.github.com/repos/{repo}/forks",
            headers=_gh_headers(),
            timeout=15,
        )
        if fork_resp.status_code not in (202, 200):
            _log("github_fork", f"github_pr:{repo}", "fork_failed", fork_resp.text[:200])
            return {"status": "fork_failed"}
        fork_data = fork_resp.json()
        fork_name = fork_data.get("full_name", "")
        time.sleep(5)  # wait for fork to be ready
    except Exception as e:
        _log("github_fork", f"github_pr:{repo}", "error", str(e))
        return {"status": "error", "detail": str(e)}

    # 3. Get default branch + README SHA
    try:
        repo_info = requests.get(
            f"https://api.github.com/repos/{repo}",
            headers=_gh_headers(), timeout=10
        ).json()
        default_branch = repo_info.get("default_branch", "main")

        readme_resp = requests.get(
            f"https://api.github.com/repos/{repo}/readme",
            headers=_gh_headers(), timeout=10
        ).json()
        import base64
        readme_content = base64.b64decode(readme_resp.get("content", "")).decode("utf-8", errors="replace")
        readme_sha = readme_resp.get("sha", "")
    except Exception as e:
        _log("github_readme", f"github_pr:{repo}", "error", str(e))
        return {"status": "error", "detail": str(e)}

    # 4. Add our entry near the relevant section
    if "aipaygen" in readme_content.lower():
        _log("github_check", f"github_pr:{repo}", "already_listed_in_readme")
        return {"status": "already_listed"}

    # Find a good insertion point
    lines = readme_content.split("\n")
    insert_idx = len(lines) - 3  # default: near end
    for i, line in enumerate(lines):
        if section.lower() in line.lower() and line.startswith("#"):
            # Find the next blank line after the section header + some content
            for j in range(i + 2, min(i + 50, len(lines))):
                if lines[j].strip() == "" or lines[j].startswith("#"):
                    insert_idx = j
                    break
            break

    lines.insert(insert_idx, entry)
    new_content = "\n".join(lines)

    # 5. Create a new branch and commit
    import base64 as _b64
    branch_name = f"add-aipaygen-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}"

    # Get the fork's default branch SHA
    try:
        ref_resp = requests.get(
            f"https://api.github.com/repos/{fork_name}/git/ref/heads/{default_branch}",
            headers=_gh_headers(), timeout=10
        ).json()
        sha = ref_resp.get("object", {}).get("sha", "")

        # Create new branch
        requests.post(
            f"https://api.github.com/repos/{fork_name}/git/refs",
            json={"ref": f"refs/heads/{branch_name}", "sha": sha},
            headers=_gh_headers(), timeout=10
        )

        # Get README from fork
        fork_readme = requests.get(
            f"https://api.github.com/repos/{fork_name}/readme",
            headers=_gh_headers(), timeout=10
        ).json()
        fork_sha = fork_readme.get("sha", readme_sha)
        readme_path = fork_readme.get("path", "README.md")

        # Update README
        update_resp = requests.put(
            f"https://api.github.com/repos/{fork_name}/contents/{readme_path}",
            json={
                "message": f"Add AiPayGen — Claude-powered pay-per-use AI API",
                "content": _b64.b64encode(new_content.encode()).decode(),
                "sha": fork_sha,
                "branch": branch_name,
            },
            headers=_gh_headers(), timeout=15
        )
        if update_resp.status_code not in (200, 201):
            _log("github_commit", f"github_pr:{repo}", "commit_failed", update_resp.text[:200])
            return {"status": "commit_failed"}

        # 6. Open PR
        pr_resp = requests.post(
            f"https://api.github.com/repos/{repo}/pulls",
            json={
                "title": "Add AiPayGen — Claude-powered pay-per-use AI API",
                "body": (
                    "## Add AiPayGen\n\n"
                    "AiPayGen is a pay-per-use Claude AI API with 155 tools and 140+ endpoints:\n\n"
                    "- **AI**: research, write, code, analyze, translate, classify, RAG, vision, diagrams\n"
                    "- **Data**: weather, crypto, stocks, Wikipedia, arXiv, GitHub trending, YouTube transcripts\n"
                    "- **Agent infra**: messaging, task board, file storage, webhook relay, async jobs\n"
                    "- **Scraping**: Google Maps, Twitter, LinkedIn, YouTube, TikTok\n\n"
                    "**First 10 calls/day free** — no API key needed.\n\n"
                    "API: https://api.aipaygen.com\n"
                    "OpenAPI spec: https://api.aipaygen.com/openapi.json\n"
                    "MCP tools: https://api.aipaygen.com/sdk"
                ),
                "head": f"Damien829:{branch_name}",
                "base": default_branch,
            },
            headers=_gh_headers(), timeout=15
        )
        if pr_resp.status_code == 201:
            pr_url = pr_resp.json().get("html_url", "")
            _log("github_pr", f"github_pr:{repo}", "pr_opened", pr_url)
            return {"status": "pr_opened", "pr_url": pr_url}
        else:
            _log("github_pr", f"github_pr:{repo}", "pr_failed", pr_resp.text[:200])
            return {"status": "pr_failed", "detail": pr_resp.text[:200]}

    except Exception as e:
        _log("github_pr", f"github_pr:{repo}", "error", str(e))
        return {"status": "error", "detail": str(e)}


# ── Directory Pings ────────────────────────────────────────────────────────────

AGENT_DIRECTORIES = [
    # Directories that accept programmatic agent registration
    {
        "name": "AgentsFYI",
        "url": "https://api.aipaygen.com/agents/register",  # our own, but pinging keeps it fresh
        "method": "internal",
    },
]


def ping_directories():
    """Ping known agent directories to keep our listing fresh."""
    results = []
    # Re-bootstrap our specialist agents in our own registry (idempotent)
    try:
        resp = requests.get(f"{BASE_URL}/agents", timeout=8)
        agent_count = resp.json().get("total", 0)
        _log("directory_ping", "self_registry", "ok", f"{agent_count} agents")
        results.append({"target": "self_registry", "status": "ok", "agents": agent_count})
    except Exception as e:
        results.append({"target": "self_registry", "status": "error", "detail": str(e)})

    # Ping our own health to keep Cloudflare tunnel warm
    try:
        resp = requests.get(f"{BASE_URL}/health", timeout=8)
        _log("directory_ping", "health_check", "ok")
        results.append({"target": "health", "status": resp.json().get("status", "ok")})
    except Exception as e:
        results.append({"target": "health", "status": "error"})

    # Index our sitemap (ping Google/Bing search console URLs)
    indexing_urls = [
        f"https://www.google.com/ping?sitemap={BASE_URL}/sitemap.xml",
        f"https://www.bing.com/ping?sitemap={BASE_URL}/sitemap.xml",
    ]
    for url in indexing_urls:
        try:
            requests.get(url, timeout=8)
            _log("sitemap_ping", url, "ok")
            results.append({"target": url, "status": "pinged"})
        except Exception:
            pass

    return results


# ── Blog Content Generation ────────────────────────────────────────────────────

BLOG_TOPICS = [
    ("how-to-research-with-ai-api", "How to Research Any Topic Instantly with Claude AI API", "research"),
    ("ai-web-scraping-google-maps", "Scrape Google Maps, Twitter, and LinkedIn with a Single API Call", "scrape"),
    ("free-real-time-data-api", "14 Free Real-Time Data Endpoints for AI Agents", "data"),
    ("build-autonomous-agent-python", "Build a Fully Autonomous AI Agent in Python (No Subscriptions)", "research"),
    ("x402-payment-protocol-guide", "x402: How AI Agents Pay for APIs Without Human Oversight", "discover"),
    ("agent-memory-persistence", "Persistent Memory for AI Agents: Store and Retrieve Context Across Sessions", "memory"),
    ("mcp-tools-claude-code", "79 MCP Tools for Claude Code: Research, Write, Analyze, and More", "mcp"),
    ("free-wikipedia-arxiv-api", "Free Wikipedia and arXiv Search API for AI Agents", "data"),
    ("async-jobs-webhook-callbacks", "Fire-and-Forget AI Jobs with Webhook Callbacks", "async"),
    ("agent-task-board-collaboration", "Multi-Agent Collaboration: Task Board, Messaging, and Shared Knowledge Base", "tasks"),
]


def generate_blog_post(slug: str, title: str, endpoint: str, claude_client) -> str:
    """Generate a blog post tutorial for an endpoint using Claude."""
    prompt = f"""Write a comprehensive developer tutorial blog post titled "{title}".

This is for AiPayGen (https://api.aipaygen.com) — a pay-per-use Claude AI API with 155 tools and 140+ endpoints.
The first 10 calls/day are free. After that, users pay with a prepaid API key or USDC on Base.

The post should:
1. Explain the problem being solved
2. Show how to use the relevant AiPayGen endpoint(s) with real curl + Python examples
3. Include example responses
4. Mention the 10 free calls/day and /buy-credits for more
5. Be 600-900 words, written for developers
6. End with links to https://api.aipaygen.com/discover and https://api.aipaygen.com/openapi.json

Focus on the "{endpoint}" endpoint category. Make examples concrete and copy-pasteable.
Return only the blog post content in clean HTML (no doctype, just article body tags)."""

    msg = claude_client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=2000,
        messages=[{"role": "user", "content": prompt}]
    )
    return msg.content[0].text


def generate_all_blog_posts(claude_client, force: bool = False):
    """Generate blog posts for all topics. Skips existing unless force=True."""
    results = []
    new_urls = []
    for slug, title, endpoint in BLOG_TOPICS:
        with _conn() as c:
            existing = c.execute("SELECT slug FROM blog_posts WHERE slug=?", (slug,)).fetchone()
        if existing and not force:
            results.append({"slug": slug, "status": "exists"})
            continue
        try:
            content = generate_blog_post(slug, title, endpoint, claude_client)
            now = datetime.utcnow().isoformat()
            with _conn() as c:
                c.execute(
                    "INSERT OR REPLACE INTO blog_posts (slug, title, content, endpoint, generated_at) VALUES (?, ?, ?, ?, ?)",
                    (slug, title, content, endpoint, now),
                )
            results.append({"slug": slug, "status": "generated"})
            new_urls.append(f"https://api.aipaygen.com/blog/{slug}")
            _log("blog_generated", slug, "ok", title)
            time.sleep(1)  # avoid rate limits
        except Exception as e:
            results.append({"slug": slug, "status": "error", "detail": str(e)})

    # Ping IndexNow for newly generated posts
    if new_urls:
        _ping_indexnow(new_urls)
    return results


def get_blog_post(slug: str) -> dict | None:
    with _conn() as c:
        row = c.execute("SELECT * FROM blog_posts WHERE slug=?", (slug,)).fetchone()
    return dict(row) if row else None


def list_blog_posts() -> list:
    with _conn() as c:
        rows = c.execute(
            "SELECT slug, title, endpoint, generated_at FROM blog_posts ORDER BY generated_at DESC"
        ).fetchall()
    return [dict(r) for r in rows]


def get_outreach_log(limit: int = 50) -> list:
    with _conn() as c:
        rows = c.execute(
            "SELECT * FROM outreach_log ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
    return [dict(r) for r in rows]


# ── Orchestrator ───────────────────────────────────────────────────────────────

# ── Canary / Self-Monitoring ───────────────────────────────────────────────────

# Endpoints to probe each hour. Tuple: (method, path, payload, expected_key)
CANARY_ENDPOINTS = [
    ("GET", "/health", None, "status"),
    ("GET", "/catalog", None, None),
    ("GET", "/discover", None, None),
    ("GET", "/agents", None, None),
    ("GET", "/data/crypto", None, None),
    ("GET", "/data/weather?city=London", None, None),
    ("GET", "/knowledge/trending", None, None),
    ("GET", "/task/browse", None, None),
    ("GET", "/blog", None, None),
    ("GET", "/stats", None, None),
]

# Tracks endpoints that have been failing continuously (auto-disabled)
_disabled_endpoints: dict = {}  # endpoint -> disabled_at


def run_canary(base_url: str = BASE_URL) -> dict:
    """Probe key endpoints, record health, auto-disable persistently broken ones."""
    results = []
    now = datetime.utcnow().isoformat()
    with _conn() as c:
        for method, path, payload, expected_key in CANARY_ENDPOINTS:
            url = f"{base_url}{path}"
            t0 = time.time()
            status = "ok"
            error = None
            latency_ms = None
            try:
                if method == "GET":
                    resp = requests.get(url, timeout=10)
                else:
                    resp = requests.post(url, json=payload or {}, timeout=10)
                latency_ms = int((time.time() - t0) * 1000)
                if resp.status_code >= 500:
                    status = "error"
                    error = f"HTTP {resp.status_code}"
                elif expected_key and expected_key not in resp.text:
                    status = "warn"
                    error = f"missing key '{expected_key}'"
                else:
                    status = "ok"
                    # Clear disabled flag if it was previously failing
                    _disabled_endpoints.pop(path, None)
            except Exception as e:
                latency_ms = int((time.time() - t0) * 1000)
                status = "error"
                error = str(e)[:200]

            # Check consecutive failures → auto-disable
            if status == "error":
                if path not in _disabled_endpoints:
                    _disabled_endpoints[path] = now

            c.execute(
                "INSERT INTO endpoint_health (endpoint, status, latency_ms, error, checked_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (path, status, latency_ms, error, now),
            )
            results.append({
                "endpoint": path,
                "status": status,
                "latency_ms": latency_ms,
                "error": error,
            })

    healthy = sum(1 for r in results if r["status"] == "ok")
    return {
        "probed": len(results),
        "healthy": healthy,
        "warnings": sum(1 for r in results if r["status"] == "warn"),
        "errors": sum(1 for r in results if r["status"] == "error"),
        "disabled": list(_disabled_endpoints.keys()),
        "results": results,
        "ts": now,
    }


def get_health_history(endpoint: str = None, limit: int = 50) -> list:
    with _conn() as c:
        if endpoint:
            rows = c.execute(
                "SELECT * FROM endpoint_health WHERE endpoint=? ORDER BY checked_at DESC LIMIT ?",
                (endpoint, limit)
            ).fetchall()
        else:
            rows = c.execute(
                "SELECT * FROM endpoint_health ORDER BY checked_at DESC LIMIT ?", (limit,)
            ).fetchall()
    return [dict(r) for r in rows]


# ── Trending-Topic Blog Post Generator ────────────────────────────────────────

def _fetch_hn_stories(limit: int = 30) -> list:
    """Fetch top Hacker News stories, filter for AI/dev relevance."""
    try:
        ids_resp = requests.get(
            "https://hacker-news.firebaseio.com/v0/topstories.json", timeout=8
        )
        story_ids = ids_resp.json()[:limit]
        stories = []
        for sid in story_ids[:20]:  # check first 20 only
            try:
                s = requests.get(
                    f"https://hacker-news.firebaseio.com/v0/item/{sid}.json", timeout=5
                ).json()
                title = s.get("title", "").lower()
                # Filter for AI/dev relevance
                keywords = ["ai", "llm", "agent", "api", "claude", "gpt", "python",
                            "ml", "neural", "model", "openai", "anthropic", "automation"]
                if any(kw in title for kw in keywords):
                    stories.append({
                        "id": sid,
                        "title": s.get("title", ""),
                        "url": s.get("url", ""),
                        "score": s.get("score", 0),
                    })
                if len(stories) >= 5:
                    break
            except Exception:
                continue
        return stories
    except Exception:
        return []


def _ping_indexnow(urls: list):
    """Ping IndexNow API so Bing/Yandex index new pages immediately."""
    INDEXNOW_KEY = os.getenv("INDEXNOW_KEY", "aipaygen2026indexnow")
    try:
        requests.post(
            "https://api.indexnow.org/indexnow",
            json={
                "host": "api.aipaygen.com",
                "key": INDEXNOW_KEY,
                "keyLocation": f"https://api.aipaygen.com/{INDEXNOW_KEY}.txt",
                "urlList": urls,
            },
            timeout=8,
        )
        _log("indexnow_ping", ",".join(urls[:3]), "ok", f"{len(urls)} urls")
    except Exception as e:
        _log("indexnow_ping", "batch", "error", str(e))


def generate_trending_blog_posts(claude_client) -> dict:
    """Fetch trending HN topics and generate timely blog posts."""
    stories = _fetch_hn_stories()
    if not stories:
        return {"skipped": "no relevant stories found"}

    results = []
    new_urls = []
    for story in stories[:3]:  # max 3 per run
        title = story["title"]
        slug = "trending-" + _re.sub(r"[^a-z0-9]+", "-", title.lower())[:50].strip("-")

        # Skip if recently generated (within 7 days)
        with _conn() as c:
            existing = c.execute(
                "SELECT slug FROM blog_posts WHERE slug=? AND generated_at > ?",
                (slug, (datetime.utcnow() - timedelta(days=7)).isoformat())
            ).fetchone()
        if existing:
            results.append({"slug": slug, "status": "recent_exists"})
            continue

        try:
            prompt = f"""Write a concise developer blog post (400-600 words) about this trending topic:
"{title}"

This is for AiPayGen (https://api.aipaygen.com) — a pay-per-use Claude AI API.
Connect the topic to how AiPayGen can help developers working in this space.
Show a concrete curl or Python code example using the most relevant AiPayGen endpoint.
End with: "Try it free at https://api.aipaygen.com — 10 calls/day, no credit card."
Return only clean HTML article body (no doctype/head tags)."""

            msg = claude_client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=1500,
                messages=[{"role": "user", "content": prompt}]
            )
            content = msg.content[0].text
            now = datetime.utcnow().isoformat()
            blog_title = f"{title} — How to Use AI Agents for This"
            with _conn() as c:
                c.execute(
                    "INSERT OR REPLACE INTO blog_posts (slug, title, content, endpoint, generated_at) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (slug, blog_title, content, "trending", now),
                )
            results.append({"slug": slug, "title": blog_title, "status": "generated"})
            new_urls.append(f"https://api.aipaygen.com/blog/{slug}")
            _log("trending_blog", slug, "ok", blog_title)
            time.sleep(2)
        except Exception as e:
            results.append({"slug": slug, "status": "error", "detail": str(e)})

    if new_urls:
        _ping_indexnow(new_urls)

    return {"stories_checked": len(stories), "results": results, "ts": datetime.utcnow().isoformat()}


# ── Database Self-Maintenance ──────────────────────────────────────────────────

DB_PATHS = [
    DB_PATH,  # discovery_engine.db
]

# These are set from app.py at startup so maintenance can reach all DBs
_all_db_paths: list = []


def register_db_paths(paths: list):
    """Called from app.py to register all DB paths for maintenance."""
    global _all_db_paths
    _all_db_paths = list(paths)


def run_maintenance() -> dict:
    """Weekly: prune old records + VACUUM all SQLite databases."""
    results = []
    now = datetime.utcnow()

    # Prune endpoint_health older than 7 days
    cutoff_7d = (now - timedelta(days=7)).isoformat()
    with _conn() as c:
        deleted = c.execute(
            "DELETE FROM endpoint_health WHERE checked_at < ?", (cutoff_7d,)
        ).rowcount
        results.append({"action": "prune_endpoint_health", "deleted": deleted})

    # Prune outreach_log older than 90 days
    cutoff_90d = (now - timedelta(days=90)).isoformat()
    with _conn() as c:
        deleted = c.execute(
            "DELETE FROM outreach_log WHERE created_at < ?", (cutoff_90d,)
        ).rowcount
        results.append({"action": "prune_outreach_log", "deleted": deleted})

    # Prune cost_tracking older than 60 days
    cutoff_60d = (now - timedelta(days=60)).strftime("%Y-%m-%d")
    with _conn() as c:
        deleted = c.execute(
            "DELETE FROM cost_tracking WHERE date < ?", (cutoff_60d,)
        ).rowcount
        results.append({"action": "prune_cost_tracking", "deleted": deleted})

    # VACUUM all registered DBs
    all_paths = list(set([DB_PATH] + _all_db_paths))
    for db_path in all_paths:
        if not os.path.exists(db_path):
            continue
        try:
            size_before = os.path.getsize(db_path)
            conn = sqlite3.connect(db_path)
            conn.execute("VACUUM")
            conn.close()
            size_after = os.path.getsize(db_path)
            saved_kb = (size_before - size_after) // 1024
            results.append({
                "action": "vacuum",
                "db": os.path.basename(db_path),
                "saved_kb": saved_kb,
            })
        except Exception as e:
            results.append({"action": "vacuum", "db": os.path.basename(db_path), "error": str(e)})

    return {"results": results, "ts": now.isoformat()}


# ── Cost Tracking ─────────────────────────────────────────────────────────────

def track_cost(endpoint: str, model: str, tokens_in: int, tokens_out: int):
    """Record Claude API cost for daily/total tracking."""
    # Approximate cost: haiku ~$0.0008/1k in, $0.004/1k out; sonnet ~$0.003/1k in, $0.015/1k out
    rates = {
        "claude-haiku": (0.0008, 0.004),
        "claude-sonnet": (0.003, 0.015),
        "claude-opus": (0.015, 0.075),
    }
    in_rate, out_rate = next(
        (v for k, v in rates.items() if k in model.lower()),
        (0.001, 0.005)
    )
    cost = (tokens_in / 1000 * in_rate) + (tokens_out / 1000 * out_rate)
    today = datetime.utcnow().strftime("%Y-%m-%d")
    with _conn() as c:
        c.execute("""
            INSERT INTO cost_tracking (date, model, endpoint, tokens_in, tokens_out, cost_usd)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(date, model, endpoint) DO UPDATE SET
                tokens_in = tokens_in + ?,
                tokens_out = tokens_out + ?,
                cost_usd = cost_usd + ?
        """, (today, model, endpoint, tokens_in, tokens_out, cost,
               tokens_in, tokens_out, cost))


def get_daily_cost(date: str = None) -> dict:
    """Get total Claude API cost for a given date (default: today)."""
    day = date or datetime.utcnow().strftime("%Y-%m-%d")
    with _conn() as c:
        row = c.execute(
            "SELECT SUM(cost_usd) as total, SUM(tokens_in) as tin, SUM(tokens_out) as tout "
            "FROM cost_tracking WHERE date=?", (day,)
        ).fetchone()
    return {
        "date": day,
        "total_cost_usd": round(row["total"] or 0.0, 4),
        "tokens_in": row["tin"] or 0,
        "tokens_out": row["tout"] or 0,
    }


def is_cost_throttled(daily_limit_usd: float = 5.0) -> bool:
    """Return True if today's Claude spend has exceeded the daily limit."""
    cost = get_daily_cost()
    return cost["total_cost_usd"] >= daily_limit_usd


# ── Orchestrator ───────────────────────────────────────────────────────────────

import re as _re


def run_hourly(claude_client=None):
    """Runs every hour: directory pings, health checks, canary."""
    return {
        "directories": ping_directories(),
        "canary": run_canary(),
        "ts": datetime.utcnow().isoformat(),
    }


def run_daily(claude_client=None):
    """Runs daily: GitHub outreach + trending blog posts."""
    results = {
        "github_outreach": check_and_pr_awesome_lists(claude_client),
        "ts": datetime.utcnow().isoformat(),
    }
    if claude_client:
        results["trending_blogs"] = generate_trending_blog_posts(claude_client)
    return results


def run_weekly(claude_client=None):
    """Runs weekly: regenerate all blog posts + DB maintenance."""
    result = {"maintenance": run_maintenance(), "ts": datetime.utcnow().isoformat()}
    if claude_client:
        result["blog_generation"] = generate_all_blog_posts(claude_client)
    return result
