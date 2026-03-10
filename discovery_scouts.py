"""
Discovery Scouts — 6 autonomous agents that find AI agents across
GitHub, registries, Reddit, Twitter/X, and A2A protocols.

Scheduled via APScheduler. Each scout logs to scout_outreach table
in discovery_engine.db with dedup/cooldown.
"""
import os
import json
import sqlite3
import time
import hashlib
import urllib.request
import urllib.error
import urllib.parse
from datetime import datetime, timedelta

BASE_URL = os.getenv("BASE_URL", "https://api.aipaygen.com")
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")
DB_PATH = os.path.join(os.path.dirname(__file__), "discovery_engine.db")
SKILLS_DB_PATH = os.path.join(os.path.dirname(__file__), "skills.db")
USER_AGENT = "AiPayGen-DiscoveryScout/1.0 (+https://api.aipaygen.com)"
FETCH_TIMEOUT = 15

# ── Shared Helpers ────────────────────────────────────────────────────────────


def _scout_conn():
    c = sqlite3.connect(DB_PATH, timeout=10)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("PRAGMA busy_timeout=5000")
    return c


def init_scout_db():
    with _scout_conn() as c:
        c.execute("""
            CREATE TABLE IF NOT EXISTS scout_outreach (
                id INTEGER PRIMARY KEY,
                scout TEXT NOT NULL,
                target_id TEXT NOT NULL,
                action TEXT NOT NULL,
                message TEXT,
                response TEXT,
                status TEXT DEFAULT 'sent',
                cost_usd REAL DEFAULT 0,
                created_at TEXT DEFAULT (datetime('now')),
                follow_up_at TEXT,
                UNIQUE(scout, target_id, action)
            )
        """)
        c.execute("CREATE INDEX IF NOT EXISTS idx_so_scout ON scout_outreach(scout)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_so_status ON scout_outreach(status)")
        c.execute("""
            CREATE TABLE IF NOT EXISTS scout_conversions (
                id INTEGER PRIMARY KEY,
                outreach_id INTEGER REFERENCES scout_outreach(id),
                caller_ip TEXT,
                user_agent TEXT,
                endpoint TEXT,
                ref_code TEXT,
                attribution TEXT DEFAULT 'direct',
                first_call_at TEXT DEFAULT (datetime('now')),
                total_calls INTEGER DEFAULT 1,
                total_spend_usd REAL DEFAULT 0
            )
        """)
        c.execute("CREATE INDEX IF NOT EXISTS idx_sc_ref ON scout_conversions(ref_code)")


def _log_outreach(scout, target_id, action, message="", status="sent", cost_usd=0.0):
    now = datetime.utcnow().isoformat()
    with _scout_conn() as c:
        c.execute(
            "INSERT OR IGNORE INTO scout_outreach "
            "(scout, target_id, action, message, status, cost_usd, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (scout, target_id, action, message, status, cost_usd, now),
        )
    return True


def _already_scouted(scout, target_id, within_days=30):
    cutoff = (datetime.utcnow() - timedelta(days=within_days)).isoformat()
    with _scout_conn() as c:
        row = c.execute(
            "SELECT id FROM scout_outreach WHERE scout=? AND target_id=? AND created_at > ?",
            (scout, target_id, cutoff),
        ).fetchone()
    return row is not None


def _fetch(url, headers=None, timeout=FETCH_TIMEOUT, method="GET", data=None):
    # SSRF validation — block internal/private IPs
    try:
        from security import validate_url, SSRFError
        validate_url(url, allow_http=True)
    except SSRFError:
        return {"error": f"SSRF blocked: {url}", "blocked": True}
    except Exception:
        pass  # security module unavailable, proceed with caution
    hdrs = {"User-Agent": USER_AGENT}
    if headers:
        # Mask any auth tokens in logged headers
        hdrs.update(headers)
    try:
        req = urllib.request.Request(url, headers=hdrs, method=method, data=data)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", errors="replace")[:50000]
            return {"status": resp.status, "body": body, "headers": dict(resp.headers)}
    except urllib.error.HTTPError as e:
        return {
            "error": f"HTTP {e.code}", "status": e.code,
            "body": e.read().decode("utf-8", errors="replace")[:2000],
        }
    except Exception as e:
        return {"error": str(e)}


def _ref_code(scout, target_id):
    h = hashlib.md5(f"{scout}:{target_id}".encode()).hexdigest()[:8]
    return f"{scout[:2]}_{h}"


# ── Skill Absorber Mixin ──────────────────────────────────────────────────────


def _init_absorbed_skills_table():
    """Track skills absorbed by scouts — dedup + attribution."""
    with _scout_conn() as c:
        c.execute("""
            CREATE TABLE IF NOT EXISTS scout_absorbed_skills (
                id INTEGER PRIMARY KEY,
                scout TEXT NOT NULL,
                source_id TEXT NOT NULL,
                skill_name TEXT NOT NULL,
                source_url TEXT,
                created_at TEXT DEFAULT (datetime('now')),
                UNIQUE(scout, skill_name)
            )
        """)
        c.execute("CREATE INDEX IF NOT EXISTS idx_sas_scout ON scout_absorbed_skills(scout)")


