"""11 autonomous discovery agents that find and catalog APIs."""
import os
import re
import time
import sqlite3
import requests
from api_catalog import upsert_api, log_run_start, log_run_end, DB_PATH as CATALOG_DB

OUTBOUND_DB = os.path.join(os.path.dirname(__file__), "discovery_engine.db")

APIFY_TOKEN = os.getenv("APIFY_TOKEN")


def score_api_with_claude(claude_client, name, desc, base_url, auth_required, docs_url) -> float:
    """Ask Claude Haiku to score an API's utility (0-10)."""
    try:
        msg = claude_client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=100,
            system="You are an API quality evaluator. Reply with a single number 0-10 only.",
            messages=[{
                "role": "user",
                "content": (
                    f"Score this API's utility for AI agents (0=useless, 10=essential):\n"
                    f"Name: {name}\nDescription: {desc[:300]}\nURL: {base_url}\n"
                    f"Auth required: {auth_required}\nDocs: {docs_url}\n"
                    f"Reply with a number only."
                ),
            }],
        )
        return float(msg.content[0].text.strip().split()[0])
    except Exception:
        return 5.0


def score_api_heuristic(name, desc, base_url, auth_required, docs_url) -> float:
    """Fast heuristic scoring without LLM call. 0-10."""
    score = 5.0
    desc_lower = (desc or "").lower()
    if docs_url and docs_url != base_url:
        score += 1.0
    if not auth_required:
        score += 1.0
    if any(k in desc_lower for k in ["free", "open", "public", "no auth"]):
        score += 0.5
    if any(k in desc_lower for k in ["rest", "json", "graphql", "openapi", "swagger"]):
        score += 0.5
    if len(desc or "") > 50:
        score += 0.5
    if "api" in (base_url or "").lower():
        score += 0.5
    return min(10.0, score)


# Regex for parsing awesome-list markdown entries: [Name](url) - Description
_AWESOME_RE = re.compile(
    r'[-*|]\s*\[([^\]]{2,80})\]\(([^)]+)\)\s*[-:|]?\s*(.{10,300}?)(?:\n|$|\|)'
)


class BaseDiscoveryAgent:
    name = "base"

    def __init__(self, claude_client):
        self.claude = claude_client
        self.found = 0

    def fetch(self, url: str, timeout: int = 15):
        try:
            time.sleep(3)  # throttled to avoid abuse flags
            resp = requests.get(url, timeout=timeout, headers={"User-Agent": "AiPayGen-Discovery/1.0"})
            resp.raise_for_status()
            return resp
        except Exception:
            return None

    def save(self, **kwargs):
        score = score_api_with_claude(
            self.claude,
            kwargs.get("name", ""),
            kwargs.get("description", ""),
            kwargs.get("base_url", ""),
            kwargs.get("auth_required", False),
            kwargs.get("docs_url", ""),
        )
        kwargs["quality_score"] = score
        kwargs["source"] = self.name
        upsert_api(**kwargs)
        self.found += 1

    def run(self):
        raise NotImplementedError


class ApisGuruAgent(BaseDiscoveryAgent):
    name = "apis_guru"
    MAX_APIS = 2500

    def run(self):
        run_id = log_run_start(self.name)
        try:
            resp = self.fetch("https://api.apis.guru/v2/list.json")
            if not resp:
                log_run_end(run_id, 0, "error", "Failed to fetch apis.guru")
                return
            data = resp.json()
            count = 0
            for api_id, api_info in data.items():
                if count >= self.MAX_APIS:
                    break
                try:
                    preferred = api_info.get("preferred", "")
                    versions = api_info.get("versions", {})
                    v = versions.get(preferred) or next(iter(versions.values()), {})
                    info = v.get("info", {})
                    name = info.get("title", api_id)
                    desc = info.get("description", "")
                    base_url = v.get("swaggerUrl", "").replace("/swagger.json", "")
                    docs_url = info.get("x-origin", [{}])[0].get("url", "") if info.get("x-origin") else ""
                    auth_required = bool(v.get("security"))
                    if not base_url:
                        continue
                    self.save(
                        name=name[:255],
                        description=desc[:500],
                        base_url=base_url,
                        docs_url=docs_url,
                        auth_required=auth_required,
                        category="api",
                    )
                    count += 1
                except Exception:
                    continue
            log_run_end(run_id, self.found, "completed")
        except Exception as e:
            log_run_end(run_id, self.found, "error", str(e))


