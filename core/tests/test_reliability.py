"""Tests for reliability and monitoring features: uptime tracker, alerting, circuit breaker, health endpoints."""
import os
import sqlite3
import tempfile
import time
import pytest


# ── Uptime Tracker Tests ─────────────────────────────────────────────────────

class TestUptimeTracker:
    def setup_method(self):
        import uptime_tracker
        self._orig_path = uptime_tracker.DB_PATH
        self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        uptime_tracker.DB_PATH = self._tmp.name
        uptime_tracker.init_uptime_db()

    def teardown_method(self):
        import uptime_tracker
        uptime_tracker.DB_PATH = self._orig_path
        try:
            os.unlink(self._tmp.name)
        except Exception:
            pass

    def test_record_and_retrieve(self):
        from uptime_tracker import record_check, get_recent_checks
        record_check("ok", 42.5, 5, 5)
        record_check("degraded", 150.0, 3, 5)
        checks = get_recent_checks(limit=10)
        assert len(checks) == 2
        assert checks[0]["status"] == "degraded"  # most recent first
        assert checks[1]["status"] == "ok"

    def test_uptime_stats(self):
        from uptime_tracker import record_check, get_uptime_stats
        # 8 ok, 2 degraded
        for _ in range(8):
            record_check("ok", 50.0, 5, 5)
        for _ in range(2):
            record_check("degraded", 200.0, 3, 5)
        stats = get_uptime_stats()
        assert stats["24h"]["total_checks"] == 10
        assert stats["24h"]["ok_checks"] == 8
        assert stats["24h"]["uptime_pct"] == 80.0

    def test_empty_stats(self):
        from uptime_tracker import get_uptime_stats
        stats = get_uptime_stats()
        assert stats["24h"]["uptime_pct"] == 100.0
        assert stats["24h"]["total_checks"] == 0

    def test_cleanup(self):
        from uptime_tracker import record_check, cleanup_old_records, get_recent_checks, _conn
        record_check("ok", 50.0, 5, 5)
        # Backdate the record
        with _conn() as c:
            c.execute("UPDATE uptime_checks SET timestamp = ?", (time.time() - 100 * 86400,))
        cleanup_old_records(days=90)
        checks = get_recent_checks()
        assert len(checks) == 0


# ── Alerting Tests ───────────────────────────────────────────────────────────

class TestAlerting:
    def setup_method(self):
        import alerting
        self._orig_path = alerting.DB_PATH
        self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        alerting.DB_PATH = self._tmp.name
        alerting.init_alerts_db()
        alerting._consecutive_failures = 0

    def teardown_method(self):
        import alerting
        alerting.DB_PATH = self._orig_path
        alerting._consecutive_failures = 0
        try:
            os.unlink(self._tmp.name)
        except Exception:
            pass

    def test_create_alert(self):
        from alerting import create_alert, get_recent_alerts
        create_alert("test_alert", "warning", "Something happened")
        alerts = get_recent_alerts(limit=10)
        assert len(alerts) == 1
        assert alerts[0]["alert_type"] == "test_alert"
        assert alerts[0]["severity"] == "warning"
        assert alerts[0]["resolved"] == 0

    def test_resolve_alert(self):
        from alerting import create_alert, resolve_alert, get_recent_alerts
        create_alert("test_resolve", "critical", "Bad thing")
        resolve_alert("test_resolve")
        # Unresolved only
        alerts = get_recent_alerts(limit=10, include_resolved=False)
        assert len(alerts) == 0
        # Including resolved
        alerts = get_recent_alerts(limit=10, include_resolved=True)
        assert len(alerts) == 1
        assert alerts[0]["resolved"] == 1

    def test_dedup_alerts(self):
        from alerting import create_alert, get_recent_alerts
        create_alert("dedup_test", "warning", "First")
        create_alert("dedup_test", "warning", "Second")  # should be deduped
        alerts = get_recent_alerts(limit=10)
        assert len(alerts) == 1

    def test_process_health_disk_alert(self):
        from alerting import process_health_result, get_recent_alerts
        process_health_result("ok", {"disk_free_mb": 200}, 100.0)
        alerts = get_recent_alerts(limit=10)
        assert any(a["alert_type"] == "low_disk" for a in alerts)

    def test_process_health_slow_response(self):
        from alerting import process_health_result, get_recent_alerts
        process_health_result("ok", {}, 6000.0)
        alerts = get_recent_alerts(limit=10)
        assert any(a["alert_type"] == "slow_response" for a in alerts)

    def test_consecutive_failures_trigger(self):
        from alerting import process_health_result, get_recent_alerts
        for _ in range(3):
            process_health_result("down", {}, 100.0)
        alerts = get_recent_alerts(limit=10)
        assert any(a["alert_type"] == "service_down" for a in alerts)

    def test_no_alert_under_threshold(self):
        from alerting import process_health_result, get_recent_alerts
        process_health_result("down", {}, 100.0)
        process_health_result("down", {}, 100.0)
        # Only 2 failures, threshold is 3
        alerts = get_recent_alerts(limit=10)
        assert not any(a["alert_type"] == "service_down" for a in alerts)