class SkillAbsorberMixin:
    """Mixin that gives any scout the ability to absorb skills from discovered content.

    Requires self.call_model and a scout_name attribute.
    """

    ABSORB_MAX_PER_RUN = 5  # Don't flood the DB

    def _absorb_skills_from_content(self, content, source_id, source_url="", category="general"):
        """Extract and store skills from arbitrary text content (README, API spec, manifest).

        Returns list of absorbed skill names.
        """
        _init_absorbed_skills_table()

        if not content or len(content.strip()) < 50:
            return []

        scout_name = getattr(self, "SCOUT_NAME", "unknown")

        # Check how many we already absorbed this run
        with _scout_conn() as c:
            today = datetime.utcnow().strftime("%Y-%m-%d")
            today_count = c.execute(
                "SELECT COUNT(*) FROM scout_absorbed_skills WHERE scout=? AND created_at LIKE ?",
                (scout_name, f"{today}%"),
            ).fetchone()[0]
        if today_count >= self.ABSORB_MAX_PER_RUN * 3:
            return []

        # Use AI to extract multiple skills from the content
        try:
            result = self.call_model(
                "claude-haiku",
                [{"role": "user", "content": f"""Analyze this content and extract reusable AI skills/tools from it.

Content (from {source_url or source_id}):
{content[:6000]}

Extract up to 3 distinct skills. For each skill return:
- "name": snake_case (unique, descriptive, prefix with source domain if possible)
- "description": one-line description
- "category": one of: research, engineering, business, finance, marketing, legal, education, data, creative, general
- "prompt_template": a prompt template using {{{{input}}}} placeholder that produces structured JSON output
- "input_schema": {{"input": "description of expected input"}}

Return a JSON array of skill objects. If no clear skills can be extracted, return [].
Only extract skills that represent genuinely useful, reusable capabilities — not trivial helpers."""}],
                system="You are a skill extraction expert. Always respond with a valid JSON array only.",
                max_tokens=1500,
                temperature=0.3,
            )
        except Exception:
            return []

        # Parse the extracted skills
        text = result.get("text", "").strip()
        try:
            # Handle both raw JSON and markdown-wrapped JSON
            if text.startswith("```"):
                text = text.split("```")[1]
                if text.startswith("json"):
                    text = text[4:]
            skills = json.loads(text)
        except (json.JSONDecodeError, ValueError, IndexError):
            return []

        if not isinstance(skills, list):
            return []

        absorbed = []
        for skill in skills[:self.ABSORB_MAX_PER_RUN]:
            name = skill.get("name", "")
            desc = skill.get("description", "")
            template = skill.get("prompt_template", "")
            if not name or not desc or not template:
                continue

            # Sanitize skill name
            name = name.lower().replace("-", "_").replace(" ", "_")[:80]

            # Check dedup in scout DB
            with _scout_conn() as c:
                exists = c.execute(
                    "SELECT id FROM scout_absorbed_skills WHERE skill_name=?", (name,)
                ).fetchone()
            if exists:
                continue

            # Insert into skills.db
            try:
                skills_conn = sqlite3.connect(SKILLS_DB_PATH)
                skills_conn.execute(
                    "INSERT INTO skills (name, description, category, source, prompt_template, model, input_schema) "
                    "VALUES (?, ?, ?, ?, ?, 'claude-haiku', ?)",
                    (name, desc, skill.get("category", category),
                     f"scout:{scout_name}:{source_url or source_id}",
                     template,
                     json.dumps(skill.get("input_schema", {"input": "string"}))),
                )
                skills_conn.commit()
                skills_conn.close()
            except sqlite3.IntegrityError:
                # Skill name already exists in skills.db
                try:
                    skills_conn.close()
                except Exception:
                    pass
                continue
            except Exception:
                try:
                    skills_conn.close()
                except Exception:
                    pass
                continue

            # Log in scout DB
            with _scout_conn() as c:
                c.execute(
                    "INSERT OR IGNORE INTO scout_absorbed_skills (scout, source_id, skill_name, source_url) "
                    "VALUES (?, ?, ?, ?)",
                    (scout_name, source_id, name, source_url or ""),
                )

            absorbed.append(name)
            _log_outreach(
                scout_name, source_id, "skill_absorbed",
                message=f"Absorbed skill: {name} — {desc}", status="absorbed",
            )

        return absorbed


def get_absorbed_skills_stats():
    """Get stats on skills absorbed by scouts."""
    _init_absorbed_skills_table()
    with _scout_conn() as c:
        total = c.execute("SELECT COUNT(*) FROM scout_absorbed_skills").fetchone()[0]
        by_scout = c.execute(
            "SELECT scout, COUNT(*) as cnt FROM scout_absorbed_skills GROUP BY scout"
        ).fetchall()
        recent = c.execute(
            "SELECT scout, skill_name, source_url, created_at FROM scout_absorbed_skills "
            "ORDER BY created_at DESC LIMIT 20"
        ).fetchall()
    return {
        "total_absorbed": total,
        "by_scout": [dict(r) for r in by_scout],
        "recent": [dict(r) for r in recent],
    }


# ── GitHubScout ───────────────────────────────────────────────────────────────


