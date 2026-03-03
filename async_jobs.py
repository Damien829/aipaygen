"""Async job queue with SQLite persistence and webhook callbacks."""
import sqlite3
import json
import uuid
import threading
import os
import requests
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(__file__), "async_jobs.db")
UPLOADS_DIR = os.path.join(os.path.dirname(__file__), "uploads")


def _conn():
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    return c


def init_jobs_db():
    with _conn() as c:
        c.execute("""
            CREATE TABLE IF NOT EXISTS async_jobs (
                job_id TEXT PRIMARY KEY,
                endpoint TEXT NOT NULL,
                payload TEXT NOT NULL,
                callback_url TEXT,
                status TEXT DEFAULT 'pending',
                result TEXT,
                error TEXT,
                created_at TEXT NOT NULL,
                completed_at TEXT
            )
        """)
        c.execute("CREATE INDEX IF NOT EXISTS idx_jobs_status ON async_jobs(status)")


def submit_job(endpoint: str, payload: dict, callback_url: str = None) -> str:
    job_id = str(uuid.uuid4())
    now = datetime.utcnow().isoformat()
    with _conn() as c:
        c.execute(
            "INSERT INTO async_jobs (job_id, endpoint, payload, callback_url, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (job_id, endpoint, json.dumps(payload), callback_url, now),
        )
    return job_id


def get_job(job_id: str) -> dict | None:
    with _conn() as c:
        row = c.execute("SELECT * FROM async_jobs WHERE job_id=?", (job_id,)).fetchone()
    if not row:
        return None
    d = dict(row)
    try:
        d["payload"] = json.loads(d["payload"])
    except Exception:
        pass
    if d.get("result"):
        try:
            d["result"] = json.loads(d["result"])
        except Exception:
            pass
    return d


def _mark_running(job_id: str):
    with _conn() as c:
        c.execute("UPDATE async_jobs SET status='running' WHERE job_id=?", (job_id,))


def _mark_done(job_id: str, result: dict):
    now = datetime.utcnow().isoformat()
    with _conn() as c:
        c.execute(
            "UPDATE async_jobs SET status='completed', result=?, completed_at=? WHERE job_id=?",
            (json.dumps(result), now, job_id),
        )


def _mark_failed(job_id: str, error: str):
    now = datetime.utcnow().isoformat()
    with _conn() as c:
        c.execute(
            "UPDATE async_jobs SET status='failed', error=?, completed_at=? WHERE job_id=?",
            (error, now, job_id),
        )


def run_job_async(job_id: str, executor_fn):
    """Run executor_fn(payload) in a background thread. POSTs result to callback_url if set."""
    def _run():
        job = get_job(job_id)
        if not job:
            return
        _mark_running(job_id)
        try:
            result = executor_fn(job["payload"])
            _mark_done(job_id, result)
            if job.get("callback_url"):
                try:
                    requests.post(job["callback_url"], json={
                        "job_id": job_id,
                        "status": "completed",
                        "result": result,
                    }, timeout=10)
                except Exception:
                    pass
        except Exception as e:
            _mark_failed(job_id, str(e))
            if job.get("callback_url"):
                try:
                    requests.post(job["callback_url"], json={
                        "job_id": job_id,
                        "status": "failed",
                        "error": str(e),
                    }, timeout=10)
                except Exception:
                    pass

    threading.Thread(target=_run, daemon=True).start()
