"""Engagement features: streaks, favorites, recents, and AI workflow generation."""
import logging
import json
import os
import sqlite3
import time as _time
from datetime import datetime, date

from flask import Blueprint, request, jsonify
from helpers import require_api_key, call_llm

_log = logging.getLogger(__name__)
engagement_bp = Blueprint("engagement", __name__)

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "engagement.db")


def _conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_engagement_db():
    with _conn() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS streaks (
            user_id TEXT PRIMARY KEY,
            current_streak INTEGER DEFAULT 0,
            last_login TEXT,
            longest_streak INTEGER DEFAULT 0,
            bonus_claimed INTEGER DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS favorites (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            item_type TEXT NOT NULL,
            item_slug TEXT NOT NULL,
            created_at REAL DEFAULT (strftime('%s','now')),
            UNIQUE(user_id, item_type, item_slug)
        );
        CREATE TABLE IF NOT EXISTS recents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            item_type TEXT NOT NULL,
            item_slug TEXT NOT NULL,
            used_at REAL DEFAULT (strftime('%s','now'))
        );
        """)


init_engagement_db()


# ── Streak Endpoints ──────────────────────────────────────────────────────────

def _get_user_id():
    """Extract user_id from the validated API key. Reject if no key."""
    key = getattr(request, "api_key", None)
    if not key:
        return None
    return key


@engagement_bp.route("/engagement/checkin", methods=["POST"])
@require_api_key
def checkin():
    user_id = _get_user_id()
    if not user_id:
        return jsonify({"error": "API key required"}), 401
    today = date.today().isoformat()

    with _conn() as c:
        row = c.execute("SELECT * FROM streaks WHERE user_id = ?", (user_id,)).fetchone()

        if not row:
            c.execute(
                "INSERT INTO streaks (user_id, current_streak, last_login, longest_streak, bonus_claimed) VALUES (?, 1, ?, 1, 0)",
                (user_id, today),
            )
            return jsonify({"streak": 1, "longest_streak": 1, "bonus_available": False})

        last_login = row["last_login"]
        current = row["current_streak"]
        longest = row["longest_streak"]
        bonus_claimed = row["bonus_claimed"]

        if last_login == today:
            bonus_available = current >= 3 and bonus_claimed == 0
            return jsonify({"streak": current, "longest_streak": longest, "bonus_available": bonus_available})

        # Check if yesterday
        from datetime import timedelta
        yesterday = (date.today() - timedelta(days=1)).isoformat()

        if last_login == yesterday:
            current += 1
        else:
            current = 1
            # Reset bonus on streak break
            bonus_claimed = 0

        if current > longest:
            longest = current

        c.execute(
            "UPDATE streaks SET current_streak = ?, last_login = ?, longest_streak = ?, bonus_claimed = ? WHERE user_id = ?",
            (current, today, longest, bonus_claimed, user_id),
        )

    bonus_available = current >= 3 and bonus_claimed == 0
    return jsonify({"streak": current, "longest_streak": longest, "bonus_available": bonus_available})


@engagement_bp.route("/engagement/claim-streak", methods=["POST"])
@require_api_key
def claim_streak():
    from api_keys import topup_key

    user_id = _get_user_id()
    if not user_id:
        return jsonify({"error": "API key required"}), 401

    with _conn() as c:
        # Atomic: only update if streak >= 3 and bonus not yet claimed
        c.execute(
            "UPDATE streaks SET bonus_claimed = 1 WHERE user_id = ? AND current_streak >= 3 AND bonus_claimed = 0",
            (user_id,),
        )
        if c.execute("SELECT changes()").fetchone()[0] == 0:
            # Either no row, streak < 3, or already claimed
            row = c.execute("SELECT * FROM streaks WHERE user_id = ?", (user_id,)).fetchone()
            if not row:
                return jsonify({"error": "No streak found. Check in first."}), 400
            if row["current_streak"] < 3:
                return jsonify({"error": "Need at least a 3-day streak.", "streak": row["current_streak"]}), 400
            return jsonify({"error": "Bonus already claimed for this streak."}), 400

        # Grant bonus: topup the user's API key balance ($0.01 = ~1 call)
        topup_key(user_id, 0.01)

        row = c.execute("SELECT current_streak FROM streaks WHERE user_id = ?", (user_id,)).fetchone()
        streak = row["current_streak"] if row else 0

    return jsonify({"success": True, "bonus_calls": 1, "streak": streak})


@engagement_bp.route("/engagement/streak", methods=["GET"])
@require_api_key
def get_streak():
    user_id = _get_user_id()
    if not user_id:
        return jsonify({"error": "API key required"}), 401

    with _conn() as c:
        row = c.execute("SELECT * FROM streaks WHERE user_id = ?", (user_id,)).fetchone()

    if not row:
        return jsonify({"streak": 0, "longest_streak": 0, "bonus_available": False, "bonus_claimed": False})

    return jsonify({
        "streak": row["current_streak"],
        "longest_streak": row["longest_streak"],
        "bonus_available": row["current_streak"] >= 3 and row["bonus_claimed"] == 0,
        "bonus_claimed": bool(row["bonus_claimed"]),
    })


# ── Favorites Endpoints ───────────────────────────────────────────────────────

@engagement_bp.route("/favorites", methods=["POST"])
@require_api_key
def add_favorite():
    user_id = _get_user_id()
    data = request.get_json() or {}
    item_type = data.get("type", "").strip()
    slug = data.get("slug", "").strip()

    if item_type not in ("tool", "workflow"):
        return jsonify({"error": "type must be 'tool' or 'workflow'"}), 400
    if not slug:
        return jsonify({"error": "slug required"}), 400

    with _conn() as c:
        try:
            c.execute(
                "INSERT INTO favorites (user_id, item_type, item_slug) VALUES (?, ?, ?)",
                (user_id, item_type, slug),
            )
        except sqlite3.IntegrityError:
            return jsonify({"error": "Already favorited"}), 409

    return jsonify({"success": True})


@engagement_bp.route("/favorites", methods=["DELETE"])
@require_api_key
def remove_favorite():
    user_id = _get_user_id()
    data = request.get_json() or {}
    item_type = data.get("type", "").strip()
    slug = data.get("slug", "").strip()

    if not item_type or not slug:
        return jsonify({"error": "type and slug required"}), 400

    with _conn() as c:
        c.execute(
            "DELETE FROM favorites WHERE user_id = ? AND item_type = ? AND item_slug = ?",
            (user_id, item_type, slug),
        )

    return jsonify({"success": True})


@engagement_bp.route("/favorites", methods=["GET"])
@require_api_key
def list_favorites():
    user_id = _get_user_id()
    type_filter = request.args.get("type", "").strip()

    with _conn() as c:
        if type_filter:
            rows = c.execute(
                "SELECT item_type, item_slug, created_at FROM favorites WHERE user_id = ? AND item_type = ? ORDER BY created_at DESC",
                (user_id, type_filter),
            ).fetchall()
        else:
            rows = c.execute(
                "SELECT item_type, item_slug, created_at FROM favorites WHERE user_id = ? ORDER BY created_at DESC",
                (user_id,),
            ).fetchall()

    return jsonify({
        "favorites": [{"type": r["item_type"], "slug": r["item_slug"], "created_at": r["created_at"]} for r in rows]
    })


# ── Recents Endpoints ─────────────────────────────────────────────────────────

@engagement_bp.route("/recents", methods=["POST"])
@require_api_key
def log_recent():
    user_id = _get_user_id()
    data = request.get_json() or {}
    item_type = data.get("type", "").strip()
    slug = data.get("slug", "").strip()

    if not item_type or not slug:
        return jsonify({"error": "type and slug required"}), 400

    with _conn() as c:
        c.execute(
            "INSERT INTO recents (user_id, item_type, item_slug) VALUES (?, ?, ?)",
            (user_id, item_type, slug),
        )
        # Keep max 20 per user — delete oldest beyond 20
        c.execute("""
            DELETE FROM recents WHERE id NOT IN (
                SELECT id FROM recents WHERE user_id = ? ORDER BY used_at DESC LIMIT 20
            ) AND user_id = ?
        """, (user_id, user_id))

    return jsonify({"success": True})


@engagement_bp.route("/recents", methods=["GET"])
@require_api_key
def list_recents():
    user_id = _get_user_id()

    with _conn() as c:
        rows = c.execute(
            "SELECT item_type, item_slug, used_at FROM recents WHERE user_id = ? ORDER BY used_at DESC LIMIT 20",
            (user_id,),
        ).fetchall()

    return jsonify({
        "recents": [{"type": r["item_type"], "slug": r["item_slug"], "used_at": r["used_at"]} for r in rows]
    })


# ── AI Workflow Generation ────────────────────────────────────────────────────

_WORKFLOW_SYSTEM_PROMPT = """You are an AiPayGen workflow builder. Given the user's description, generate a JSON workflow with steps.

