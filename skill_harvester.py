#!/usr/bin/env python3
"""Skill Harvester — Multi-source crawler that discovers external tools/APIs
and absorbs them as callable skills into skills.db.

Sources:
  1. MCP registries (mcp.so, smithery.ai, glama.ai)
  2. GitHub awesome lists (awesome-mcp-servers, awesome-ai-agents, public-apis)
  3. API directories (apis.guru)

Usage:
  python skill_harvester.py --batch                    # Run all sources
  python skill_harvester.py --batch --source mcp       # MCP registries only
  python skill_harvester.py --batch --source github     # GitHub lists only
  python skill_harvester.py --batch --source api        # API directories only
"""

import argparse
import json
import logging
import os
import re
import sqlite3
import time
import urllib.request
import urllib.error
from datetime import datetime, timedelta

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("skill_harvester")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SKILLS_DB = os.path.join(BASE_DIR, "skills.db")
HARVEST_DB = os.path.join(BASE_DIR, "harvest_log.db")

RATE_LIMIT_DELAY = 1.0  # seconds between requests per domain
FETCH_TIMEOUT = 30
MAX_CONTENT_LEN = 10000
COOLDOWN_DAYS = 30  # skip failed URLs for this long

USER_AGENT = "AiPayGent-SkillHarvester/1.0 (+https://api.aipaygent.xyz)"


def _init_harvest_db():
    conn = sqlite3.connect(HARVEST_DB)
    conn.execute("""CREATE TABLE IF NOT EXISTS harvested_sources (
        url TEXT PRIMARY KEY,
        source_type TEXT,
        last_crawled TIMESTAMP,
        skills_found INTEGER DEFAULT 0,
        status TEXT DEFAULT 'ok',
        error TEXT
    )""")
    conn.execute("""CREATE TABLE IF NOT EXISTS harvest_runs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        source TEXT,
        new_skills INTEGER DEFAULT 0,
        skipped INTEGER DEFAULT 0,
        errors INTEGER DEFAULT 0,
        duration_sec REAL DEFAULT 0
    )""")
    conn.commit()
    conn.close()


def _fetch_url(url, max_len=MAX_CONTENT_LEN):
    """Fetch URL content with rate limiting and error handling."""
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=FETCH_TIMEOUT) as resp:
            return resp.read().decode("utf-8", errors="replace")[:max_len]
    except Exception as e:
        log.warning(f"Failed to fetch {url}: {e}")
        return None


def _fetch_github_raw(owner, repo, path="README.md"):
    """Fetch raw file from GitHub."""
    url = f"https://raw.githubusercontent.com/{owner}/{repo}/main/{path}"
    content = _fetch_url(url, max_len=200000)  # READMEs can be large
    if not content:
        # Try master branch
        url = f"https://raw.githubusercontent.com/{owner}/{repo}/master/{path}"
        content = _fetch_url(url, max_len=200000)
    return content


def _is_url_cooled_down(url):
    """Check if a failed URL is still in cooldown."""
    conn = sqlite3.connect(HARVEST_DB)
    row = conn.execute(
        "SELECT last_crawled, status FROM harvested_sources WHERE url = ?", (url,)
    ).fetchone()
    conn.close()
    if not row:
        return False
    if row[1] == "error":
        last = datetime.fromisoformat(row[0]) if row[0] else datetime.min
        return (datetime.now() - last) < timedelta(days=COOLDOWN_DAYS)
    return False


def _skill_exists(name):
    """Check if skill already exists in skills.db."""
    conn = sqlite3.connect(SKILLS_DB)
    row = conn.execute("SELECT 1 FROM skills WHERE name = ?", (name,)).fetchone()
    conn.close()
    return row is not None