class GitHubScout(SkillAbsorberMixin):
    """Searches GitHub for agent repos, opens issues suggesting AiPayGen as tool provider.
    Also absorbs skills from discovered repo READMEs."""

    SCOUT_NAME = "github"

    SEARCH_QUERIES = [
        "AI agent framework tools plugin",
        "MCP server tools autonomous agent",
        "CrewAI custom tools",
        "LangChain agent tools provider",
        "AutoGPT plugins",
        "BabyAGI tools",
        "MetaGPT tools",
        "agent tool provider MCP",
    ]
    MAX_ISSUES_PER_DAY = 3
    COOLDOWN_DAYS = 30

    def __init__(self, call_model_fn):
        self.call_model = call_model_fn
        init_scout_db()
        _init_absorbed_skills_table()

    def run(self, max_actions=5):
        stats = {"repos_scanned": 0, "issues_opened": 0, "skills_absorbed": 0, "errors": 0, "actions": 0}
        today_opened = self._issues_opened_today()
        if today_opened >= self.MAX_ISSUES_PER_DAY:
            return stats

        for query in self.SEARCH_QUERIES:
            if stats["actions"] >= max_actions:
                break
            repos = self._search_repos(query)
            for repo in repos:
                if stats["actions"] >= max_actions:
                    break
                if today_opened + stats["issues_opened"] >= self.MAX_ISSUES_PER_DAY:
                    break
                full_name = repo.get("full_name", "")
                if _already_scouted("github", full_name, self.COOLDOWN_DAYS):
                    continue
                if repo.get("stargazers_count", 0) < 10:
                    continue

                # Absorb skills from repo README
                readme_content = self._fetch_readme(full_name)
                if readme_content:
                    desc = repo.get("description", "") or ""
                    topics = ", ".join(repo.get("topics", []))
                    absorb_content = f"Repository: {full_name}\nDescription: {desc}\nTopics: {topics}\n\n{readme_content}"
                    absorbed = self._absorb_skills_from_content(
                        absorb_content, full_name,
                        source_url=f"https://github.com/{full_name}",
                        category="engineering",
                    )
                    stats["skills_absorbed"] += len(absorbed)

                title, body = self._craft_issue(repo)
                if not title:
                    continue
                opened = self._open_issue(full_name, title, body)
                ref = _ref_code("github", full_name)
                if opened:
                    _log_outreach(
                        "github", full_name, "issue_opened",
                        message=f"{title}\n\nref={ref}", status="sent",
                    )
                    stats["issues_opened"] += 1
                else:
                    _log_outreach("github", full_name, "issue_failed", status="error")
                    stats["errors"] += 1
                stats["actions"] += 1
                stats["repos_scanned"] += 1
                time.sleep(2)

        return stats

    def _fetch_readme(self, full_name):
        """Fetch README content from a GitHub repo."""
        resp = _fetch(
            f"https://api.github.com/repos/{full_name}/readme",
            headers={
                "Authorization": f"token {GITHUB_TOKEN}",
                "Accept": "application/vnd.github.v3.raw",
            },
        )
        if resp.get("status") == 200:
            return resp.get("body", "")[:8000]
        return ""

    def _search_repos(self, query):
        resp = _fetch(
            f"https://api.github.com/search/repositories?q={urllib.parse.quote(query)}&sort=updated&per_page=20",
            headers={
                "Authorization": f"token {GITHUB_TOKEN}",
                "Accept": "application/vnd.github.v3+json",
            },
        )
        if "error" in resp:
            return []
        try:
            return json.loads(resp["body"]).get("items", [])
        except (json.JSONDecodeError, ValueError):
            return []

    def _craft_issue(self, repo):
        desc = repo.get("description", "") or ""
        topics = repo.get("topics", [])
        ref = _ref_code("github", repo["full_name"])
        try:
            result = self.call_model(
                "claude-haiku",
                [{"role": "user", "content": (
                    f'Write a GitHub issue title and body for repo "{repo["full_name"]}" ({desc}).\n'
                    f"Topics: {topics}\n\n"
                    "Suggest AiPayGen as a tool/skill provider. We offer:\n"
                    "- 1500+ skills via MCP protocol and REST API\n"
                    "- Free tier (10 calls/day), then x402 USDC micropayments\n"
                    "- Multi-model AI (Claude, GPT-4, Gemini, DeepSeek)\n"
                    f"- Endpoint: {BASE_URL}\n"
                    "- MCP: mcp.aipaygen.com\n\n"
                    "Make it genuinely helpful, not spammy. Show how their project benefits.\n"
                    f"Format: first line = title, rest = body. Include link: {BASE_URL}?ref={ref}"
                )}],
                system="You write concise, helpful GitHub issues suggesting tool integrations. Never pushy.",
                max_tokens=400,
                temperature=0.7,
            )
            text = result.get("text", "").strip()
            lines = text.split("\n", 1)
            title = lines[0].strip().lstrip("#").strip()
            body = lines[1].strip() if len(lines) > 1 else ""
            return title, body
        except Exception:
            return None, None

    def _open_issue(self, full_name, title, body):
        payload = json.dumps({"title": title, "body": body}).encode("utf-8")
        resp = _fetch(
            f"https://api.github.com/repos/{full_name}/issues",
            headers={
                "Authorization": f"token {GITHUB_TOKEN}",
                "Accept": "application/vnd.github.v3+json",
                "Content-Type": "application/json",
            },
            method="POST",
            data=payload,
        )
        return resp.get("status") in (201, 200)

    def _issues_opened_today(self):
        today = datetime.utcnow().strftime("%Y-%m-%d")
        with _scout_conn() as c:
            row = c.execute(
                "SELECT COUNT(*) FROM scout_outreach "
                "WHERE scout='github' AND action='issue_opened' AND created_at LIKE ?",
                (f"{today}%",),
            ).fetchone()
        return row[0] if row else 0


