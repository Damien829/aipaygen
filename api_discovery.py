"""6 autonomous discovery agents that find and catalog APIs."""
import os
import time
import requests
from api_catalog import upsert_api, log_run_start, log_run_end

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


class BaseDiscoveryAgent:
    name = "base"

    def __init__(self, claude_client):
        self.claude = claude_client
        self.found = 0

    def fetch(self, url: str, timeout: int = 15):
        try:
            time.sleep(0.75)
            resp = requests.get(url, timeout=timeout, headers={"User-Agent": "AiPayGent-Discovery/1.0"})
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
    MAX_APIS = 200

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


def run_all_agents(claude_client) -> dict:
    """Run all 6 agents sequentially, return per-agent results."""
    agents = [
        DomainAgent(claude_client),
        ApisGuruAgent(claude_client),
        GitHubAgent(claude_client),
        RedditAgent(claude_client),
        HackerNewsAgent(claude_client),
        ApifyStoreAgent(claude_client),
    ]
    results = {}
    for agent in agents:
        try:
            agent.run()
            results[agent.name] = {"found": agent.found, "status": "ok"}
        except Exception as e:
            results[agent.name] = {"found": agent.found, "status": "error", "error": str(e)}
    return results