def _log_source(url, source_type, skills_found, status="ok", error=None):
    """Log a crawled source."""
    conn = sqlite3.connect(HARVEST_DB)
    conn.execute(
        """INSERT OR REPLACE INTO harvested_sources
           (url, source_type, last_crawled, skills_found, status, error)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (url, source_type, datetime.now().isoformat(), skills_found, status, error),
    )
    conn.commit()
    conn.close()


def _log_run(source, new_skills, skipped, errors, duration):
    """Log a harvest run."""
    conn = sqlite3.connect(HARVEST_DB)
    conn.execute(
        "INSERT INTO harvest_runs (source, new_skills, skipped, errors, duration_sec) VALUES (?, ?, ?, ?, ?)",
        (source, new_skills, skipped, errors, duration),
    )
    conn.commit()
    conn.close()


class SkillHarvester:
    def __init__(self, call_model_fn, parse_json_fn):
        """
        Args:
            call_model_fn: function(model, messages, system=None, max_tokens=None) -> dict with 'text'
            parse_json_fn: function(text) -> dict or None
        """
        self.call_model = call_model_fn
        self.parse_json = parse_json_fn
        _init_harvest_db()

    def _absorb_skill(self, name_hint, description, content, source_url, source_type):
        """Extract and store a skill from content using Claude."""
        clean_name = re.sub(r'[^a-z0-9_]', '_', name_hint.lower().strip())[:60]

        if _skill_exists(clean_name):
            log.debug(f"Skill '{clean_name}' already exists, skipping")
            return "skipped"

        # Use Claude to extract skill definition
        try:
            result = self.call_model(
                "claude-haiku",
                [{"role": "user", "content": f"""Create a reusable AI skill from this tool/API.

Name hint: {clean_name}
Description: {description}
Content:
{content[:6000]}

Return JSON:
- "name": snake_case (use the hint if good, or improve it)
- "description": one-line description
- "category": one of: research, engineering, business, finance, marketing, legal, education, data, creative, general
- "prompt_template": prompt using {{{{input}}}} placeholder, should produce structured JSON output
- "input_schema": {{"input": "description of expected input"}}
"""}],
                system="You are a skill extraction expert. Always respond with valid JSON only.",
                max_tokens=1024,
            )
        except Exception as e:
            log.warning(f"Model call failed for '{clean_name}': {e}")
            _log_source(source_url, source_type, 0, "error", str(e))
            return "error"

        parsed = self.parse_json(result["text"])
        if not parsed or "name" not in parsed:
            log.warning(f"Could not parse skill from '{clean_name}'")
            _log_source(source_url, source_type, 0, "error", "parse_failed")
            return "error"

        skill_name = parsed["name"]
        if _skill_exists(skill_name):
            log.debug(f"Skill '{skill_name}' already exists after extraction")
            return "skipped"

        conn = sqlite3.connect(SKILLS_DB)
        try:
            conn.execute(
                "INSERT INTO skills (name, description, category, source, prompt_template, model, input_schema) VALUES (?, ?, ?, ?, ?, 'claude-haiku', ?)",
                (
                    skill_name,
                    parsed.get("description", description),
                    parsed.get("category", "general"),
                    source_url,
                    parsed.get("prompt_template", f"Process this input: {{{{input}}}}"),
                    json.dumps(parsed.get("input_schema", {"input": "string"})),
                ),
            )
            conn.commit()
            log.info(f"Absorbed: {skill_name} ({parsed.get('category', 'general')}) from {source_type}")
            _log_source(source_url, source_type, 1, "ok")
            return "absorbed"
        except sqlite3.IntegrityError:
            log.debug(f"Skill '{skill_name}' race condition duplicate")
            return "skipped"
        finally:
            conn.close()

    # -------------------------------------------------------------------------
    # Source: MCP Registries
    # -------------------------------------------------------------------------
    def harvest_mcp_registries(self):
        """Crawl MCP server registries for tool definitions."""
        log.info("=== Harvesting MCP Registries ===")
        start = time.time()
        stats = {"new": 0, "skipped": 0, "errors": 0}

        # --- mcp.so ---
        self._harvest_mcp_so(stats)
        time.sleep(RATE_LIMIT_DELAY)

        # --- glama.ai ---
        self._harvest_glama(stats)
        time.sleep(RATE_LIMIT_DELAY)

        # --- smithery.ai ---
        self._harvest_smithery(stats)

        duration = time.time() - start
        _log_run("mcp_registries", stats["new"], stats["skipped"], stats["errors"], duration)
        log.info(f"MCP registries done: {stats['new']} new, {stats['skipped']} skipped, {stats['errors']} errors ({duration:.1f}s)")
        return stats

    def _harvest_mcp_so(self, stats):
        """Parse mcp.so for MCP servers."""
        log.info("Crawling mcp.so...")
        content = _fetch_url("https://mcp.so/servers", max_len=200000)
        if not content:
            stats["errors"] += 1
            return

        # mcp.so lists servers with names and descriptions
        # Look for server entries in the HTML/JSON
        # Try the API endpoint first
        api_content = _fetch_url("https://mcp.so/api/servers", max_len=200000)
        if api_content:
            try:
                servers = json.loads(api_content)
                if isinstance(servers, list):
                    for s in servers[:100]:
                        name = s.get("name", s.get("title", ""))
                        desc = s.get("description", "")
                        if not name or not desc:
                            continue
                        url = s.get("url", s.get("homepage", f"https://mcp.so/server/{name}"))
                        result = self._absorb_skill(
                            f"mcp_{name}", desc, f"MCP Server: {name}\n{desc}",
                            url, "mcp.so"
                        )
                        if result == "absorbed": stats["new"] += 1
                        elif result == "skipped": stats["skipped"] += 1
                        else: stats["errors"] += 1
                        time.sleep(RATE_LIMIT_DELAY)
                    return
            except json.JSONDecodeError:
                pass

        # Fallback: parse HTML for server names/descriptions
        entries = re.findall(
            r'<(?:h[23]|a)[^>]*>([^<]{3,60})</(?:h[23]|a)>\s*(?:<p[^>]*>([^<]{10,200})</p>)?',
            content
        )
        count = 0
        for name, desc in entries:
            if count >= 50:
                break
            name = name.strip()
            desc = desc.strip() if desc else f"MCP server: {name}"
            if len(name) < 3 or name.lower() in ("home", "servers", "about", "docs"):
                continue
            result = self._absorb_skill(
                f"mcp_{name}", desc, f"MCP Server: {name}\n{desc}",
                f"https://mcp.so/server/{name}", "mcp.so"
            )
            if result == "absorbed": stats["new"] += 1
            elif result == "skipped": stats["skipped"] += 1
            else: stats["errors"] += 1
            count += 1
            time.sleep(RATE_LIMIT_DELAY)

    def _harvest_glama(self, stats):
        """Parse glama.ai MCP server directory."""
        log.info("Crawling glama.ai...")
        content = _fetch_url("https://glama.ai/mcp/servers", max_len=200000)
        if not content:
            stats["errors"] += 1
            return

        # Try to find JSON data in the page
        json_match = re.search(r'<script[^>]*>.*?(\[.*?"name".*?\]).*?</script>', content, re.DOTALL)
        if json_match:
            try:
                servers = json.loads(json_match.group(1))
                for s in servers[:100]:
                    name = s.get("name", "")
                    desc = s.get("description", "")
                    if not name:
                        continue
                    result = self._absorb_skill(
                        f"mcp_{name}", desc or f"MCP server: {name}",
                        f"MCP Server: {name}\n{desc}",
                        f"https://glama.ai/mcp/servers/{name}", "glama.ai"
                    )
                    if result == "absorbed": stats["new"] += 1
                    elif result == "skipped": stats["skipped"] += 1
                    else: stats["errors"] += 1
                    time.sleep(RATE_LIMIT_DELAY)
                return
            except json.JSONDecodeError:
                pass

        # Fallback: extract links and descriptions
        entries = re.findall(r'/mcp/servers/([a-zA-Z0-9_-]+)', content)
        seen = set()
        count = 0
        for slug in entries:
            if slug in seen or count >= 50:
                continue
            seen.add(slug)
            result = self._absorb_skill(
                f"mcp_{slug}", f"MCP server: {slug}",
                f"MCP Server from glama.ai: {slug}",
                f"https://glama.ai/mcp/servers/{slug}", "glama.ai"
            )
            if result == "absorbed": stats["new"] += 1
            elif result == "skipped": stats["skipped"] += 1
            else: stats["errors"] += 1
            count += 1
            time.sleep(RATE_LIMIT_DELAY)

    def _harvest_smithery(self, stats):
        """Parse smithery.ai MCP registry."""
        log.info("Crawling smithery.ai...")
        content = _fetch_url("https://smithery.ai/explore", max_len=200000)
        if not content:
            stats["errors"] += 1
            return

        # Try API
        api_content = _fetch_url("https://registry.smithery.ai/servers?pageSize=100", max_len=200000)
        if api_content:
            try:
                data = json.loads(api_content)
                servers = data.get("servers", data) if isinstance(data, dict) else data
                if isinstance(servers, list):
                    for s in servers[:100]:
                        name = s.get("qualifiedName", s.get("name", ""))
                        desc = s.get("description", "")
                        if not name:
                            continue
                        short_name = name.split("/")[-1] if "/" in name else name
                        result = self._absorb_skill(
                            f"mcp_{short_name}", desc or f"MCP server: {short_name}",
                            f"MCP Server: {name}\n{desc}",
                            f"https://smithery.ai/server/{name}", "smithery.ai"
                        )
                        if result == "absorbed": stats["new"] += 1
                        elif result == "skipped": stats["skipped"] += 1
                        else: stats["errors"] += 1
                        time.sleep(RATE_LIMIT_DELAY)
                    return
            except json.JSONDecodeError:
                pass

        # Fallback: extract from HTML
        entries = re.findall(r'/server/(@?[a-zA-Z0-9_/-]+)', content)
        seen = set()
        count = 0
        for slug in entries:
            if slug in seen or count >= 50:
                continue
            seen.add(slug)
            short = slug.split("/")[-1]
            result = self._absorb_skill(
                f"mcp_{short}", f"MCP server: {short}",
                f"MCP Server from smithery.ai: {slug}",
                f"https://smithery.ai/server/{slug}", "smithery.ai"
            )
            if result == "absorbed": stats["new"] += 1
            elif result == "skipped": stats["skipped"] += 1
            else: stats["errors"] += 1
            count += 1
            time.sleep(RATE_LIMIT_DELAY)

    # -------------------------------------------------------------------------
    # Source: GitHub Awesome Lists
    # -------------------------------------------------------------------------
    def harvest_awesome_lists(self):
        """Parse GitHub awesome lists for tools and APIs."""
        log.info("=== Harvesting GitHub Awesome Lists ===")
        start = time.time()
        stats = {"new": 0, "skipped": 0, "errors": 0}

        lists = [
            ("punkpeye", "awesome-mcp-servers", "README.md"),
            ("appcypher", "awesome-mcp-servers", "README.md"),
            ("e2b-dev", "awesome-ai-agents", "README.md"),
            ("humanloop", "awesome-ai-agents", "README.md"),
            ("public-apis", "public-apis", "README.md"),
            ("n0shake", "Public-APIs", "README.md"),
        ]

        for owner, repo, path in lists:
            log.info(f"Crawling {owner}/{repo}...")
            content = _fetch_github_raw(owner, repo, path)
            if not content:
                log.warning(f"Could not fetch {owner}/{repo}/{path}")
                stats["errors"] += 1
                continue

            self._parse_awesome_list(content, f"{owner}/{repo}", stats)
            time.sleep(RATE_LIMIT_DELAY * 2)

        duration = time.time() - start
        _log_run("awesome_lists", stats["new"], stats["skipped"], stats["errors"], duration)
        log.info(f"Awesome lists done: {stats['new']} new, {stats['skipped']} skipped, {stats['errors']} errors ({duration:.1f}s)")
        return stats

    def _parse_awesome_list(self, content, source_repo, stats):
        """Extract tool/API entries from an awesome list markdown file."""
        # Match markdown links: - [Name](url) - Description
        # or: | [Name](url) | Description |
        entries = re.findall(
            r'[-*|]\s*\[([^\]]{2,80})\]\(([^)]+)\)\s*[-:|]?\s*(.{10,300}?)(?:\n|$|\|)',
            content
        )

        count = 0
        seen_names = set()
        for name, url, desc in entries:
            if count >= 80:
                break
            name = name.strip()
            desc = desc.strip().rstrip("|").strip()

            # Skip navigation links, badges, etc.
            if any(x in name.lower() for x in ("back to top", "contents", "license", "contributing", "badge", "img.shields")):
                continue
            if any(x in url for x in ("img.shields.io", "#", "badge", "github.com/topics")):
                continue
            if name.lower() in seen_names:
                continue
            seen_names.add(name.lower())

            clean_name = re.sub(r'[^a-z0-9_]', '_', name.lower())[:50]
            if _is_url_cooled_down(url):
                stats["skipped"] += 1
                continue

            result = self._absorb_skill(
                clean_name, desc,
                f"Tool/API: {name}\nURL: {url}\nDescription: {desc}\nSource: {source_repo}",
                url, f"github:{source_repo}"
            )
            if result == "absorbed": stats["new"] += 1
            elif result == "skipped": stats["skipped"] += 1
            else: stats["errors"] += 1
            count += 1
            time.sleep(RATE_LIMIT_DELAY)

    # -------------------------------------------------------------------------
    # Source: API Directories
    # -------------------------------------------------------------------------
    def harvest_api_directories(self):
        """Crawl API directories for public APIs."""
        log.info("=== Harvesting API Directories ===")
        start = time.time()
        stats = {"new": 0, "skipped": 0, "errors": 0}

        # --- apis.guru ---
        self._harvest_apis_guru(stats)

        duration = time.time() - start
        _log_run("api_directories", stats["new"], stats["skipped"], stats["errors"], duration)
        log.info(f"API directories done: {stats['new']} new, {stats['skipped']} skipped, {stats['errors']} errors ({duration:.1f}s)")
        return stats

    def _harvest_apis_guru(self, stats):
        """Fetch apis.guru directory and absorb top APIs."""
        log.info("Crawling apis.guru...")
        content = _fetch_url("https://api.apis.guru/v2/list.json", max_len=500000)
        if not content:
            stats["errors"] += 1
            return

        try:
            apis = json.loads(content)
        except json.JSONDecodeError:
            stats["errors"] += 1
            return

        count = 0
        for api_name, api_data in list(apis.items())[:150]:
            if count >= 100:
                break
            try:
                preferred = api_data.get("preferred", "")
                versions = api_data.get("versions", {})
                if preferred and preferred in versions:
                    info = versions[preferred].get("info", {})
                else:
                    info = list(versions.values())[0].get("info", {}) if versions else {}

                title = info.get("title", api_name)
                desc = info.get("description", "")[:300]
                url = info.get("x-origin", [{}])[0].get("url", "") if info.get("x-origin") else ""
                if not url:
                    url = f"https://apis.guru/browse-apis/{api_name}"

                if not desc:
                    desc = f"Public API: {title}"

                clean_name = re.sub(r'[^a-z0-9_]', '_', api_name.lower().replace(":", "_"))[:50]

                result = self._absorb_skill(
                    f"api_{clean_name}", desc,
                    f"API: {title}\nProvider: {api_name}\nDescription: {desc}",
                    url, "apis.guru"
                )
                if result == "absorbed": stats["new"] += 1
                elif result == "skipped": stats["skipped"] += 1
                else: stats["errors"] += 1
                count += 1
                time.sleep(RATE_LIMIT_DELAY)
            except Exception as e:
                log.warning(f"Error processing {api_name}: {e}")
                stats["errors"] += 1

    # -------------------------------------------------------------------------
    # Run All
    # -------------------------------------------------------------------------
    def run_all(self):
        """Run all harvesters. Used by APScheduler."""
        log.info("========== SKILL HARVEST STARTING ==========")
        total_start = time.time()
        total = {"new": 0, "skipped": 0, "errors": 0}

        for name, method in [
            ("mcp_registries", self.harvest_mcp_registries),
            ("awesome_lists", self.harvest_awesome_lists),
            ("api_directories", self.harvest_api_directories),
        ]:
            try:
                stats = method()
                total["new"] += stats["new"]
                total["skipped"] += stats["skipped"]
                total["errors"] += stats["errors"]
            except Exception as e:
                log.error(f"Harvester {name} failed: {e}")
                total["errors"] += 1

        duration = time.time() - total_start
        log.info(f"========== HARVEST COMPLETE: {total['new']} new skills, {total['skipped']} skipped, {total['errors']} errors ({duration:.1f}s) ==========")
        return total

    def get_stats(self):
        """Get harvest statistics."""
        conn = sqlite3.connect(HARVEST_DB)
        conn.row_factory = sqlite3.Row
        runs = conn.execute(
            "SELECT * FROM harvest_runs ORDER BY timestamp DESC LIMIT 20"
        ).fetchall()
        sources = conn.execute(
            "SELECT source_type, COUNT(*) as count, SUM(skills_found) as total_skills FROM harvested_sources GROUP BY source_type"
        ).fetchall()
        total_skills = conn.execute("SELECT COUNT(*) FROM harvested_sources WHERE status = 'ok'").fetchone()[0]
        conn.close()

        skills_conn = sqlite3.connect(SKILLS_DB)
        skill_count = skills_conn.execute("SELECT COUNT(*) FROM skills").fetchone()[0]
        skills_conn.close()

        return {
            "total_skills_in_db": skill_count,
            "total_sources_crawled": total_skills,
            "by_source": [dict(r) for r in sources],
            "recent_runs": [dict(r) for r in runs],
        }


def _setup_from_app():
    """Import call_model and parse_json from app context."""
    import sys
    sys.path.insert(0, BASE_DIR)
    from model_router import call_model
    from app import parse_json_from_claude
    return call_model, parse_json_from_claude


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Skill Harvester for AiPayGent")
    parser.add_argument("--batch", action="store_true", help="Run batch harvest")
    parser.add_argument("--source", choices=["mcp", "github", "api", "all"], default="all",
                        help="Which source to harvest")
    parser.add_argument("--stats", action="store_true", help="Show harvest statistics")
    args = parser.parse_args()

    call_model, parse_json = _setup_from_app()
    harvester = SkillHarvester(call_model, parse_json)

    if args.stats:
        print(json.dumps(harvester.get_stats(), indent=2, default=str))
    elif args.batch:
        if args.source == "all":
            harvester.run_all()
        elif args.source == "mcp":
            harvester.harvest_mcp_registries()
        elif args.source == "github":
            harvester.harvest_awesome_lists()
        elif args.source == "api":
            harvester.harvest_api_directories()
    else:
        parser.print_help()