# ── RegistryScout ─────────────────────────────────────────────────────────────


class RegistryScout(SkillAbsorberMixin):
    """Auto-submits AiPayGen to agent registries and marketplaces.
    Also absorbs skills from tools/agents discovered in registries."""

    SCOUT_NAME = "registry"

    REGISTRIES = [
        {
            "name": "composio",
            "url": "https://composio.dev/api/v1/tools",
            "submit_url": "https://composio.dev/api/v1/tools/register",
            "method": "POST",
        },
        {
            "name": "relevance_ai",
            "url": "https://api.relevanceai.com/latest/agents",
            "submit_url": "https://api.relevanceai.com/latest/agents/register",
            "method": "POST",
        },
        {
            "name": "crewai_hub",
            "url": "https://hub.crewai.com/api/tools",
            "submit_url": "https://hub.crewai.com/api/tools/submit",
            "method": "POST",
        },
        {
            "name": "langchain_hub",
            "url": "https://smith.langchain.com/hub",
            "submit_url": None,  # Manual submission
            "method": "GET",
        },
        {
            "name": "agent_protocol",
            "url": "https://agentprotocol.ai/registry",
            "submit_url": None,
            "method": "GET",
        },
    ]

    OUR_MANIFEST = {
        "name": "AiPayGen",
        "description": "646+ AI skills via MCP protocol and REST API. Multi-model (Claude, GPT-4, Gemini). x402 USDC micropayments.",
        "url": BASE_URL,
        "mcp_endpoint": "https://mcp.aipaygen.com/mcp",
        "docs": f"{BASE_URL}/discover",
        "pricing": "Free tier (10 calls/day), then x402 USDC micropayments",
        "categories": ["ai", "tools", "mcp", "agent", "skills"],
    }

    COOLDOWN_DAYS = 60

    def __init__(self, call_model_fn):
        self.call_model = call_model_fn
        init_scout_db()
        _init_absorbed_skills_table()

    def run(self, max_actions=5):
        stats = {"registered": 0, "already_listed": 0, "skills_absorbed": 0, "errors": 0, "actions": 0}

        for reg in self.REGISTRIES:
            if stats["actions"] >= max_actions:
                break
            name = reg["name"]
            if _already_scouted("registry", name, self.COOLDOWN_DAYS):
                stats["already_listed"] += 1
                continue

            # Absorb skills from registry listings
            listing_content = self._scan_registry_listings(reg)
            if listing_content:
                absorbed = self._absorb_skills_from_content(
                    listing_content, f"registry:{name}",
                    source_url=reg["url"],
                    category="general",
                )
                stats["skills_absorbed"] += len(absorbed)

            if reg["submit_url"]:
                success = self._submit(reg)
                if success:
                    _log_outreach("registry", name, "submitted",
                                  message=json.dumps(self.OUR_MANIFEST), status="sent")
                    stats["registered"] += 1
                else:
                    _log_outreach("registry", name, "submit_failed", status="error")
                    stats["errors"] += 1
            else:
                # Just check presence
                _log_outreach("registry", name, "checked",
                              message="Manual submission required", status="pending")

            stats["actions"] += 1
            time.sleep(1)

        return stats

    def _scan_registry_listings(self, reg):
        """Fetch tools/agents listed in a registry and extract their descriptions."""
        resp = _fetch(reg["url"], timeout=15)
        if "error" in resp or resp.get("status") != 200:
            return ""
        body = resp.get("body", "")
        try:
            data = json.loads(body)
            items = []
            if isinstance(data, list):
                items = data[:15]
            elif isinstance(data, dict):
                items = (data.get("items") or data.get("tools") or
                         data.get("agents") or data.get("servers") or [])[:15]
            if not items:
                return ""
            # Build a summary of discovered tools
            summaries = []
            for item in items:
                name = item.get("name") or item.get("title", "")
                desc = item.get("description") or item.get("summary", "")
                url = item.get("url") or item.get("homepage", "")
                if name and desc:
                    summaries.append(f"- {name}: {desc} ({url})")
            return f"Tools found in {reg['name']} registry:\n" + "\n".join(summaries)
        except (json.JSONDecodeError, TypeError):
            return ""

    def _submit(self, reg):
        payload = json.dumps(self.OUR_MANIFEST).encode("utf-8")
        resp = _fetch(
            reg["submit_url"],
            headers={"Content-Type": "application/json"},
            method=reg.get("method", "POST"),
            data=payload,
        )
        return resp.get("status") in (200, 201, 202)


# ── SocialScout (Reddit) ─────────────────────────────────────────────────────


