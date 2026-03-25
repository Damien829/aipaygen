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

    # ── Core content jobs (disabled when None to save API credits) ──────
    if run_hourly_fn:
        _scheduler.add_job(lambda: run_all_hunters(claude_client), "cron", hour=3, minute=0)
        _scheduler.add_job(lambda: run_hourly_fn(claude_client), "interval", hours=1)
    if run_daily_fn:
        _scheduler.add_job(lambda: run_daily_fn(claude_client), "cron", hour=6, minute=0)
    if run_weekly_fn:
        _scheduler.add_job(lambda: run_weekly_fn(claude_client), "cron", day_of_week="mon", hour=7, minute=0)
    if run_economy_fn:
        _scheduler.add_job(run_economy_fn, "interval", minutes=30)

    # ── Skill Harvester — DISABLED (costs API credits, re-enable when profitable)
    # try:
    #     from skill_harvester import SkillHarvester
    #     _harvester = SkillHarvester(call_model_fn, parse_json_fn)
    #     _scheduler.add_job(_harvester.run_all, "cron", hour=4, minute=0)
    # except Exception as e:
    #     logger.warning("skill harvester init failed: %s", e)

    # ══════════════════════════════════════════════════════════════════════
    # ALL BELOW DISABLED — $0 revenue, every API call costs real money
    # Re-enable when revenue covers costs
    # ══════════════════════════════════════════════════════════════════════

    # API Hunter-Gatherer — DISABLED (uses claude_client hourly)
    # Auto-skill generator — DISABLED (uses call_model_fn daily)
    # Discovery scouts — DISABLED (6 scouts using call_model_fn 10+x/day)
    # Health checker — DISABLED (makes HTTP requests to 30 APIs every 4h)
    logger.info("Expensive scheduled jobs DISABLED (pre-revenue mode)")

    # ── Email queue processor — every 5 min (FREE, uses Resend free tier) ──
    try:
        from routes.auth import _process_email_queue
        _scheduler.add_job(_process_email_queue, "interval", minutes=5, id="email_queue")
        logger.info("Email queue processor started (every 5 min)")
    except Exception as e:
        logger.warning("email queue init failed: %s", e)

    # ── Daily cleanup — purge old audit logs and trim DBs (FREE) ─────
    def _daily_cleanup():
        import sqlite3 as _sql
        try:
            db = _sql.connect(os.path.join(os.path.dirname(__file__), "billing_audit.db"))
            db.execute("DELETE FROM billing_audit WHERE created_at < datetime('now', '-7 days')")
            db.commit()
            db.execute("VACUUM")
            db.close()
            logger.info("daily_cleanup: purged old billing_audit rows")
        except Exception as e:
            logger.error("daily_cleanup failed: %s", e)

    _scheduler.add_job(_daily_cleanup, "cron", hour=2, minute=0, id="daily_cleanup")

    # ── PyPI download tracker — every 6h ──────────────────────────────
    try:
        from funnel_tracker import poll_pypi_downloads
        _scheduler.add_job(poll_pypi_downloads, "interval", hours=6, id="pypi_downloads")
    except Exception as e:
        logger.warning("pypi download tracker init failed: %s", e)

    # ── Start scheduler ──────────────────────────────────────────────────
    _scheduler.start()

    # ── One-time startup tasks ───────────────────────────────────────────
    import threading as _threading
    if generate_blog_fn:
        _threading.Thread(target=lambda: generate_blog_fn(claude_client), daemon=True).start()
    if run_canary_fn:
        _threading.Timer(60.0, lambda: run_canary_fn()).start()


def add_job(func, *args, **kwargs):
    """Add a job to the scheduler (convenience wrapper)."""
    _scheduler.add_job(func, *args, **kwargs)


def get_scheduler():
    """Return the scheduler instance for adding jobs externally."""
    return _scheduler
