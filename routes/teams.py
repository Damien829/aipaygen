"""Team / organization management routes for AiPayGen API platform."""

import csv
import io
import os
import sqlite3
from datetime import datetime, timezone

from flask import Blueprint, request, jsonify, Response

from helpers import require_api_key, rate_limit
from teams import (
    create_team,
    invite_member,
    accept_invite,
    remove_member,
    set_member_role,
    get_team,
    get_team_by_slug,
    list_user_teams,
    add_key_to_team,
    remove_key_from_team,
    get_team_keys,
    get_team_usage,
    _get_account_id_for_key,
    _is_team_admin_or_owner,
)

teams_bp = Blueprint("teams", __name__)


def _resolve_account(api_key: str) -> int | None:
    """Resolve account_id from the authenticated API key."""
    if not api_key:
        return None
    return _get_account_id_for_key(api_key)


# ── POST /teams/create ────────────────────────────────────────────────────

@teams_bp.route("/teams/create", methods=["POST"])
@require_api_key
def create_team_route():
    account_id = _resolve_account(request.api_key)
    if not account_id:
        return jsonify({"error": "No account linked to this API key. Sign in first."}), 403
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"error": "name is required"}), 400
    if len(name) > 100:
        return jsonify({"error": "name must be 100 chars or less"}), 400
    billing_email = (data.get("billing_email") or "").strip()
    result = create_team(name, account_id, billing_email)
    return jsonify(result), 201


# ── GET /teams ─────────────────────────────────────────────────────────────

@teams_bp.route("/teams", methods=["GET"])
@require_api_key
def list_teams_route():
    account_id = _resolve_account(request.api_key)
    if not account_id:
        return jsonify({"error": "No account linked to this API key."}), 403
    teams = list_user_teams(account_id)
    return jsonify({"teams": teams})


# ── GET /teams/<team_id> ──────────────────────────────────────────────────

@teams_bp.route("/teams/<team_id>", methods=["GET"])
@require_api_key
def get_team_route(team_id):
    account_id = _resolve_account(request.api_key)
    if not account_id:
        return jsonify({"error": "No account linked to this API key."}), 403
    # Allow lookup by slug
    if not team_id.startswith("team_"):
        team = get_team_by_slug(team_id)
    else:
        team = get_team(team_id)
    if not team:
        return jsonify({"error": "team_not_found"}), 404
    # Only members can view team details
    member_ids = [m["account_id"] for m in team.get("members", [])]
    if account_id not in member_ids:
        return jsonify({"error": "not_a_member"}), 403
    return jsonify(team)


# ── POST /teams/<team_id>/invite ──────────────────────────────────────────

@teams_bp.route("/teams/<team_id>/invite", methods=["POST"])
@require_api_key
def invite_member_route(team_id):
    account_id = _resolve_account(request.api_key)
    if not account_id:
        return jsonify({"error": "No account linked to this API key."}), 403
    if not _is_team_admin_or_owner(team_id, account_id):
        return jsonify({"error": "Only admins or owners can invite members."}), 403
    data = request.get_json(silent=True) or {}
    email = (data.get("email") or "").strip().lower()
    if not email:
        return jsonify({"error": "email is required"}), 400
    role = (data.get("role") or "member").strip().lower()
    result = invite_member(team_id, email, role, account_id)
    if "error" in result:
        return jsonify(result), 400
    return jsonify(result), 201


# ── POST /teams/<team_id>/accept ──────────────────────────────────────────

@teams_bp.route("/teams/<team_id>/accept", methods=["POST"])
@require_api_key
def accept_invite_route(team_id):
    account_id = _resolve_account(request.api_key)
    if not account_id:
        return jsonify({"error": "No account linked to this API key."}), 403
    data = request.get_json(silent=True) or {}
    email = (data.get("email") or "").strip().lower()
    ok = accept_invite(team_id, account_id, email=email)
    if not ok:
        return jsonify({"error": "No pending invite found."}), 404
    return jsonify({"ok": True, "message": "Invite accepted."})


# ── DELETE /teams/<team_id>/members/<account_id> ──────────────────────────