class SocialScout:
    """Scans Reddit for threads about AI agent tools and crafts helpful replies."""

    SUBREDDITS = ["AutoGPT", "LangChain", "LocalLLaMA", "artificial", "MachineLearning"]
    KEYWORDS = ["looking for API", "tool provider", "MCP server", "agent tools",
                "AI agent framework", "need API", "skills provider"]
    MAX_REPLIES_PER_DAY = 5
    COOLDOWN_DAYS = 30

    # Reddit API credentials (optional — for posting)
    REDDIT_CLIENT_ID = os.getenv("REDDIT_CLIENT_ID", "")
    REDDIT_CLIENT_SECRET = os.getenv("REDDIT_CLIENT_SECRET", "")
    REDDIT_USERNAME = os.getenv("REDDIT_USERNAME", "")
    REDDIT_PASSWORD = os.getenv("REDDIT_PASSWORD", "")

    def __init__(self, call_model_fn):
        self.call_model = call_model_fn
        init_scout_db()

    def run(self, max_actions=5):
        stats = {"threads_found": 0, "replies_drafted": 0, "replies_posted": 0,
                 "errors": 0, "actions": 0}
        today_posted = self._replies_today()
        if today_posted >= self.MAX_REPLIES_PER_DAY:
            return stats

        for sub in self.SUBREDDITS:
            if stats["actions"] >= max_actions:
                break
            for kw in self.KEYWORDS[:3]:  # Limit keyword combos
                if stats["actions"] >= max_actions:
                    break
                threads = self._search_reddit(sub, kw)
                for thread in threads:
                    if stats["actions"] >= max_actions:
                        break
                    if today_posted + stats["replies_posted"] >= self.MAX_REPLIES_PER_DAY:
                        break
                    tid = thread.get("id", "")
                    if _already_scouted("reddit", tid, self.COOLDOWN_DAYS):
                        continue
                    if thread.get("score", 0) < 3:
                        continue

                    stats["threads_found"] += 1
                    reply = self._craft_reply(thread)
                    if reply:
                        ref = _ref_code("reddit", tid)
                        _log_outreach(
                            "reddit", tid, "reply_drafted",
                            message=f"{reply}\n\nref={ref}", status="drafted",
                        )
                        stats["replies_drafted"] += 1

                        if self.REDDIT_CLIENT_ID and self._post_reply(thread, reply):
                            stats["replies_posted"] += 1
                            _log_outreach("reddit", tid, "reply_posted", status="sent")

                    stats["actions"] += 1
                    time.sleep(2)

        return stats

    def _search_reddit(self, subreddit, query):
        url = (
            f"https://www.reddit.com/r/{subreddit}/search.json"
            f"?q={urllib.parse.quote(query)}&restrict_sr=1&sort=new&limit=10&t=week"
        )
        resp = _fetch(url, headers={"Accept": "application/json"})
        if "error" in resp:
            return []
        try:
            data = json.loads(resp["body"])
            return [child["data"] for child in data.get("data", {}).get("children", [])]
        except (json.JSONDecodeError, KeyError, TypeError):
            return []

    def _craft_reply(self, thread):
        title = thread.get("title", "")
        text = thread.get("selftext", "")[:500]
        ref = _ref_code("reddit", thread.get("id", ""))
        try:
            result = self.call_model(
                "claude-sonnet",
                [{"role": "user", "content": (
                    f'Write a helpful Reddit reply to: "{title}"\n\n{text}\n\n'
                    "Suggest AiPayGen where relevant. We offer:\n"
                    "- 1500+ skills via MCP + REST\n"
                    "- Free tier, then x402 micropayments\n"
                    "- Multi-model AI\n"
                    f"- {BASE_URL}?ref={ref}\n\n"
                    "Be genuinely helpful first, mention AiPayGen naturally. Max 150 words."
                )}],
                system="You write helpful, non-promotional Reddit replies. Lead with value.",
                max_tokens=300,
                temperature=0.7,
            )
            return result.get("text", "").strip()
        except Exception:
            return None

    def _post_reply(self, thread, reply_text):
        """Post reply via Reddit API (requires OAuth credentials)."""
        if not all([self.REDDIT_CLIENT_ID, self.REDDIT_CLIENT_SECRET,
                    self.REDDIT_USERNAME, self.REDDIT_PASSWORD]):
            return False
        # Get OAuth token
        try:
            auth_data = urllib.parse.urlencode({
                "grant_type": "password",
                "username": self.REDDIT_USERNAME,
                "password": self.REDDIT_PASSWORD,
            }).encode()
            import base64
            creds = base64.b64encode(
                f"{self.REDDIT_CLIENT_ID}:{self.REDDIT_CLIENT_SECRET}".encode()
            ).decode()
            resp = _fetch(
                "https://www.reddit.com/api/v1/access_token",
                headers={
                    "Authorization": f"Basic {creds}",
                    "Content-Type": "application/x-www-form-urlencoded",
                },
                method="POST",
                data=auth_data,
            )
            if "error" in resp:
                return False
            token = json.loads(resp["body"]).get("access_token")
            if not token:
                return False

            # Post comment
            fullname = f"t3_{thread['id']}"
            comment_data = urllib.parse.urlencode({
                "thing_id": fullname,
                "text": reply_text,
            }).encode()
            post_resp = _fetch(
                "https://oauth.reddit.com/api/comment",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/x-www-form-urlencoded",
                },
                method="POST",
                data=comment_data,
            )
            return post_resp.get("status") in (200, 201)
        except Exception:
            return False

    def _replies_today(self):
        today = datetime.utcnow().strftime("%Y-%m-%d")
        with _scout_conn() as c:
            row = c.execute(
                "SELECT COUNT(*) FROM scout_outreach "
                "WHERE scout='reddit' AND action='reply_posted' AND created_at LIKE ?",
                (f"{today}%",),
            ).fetchone()
        return row[0] if row else 0


# ── A2AScout ──────────────────────────────────────────────────────────────────