class DomainAgent(BaseDiscoveryAgent):
    name = "domain"

    SEEDS = [
        {"name": "Open Meteo", "description": "Free weather forecast API, no auth needed", "base_url": "https://api.open-meteo.com", "docs_url": "https://open-meteo.com/en/docs", "auth_required": False, "category": "weather"},
        {"name": "REST Countries", "description": "Country data: names, capitals, currencies, flags", "base_url": "https://restcountries.com", "docs_url": "https://restcountries.com", "auth_required": False, "category": "geo"},
        {"name": "CoinGecko", "description": "Cryptocurrency prices, market data, trends", "base_url": "https://api.coingecko.com/api/v3", "docs_url": "https://www.coingecko.com/en/api/documentation", "auth_required": False, "category": "finance"},
        {"name": "JSONPlaceholder", "description": "Free fake REST API for testing and prototyping", "base_url": "https://jsonplaceholder.typicode.com", "docs_url": "https://jsonplaceholder.typicode.com", "auth_required": False, "category": "testing"},
        {"name": "Public APIs List", "description": "Aggregator of hundreds of free public APIs", "base_url": "https://api.publicapis.org", "docs_url": "https://api.publicapis.org", "auth_required": False, "category": "meta"},
        {"name": "OpenFDA", "description": "FDA drug, food, device adverse event data", "base_url": "https://api.fda.gov", "docs_url": "https://open.fda.gov/apis/", "auth_required": False, "category": "health"},
        {"name": "NASA APIs", "description": "Space imagery, asteroid data, earth imagery", "base_url": "https://api.nasa.gov", "docs_url": "https://api.nasa.gov", "auth_required": True, "auth_type": "api_key", "category": "science"},
        {"name": "The Movie Database", "description": "Movies, TV shows, people, images", "base_url": "https://api.themoviedb.org/3", "docs_url": "https://developer.themoviedb.org/docs", "auth_required": True, "auth_type": "api_key", "category": "entertainment"},
        {"name": "GitHub REST API", "description": "Repos, issues, PRs, users, gists", "base_url": "https://api.github.com", "docs_url": "https://docs.github.com/en/rest", "auth_required": False, "category": "developer"},
        {"name": "Hacker News API", "description": "Stories, jobs, comments from HN (read-only, free)", "base_url": "https://hacker-news.firebaseio.com/v0", "docs_url": "https://github.com/HackerNews/API", "auth_required": False, "category": "news"},
        {"name": "NewsAPI", "description": "News articles from 80k+ sources worldwide", "base_url": "https://newsapi.org/v2", "docs_url": "https://newsapi.org/docs", "auth_required": True, "auth_type": "api_key", "category": "news"},
        {"name": "IPGeolocation", "description": "IP to country, city, timezone, ISP lookup", "base_url": "https://api.ipgeolocation.io", "docs_url": "https://ipgeolocation.io/documentation.html", "auth_required": True, "auth_type": "api_key", "category": "geo"},
        {"name": "Unsplash API", "description": "High-res free photos for apps and websites", "base_url": "https://api.unsplash.com", "docs_url": "https://unsplash.com/documentation", "auth_required": True, "auth_type": "oauth", "category": "media"},
        {"name": "ExchangeRate API", "description": "Real-time and historical currency exchange rates", "base_url": "https://api.exchangerate-api.com/v4", "docs_url": "https://www.exchangerate-api.com/docs/overview", "auth_required": False, "category": "finance"},
        {"name": "Nominatim (OSM)", "description": "Geocoding and reverse geocoding via OpenStreetMap", "base_url": "https://nominatim.openstreetmap.org", "docs_url": "https://nominatim.org/release-docs/develop/api/Overview/", "auth_required": False, "category": "geo"},
    ]

    def run(self):
        run_id = log_run_start(self.name)
        try:
            for api in self.SEEDS:
                self.save(**api)
            log_run_end(run_id, self.found, "completed")
        except Exception as e:
            log_run_end(run_id, self.found, "error", str(e))


class GitHubAgent(BaseDiscoveryAgent):
    name = "github"
    MAX_REPOS = 3

    def run(self):
        run_id = log_run_start(self.name)
        try:
            resp = self.fetch(
                "https://api.github.com/search/repositories"
                "?q=awesome+api+list&sort=stars&order=desc&per_page=10"
            )
            if not resp:
                log_run_end(run_id, 0, "error", "GitHub fetch failed")
                return
            items = resp.json().get("items", [])[:self.MAX_REPOS]
            for repo in items:
                self.save(
                    name=repo["full_name"],
                    description=repo.get("description", "")[:500],
                    base_url=repo["html_url"],
                    docs_url=repo["html_url"],
                    auth_required=False,
                    category="meta",
                )
            log_run_end(run_id, self.found, "completed")
        except Exception as e:
            log_run_end(run_id, self.found, "error", str(e))