@teams_bp.route("/teams/<team_id>/members/<int:target_account_id>", methods=["DELETE"])
@require_api_key
def remove_member_route(team_id, target_account_id):
    account_id = _resolve_account(request.api_key)
    if not account_id:
        return jsonify({"error": "No account linked to this API key."}), 403
    # Allow self-removal or admin/owner removal
    if account_id != target_account_id and not _is_team_admin_or_owner(team_id, account_id):
        return jsonify({"error": "Only admins/owners can remove other members."}), 403
    ok = remove_member(team_id, target_account_id)
    if not ok:
        return jsonify({"error": "Cannot remove member. They may be the owner or not found."}), 400
    return jsonify({"ok": True, "message": "Member removed."})


# ── PATCH /teams/<team_id>/members/<account_id>/role ──────────────────────

@teams_bp.route("/teams/<team_id>/members/<int:target_account_id>/role", methods=["PATCH"])
@require_api_key
def set_role_route(team_id, target_account_id):
    account_id = _resolve_account(request.api_key)
    if not account_id:
        return jsonify({"error": "No account linked to this API key."}), 403
    if not _is_team_admin_or_owner(team_id, account_id):
        return jsonify({"error": "Only admins/owners can change roles."}), 403
    data = request.get_json(silent=True) or {}
    role = (data.get("role") or "").strip().lower()
    if role not in ("admin", "member"):
        return jsonify({"error": "role must be 'admin' or 'member'"}), 400
    ok = set_member_role(team_id, target_account_id, role)
    if not ok:
        return jsonify({"error": "Cannot change role. Member not found or is the owner."}), 400
    return jsonify({"ok": True, "message": f"Role updated to {role}."})


# ── POST /teams/<team_id>/keys ────────────────────────────────────────────

@teams_bp.route("/teams/<team_id>/keys", methods=["POST"])
@require_api_key
def add_key_route(team_id):
    account_id = _resolve_account(request.api_key)
    if not account_id:
        return jsonify({"error": "No account linked to this API key."}), 403
    if not _is_team_admin_or_owner(team_id, account_id):
        return jsonify({"error": "Only admins/owners can manage team keys."}), 403
    data = request.get_json(silent=True) or {}
    api_key = (data.get("api_key") or "").strip()
    if not api_key:
        return jsonify({"error": "api_key is required"}), 400
    label = (data.get("label") or "").strip()
    ok = add_key_to_team(team_id, api_key, label, account_id)
    if not ok:
        return jsonify({"error": "Key already linked or team not found."}), 400
    return jsonify({"ok": True, "message": "API key added to team."}), 201


# ── DELETE /teams/<team_id>/keys/<key_id> ─────────────────────────────────

@teams_bp.route("/teams/<team_id>/keys/<key_id>", methods=["DELETE"])
@require_api_key
def remove_key_route(team_id, key_id):
    account_id = _resolve_account(request.api_key)
    if not account_id:
        return jsonify({"error": "No account linked to this API key."}), 403
    if not _is_team_admin_or_owner(team_id, account_id):
        return jsonify({"error": "Only admins/owners can manage team keys."}), 403
    # key_id is the api_key string
    ok = remove_key_from_team(team_id, key_id)
    if not ok:
        return jsonify({"error": "Key not found in this team."}), 404
    return jsonify({"ok": True, "message": "API key removed from team."})


# ── GET /teams/<team_id>/usage ────────────────────────────────────────────

@teams_bp.route("/teams/<team_id>/usage", methods=["GET"])
@require_api_key
def team_usage_route(team_id):
    account_id = _resolve_account(request.api_key)
    if not account_id:
        return jsonify({"error": "No account linked to this API key."}), 403
    # Only members can view usage
    team = get_team(team_id)
    if not team:
        return jsonify({"error": "team_not_found"}), 404
    member_ids = [m["account_id"] for m in team.get("members", [])]
    if account_id not in member_ids:
        return jsonify({"error": "not_a_member"}), 403
    usage = get_team_usage(team_id)
    return jsonify(usage)


# ── Usage Export Helpers ─────────────────────────────────────────────────────

_BASE_DIR = os.path.dirname(os.path.dirname(__file__))
_TOOL_USAGE_DB = os.path.join(_BASE_DIR, "tool_usage.db")
_COST_PER_CALL = 0.001  # USD


def _usage_db():
    """Return a sqlite3 connection to tool_usage.db with WAL mode."""
    conn = sqlite3.connect(_TOOL_USAGE_DB)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.row_factory = sqlite3.Row
    return conn