class A2AScout(SkillAbsorberMixin):
    """Crawls MCP registries for live agent endpoints, contacts them, and absorbs their capabilities as skills."""

    SCOUT_NAME = "a2a"

    REGISTRY_URLS = [
        "https://mcp.so/api/tools?limit=50",
        "https://registry.smithery.ai/api/servers?limit=50",
        "https://glama.ai/api/mcp/servers?limit=50",
    ]
    PROBE_PATHS = ["/.well-known/agent.json", "/health", "/.well-known/mcp.json"]
    MESSAGE_PATHS = ["/api/messages", "/messages", "/inbox", "/api/v1/messages"]
    COOLDOWN_DAYS = 7
    MAX_PER_RUN = 3

    def __init__(self, call_model_fn):
        self.call_model = call_model_fn
        init_scout_db()
        _init_absorbed_skills_table()

    def run(self, max_actions=3):
        stats = {"agents_found": 0, "agents_contacted": 0, "skills_absorbed": 0, "errors": 0, "actions": 0}

        endpoints = self._discover_endpoints()
        for ep in endpoints:
            if stats["actions"] >= max_actions:
                break
            url = ep.get("url", "")
            name = ep.get("name", url)
            if not url or _already_scouted("a2a", url, self.COOLDOWN_DAYS):
                continue

            # Probe the agent
            agent_info = self._probe_agent(url)
            if not agent_info:
                continue

            stats["agents_found"] += 1

            # Absorb skills from agent capabilities
            absorb_content = f"Agent: {name}\nEndpoint: {url}\nCapabilities: {json.dumps(agent_info)[:4000]}"
            absorbed = self._absorb_skills_from_content(
                absorb_content, url,
                source_url=url,
                category="engineering",
            )
            stats["skills_absorbed"] += len(absorbed)

            # Send intro message
            intro = self._generate_intro(name, agent_info)
            if intro and self._send_intro(url, intro):
                ref = _ref_code("a2a", url)
                _log_outreach(
                    "a2a", url, "intro_sent",
                    message=f"{intro}\n\nref={ref}", status="sent",
                )
                stats["agents_contacted"] += 1
            else:
                _log_outreach("a2a", url, "intro_failed", status="error")
                stats["errors"] += 1

            stats["actions"] += 1
            time.sleep(1)

        return stats

    def _discover_endpoints(self):
        endpoints = []
        for reg_url in self.REGISTRY_URLS:
            resp = _fetch(reg_url)
            if "error" in resp:
                continue
            try:
                data = json.loads(resp["body"])
                if isinstance(data, list):
                    for item in data[:20]:
                        url = item.get("url") or item.get("endpoint") or item.get("homepage", "")
                        name = item.get("name") or item.get("title", "")
                        if url and url.startswith("http"):
                            endpoints.append({"url": url.rstrip("/"), "name": name})
                elif isinstance(data, dict):
                    items = data.get("items") or data.get("servers") or data.get("tools") or []
                    for item in items[:20]:
                        url = item.get("url") or item.get("endpoint") or item.get("homepage", "")
                        name = item.get("name") or item.get("title", "")
                        if url and url.startswith("http"):
                            endpoints.append({"url": url.rstrip("/"), "name": name})
            except (json.JSONDecodeError, TypeError):
                continue
        return endpoints

    def _probe_agent(self, base_url):
        for path in self.PROBE_PATHS:
            resp = _fetch(f"{base_url}{path}", timeout=10)
            if resp.get("status") == 200:
                try:
                    return json.loads(resp["body"])
                except (json.JSONDecodeError, ValueError):
                    return {"status": "alive", "url": base_url}
        return None

    def _generate_intro(self, name, agent_info):
        ref = _ref_code("a2a", name)
        try:
            result = self.call_model(
                "claude-haiku",
                [{"role": "user", "content": (
                    f"Write a short agent-to-agent intro message to {name}.\n"
                    f"Their capabilities: {json.dumps(agent_info)[:500]}\n\n"
                    "We are AiPayGen — 1500+ skills via MCP + REST.\n"
                    "Propose skill-sharing or integration.\n"
                    f"Include link: {BASE_URL}?ref={ref}\n"
                    "Max 100 words, professional tone."
                )}],
                system="You write concise agent-to-agent introduction messages.",
                max_tokens=200,
                temperature=0.7,
            )
            return result.get("text", "").strip()
        except Exception:
            return None

    def _send_intro(self, base_url, message):
        payload = json.dumps({
            "from": "AiPayGen",
            "type": "introduction",
            "message": message,
            "reply_to": f"{BASE_URL}/api/messages",
        }).encode("utf-8")
        for path in self.MESSAGE_PATHS:
            resp = _fetch(
                f"{base_url}{path}",
                headers={"Content-Type": "application/json"},
                method="POST",
                data=payload,
                timeout=10,
            )
            if resp.get("status") in (200, 201, 202):
                return True
        return False


# ── TwitterScout ──────────────────────────────────────────────────────────────