# ── Circuit Breaker Tests ────────────────────────────────────────────────────

class TestCircuitBreaker:
    def test_maintenance_mode_toggle(self):
        from circuit_breaker import set_maintenance_mode, is_maintenance_mode, get_maintenance_retry_after
        assert not is_maintenance_mode()
        set_maintenance_mode(True, 600)
        assert is_maintenance_mode()
        assert get_maintenance_retry_after() == 600
        set_maintenance_mode(False)
        assert not is_maintenance_mode()

    def test_db_retry_success(self):
        tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        try:
            conn = sqlite3.connect(tmp.name)
            conn.execute("CREATE TABLE test (id INTEGER)")
            conn.execute("INSERT INTO test VALUES (1)")
            conn.commit()
            conn.close()

            from circuit_breaker import db_execute_with_retry
            row = db_execute_with_retry(tmp.name, "SELECT id FROM test", fetch="one")
            assert row["id"] == 1

            rows = db_execute_with_retry(tmp.name, "SELECT id FROM test", fetch="all")
            assert len(rows) == 1
        finally:
            os.unlink(tmp.name)

    def test_db_retry_non_lock_error(self):
        from circuit_breaker import db_execute_with_retry
        with pytest.raises(sqlite3.OperationalError):
            db_execute_with_retry("/nonexistent/path.db", "SELECT 1", fetch="one")

    def test_fallback_response(self):
        from circuit_breaker import get_model_fallback_response
        resp = get_model_fallback_response("summarize")
        assert resp["fallback"] is True
        assert resp["model"] == "fallback"
        assert "unavailable" in resp["text"]

        default = get_model_fallback_response()
        assert default["fallback"] is True

    def test_all_providers_down_false_by_default(self):
        from circuit_breaker import all_providers_down
        # By default no circuits are open
        assert not all_providers_down()


# ── Health Endpoint Tests (via Flask test client) ────────────────────────────

class TestHealthEndpoints:
    @pytest.fixture
    def client(self):
        from app import app
        app.config["TESTING"] = True
        # Clear health cache
        from routes.meta import _health_cache
        _health_cache["data"] = None
        _health_cache["ts"] = 0
        with app.test_client() as c:
            yield c

    def test_health_fast(self, client):
        resp = client.get("/health")
        assert resp.status_code in (200, 503)
        data = resp.get_json()
        assert "status" in data
        assert "checks" in data
        checks = data["checks"]
        assert "db_api_keys" in checks
        assert "disk_free_mb" in checks
        assert "memory_used_pct" in checks
        assert "uptime_seconds" in checks
        assert "health_check_ms" in checks

    def test_health_deep(self, client):
        resp = client.get("/health/deep")
        assert resp.status_code in (200, 503)
        data = resp.get_json()
        assert "checks_passed" in data
        assert "checks_total" in data
        checks = data["checks"]
        # Should check all core DBs
        assert "db_api_keys" in checks
        assert "db_skills" in checks
        assert "db_agent_network" in checks
        assert "model_providers_available" in checks
        assert "memory_used_pct" in checks
        assert "memory_available_mb" in checks

    def test_uptime_endpoint(self, client):
        resp = client.get("/api/uptime")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "uptime" in data
        assert "24h" in data["uptime"]
        assert "7d" in data["uptime"]
        assert "30d" in data["uptime"]

    def test_status_page(self, client):
        resp = client.get("/status")
        assert resp.status_code == 200
        html = resp.data.decode()
        assert "Uptime" in html
        assert "Recent Alerts" in html

    def test_maintenance_mode_blocks_requests(self, client):
        from circuit_breaker import set_maintenance_mode
        try:
            set_maintenance_mode(True, 120)
            # Health should still work
            resp = client.get("/health")
            assert resp.status_code in (200, 503)
            # Other endpoints should return 503
            resp = client.get("/models")
            assert resp.status_code == 503
            data = resp.get_json()
            assert data["error"] == "maintenance"
            assert resp.headers.get("Retry-After") == "120"
        finally:
            set_maintenance_mode(False)

    def test_maintenance_mode_off(self, client):
        from circuit_breaker import set_maintenance_mode
        set_maintenance_mode(False)
        resp = client.get("/models")
        assert resp.status_code == 200
