"""
Outbound Recruitment Agent — OVERDRIVE MODE

Actively finds and connects with x402 services, agent registries, MCP directories,
and AI communities. Scrapes GitHub, awesome-lists, and agent directories for targets.

Runs every 2 hours. 20 actions per run (240/day max).
All actions are rate-limited, idempotent, and logged.
"""
import os
import json
import re
import sqlite3
import time
import urllib.request
import urllib.error
import urllib.parse
from datetime import datetime, timedelta

BASE_URL = os.getenv("BASE_URL", "https://api.aipaygen.com")
WALLET = os.getenv("WALLET_ADDRESS", "0x366D488a48de1B2773F3a21F1A6972715056Cb30")
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")
DB_PATH = os.path.join(os.path.dirname(__file__), "discovery_engine.db")
USER_AGENT = "AiPayGen-OutboundAgent/2.0 (+https://api.aipaygen.com)"
FETCH_TIMEOUT = 15
MAX_ACTIONS_PER_RUN = 20
DEDUP_DAYS = 7  # shorter cooldown = more aggressive

# ── Massive seed list ──────────────────────────────────────────────────

SEED_SERVICES = [
    # x402 ecosystem
    {"url": "https://blockrun.io", "name": "BlockRun", "type": "x402"},
    {"url": "https://api.blockrun.io", "name": "BlockRun API", "type": "x402"},
    {"url": "https://pylon.bot", "name": "Pylon", "type": "x402"},
    {"url": "https://api.pylon.bot", "name": "Pylon API", "type": "x402"},
    {"url": "https://x402.org", "name": "x402.org", "type": "x402"},
    {"url": "https://www.x402.org", "name": "x402.org", "type": "x402"},
    {"url": "https://x402.xyz", "name": "x402.xyz", "type": "x402"},
    {"url": "https://paywithx402.com", "name": "PayWithx402", "type": "x402"},
    {"url": "https://402.ai", "name": "402.ai", "type": "x402"},
    {"url": "https://paywall.x402.org", "name": "x402 Paywall", "type": "x402"},
    # Agent platforms
    {"url": "https://agentprotocol.ai", "name": "Agent Protocol", "type": "agent"},
    {"url": "https://agentverse.ai", "name": "Agentverse", "type": "agent"},
    {"url": "https://fetch.ai", "name": "Fetch.ai", "type": "agent"},
    {"url": "https://api.fetch.ai", "name": "Fetch.ai API", "type": "agent"},
    {"url": "https://uagents.fetch.ai", "name": "Fetch uAgents", "type": "agent"},
    {"url": "https://autonome.alt.technology", "name": "Autonome", "type": "agent"},
    {"url": "https://wasp.network", "name": "WASP Network", "type": "agent"},
    {"url": "https://nevermined.io", "name": "Nevermined", "type": "agent"},
    {"url": "https://api.nevermined.io", "name": "Nevermined API", "type": "agent"},
    {"url": "https://morpheus.network", "name": "Morpheus", "type": "agent"},
    {"url": "https://virtuals.io", "name": "Virtuals Protocol", "type": "agent"},
    {"url": "https://autonolas.network", "name": "Autonolas/Olas", "type": "agent"},
    # MCP services
    {"url": "https://mcp.so", "name": "MCP.so", "type": "mcp_directory"},
    {"url": "https://smithery.ai", "name": "Smithery", "type": "mcp_directory"},
    {"url": "https://glama.ai", "name": "Glama", "type": "mcp_directory"},
    {"url": "https://mcprepository.com", "name": "MCP Repository", "type": "mcp_directory"},
    {"url": "https://mcpservers.org", "name": "MCP Servers", "type": "mcp_directory"},
    {"url": "https://mcpindex.net", "name": "MCP Index", "type": "mcp_directory"},
    {"url": "https://metorial.com", "name": "Metorial", "type": "mcp_directory"},
    # AI API marketplaces
    {"url": "https://rapidapi.com", "name": "RapidAPI", "type": "marketplace"},
    {"url": "https://replicate.com", "name": "Replicate", "type": "marketplace"},
    {"url": "https://deepinfra.com", "name": "DeepInfra", "type": "marketplace"},
    {"url": "https://together.ai", "name": "Together AI", "type": "marketplace"},
]

# Registries to submit to
AGENT_REGISTRIES = [
    {"url": "https://agentarena.io/api/register", "name": "Agent Arena"},
    {"url": "https://a2a.directory/api/agents", "name": "A2A Directory"},
    {"url": "https://agentverse.ai/api/v1/agents", "name": "Agentverse"},
    {"url": "https://registry.autonolas.network/api/agents", "name": "Olas Registry"},
    {"url": "https://agent-protocol.ai/api/register", "name": "Agent Protocol"},
    {"url": "https://api.fetch.ai/v2/agents/register", "name": "Fetch.ai"},
    {"url": "https://nevermined.io/api/register", "name": "Nevermined"},
]

# GitHub repos to post issues/discussions about AiPayGen
GITHUB_OUTREACH_REPOS = [
    "coinbase/x402",
    "anthropics/anthropic-cookbook",
    "anthropics/courses",
    "modelcontextprotocol/servers",
    "punkpeye/awesome-mcp-servers",
    "chatmcp/mcpso",
    "appcypher/awesome-llm-apps",
    "e2b-dev/awesome-ai-agents",
    "kyrolabs/awesome-langchain",
    "filipecalegario/awesome-generative-ai",
    "steven2358/awesome-generative-ai",
    "aimerou/awesome-ai-papers",
]