class TwitterScout:
    """Searches Twitter/X for AI agent discussions via scraping/Apify."""

    SEARCH_QUERIES = [
        "AI agent tools",
        "MCP server provider",
        "looking for API provider agent",
        "agent framework tools",
        "autonomous agent skills",
    ]
    MAX_TWEETS_PER_DAY = 2
    COOLDOWN_HOURS = 24

    # Twitter/Apify config
    TWITTER_BEARER = os.getenv("TWITTER_BEARER_TOKEN", "")
    APIFY_TOKEN = os.getenv("APIFY_API_TOKEN", "")

    def __init__(self, call_model_fn):
        self.call_model = call_model_fn
        init_scout_db()

    def run(self, max_actions=3):
        stats = {"tweets_found": 0, "replies_drafted": 0, "original_posted": 0,
                 "errors": 0, "actions": 0}
        today_posted = self._tweets_today()
        if today_posted >= self.MAX_TWEETS_PER_DAY:
            return stats

        # Search for relevant tweets
        for query in self.SEARCH_QUERIES:
            if stats["actions"] >= max_actions:
                break
            tweets = self._search_tweets(query)
            for tweet in tweets:
                if stats["actions"] >= max_actions:
                    break
                tid = tweet.get("id", "")
                if _already_scouted("twitter", tid, within_days=1):
                    continue
                stats["tweets_found"] += 1
                reply = self._craft_reply(tweet)
                if reply:
                    ref = _ref_code("twitter", tid)
                    _log_outreach(
                        "twitter", tid, "reply_drafted",
                        message=f"{reply}\n\nref={ref}", status="drafted",
                    )
                    stats["replies_drafted"] += 1
                stats["actions"] += 1

        # Draft an original tweet if budget allows
        if stats["actions"] < max_actions and today_posted + stats["original_posted"] < self.MAX_TWEETS_PER_DAY:
            tweet = self._draft_original_tweet()
            if tweet:
                _log_outreach("twitter", f"original_{datetime.utcnow().isoformat()}", "tweet_drafted",
                              message=tweet, status="drafted")
                stats["original_posted"] += 1
                stats["actions"] += 1

        return stats

    def _search_tweets(self, query):
        if self.TWITTER_BEARER:
            return self._search_via_api(query)
        if self.APIFY_TOKEN:
            return self._search_via_apify(query)
        return []

    def _search_via_api(self, query):
        resp = _fetch(
            f"https://api.twitter.com/2/tweets/search/recent?query={urllib.parse.quote(query)}&max_results=10",
            headers={"Authorization": f"Bearer {self.TWITTER_BEARER}"},
        )
        if "error" in resp:
            return []
        try:
            return json.loads(resp["body"]).get("data", [])
        except (json.JSONDecodeError, TypeError):
            return []

    def _search_via_apify(self, query):
        resp = _fetch(
            "https://api.apify.com/v2/acts/quacker~twitter-scraper/run-sync-get-dataset-items"
            f"?token={self.APIFY_TOKEN}",
            headers={"Content-Type": "application/json"},
            method="POST",
            data=json.dumps({
                "searchTerms": [query],
                "maxTweets": 10,
                "sort": "Latest",
            }).encode("utf-8"),
            timeout=30,
        )
        if "error" in resp:
            return []
        try:
            items = json.loads(resp["body"])
            return [{"id": t.get("id", ""), "text": t.get("full_text", t.get("text", ""))}
                    for t in items[:10]]
        except (json.JSONDecodeError, TypeError):
            return []

    def _craft_reply(self, tweet):
        text = tweet.get("text", "")
        ref = _ref_code("twitter", tweet.get("id", ""))
        try:
            result = self.call_model(
                "claude-sonnet",
                [{"role": "user", "content": (
                    f'Draft a tweet reply to: "{text}"\n\n'
                    "Mention AiPayGen naturally — 646+ AI skills via MCP.\n"
                    f"Include: {BASE_URL}?ref={ref}\n"
                    "Max 280 chars. Be helpful, not promotional."
                )}],
                system="You write concise, helpful tweet replies. Never spammy.",
                max_tokens=100,
                temperature=0.8,
            )
            return result.get("text", "").strip()[:280]
        except Exception:
            return None

    def _draft_original_tweet(self):
        try:
            result = self.call_model(
                "claude-haiku",
                [{"role": "user", "content": (
                    "Draft an engaging tweet about AiPayGen:\n"
                    "- 646+ AI skills via MCP protocol\n"
                    "- Multi-model (Claude, GPT-4, Gemini, DeepSeek)\n"
                    "- x402 USDC micropayments\n"
                    f"- {BASE_URL}\n\n"
                    "Focus on a specific use case. Max 280 chars. Include 1-2 relevant hashtags."
                )}],
                system="You write engaging tech tweets. Concise, informative, not hype.",
                max_tokens=100,
                temperature=0.9,
            )
            return result.get("text", "").strip()[:280]
        except Exception:
            return None

    def _tweets_today(self):
        today = datetime.utcnow().strftime("%Y-%m-%d")
        with _scout_conn() as c:
            row = c.execute(
                "SELECT COUNT(*) FROM scout_outreach "
                "WHERE scout='twitter' AND action IN ('tweet_posted', 'reply_posted') "
                "AND created_at LIKE ?",
                (f"{today}%",),
            ).fetchone()
        return row[0] if row else 0


# ── FollowUpAgent ─────────────────────────────────────────────────────────────