class RedditAgent(BaseDiscoveryAgent):
    name = "reddit"

    SUBREDDITS = ["api", "webdev", "programming"]

    def run(self):
        run_id = log_run_start(self.name)
        try:
            for sub in self.SUBREDDITS:
                resp = self.fetch(f"https://www.reddit.com/r/{sub}/top.json?t=month&limit=5")
                if not resp:
                    continue
                posts = resp.json().get("data", {}).get("children", [])
                for post in posts:
                    d = post.get("data", {})
                    url = d.get("url", "")
                    title = d.get("title", "")
                    if not url or "reddit.com" in url:
                        continue
                    if not any(kw in title.lower() for kw in ["api", "library", "sdk", "client"]):
                        continue
                    try:
                        base = "/".join(url.split("/")[:3])
                        self.save(
                            name=title[:255],
                            description=d.get("selftext", "")[:300] or f"From r/{sub}: {title}",
                            base_url=base,
                            docs_url=url,
                            auth_required=False,
                            category="community",
                        )
                    except Exception:
                        continue
            log_run_end(run_id, self.found, "completed")
        except Exception as e:
            log_run_end(run_id, self.found, "error", str(e))


class HackerNewsAgent(BaseDiscoveryAgent):
    name = "hackernews"

    def run(self):
        run_id = log_run_start(self.name)
        try:
            resp = self.fetch(
                "https://hn.algolia.com/api/v1/search"
                "?query=Show+HN+API&tags=show_hn&hitsPerPage=20"
            )
            if not resp:
                log_run_end(run_id, 0, "error", "HN fetch failed")
                return
            hits = resp.json().get("hits", [])
            for hit in hits:
                url = hit.get("url", "")
                title = hit.get("title", "")
                if not url:
                    continue
                try:
                    base = "/".join(url.split("/")[:3])
                    self.save(
                        name=title[:255],
                        description=hit.get("story_text", "")[:300] or f"HN: {title}",
                        base_url=base,
                        docs_url=url,
                        auth_required=False,
                        category="startup",
                    )
                except Exception:
                    continue
            log_run_end(run_id, self.found, "completed")
        except Exception as e:
            log_run_end(run_id, self.found, "error", str(e))


class ApifyStoreAgent(BaseDiscoveryAgent):
    name = "apify_store"

    def run(self):
        run_id = log_run_start(self.name)
        try:
            url = f"https://api.apify.com/v2/store?token={APIFY_TOKEN}&limit=100"
            resp = self.fetch(url)
            if not resp:
                log_run_end(run_id, 0, "error", "Apify store fetch failed")
                return
            items = resp.json().get("data", {}).get("items", [])
            for actor in items:
                actor_id = actor.get("id") or actor.get("username", "") + "/" + actor.get("name", "")
                title = actor.get("title") or actor.get("name", "")
                desc = actor.get("description", "")
                # Derive category from title/description keywords
                text = (title + " " + desc).lower()
                if any(k in text for k in ["map", "place", "location", "google"]):
                    cat = "geo"
                elif any(k in text for k in ["instagram", "twitter", "linkedin", "tiktok", "facebook", "social"]):
                    cat = "social_media"
                elif any(k in text for k in ["ecommerce", "shop", "amazon", "product"]):
                    cat = "ecommerce"
                elif any(k in text for k in ["news", "article", "blog"]):
                    cat = "news"
                else:
                    cat = "scraping"
                self.save(
                    name=title[:255],
                    description=desc[:500],
                    base_url=f"https://api.apify.com/v2/acts/{actor_id}",
                    docs_url=f"https://apify.com/store/{actor_id}",
                    auth_required=True,
                    auth_type="api_key",
                    category=cat,
                    sample_endpoint=f"https://api.apify.com/v2/acts/{actor_id}/run-sync-get-dataset-items",
                )
            log_run_end(run_id, self.found, "completed")
        except Exception as e:
            log_run_end(run_id, self.found, "error", str(e))