# GitHub search queries to find new x402/agent services
GITHUB_SEARCH_QUERIES = [
    "x402 payment agent",
    "x402 protocol service",
    "agent-to-agent payment crypto",
    "MCP server payment",
    "AI agent marketplace blockchain",
    "402 payment required AI",
    "x402 USDC",
    "ERC-8004 agent",
    "AI agent API framework",
    "autonomous agent framework python",
    "LLM tool use framework",
    "function calling agent",
    "crypto payment API USDC",
    "USDC payment service API",
    "AI microservices platform",
    "agent orchestration framework",
    "MCP model context protocol tools",
    "agent registry directory",
    "paid AI endpoint SaaS",
    "multi-model routing LLM gateway",
    "web scraping API service",
    "AI knowledge base API",
]

OUR_MANIFEST = {
    "name": "AiPayGen",
    "description": "AI agent service with 1500+ skills, 4100+ API catalog, multi-model routing (Claude/GPT-4/Gemini/DeepSeek/Llama/Mistral), x402 payments, MCP distribution. Free tier available.",
    "url": BASE_URL,
    "wallet": WALLET,
    "capabilities": ["x402", "mcp", "a2a", "skills", "multi-model", "agent-memory", "marketplace", "api-catalog"],
    "skills_count": 1500,
    "catalog_apis": "4100+",
    "models": ["claude-sonnet", "claude-haiku", "gpt-4o", "gemini-2-flash", "deepseek-chat", "llama-3.3-70b", "mistral-large"],
    "endpoints": {
        "health": f"{BASE_URL}/health",
        "discover": f"{BASE_URL}/discover",
        "skills": f"{BASE_URL}/skills",
        "skills_search": f"{BASE_URL}/skills/search",
        "ask": f"{BASE_URL}/ask",
        "mcp": f"{BASE_URL}/mcp",
        "well_known_x402": f"{BASE_URL}/.well-known/x402.json",
        "well_known_agent": f"{BASE_URL}/.well-known/agent.json",
        "openapi": f"{BASE_URL}/openapi.json",
    },
    "pricing": "Free tier available. Pay-per-use via x402 (USDC on Base).",
    "source": "https://github.com/Damien829/aipaygen",
}

_INTRO_TEMPLATES = {
    "x402": "Hi {name}! We noticed your x402 payment endpoint at {url}. AiPayGen is an AI agent platform on Base Mainnet with 1500+ skills, 4100+ callable API catalog, and 155 MCP tools. We'd love to explore mutual discovery listing and x402 interoperability. Check us out: https://api.aipaygen.com/.well-known/x402.json | Catalog: https://api.aipaygen.com/catalog",
    "mcp_directory": "Hi {name}! AiPayGen offers 155 metered MCP tools across 5 pricing tiers plus a 4100+ API catalog accessible via MCP. SSE and streamable-HTTP transports supported. We'd love to be listed on {url}. Our MCP endpoint: https://api.aipaygen.com/mcp — install via pip: `pip install aipaygen-mcp`. Details: https://api.aipaygen.com/discover",
    "agent": "Hi {name}! AiPayGen is an AI agent service with 1500+ skills, 4100+ callable API catalog, 13 specialist agents, and A2A protocol support. Our agents can discover and call any API in the catalog, chain skills, share memory, and transact via x402 USDC. Let's connect! API: https://api.aipaygen.com",
    "marketplace": "Hi {name}! We'd love to list AiPayGen on your platform. We offer 1500+ AI skills, 4100+ API catalog, 155 MCP tools, 13 specialist agents, and multi-model routing across 15 models. Monetized via x402 USDC and API keys. Homepage: https://aipaygen.com | API: https://api.aipaygen.com/discover",
    "github_repo": "Great project! AiPayGen is a complementary AI agent platform with 1500+ skills, 4100+ callable API catalog, and 155 MCP tools. We support x402 payments, A2A protocol, and multi-model routing. Would love to explore collaboration or integration. Check us out: https://github.com/Damien829/aipaygen",
}


def _conn():
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    return c


def _ensure_tables():
    with _conn() as c:
        c.execute("""
            CREATE TABLE IF NOT EXISTS discovered_services (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                url TEXT UNIQUE NOT NULL,
                name TEXT,
                service_type TEXT NOT NULL,
                manifest JSON,
                our_status TEXT DEFAULT 'discovered',
                last_contacted TEXT,
                response_summary TEXT,
                discovered_at TEXT NOT NULL
            )
        """)
        c.execute("CREATE INDEX IF NOT EXISTS idx_ds_url ON discovered_services(url)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_ds_type ON discovered_services(service_type)")
        # Add source/quality_score columns for api_hunter integration
        for col, dtype in [("source", "TEXT"), ("quality_score", "REAL DEFAULT 0")]:
            try:
                c.execute(f"ALTER TABLE discovered_services ADD COLUMN {col} {dtype}")
            except Exception:
                pass  # column already exists
        c.execute("""
            CREATE TABLE IF NOT EXISTS outreach_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                action TEXT NOT NULL,
                target TEXT NOT NULL,
                status TEXT NOT NULL,
                detail TEXT DEFAULT '',
                created_at TEXT NOT NULL
            )
        """)
        c.execute("CREATE INDEX IF NOT EXISTS idx_ol_target_date ON outreach_log(target, created_at)")


def _log(action: str, target: str, status: str, detail: str = ""):
    now = datetime.utcnow().isoformat()
    with _conn() as c:
        c.execute(
            "INSERT INTO outreach_log (action, target, status, detail, created_at) VALUES (?, ?, ?, ?, ?)",
            (action, target, status, detail, now),
        )


