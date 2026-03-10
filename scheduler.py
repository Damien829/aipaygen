"""APScheduler job definitions — extracted from app.py for modularity."""
import logging
import os
import time as _time
import re as _re
from apscheduler.schedulers.background import BackgroundScheduler

logger = logging.getLogger(__name__)

_scheduler = BackgroundScheduler(daemon=True)


def init_scheduler(claude_client, call_model_fn, parse_json_fn,
                   run_hourly_fn, run_daily_fn, run_weekly_fn,
                   run_canary_fn, generate_blog_fn, run_economy_fn):
    """Register all scheduled jobs. Call once at app startup."""
    from api_discovery import run_all_hunters, inject_high_scorers

    # ── Core content jobs ────────────────────────────────────────────────
    _scheduler.add_job(lambda: run_all_hunters(claude_client), "cron", hour=3, minute=0)
    _scheduler.add_job(lambda: run_hourly_fn(claude_client), "interval", hours=6)
    _scheduler.add_job(lambda: run_daily_fn(claude_client), "cron", hour=6, minute=0)
    _scheduler.add_job(lambda: run_weekly_fn(claude_client), "cron", day_of_week="mon", hour=7, minute=0)
    if run_economy_fn:
        _scheduler.add_job(run_economy_fn, "interval", minutes=30)

    # ── Skill Harvester — daily ──────────────────────────────────────────
    try:
        from skill_harvester import SkillHarvester
        _harvester = SkillHarvester(call_model_fn, parse_json_fn)
        _scheduler.add_job(_harvester.run_all, "cron", hour=4, minute=0)
    except Exception as e:
        logger.warning("skill harvester init failed: %s", e)

    # ── API Hunter-Gatherer — hourly ─────────────────────────────────────
    def _run_api_hunter():
        try:
            found = run_all_hunters(claude_client, max_per_run=200)
            injected = inject_high_scorers(min_score=7)
            logger.info("api_hunter found=%s, injected=%s", found, injected)
        except Exception as e:
            logger.error("api_hunter failed: %s", e)

    _scheduler.add_job(_run_api_hunter, "interval", hours=1, id="api_hunter")

    # ── Health checker — every 4h ────────────────────────────────────────
    def _run_health_checks():
        from api_catalog import get_apis_for_health_check, update_health
        from security import safe_fetch
        try:
            apis = get_apis_for_health_check(limit=30)
            for api in apis:
                url = api["base_url"]
                if api.get("sample_endpoint"):
                    url = url.rstrip("/") + "/" + api["sample_endpoint"].lstrip("/")
                start = _time.time()
                result = safe_fetch(url, timeout=10, max_size=1000)
                latency = (_time.time() - start) * 1000
                status_code = result.get("status", 0)
                if "error" in result or status_code >= 500:
                    update_health(api["id"], "error", latency)
                elif status_code >= 400:
                    update_health(api["id"], "dead", latency)
                else:
                    update_health(api["id"], "healthy", latency)
        except Exception as e:
            logger.error("health_check failed: %s", e)

    _scheduler.add_job(_run_health_checks, "interval", hours=4, id="health_checks")

    # ── Auto-skill generator — daily ─────────────────────────────────────
    def _auto_generate_skills():
        from api_catalog import get_all_apis
        try:
            apis, _ = get_all_apis(page=1, per_page=50, min_score=8)
            import sqlite3 as _sql
            skills_db = os.path.join(os.path.dirname(__file__), "skills.db")
            conn = _sql.connect(skills_db)
            generated = 0
            for api in apis:
                skill_name = "api_" + _re.sub(r'[^a-z0-9_]', '_', api['name'].lower())[:50]
                exists = conn.execute("SELECT 1 FROM skills WHERE name = ?", (skill_name,)).fetchone()
                if exists:
                    continue
                template = (f"Use the call_api tool with api_id={api['id']} to call the {api['name']} API "
                            f"(base: {api['base_url']}). {api.get('description','')[:150]}. "
                            f"User request: {{{{input}}}}. Return the API response.")
                conn.execute(
                    "INSERT INTO skills (name, description, category, source, prompt_template, model, input_schema, calls) "
                    "VALUES (?, ?, ?, ?, ?, 'claude-haiku', ?, 0)",
                    (skill_name, (api.get("description") or "")[:200], api.get("category", "api"),
                     f"catalog:{api['id']}", template, '{"input": "What to do with this API"}'),
                )
                generated += 1
            conn.commit()
            conn.close()
            if generated:
                logger.info("auto_skills generated %s new skills from catalog", generated)
        except Exception as e:
            logger.error("auto_skills failed: %s", e)

    _scheduler.add_job(_auto_generate_skills, "cron", hour=5, minute=30, id="auto_skills")

    # ── Discovery scouts ─────────────────────────────────────────────────
    try:
        from discovery_scouts import (
            GitHubScout, RegistryScout, SocialScout,
            A2AScout, TwitterScout, FollowUpAgent, init_scout_db,
        )
        init_scout_db()
        _gh = GitHubScout(call_model_fn)
        _reg = RegistryScout(call_model_fn)
        _social = SocialScout(call_model_fn)
        _a2a = A2AScout(call_model_fn)
        _tw = TwitterScout(call_model_fn)
        _follow = FollowUpAgent(call_model_fn)

        _scheduler.add_job(_gh.run, "cron", hour="8,20", minute=0, id="scout_github")
        _scheduler.add_job(_reg.run, "cron", hour=5, minute=0, id="scout_registry")
        _scheduler.add_job(_social.run, "cron", hour="9,15,21", minute=0, id="scout_social")
        _scheduler.add_job(_a2a.run, "interval", hours=1, id="scout_a2a")
        _scheduler.add_job(_tw.run, "cron", hour="6,12,18,0", minute=0, id="scout_twitter")
        _scheduler.add_job(_follow.run, "interval", hours=6, id="scout_followup")
    except Exception as e:
        logger.warning("scout init failed: %s", e)

    # ── Start scheduler ──────────────────────────────────────────────────
    _scheduler.start()

    # ── One-time startup tasks ───────────────────────────────────────────
    import threading as _threading
    _threading.Thread(target=lambda: generate_blog_fn(claude_client), daemon=True).start()
    _threading.Timer(60.0, lambda: run_canary_fn()).start()


def add_job(func, *args, **kwargs):
    """Add a job to the scheduler (convenience wrapper)."""
    _scheduler.add_job(func, *args, **kwargs)


def get_scheduler():
    """Return the scheduler instance for adding jobs externally."""
    return _scheduler