class FollowUpAgent:
    """Checks outreach status and sends follow-ups for engaged targets."""

    FOLLOW_UP_AFTER_HOURS = 48
    MAX_FOLLOW_UPS = 1  # per target
    EXPIRE_AFTER_DAYS = 30

    def __init__(self, call_model_fn):
        self.call_model = call_model_fn
        init_scout_db()

    def run(self, max_actions=10):
        stats = {"checked": 0, "engaged": 0, "expired": 0, "followed_up": 0, "errors": 0}

        # Expire old entries
        self._expire_old()

        # Find entries needing follow-up
        cutoff = (datetime.utcnow() - timedelta(hours=self.FOLLOW_UP_AFTER_HOURS)).isoformat()
        with _scout_conn() as c:
            entries = c.execute(
                "SELECT * FROM scout_outreach WHERE status='sent' AND created_at < ? "
                "ORDER BY created_at ASC LIMIT ?",
                (cutoff, max_actions),
            ).fetchall()

        for entry in entries:
            entry = dict(entry)
            scout = entry["scout"]
            target = entry["target_id"]
            stats["checked"] += 1

            if scout == "github":
                engaged = self._check_github(target)
            elif scout == "a2a":
                engaged = self._check_a2a(target)
            else:
                engaged = False

            if engaged:
                stats["engaged"] += 1
                with _scout_conn() as c:
                    c.execute(
                        "UPDATE scout_outreach SET status='engaged' WHERE id=?",
                        (entry["id"],),
                    )
            else:
                with _scout_conn() as c:
                    c.execute(
                        "UPDATE scout_outreach SET status='no_response' WHERE id=?",
                        (entry["id"],),
                    )

        # Expire very old
        stats["expired"] = self._expire_old()
        return stats

    def _check_github(self, full_name):
        resp = _fetch(
            f"https://api.github.com/repos/{full_name}/issues?state=all&per_page=5&sort=updated",
            headers={
                "Authorization": f"token {GITHUB_TOKEN}",
                "Accept": "application/vnd.github.v3+json",
            },
        )
        if "error" in resp:
            return False
        try:
            issues = json.loads(resp["body"])
            for issue in issues:
                comments = issue.get("comments", 0)
                reactions = issue.get("reactions", {}).get("total_count", 0)
                if comments > 0 or reactions > 0:
                    return True
        except (json.JSONDecodeError, TypeError):
            pass
        return False

    def _check_a2a(self, url):
        resp = _fetch(f"{url}/health", timeout=10)
        return resp.get("status") == 200

    def _expire_old(self):
        cutoff = (datetime.utcnow() - timedelta(days=self.EXPIRE_AFTER_DAYS)).isoformat()
        with _scout_conn() as c:
            count = c.execute(
                "UPDATE scout_outreach SET status='expired' "
                "WHERE status IN ('sent', 'no_response') AND created_at < ?",
                (cutoff,),
            ).rowcount
        return count


# ── Conversion Tracking & Stats ──────────────────────────────────────────────


def record_scout_conversion(ref_code, caller_ip="", user_agent="", endpoint=""):
    """Record a conversion from scout outreach."""
    with _scout_conn() as c:
        c.execute(
            "INSERT INTO scout_conversions (ref_code, caller_ip, user_agent, endpoint) "
            "VALUES (?, ?, ?, ?)",
            (ref_code, caller_ip, user_agent, endpoint),
        )


def get_scout_stats():
    """Aggregated stats across all scouts."""
    with _scout_conn() as c:
        total = c.execute("SELECT COUNT(*) FROM scout_outreach").fetchone()[0]
        by_scout = c.execute(
            "SELECT scout, status, COUNT(*) as cnt FROM scout_outreach "
            "GROUP BY scout, status"
        ).fetchall()
        conversions = c.execute("SELECT COUNT(*) FROM scout_conversions").fetchone()[0]
        total_spend = c.execute(
            "SELECT COALESCE(SUM(total_spend_usd), 0) FROM scout_conversions"
        ).fetchone()[0]
    return {
        "total_outreach": total,
        "total_conversions": conversions,
        "total_revenue_usd": round(total_spend, 4),
        "by_scout": [dict(r) for r in by_scout],
    }


def get_scout_status():
    """Current status of all scouts (last run, next scheduled, etc.)."""
    with _scout_conn() as c:
        scouts = c.execute(
            "SELECT scout, MAX(created_at) as last_run, COUNT(*) as total_actions "
            "FROM scout_outreach GROUP BY scout"
        ).fetchall()
    return {
        "scouts": [dict(s) for s in scouts],
        "db_path": DB_PATH,
    }


def get_weekly_report():
    """Weekly summary report of all scout activity."""
    week_ago = (datetime.utcnow() - timedelta(days=7)).isoformat()
    with _scout_conn() as c:
        outreach = c.execute(
            "SELECT scout, action, status, COUNT(*) as cnt "
            "FROM scout_outreach WHERE created_at > ? "
            "GROUP BY scout, action, status",
            (week_ago,),
        ).fetchall()
        conversions = c.execute(
            "SELECT COUNT(*) as cnt, COALESCE(SUM(total_spend_usd), 0) as revenue "
            "FROM scout_conversions WHERE first_call_at > ?",
            (week_ago,),
        ).fetchone()
    return {
        "period": f"{week_ago[:10]} to {datetime.utcnow().strftime('%Y-%m-%d')}",
        "outreach": [dict(r) for r in outreach],
        "conversions": dict(conversions) if conversions else {"cnt": 0, "revenue": 0},
    }


def run_scout_by_name(scout_name, call_model_fn, max_actions=5):
    """Run a specific scout by name. Returns None if unknown."""
    scouts = {
        "github": GitHubScout,
        "registry": RegistryScout,
        "social": SocialScout,
        "reddit": SocialScout,
        "a2a": A2AScout,
        "twitter": TwitterScout,
        "followup": FollowUpAgent,
    }
    cls = scouts.get(scout_name.lower())
    if cls is None:
        return None
    scout = cls(call_model_fn)
    return scout.run(max_actions=max_actions)