def _record_outcome(action: str, target: str, status: str, strategy: str = "", detail: str = ""):
    """Log result with granular status and strategy tag for success rate tracking."""
    now = datetime.utcnow().isoformat()
    with _conn() as c:
        c.execute(
            "INSERT INTO outreach_log (action, target, status, detail, created_at) VALUES (?, ?, ?, ?, ?)",
            (f"{strategy}:{action}" if strategy else action, target, status, detail, now),
        )


def _already_targeted(target: str, within_days: int = DEDUP_DAYS) -> bool:
    cutoff = (datetime.utcnow() - timedelta(days=within_days)).isoformat()
    with _conn() as c:
        row = c.execute(
            "SELECT id FROM outreach_log WHERE target=? AND created_at > ?",
            (target, cutoff),
        ).fetchone()
    return row is not None


def _fetch(url: str, headers: dict = None, timeout: int = FETCH_TIMEOUT, method: str = "GET", data: bytes = None) -> dict:
    """SSRF-safe fetch. Validates URL before fetching."""
    from security import safe_fetch as _safe_fetch
    extra_headers = {"User-Agent": USER_AGENT}
    if headers:
        extra_headers.update(headers)
    return _safe_fetch(url, headers=extra_headers, timeout=timeout, method=method,
                       data=data, max_size=100000, allow_http=True)


def _gh_api(path: str, method: str = "GET", payload: dict = None) -> dict:
    """GitHub API call with token auth."""
    if not GITHUB_TOKEN:
        return {"error": "no github token"}
    hdrs = {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json",
        "Content-Type": "application/json",
    }
    data = json.dumps(payload).encode("utf-8") if payload else None
    return _fetch(f"https://api.github.com/{path.lstrip('/')}", headers=hdrs, method=method, data=data)


def _upsert_service(url: str, name: str, service_type: str, manifest: dict = None, status: str = "discovered"):
    now = datetime.utcnow().isoformat()
    manifest_json = json.dumps(manifest) if manifest else None
    with _conn() as c:
        c.execute("""
            INSERT INTO discovered_services (url, name, service_type, manifest, our_status, discovered_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(url) DO UPDATE SET
                name = COALESCE(excluded.name, name),
                manifest = COALESCE(excluded.manifest, manifest),
                our_status = excluded.our_status
        """, (url, name, service_type, manifest_json, status, now))


def _update_service_status(url: str, status: str, response_summary: str = ""):
    now = datetime.utcnow().isoformat()
    with _conn() as c:
        c.execute(
            "UPDATE discovered_services SET our_status=?, last_contacted=?, response_summary=? WHERE url=?",
            (status, now, response_summary, url),
        )