class PublicApisAgent(BaseDiscoveryAgent):
    """Parses the public-apis/public-apis GitHub repo — 1400+ APIs."""
    name = "public_apis"

    REPOS = [
        "https://raw.githubusercontent.com/public-apis/public-apis/master/README.md",
        "https://raw.githubusercontent.com/n0shake/Public-APIs/master/README.md",
    ]

    def run(self):
        run_id = log_run_start(self.name)
        try:
            for repo_url in self.REPOS:
                resp = self.fetch(repo_url, timeout=30)
                if not resp:
                    continue
                entries = _AWESOME_RE.findall(resp.text)
                for name, url, desc in entries:
                    if any(x in url for x in ["img.shields", "#", "badge", "github.com/topics"]):
                        continue
                    base = "/".join(url.split("/")[:3])
                    if len(base) < 10:
                        continue
                    score = score_api_heuristic(name, desc, base, False, url)
                    self.save(
                        name=name.strip()[:255],
                        description=desc.strip()[:500],
                        base_url=base,
                        docs_url=url,
                        auth_required=False,
                        category="api",
                        quality_score=score,
                    )
            log_run_end(run_id, self.found, "completed")
        except Exception as e:
            log_run_end(run_id, self.found, "error", str(e))


class AwesomeApiAgent(BaseDiscoveryAgent):
    """Parses awesome-api lists from GitHub."""
    name = "awesome_api"

    LISTS = [
        "https://raw.githubusercontent.com/TonnyL/Awesome_APIs/master/README.md",
        "https://raw.githubusercontent.com/Kikobeats/awesome-api/master/README.md",
        "https://raw.githubusercontent.com/yosriady/api-development-tools/master/README.md",
    ]

    def run(self):
        run_id = log_run_start(self.name)
        try:
            for list_url in self.LISTS:
                resp = self.fetch(list_url, timeout=30)
                if not resp:
                    continue
                entries = _AWESOME_RE.findall(resp.text)
                for name, url, desc in entries:
                    if any(x in url for x in ["img.shields", "#", "badge"]):
                        continue
                    base = "/".join(url.split("/")[:3])
                    if len(base) < 10:
                        continue
                    score = score_api_heuristic(name, desc, base, False, url)
                    self.save(
                        name=name.strip()[:255],
                        description=desc.strip()[:500],
                        base_url=base,
                        docs_url=url,
                        auth_required=False,
                        category="api",
                        quality_score=score,
                    )
            log_run_end(run_id, self.found, "completed")
        except Exception as e:
            log_run_end(run_id, self.found, "error", str(e))


class AwesomeMCPAgent(BaseDiscoveryAgent):
    """Discovers MCP servers from awesome-mcp-servers lists."""
    name = "awesome_mcp"

    LISTS = [
        "https://raw.githubusercontent.com/punkpeye/awesome-mcp-servers/main/README.md",
        "https://raw.githubusercontent.com/appcypher/awesome-mcp-servers/main/README.md",
    ]

    def run(self):
        run_id = log_run_start(self.name)
        try:
            for list_url in self.LISTS:
                resp = self.fetch(list_url, timeout=30)
                if not resp:
                    continue
                entries = _AWESOME_RE.findall(resp.text)
                for name, url, desc in entries:
                    if any(x in url for x in ["img.shields", "#", "badge"]):
                        continue
                    base = "/".join(url.split("/")[:3])
                    if len(base) < 10:
                        continue
                    self.save(
                        name=name.strip()[:255],
                        description=desc.strip()[:500],
                        base_url=base,
                        docs_url=url,
                        auth_required=False,
                        category="mcp",
                    )
            log_run_end(run_id, self.found, "completed")
        except Exception as e:
            log_run_end(run_id, self.found, "error", str(e))