# ── GET /api/usage/export ────────────────────────────────────────────────────

@teams_bp.route("/api/usage/export", methods=["GET"])
@require_api_key
@rate_limit(30)
def usage_export():
    fmt = request.args.get("format", "json").lower()
    if fmt not in ("csv", "json"):
        return jsonify({"error": "format must be csv or json"}), 400

    days = request.args.get("days", "30")
    try:
        days = int(days)
        if days < 1 or days > 90:
            raise ValueError
    except (ValueError, TypeError):
        return jsonify({"error": "days must be an integer between 1 and 90"}), 400

    filter_key = request.args.get("api_key") or request.api_key

    try:
        conn = _usage_db()
        rows = conn.execute(
            """SELECT date(last_used) as date, tool_name, count as calls
               FROM tool_usage
               WHERE api_key = ? AND last_used >= datetime('now', ?)
               ORDER BY date DESC, tool_name""",
            (filter_key, f"-{days} days"),
        ).fetchall()
        conn.close()
    except Exception:
        rows = []

    records = [
        {
            "date": r["date"],
            "endpoint": r["tool_name"],
            "calls": r["calls"],
            "cost_usd": round(r["calls"] * _COST_PER_CALL, 4),
        }
        for r in rows
    ]

    if fmt == "csv":
        buf = io.StringIO()
        writer = csv.DictWriter(buf, fieldnames=["date", "endpoint", "calls", "cost_usd"])
        writer.writeheader()
        writer.writerows(records)
        return Response(
            buf.getvalue(),
            mimetype="text/csv",
            headers={"Content-Disposition": "attachment; filename=usage_export.csv"},
        )

    return jsonify({"days": days, "api_key": filter_key, "rows": len(records), "data": records})


# ── GET /api/usage/summary ───────────────────────────────────────────────────

@teams_bp.route("/api/usage/summary", methods=["GET"])
@require_api_key
@rate_limit(60)
def usage_summary():
    api_key = request.api_key

    try:
        conn = _usage_db()

        # Total calls (all time)
        total_calls = conn.execute(
            "SELECT COALESCE(SUM(count), 0) FROM tool_usage WHERE api_key = ?",
            (api_key,),
        ).fetchone()[0]

        # Calls today
        calls_today = conn.execute(
            "SELECT COALESCE(SUM(count), 0) FROM tool_usage WHERE api_key = ? AND date(last_used) = date('now')",
            (api_key,),
        ).fetchone()[0]

        # Calls this week (last 7 days)
        calls_this_week = conn.execute(
            "SELECT COALESCE(SUM(count), 0) FROM tool_usage WHERE api_key = ? AND last_used >= datetime('now', '-7 days')",
            (api_key,),
        ).fetchone()[0]

        # Calls this month (last 30 days)
        calls_this_month = conn.execute(
            "SELECT COALESCE(SUM(count), 0) FROM tool_usage WHERE api_key = ? AND last_used >= datetime('now', '-30 days')",
            (api_key,),
        ).fetchone()[0]

        # Top 5 tools
        top_rows = conn.execute(
            "SELECT tool_name, SUM(count) as total FROM tool_usage WHERE api_key = ? GROUP BY tool_name ORDER BY total DESC LIMIT 5",
            (api_key,),
        ).fetchall()
        top_tools = [{"tool": r["tool_name"], "calls": r["total"]} for r in top_rows]

        # Daily average (over last 30 days)
        day_count = conn.execute(
            "SELECT COUNT(DISTINCT date(last_used)) FROM tool_usage WHERE api_key = ? AND last_used >= datetime('now', '-30 days')",
            (api_key,),
        ).fetchone()[0] or 1
        daily_average = round(calls_this_month / day_count, 1)

        conn.close()
    except Exception:
        return jsonify({"error": "Failed to read usage data"}), 500

    total_spent = round(total_calls * _COST_PER_CALL, 4)

    return jsonify({
        "api_key": api_key,
        "total_calls": total_calls,
        "total_spent": total_spent,
        "calls_today": calls_today,
        "calls_this_week": calls_this_week,
        "calls_this_month": calls_this_month,
        "top_tools": top_tools,
        "daily_average": daily_average,
    })