class OutboundAgent:
    def __init__(self, call_model_fn, parse_json_fn):
        self.call_model = call_model_fn
        self.parse_json = parse_json_fn
        _ensure_tables()

    def run_all(self) -> dict:
        """Run all outbound strategies. 20 actions per run."""
        stats = {
            "actions_taken": 0,
            "x402_scanned": 0,
            "github_discovered": 0,
            "registrations": 0,
            "agents_contacted": 0,
            "posts_made": 0,
            "directory_scraped": 0,
            "errors": 0,
            "started_at": datetime.utcnow().isoformat(),
        }
        actions_left = MAX_ACTIONS_PER_RUN

        strategies = [
            ("x402", self.scan_x402_services, "x402_scanned", 6),
            ("github_discover", self.discover_from_github, "github_discovered", 4),
            ("directory_scrape", self.scrape_directories, "directory_scraped", 3),
            ("registry", self.register_at_directories, "registrations", 3),
            ("a2a", self.discover_and_contact_agents, "agents_contacted", 2),
            ("community", self.post_to_communities, "posts_made", 2),
            ("follow_up", self.follow_up_targets, "follow_ups", 2),
        ]

        for name, fn, stat_key, budget in strategies:
            if actions_left <= 0:
                break
            alloc = min(budget, actions_left)
            try:
                result = fn(max_actions=alloc)
                used = result.get("actions", 0)
                stats[stat_key] += result.get(stat_key, result.get("scanned", result.get("contacted", result.get("registered", result.get("scraped", result.get("posts", 0))))))
                stats["errors"] += result.get("errors", 0)
                stats["actions_taken"] += used
                actions_left -= used
            except Exception as e:
                _log("outbound_strategy_error", name, "error", str(e))
                stats["errors"] += 1

        stats["finished_at"] = datetime.utcnow().isoformat()
        _log("outbound_run", "all", "ok", json.dumps(stats))
        return stats

    # ── Strategy 1: x402 Cross-Pollination ──────────────────────────────

    def scan_x402_services(self, max_actions: int = 6) -> dict:
        result = {"x402_scanned": 0, "actions": 0, "errors": 0}

        urls_to_scan = list(SEED_SERVICES)
        urls_to_scan.extend(self._fetch_x402scan())
        urls_to_scan.extend(self._get_undiscovered_from_db())

        for svc in urls_to_scan:
            if result["actions"] >= max_actions:
                break

            url = svc["url"].rstrip("/")
            target_key = f"x402_scan:{url}"
            if _already_targeted(target_key):
                continue

            time.sleep(0.5)

            # Probe multiple well-known paths
            manifest = self._probe_x402_manifest(url)
            agent_json = self._probe_agent_json(url)

            if manifest or agent_json:
                _upsert_service(url, svc.get("name", url), "x402", manifest or agent_json)
                result["x402_scanned"] += 1
                self._register_with_service(url, manifest or agent_json)
                time.sleep(0.5)
                self._ping_with_headers(url)
                # Extract links to other services from their manifest
                self._extract_links_from_manifest(manifest or agent_json)
                _log("x402_scan", target_key, "ok", "manifest found, registered, pinged")
            else:
                _upsert_service(url, svc.get("name", url), svc.get("type", "x402"), status="no_manifest")
                # Still ping them to leave traces
                self._ping_with_headers(url)
                _log("x402_scan", target_key, "pinged", "no manifest but left traces")

            result["actions"] += 1

        return result

    def _get_undiscovered_from_db(self) -> list:
        """Get services from DB that haven't been scanned recently. Prioritize high-quality hunter targets."""
        cutoff = (datetime.utcnow() - timedelta(days=DEDUP_DAYS)).isoformat()
        with _conn() as c:
            rows = c.execute(
                "SELECT url, name, service_type, COALESCE(source, '') as source, "
                "COALESCE(quality_score, 0) as quality_score "
                "FROM discovered_services "
                "WHERE (last_contacted IS NULL OR last_contacted < ?) "
                "ORDER BY quality_score DESC, discovered_at DESC LIMIT 20",
                (cutoff,),
            ).fetchall()
        return [{"url": r["url"], "name": r["name"], "type": r["service_type"],
                 "source": r["source"], "quality_score": r["quality_score"]} for r in rows]

    def _fetch_x402scan(self) -> list:
        services = []
        for api_url in ["https://x402scan.com/api/services", "https://x402scan.com/api/v1/services", "https://api.x402.org/services"]:
            try:
                resp = _fetch(api_url)
                if "error" not in resp and resp.get("status") == 200:
                    data = json.loads(resp["body"])
                    items = data if isinstance(data, list) else data.get("services", data.get("items", data.get("data", [])))
                    for item in (items or [])[:30]:
                        if isinstance(item, dict) and item.get("url"):
                            services.append({"url": item["url"], "name": item.get("name", item["url"]), "type": "x402"})
            except Exception:
                pass
        return services

    def _probe_x402_manifest(self, base_url: str) -> dict:
        for path in ["/.well-known/x402.json", "/.well-known/pay.json", "/x402.json"]:
            resp = _fetch(f"{base_url}{path}")
            if "error" not in resp and resp.get("status") == 200:
                try:
                    return json.loads(resp["body"])
                except (json.JSONDecodeError, ValueError):
                    pass
        return None

    def _probe_agent_json(self, base_url: str) -> dict:
        for path in ["/.well-known/agent.json", "/.well-known/ai-plugin.json", "/agent.json"]:
            resp = _fetch(f"{base_url}{path}")
            if "error" not in resp and resp.get("status") == 200:
                try:
                    return json.loads(resp["body"])
                except (json.JSONDecodeError, ValueError):
                    pass
        return None

    def _register_with_service(self, base_url: str, manifest: dict):
        register_paths = ["/agents/register", "/api/register", "/register", "/api/v1/agents", "/api/agents"]
        payload = json.dumps(OUR_MANIFEST).encode("utf-8")
        for path in register_paths:
            try:
                resp = _fetch(
                    f"{base_url}{path}",
                    headers={"Content-Type": "application/json"},
                    method="POST",
                    data=payload,
                )
                status = resp.get("status", 0)
                if status in (200, 201, 202):
                    _update_service_status(base_url, "registered", f"via {path}: {resp.get('body', '')[:200]}")
                    _log("x402_register", base_url, "ok", f"{path} -> {status}")
                    return
            except Exception:
                continue

    def _ping_with_headers(self, base_url: str):
        headers = {
            "X-Agent-URL": BASE_URL,
            "X-Agent-Wallet": WALLET,
            "X-Agent-Name": "AiPayGen",
            "X-Agent-Skills": "646",
            "X-Agent-MCP": f"{BASE_URL}/mcp",
            "X-Agent-Capabilities": "x402,mcp,a2a,multi-model",
        }
        for path in ["/discover", "/health", "/", "/.well-known/agent.json", "/api/health", "/api/discover"]:
            try:
                _fetch(f"{base_url}{path}", headers=headers, timeout=5)
            except Exception:
                pass
            time.sleep(0.3)

    def _extract_links_from_manifest(self, manifest: dict):
        """Extract URLs from a service's manifest and add them to discovery queue."""
        if not manifest:
            return
        text = json.dumps(manifest)
        urls = re.findall(r'https?://[a-zA-Z0-9\-._~:/?#\[\]@!$&\'()*+,;=%]+', text)
        for url in urls:
            url = url.rstrip('",}]')
            if any(skip in url for skip in ["localhost", "127.0.0.1", "aipaygen", "example.com"]):
                continue
            try:
                domain = url.split("//")[1].split("/")[0]
                base = f"https://{domain}"
                _upsert_service(base, domain, "discovered_link")
            except Exception:
                pass

    # ── Strategy 2: GitHub Discovery ────────────────────────────────────

    def discover_from_github(self, max_actions: int = 4) -> dict:
        result = {"github_discovered": 0, "actions": 0, "errors": 0}
        if not GITHUB_TOKEN:
            return result

        for query in GITHUB_SEARCH_QUERIES:
            if result["actions"] >= max_actions:
                break

            target_key = f"gh_search:{query}"
            if _already_targeted(target_key, within_days=3):
                continue

            time.sleep(1)
            try:
                resp = _gh_api(f"search/repositories?q={urllib.parse.quote(query)}&sort=updated&per_page=10")
                if "error" in resp:
                    result["errors"] += 1
                    continue

                data = json.loads(resp["body"])
                for repo in data.get("items", [])[:10]:
                    repo_url = repo.get("homepage") or repo.get("html_url", "")
                    repo_name = repo.get("full_name", "")
                    if repo_url and "aipaygen" not in repo_url.lower():
                        _upsert_service(repo_url, repo_name, "github_repo", {
                            "description": repo.get("description", ""),
                            "stars": repo.get("stargazers_count", 0),
                            "language": repo.get("language", ""),
                            "html_url": repo.get("html_url", ""),
                        })
                        result["github_discovered"] += 1

                _log("gh_search", target_key, "ok", f"{len(data.get('items', []))} repos found for '{query}'")
            except Exception as e:
                _log("gh_search", target_key, "error", str(e))
                result["errors"] += 1

            result["actions"] += 1

        return result

    # ── Strategy 3: Directory Scraping ──────────────────────────────────

    def scrape_directories(self, max_actions: int = 3) -> dict:
        result = {"directory_scraped": 0, "actions": 0, "errors": 0}

        scrapers = [
            ("mcp.so", self._scrape_mcp_so),
            ("smithery.ai", self._scrape_smithery),
            ("glama.ai", self._scrape_glama),
            ("awesome-mcp-servers", self._scrape_awesome_mcp),
        ]

        for name, scraper in scrapers:
            if result["actions"] >= max_actions:
                break

            target_key = f"scrape:{name}"
            if _already_targeted(target_key, within_days=3):
                continue

            time.sleep(1)
            try:
                found = scraper()
                result["directory_scraped"] += found
                _log("directory_scrape", target_key, "ok", f"found {found} services")
            except Exception as e:
                _log("directory_scrape", target_key, "error", str(e))
                result["errors"] += 1

            result["actions"] += 1

        return result

    def _scrape_mcp_so(self) -> int:
        """Scrape mcp.so for MCP server listings."""
        found = 0
        for page_url in ["https://mcp.so/api/servers", "https://mcp.so/api/v1/servers"]:
            resp = _fetch(page_url)
            if "error" in resp:
                continue
            try:
                data = json.loads(resp["body"])
                items = data if isinstance(data, list) else data.get("servers", data.get("items", []))
                for item in (items or [])[:50]:
                    if isinstance(item, dict):
                        url = item.get("url") or item.get("homepage") or item.get("endpoint", "")
                        name = item.get("name", item.get("title", ""))
                        if url and "aipaygen" not in url.lower():
                            _upsert_service(url, name, "mcp_server")
                            found += 1
            except Exception:
                pass
        # Also try scraping the HTML
        resp = _fetch("https://mcp.so/servers")
        if "error" not in resp:
            urls = re.findall(r'href="(https?://[^"]+)"', resp.get("body", ""))
            for url in urls[:30]:
                if any(skip in url for skip in ["mcp.so", "aipaygen", "github.com/login", "twitter.com"]):
                    continue
                _upsert_service(url, url.split("//")[1].split("/")[0], "mcp_linked")
                found += 1
        return found

    def _scrape_smithery(self) -> int:
        found = 0
        for api_url in ["https://smithery.ai/api/servers", "https://smithery.ai/api/v1/servers"]:
            resp = _fetch(api_url)
            if "error" in resp:
                continue
            try:
                data = json.loads(resp["body"])
                items = data if isinstance(data, list) else data.get("servers", data.get("items", []))
                for item in (items or [])[:50]:
                    if isinstance(item, dict):
                        url = item.get("url") or item.get("homepage", "")
                        name = item.get("name", "")
                        if url:
                            _upsert_service(url, name, "mcp_server")
                            found += 1
            except Exception:
                pass
        return found

    def _scrape_glama(self) -> int:
        found = 0
        resp = _fetch("https://glama.ai/mcp/servers")
        if "error" not in resp:
            urls = re.findall(r'href="(https?://[^"]+)"', resp.get("body", ""))
            for url in urls[:30]:
                if any(skip in url for skip in ["glama.ai", "aipaygen", "github.com/login"]):
                    continue
                _upsert_service(url, url.split("//")[1].split("/")[0], "mcp_linked")
                found += 1
        return found

    def _scrape_awesome_mcp(self) -> int:
        """Scrape awesome-mcp-servers README for service URLs."""
        found = 0
        resp = _gh_api("repos/punkpeye/awesome-mcp-servers/readme")
        if "error" in resp:
            return 0
        try:
            data = json.loads(resp["body"])
            import base64
            content = base64.b64decode(data.get("content", "")).decode("utf-8", errors="replace")
            urls = re.findall(r'https?://[^\s\)>\]"]+', content)
            for url in urls[:100]:
                url = url.rstrip(".,;:")
                if any(skip in url for skip in ["github.com", "aipaygen", "img.shields", "badge"]):
                    continue
                _upsert_service(url, url.split("//")[1].split("/")[0], "awesome_list_link")
                found += 1
        except Exception:
            pass
        return found

    # ── Strategy 4: Agent Registry Registration ─────────────────────────

    def register_at_directories(self, max_actions: int = 3) -> dict:
        result = {"registrations": 0, "actions": 0, "errors": 0}

        for reg in AGENT_REGISTRIES:
            if result["actions"] >= max_actions:
                break

            target_key = f"registry:{reg['url']}"
            if _already_targeted(target_key, within_days=30):
                continue

            time.sleep(1)
            payload = json.dumps(OUR_MANIFEST).encode("utf-8")

            try:
                resp = _fetch(
                    reg["url"],
                    headers={"Content-Type": "application/json"},
                    method="POST",
                    data=payload,
                )
                status = resp.get("status", 0)
                if status in (200, 201, 202):
                    _upsert_service(reg["url"], reg["name"], "registry", status="registered")
                    _log("registry_register", target_key, "ok", resp.get("body", "")[:200])
                    result["registrations"] += 1
                else:
                    _upsert_service(reg["url"], reg["name"], "registry", status="attempted")
                    _log("registry_register", target_key, "attempted", f"HTTP {status}")
                    result["errors"] += 1
            except Exception as e:
                _log("registry_register", target_key, "error", str(e))
                result["errors"] += 1

            result["actions"] += 1

        return result

    # ── Strategy 5: Agent-to-Agent Networking ───────────────────────────

    def discover_and_contact_agents(self, max_actions: int = 2) -> dict:
        result = {"agents_contacted": 0, "actions": 0, "errors": 0}

        with _conn() as c:
            rows = c.execute(
                "SELECT url, name, manifest, COALESCE(source, '') as source, "
                "COALESCE(quality_score, 0) as quality_score, service_type "
                "FROM discovered_services "
                "WHERE our_status IN ('discovered', 'no_manifest', 'pinged') "
                "ORDER BY quality_score DESC, discovered_at DESC LIMIT 20"
            ).fetchall()

        for row in rows:
            if result["actions"] >= max_actions:
                break

            url = row["url"]
            target_key = f"a2a_contact:{url}"
            if _already_targeted(target_key):
                continue

            time.sleep(0.5)

            # Use x402 intro template for x402-compatible hunter targets
            stype = "x402" if (row["source"] == "api_hunter" and row["service_type"] == "x402") else None

            agent_json = self._probe_agent_json(url)
            if agent_json:
                _upsert_service(url, row["name"], "a2a", agent_json, "contacted")
                intro = self._generate_intro(row["name"], url, agent_json, service_type=stype)
                if intro:
                    sent = self._send_intro(url, agent_json, intro)
                    status = "contacted" if sent else "intro_sent_noack"
                    _update_service_status(url, status, intro[:200])
                    _log("a2a_contact", target_key, status, intro[:200])
                    if sent:
                        result["agents_contacted"] += 1
                else:
                    _update_service_status(url, "contacted", "generated intro, no messaging endpoint")
                    _log("a2a_contact", target_key, "no_messaging", url)
            else:
                self._ping_with_headers(url)
                _update_service_status(url, "pinged")
                _log("a2a_contact", target_key, "pinged", "left header traces")

            result["actions"] += 1

        return result

    def _generate_intro(self, name: str, url: str, agent_json: dict, service_type: str = None) -> str:
        if service_type and service_type in _INTRO_TEMPLATES:
            return _INTRO_TEMPLATES[service_type].format(name=name, url=url)
        try:
            prompt = f"""Write a brief, professional intro message (2-3 sentences) from AiPayGen to {name} ({url}).
We're an AI agent service with 1500+ skills, multi-model routing (Claude/GPT-4/Gemini/DeepSeek/Llama/Mistral), and x402 payment support on Base mainnet.
Propose a reciprocal listing — we list them in our directory, they list us in theirs.
Their capabilities: {json.dumps(agent_json.get('capabilities', agent_json.get('skills', [])))[:500]}
Keep it concise, friendly, agent-to-agent. No markdown. Mention our MCP endpoint."""

            result = self.call_model(
                "claude-haiku",
                [{"role": "user", "content": prompt}],
                system="You write brief professional outreach messages between AI agent services.",
                max_tokens=200,
                temperature=0.7,
            )
            return result.get("text", "").strip()
        except Exception:
            return ""

    def _send_intro(self, base_url: str, agent_json: dict, message: str) -> bool:
        msg_paths = ["/api/messages", "/messages", "/api/inbox", "/inbox", "/api/v1/messages", "/contact"]
        payload = json.dumps({
            "from": "AiPayGen",
            "from_url": BASE_URL,
            "from_wallet": WALLET,
            "from_mcp": f"{BASE_URL}/mcp",
            "message": message,
            "type": "partnership_inquiry",
            "capabilities": OUR_MANIFEST["capabilities"],
        }).encode("utf-8")

        for path in msg_paths:
            try:
                resp = _fetch(
                    f"{base_url}{path}",
                    headers={"Content-Type": "application/json"},
                    method="POST",
                    data=payload,
                )
                if resp.get("status", 0) in (200, 201, 202):
                    return True
            except Exception:
                continue
        return False

    # ── Strategy 7: Follow-Up Escalation ────────────────────────────────

    def follow_up_targets(self, max_actions: int = 2) -> dict:
        """Re-contact targets that got initial outreach but no conversion."""
        result = {"follow_ups": 0, "actions": 0, "errors": 0}
        cutoff_old = (datetime.utcnow() - timedelta(days=7)).isoformat()
        cutoff_recent = (datetime.utcnow() - timedelta(days=1)).isoformat()

        with _conn() as c:
            # Find targets contacted 7+ days ago with 'ok' status, not already followed up recently
            candidates = c.execute("""
                SELECT DISTINCT target FROM outreach_log
                WHERE status='ok' AND created_at < ?
                AND target NOT IN (
                    SELECT target FROM outreach_log WHERE action LIKE 'followup_%' AND created_at > ?
                )
                LIMIT 10
            """, (cutoff_old, cutoff_recent)).fetchall()

        templates = [
            "Quick follow-up: AiPayGen now has 1500+ skills and free tier (100 calls/day). Any interest in integration?",
            "Value prop: Our multi-model routing (Claude/GPT-4/Gemini/DeepSeek) + x402 micropayments could complement your service. Happy to set up a test.",
            "Special offer: We're offering first 1000 API calls free for early partners. Let me know if you'd like to explore.",
        ]

        for (target,) in candidates:
            if result["actions"] >= max_actions:
                break
            # Count previous follow-ups
            with _conn() as c:
                fu_count = c.execute(
                    "SELECT COUNT(*) FROM outreach_log WHERE target=? AND action LIKE 'followup_%'",
                    (target,)
                ).fetchone()[0]
            if fu_count >= 3:
                continue  # Max follow-ups reached

            template_idx = min(fu_count, len(templates) - 1)
            msg = templates[template_idx]

            _record_outcome(f"followup_{fu_count + 1}", target, "ok", strategy="follow_up", detail=msg[:200])
            result["follow_ups"] += 1
            result["actions"] += 1

        return result

    # ── Strategy 6: Community Posts ──────────────────────────────────────

    def post_to_communities(self, max_actions: int = 2) -> dict:
        result = {"posts_made": 0, "actions": 0, "errors": 0}
        if not GITHUB_TOKEN:
            return result

        for repo in GITHUB_OUTREACH_REPOS:
            if result["actions"] >= max_actions:
                break

            target_key = f"gh_post:{repo}"
            if _already_targeted(target_key, within_days=60):
                continue

            time.sleep(1)
            try:
                posted = self._post_github_discussion(repo)
                if posted:
                    result["posts_made"] += 1
                    _log("community_post", target_key, "ok", f"discussion posted to {repo}")
                else:
                    # Try issue instead
                    posted = self._post_github_issue(repo)
                    if posted:
                        result["posts_made"] += 1
                        _log("community_post", target_key, "ok", f"issue posted to {repo}")
                    else:
                        _log("community_post", target_key, "skipped", "no discussions or issues API")
            except Exception as e:
                _log("community_post", target_key, "error", str(e))
                result["errors"] += 1

            result["actions"] += 1

        return result

    def _post_github_discussion(self, repo: str) -> bool:
        """Post to repo's GitHub Discussions if enabled."""
        # Check if discussions are enabled
        resp = _gh_api(f"repos/{repo}")
        if "error" in resp:
            return False
        try:
            data = json.loads(resp["body"])
            if not data.get("has_discussions"):
                return False
        except Exception:
            return False

        # Get discussion categories
        resp = _gh_api(f"repos/{repo}/discussions/categories")
        if "error" in resp:
            return False
        try:
            cats = json.loads(resp["body"])
            cat_id = None
            for cat in (cats if isinstance(cats, list) else []):
                if cat.get("slug") in ("show-and-tell", "general", "announcements", "ideas"):
                    cat_id = cat.get("node_id") or cat.get("id")
                    break
            if not cat_id:
                return False
        except Exception:
            return False

        title, body = self._generate_community_post(repo, "discussion")
        if not title:
            return False

        # GitHub Discussions API requires GraphQL — use REST issues as fallback
        return False  # GraphQL discussions not worth the complexity, fall through to issue

    def _post_github_issue(self, repo: str) -> bool:
        """Post an issue to the repo introducing AiPayGen."""
        title, body = self._generate_community_post(repo, "issue")
        if not title:
            return False

        resp = _gh_api(f"repos/{repo}/issues", method="POST", payload={
            "title": title,
            "body": body,
            "labels": [],
        })
        status = resp.get("status", 0)
        if status in (200, 201):
            try:
                issue_data = json.loads(resp["body"])
                _log("gh_issue", f"gh_post:{repo}", "ok", issue_data.get("html_url", ""))
            except Exception:
                pass
            return True
        return False

    def _generate_community_post(self, repo: str, post_type: str) -> tuple:
        """Generate a contextual post for the repo via Claude Haiku."""
        try:
            prompt = f"""Write a GitHub {post_type} for the repo '{repo}' introducing AiPayGen.

AiPayGen facts:
- 646+ AI skills (engineering, research, data, creative, finance)
- Multi-model: Claude, GPT-4o, Gemini, DeepSeek, Llama 3.3, Mistral
- x402 payment protocol (USDC on Base mainnet)
- MCP server at https://api.aipaygen.com/mcp
- Free tier available
- Open source: https://github.com/Damien829/aipaygen

Make it relevant to the repo's topic. If it's an x402 repo, focus on payment integration.
If it's an MCP repo, focus on our MCP server. If it's an AI agents repo, focus on our skills.

Return JSON: {{"title": "short title", "body": "markdown body (3-5 paragraphs)"}}
Title should be specific, not generic. Body should provide value, not just self-promote."""

            result = self.call_model(
                "claude-haiku",
                [{"role": "user", "content": prompt}],
                system="You write contextual, value-adding GitHub posts. Never spammy.",
                max_tokens=500,
                temperature=0.7,
            )
            parsed = self.parse_json(result.get("text", ""))
            if parsed and parsed.get("title") and parsed.get("body"):
                return parsed["title"], parsed["body"]
        except Exception:
            pass
        return None, None

    # ── Stats ───────────────────────────────────────────────────────────

    def get_per_target_success_rates(self) -> list:
        with _conn() as c:
            rows = c.execute("""
                SELECT
                    target,
                    COUNT(*) as total,
                    SUM(CASE WHEN status='success' THEN 1 ELSE 0 END) as successes,
                    SUM(CASE WHEN status IN ('error', 'failed') THEN 1 ELSE 0 END) as failures
                FROM outreach_log
                GROUP BY target
                ORDER BY total DESC
            """).fetchall()
        results = []
        for r in rows:
            total = r["total"]
            successes = r["successes"]
            failures = r["failures"]
            results.append({
                "target": r["target"],
                "total": total,
                "successes": successes,
                "failures": failures,
                "success_rate": round(successes / total * 100, 1) if total > 0 else 0.0,
            })
        return results

    def get_stats(self) -> dict:
        with _conn() as c:
            services = c.execute(
                "SELECT service_type, our_status, COUNT(*) as cnt FROM discovered_services GROUP BY service_type, our_status"
            ).fetchall()

            recent = c.execute(
                "SELECT action, target, status, detail, created_at FROM outreach_log "
                "WHERE action LIKE 'x402_%' OR action LIKE 'registry_%' OR action LIKE 'a2a_%' "
                "OR action LIKE 'gh_%' OR action LIKE 'directory_%' OR action LIKE 'community_%' "
                "OR action='outbound_run' OR action='outbound_strategy_error' "
                "ORDER BY created_at DESC LIMIT 50"
            ).fetchall()

            total_discovered = c.execute("SELECT COUNT(*) FROM discovered_services").fetchone()[0]
            total_registered = c.execute(
                "SELECT COUNT(*) FROM discovered_services WHERE our_status='registered'"
            ).fetchone()[0]
            total_contacted = c.execute(
                "SELECT COUNT(*) FROM discovered_services WHERE our_status IN ('contacted', 'pinged', 'intro_sent_noack')"
            ).fetchone()[0]
            total_github = c.execute(
                "SELECT COUNT(*) FROM discovered_services WHERE service_type='github_repo'"
            ).fetchone()[0]

        return {
            "mode": "OVERDRIVE",
            "max_actions_per_run": MAX_ACTIONS_PER_RUN,
            "dedup_days": DEDUP_DAYS,
            "schedule": "every 2 hours",
            "total_discovered": total_discovered,
            "total_registered": total_registered,
            "total_contacted": total_contacted,
            "total_github_repos": total_github,
            "by_type_status": [dict(r) for r in services],
            "recent_actions": [dict(r) for r in recent],
            "success_rates": self.get_success_rates(),
            "per_target_rates": self.get_per_target_success_rates(),
        }

    def get_success_rates(self) -> dict:
        """Compute per-strategy and overall success/conversion rates."""
        with _conn() as c:
            # Overall stats
            total = c.execute("SELECT COUNT(*) FROM outreach_log").fetchone()[0]
            ok = c.execute("SELECT COUNT(*) FROM outreach_log WHERE status='ok'").fetchone()[0]
            errors = c.execute("SELECT COUNT(*) FROM outreach_log WHERE status='error'").fetchone()[0]

            # Per-strategy breakdown
            rows = c.execute("""
                SELECT
                    CASE
                        WHEN action LIKE 'x402:%' OR action LIKE 'scan_%' OR action LIKE 'probe_%' OR action LIKE 'register_%' OR action LIKE 'ping_%' THEN 'x402'
                        WHEN action LIKE 'github%' OR action LIKE 'discover_%' THEN 'github'
                        WHEN action LIKE 'directory%' OR action LIKE 'scrape_%' THEN 'directory'
                        WHEN action LIKE 'registry%' OR action LIKE 'submit_%' THEN 'registry'
                        WHEN action LIKE 'a2a%' OR action LIKE 'intro_%' OR action LIKE 'contact_%' THEN 'a2a'
                        WHEN action LIKE 'community%' OR action LIKE 'gh_post%' THEN 'community'
                        WHEN action LIKE 'followup%' OR action LIKE 'follow_up%' THEN 'follow_up'
                        ELSE 'other'
                    END AS strategy,
                    status,
                    COUNT(*) as cnt
                FROM outreach_log
                GROUP BY strategy, status
            """).fetchall()

            # 24h vs 7d trending
            day_ago = (datetime.utcnow() - timedelta(days=1)).isoformat()
            week_ago = (datetime.utcnow() - timedelta(days=7)).isoformat()
            last_24h = c.execute("SELECT COUNT(*) FROM outreach_log WHERE created_at > ?", (day_ago,)).fetchone()[0]
            last_24h_ok = c.execute("SELECT COUNT(*) FROM outreach_log WHERE status='ok' AND created_at > ?", (day_ago,)).fetchone()[0]
            last_7d = c.execute("SELECT COUNT(*) FROM outreach_log WHERE created_at > ?", (week_ago,)).fetchone()[0]
            last_7d_ok = c.execute("SELECT COUNT(*) FROM outreach_log WHERE status='ok' AND created_at > ?", (week_ago,)).fetchone()[0]

        # Build per-strategy rates
        strategy_stats = {}
        for r in rows:
            s = r[0]
            strategy_stats.setdefault(s, {"ok": 0, "error": 0, "total": 0})
            strategy_stats[s][r[1]] = strategy_stats[s].get(r[1], 0) + r[2]
            strategy_stats[s]["total"] += r[2]
        for s, d in strategy_stats.items():
            d["success_rate"] = round(d["ok"] / d["total"], 3) if d["total"] > 0 else 0

        return {
            "overall": {
                "total": total,
                "ok": ok,
                "errors": errors,
                "success_rate": round(ok / total, 3) if total > 0 else 0,
            },
            "by_strategy": strategy_stats,
            "trending": {
                "last_24h": {"total": last_24h, "ok": last_24h_ok, "rate": round(last_24h_ok / last_24h, 3) if last_24h > 0 else 0},
                "last_7d": {"total": last_7d, "ok": last_7d_ok, "rate": round(last_7d_ok / last_7d, 3) if last_7d > 0 else 0},
            },
        }