Each step has:
- id: unique string (e.g. "step_1")
- toolName: from available AiPayGen tools (summarize, translate, sentiment, extract, rewrite, analyze, research, web_search, scrape_website, code, write, classify, keywords, tag, qa, compare, explain, outline, proofread, score, questions, vision, email, social, headline, pitch, plan, decide, debate, fact, timeline, diagram, mock, test_cases, json_schema, regex, sql, transform, run_python_code)
- label: human-readable name for this step
- config: object with tool parameters (e.g. {"text": "...", "lang": "es"} for translate)
- inputFrom: "user_input" for the first step, or a previous step id to chain output

Return ONLY valid JSON: {"name": "...", "description": "...", "steps": [...]}"""


@engagement_bp.route("/workflow/generate", methods=["POST"])
@require_api_key
def generate_workflow():
    data = request.get_json() or {}
    prompt = data.get("prompt", "").strip()

    if not prompt:
        return jsonify({"error": "prompt required"}), 400

    messages = [{"role": "user", "content": prompt}]
    result, err = call_llm(messages, system=_WORKFLOW_SYSTEM_PROMPT, max_tokens=2048, endpoint="workflow/generate")

    if err:
        return jsonify({"error": f"LLM call failed: {err}"}), 500

    # Parse JSON from the LLM response
    from helpers import parse_json_from_claude
    text = result.get("text", "") if isinstance(result, dict) else str(result)
    parsed = parse_json_from_claude(text)

    if not parsed:
        return jsonify({"error": "Failed to parse workflow from AI response", "raw": text}), 500

    return jsonify(parsed)