class X402RegistryAgent(BaseDiscoveryAgent):
    name = "x402_registry"

    KNOWN_X402 = [
        {"name": "BlockRun", "base_url": "https://blockrun.io", "docs_url": "https://blockrun.io/docs", "description": "600+ AI API services with x402 payment support"},
        {"name": "BlockRun API", "base_url": "https://api.blockrun.io", "docs_url": "https://blockrun.io/docs", "description": "BlockRun API endpoint for x402-gated services"},
        {"name": "Pylon", "base_url": "https://pylon.bot", "docs_url": "https://pylon.bot/docs", "description": "x402 payment proxy and API gateway"},
        {"name": "PayWithx402", "base_url": "https://paywithx402.com", "docs_url": "https://paywithx402.com", "description": "x402 payment facilitator service"},
        {"name": "402.ai", "base_url": "https://402.ai", "docs_url": "https://402.ai", "description": "AI services monetized via x402 protocol"},
        {"name": "x402.org", "base_url": "https://x402.org", "docs_url": "https://x402.org", "description": "x402 protocol registry and specification"},
        {"name": "x402.xyz", "base_url": "https://x402.xyz", "docs_url": "https://x402.xyz", "description": "x402 ecosystem directory"},
    ]

    def run(self):
        run_id = log_run_start(self.name)
        try:
            # 1. Catalog known x402 services
            for svc in self.KNOWN_X402:
                self.save(
                    x402_compatible=True,
                    category="x402",
                    auth_required=False,
                    **svc,
                )

            # 2. Try x402.org registry API
            for registry_url in [
                "https://x402.org/api/services",
                "https://api.x402.org/services",
                "https://x402.org/registry",
            ]:
                resp = self.fetch(registry_url)
                if not resp:
                    continue
                try:
                    data = resp.json()
                    items = data if isinstance(data, list) else data.get("services", data.get("items", []))
                    for item in (items or [])[:30]:
                        if isinstance(item, dict) and item.get("url"):
                            self.save(
                                name=item.get("name", item["url"])[:255],
                                description=item.get("description", "x402-compatible service")[:500],
                                base_url=item["url"].rstrip("/"),
                                docs_url=item.get("docs_url", item["url"]),
                                auth_required=False,
                                category="x402",
                                x402_compatible=True,
                            )
                except Exception:
                    continue

            # 3. Search GitHub for x402-related repos
            resp = self.fetch(
                "https://api.github.com/search/repositories"
                "?q=x402+in:name,description,topics&sort=updated&per_page=15"
            )
            if resp:
                try:
                    for repo in resp.json().get("items", [])[:10]:
                        url = repo.get("homepage") or repo["html_url"]
                        self.save(
                            name=repo["full_name"][:255],
                            description=repo.get("description", "")[:500],
                            base_url=url.rstrip("/"),
                            docs_url=repo["html_url"],
                            auth_required=False,
                            category="x402",
                            x402_compatible=True,
                        )
                except Exception:
                    pass

            log_run_end(run_id, self.found, "completed")
        except Exception as e:
            log_run_end(run_id, self.found, "error", str(e))


def run_all_hunters(claude_client, max_per_run=50) -> int:
    """Run all 11 discovery agents with a cap, apply scoring boosts, return new API count."""
    agents = [
        X402RegistryAgent(claude_client),
        PublicApisAgent(claude_client),
        AwesomeApiAgent(claude_client),
        AwesomeMCPAgent(claude_client),
        ApisGuruAgent(claude_client),
        DomainAgent(claude_client),
        GitHubAgent(claude_client),
        RedditAgent(claude_client),
        HackerNewsAgent(claude_client),
        ApifyStoreAgent(claude_client),
    ]
    total_found = 0
    for agent in agents:
        if total_found >= max_per_run:
            break
        try:
            agent.run()
            total_found += agent.found
        except Exception:
            continue

    # Apply scoring boosts for x402 and AI/ML APIs
    try:
        conn = sqlite3.connect(CATALOG_DB)
        conn.row_factory = sqlite3.Row
        # x402 boost: +3
        conn.execute(
            "UPDATE discovered_apis SET quality_score = MIN(10, quality_score + 3) "
            "WHERE category = 'x402' AND quality_score <= 7"
        )
        # AI/ML boost: +2
        conn.execute(
            "UPDATE discovered_apis SET quality_score = MIN(10, quality_score + 2) "
            "WHERE category IN ('ai', 'ml', 'inference', 'embeddings') AND quality_score <= 8"
        )
        conn.commit()
        conn.close()
    except Exception:
        pass

    return total_found


def inject_high_scorers(min_score=7) -> int:
    """Inject high-scoring catalog APIs into outbound discovered_services table."""
    injected = 0
    try:
        cat_conn = sqlite3.connect(CATALOG_DB)
        cat_conn.row_factory = sqlite3.Row
        rows = cat_conn.execute(
            "SELECT name, base_url, category, quality_score FROM discovered_apis "
            "WHERE quality_score >= ? AND is_active = 1",
            (min_score,),
        ).fetchall()
        cat_conn.close()

        if not rows:
            return 0

        out_conn = sqlite3.connect(OUTBOUND_DB)
        for r in rows:
            stype = "x402" if r["category"] == "x402" else "api"
            try:
                out_conn.execute(
                    "INSERT INTO discovered_services "
                    "(url, name, service_type, our_status, discovered_at, source, quality_score) "
                    "VALUES (?, ?, ?, 'discovered', datetime('now'), 'api_hunter', ?) "
                    "ON CONFLICT(url) DO NOTHING",
                    (r["base_url"], r["name"], stype, r["quality_score"]),
                )
                injected += 1
            except Exception:
                continue
        out_conn.commit()
        out_conn.close()
    except Exception:
        pass
    return injected



# run_all_agents() removed — superseded by run_all_hunters() which runs 10 agents
# with scoring boosts and max_per_run cap.
